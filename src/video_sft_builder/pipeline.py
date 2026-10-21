"""Four stages, coordinated serially so audit feedback affects later dispatches."""
from copy import deepcopy
from pathlib import Path

from .errors import Blocked, BudgetBreach, PipelineError, ProtocolError, UnknownExecution
from .media import FFmpegMedia, enumerate_mp4, windows
from .provider import ModelGateway
from .quality import normalized, prepare_candidate, validate_audit, validate_envelope, validate_gate
from .scheduler import Scheduler
from .util import asset, digest


class Pipeline:
    def __init__(self, config, store, *, media=None, provider=None):
        self.config, self.store = config, store
        self.media = media or FFmpegMedia(config)
        self.provider = provider
        self.gateway = ModelGateway(config, store, self.provider)
        self.scheduler = Scheduler(config, store)
        self.prompts = {name: asset('prompts/runtime/' + name + '.txt').read_text(encoding='utf-8')
                        for name in ('caption', 'caption_gate', 'audit')}
        self.generation_prompt = asset('prompts/task_scheduler/generation.system.en.txt').read_text(encoding='utf-8')
        self.generation_prompt += ('\nFor event_order only, optional ordering may contain items [{id,text}] and correct_order '
                                   '(3-6 item IDs). The program randomizes presentation and builds permutations. '
                                   'Do not put answer option labels into question text; the program appends options.')

    def _event(self, stage, video, decision, reason, *, entity=None, unit='video', detail=None):
        self.store.event(stage, unit, entity or video['id'], video, decision, reason, detail)

    def prepare(self):
        saved = self.store.get('input_manifest')
        if saved:
            return saved['videos']
        videos, exact, perceptual = [], {}, []
        paths = enumerate_mp4(self.config)
        for path in paths:
            relative = path.relative_to(Path(self.config.data['input']['root'])).as_posix()
            fallback = {'id': digest(str(path))[:24], 'source': self.config.source_for(relative), 'relative_path': relative}
            try:
                video = self.media.prepare(path)
            except PipelineError as error:
                self._event('prepare', fallback, 'reject', 'unreadable_media', detail={'error_class': type(error).__name__})
                self.store.reject('prepare', fallback['id'], fallback['id'], {'input': fallback, 'reason': 'unreadable_media'})
                continue
            self.store.put('manifest:' + video['id'], 'video', video['id'], video)
            reason = None
            cfg, metrics = self.config.data['media'], video['metrics']
            if video['width'] < cfg['min_width'] or video['height'] < cfg['min_height']:
                reason = 'resolution_below_threshold'
            elif metrics['black_fraction'] >= cfg['black_fraction_threshold']:
                reason = 'black_frames_above_threshold'
            elif metrics['laplacian_variance_mean'] < cfg['blur_laplacian_threshold']:
                reason = 'blur_below_threshold'
            elif video['sha256'] in exact:
                reason = 'exact_media_duplicate'
                self.store.put('duplicate:' + video['id'], 'duplicate', video['id'],
                               {'video_id': video['id'], 'representative': exact[video['sha256']], 'method': 'sha256'})
            elif cfg['perceptual_duplicate_hamming'] is not None:
                for other in perceptual:
                    left, right = metrics['dhashes'], other['metrics']['dhashes']
                    if len(left) == len(right) and max((int(a, 16) ^ int(b, 16)).bit_count() for a, b in zip(left, right)) <= cfg['perceptual_duplicate_hamming']:
                        reason = 'perceptual_media_duplicate'
                        self.store.put('duplicate:' + video['id'], 'duplicate', video['id'],
                                       {'video_id': video['id'], 'representative': other['id'], 'method': 'sampled_dhash'})
                        break
            exact.setdefault(video['sha256'], video['id'])
            if reason:
                self._event('prepare', video, 'reject', reason)
                self.store.reject('prepare', video['id'], video['id'], {'video_id': video['id'], 'reason': reason, 'metrics': metrics})
            else:
                perceptual.append(video)
                videos.append(video)
                self._event('prepare', video, 'pass', 'media_eligible')
        self.store.put('input_manifest', 'run_manifest', None,
                       {'videos': videos, 'enumerated_count': len(paths), 'source': self.config.data['input']['source']})
        return videos

    def caption(self, video):
        cached = self.store.get('caption_bundle:' + video['id'])
        if cached:
            return cached
        cfg = self.config.data['caption']
        local_windows = windows(video['duration'], cfg['l1_seconds'], 'w')
        blocks = windows(video['duration'], cfg['l2_seconds'], 'b')
        descriptions, summaries = [], []
        for block in blocks:
            new_descriptions = []
            for window in local_windows:
                if not block['start'] <= window['start'] < block['end']:
                    continue
                context = {'role': 'A1', 'video_id': video['id'], 'original_duration': video['duration'],
                           'visual_window': window, 'source_start_seconds': window['start'],
                           'previous_l2': summaries[-1]['description'] if summaries else None,
                           'unsummarized_l1': new_descriptions}
                key = f'caption:{video["id"]}:A1:{window["id"]}'
                record = self.store.get(key)
                if not record:
                    self._event('caption_unit', video, 'pending', 'awaiting_caption', entity='l1_' + window['id'], unit='caption_unit')
                    path = self.media.clip(video, window)
                    output, request_id = self.gateway.call('A1', window['id'], video, self.prompts['caption'], context,
                                                          [{'type': 'video', 'path': str(path), **window}])
                    record = self._caption_record(output, 'l1_' + window['id'], window['start'], window['end'], request_id)
                    self.store.put(key, 'caption', video['id'], record)
                new_descriptions.append(record)
                descriptions.append(record)
                self._event('caption_unit', video, 'pass', 'l1_complete', entity=record['id'], unit='caption_unit')
            key = f'caption:{video["id"]}:A2:{block["id"]}'
            record = self.store.get(key)
            if not record:
                self._event('caption_unit', video, 'pending', 'awaiting_caption', entity='l2_' + block['id'], unit='caption_unit')
                path = self.media.clip(video, block)
                context = {'role': 'A2', 'video_id': video['id'], 'original_duration': video['duration'],
                           'visual_window': block, 'source_start_seconds': block['start'],
                           'cumulative_text_range': {'start': 0, 'end': block['end']},
                           'previous_l2': summaries[-1]['description'] if summaries else None,
                           'new_l1': new_descriptions}
                output, request_id = self.gateway.call('A2', block['id'], video, self.prompts['caption'], context,
                                                      [{'type': 'video', 'path': str(path), **block}])
                record = self._caption_record(output, 'l2_' + block['id'], 0, block['end'], request_id)
                record['visual_window'] = block
                self.store.put(key, 'caption', video['id'], record)
            summaries.append(record)
            self._event('caption_unit', video, 'pass', 'l2_complete', entity=record['id'], unit='caption_unit')
        # No extra L3 call. Keep all L2 text records; L3 references the last one.
        bundle = {'video_id': video['id'], 'l1': descriptions, 'l2': summaries,
                  'l3': {**summaries[-1], 'id': 'l3', 'derived_from': summaries[-1]['id']}, 'windows': local_windows}
        return self.store.put('caption_bundle:' + video['id'], 'caption_bundle', video['id'], bundle)

    @staticmethod
    def _caption_record(output, ident, start, end, request_id):
        if set(output) != {'description', 'uncertain_details'} or not isinstance(output['description'], str) or not output['description'].strip():
            raise ProtocolError('Invalid caption response')
        if not isinstance(output['uncertain_details'], list):
            raise ProtocolError('Caption uncertainty field must be an array')
        return {'id': ident, 'start': start, 'end': end, 'description': output['description'],
                'uncertain_details': output['uncertain_details'], 'request_id': request_id}

    def caption_gate(self, video, bundle):
        key = 'caption_gate:' + video['id']
        cached = self.store.get(key)
        if cached:
            if cached['decision'] != 'pass':
                self.store.reject('caption', video['id'], video['id'],
                                  {'video_id': video['id'], 'reason': cached['reason'], 'l3': bundle['l3'], 'response': cached['response']})
            return cached['decision'] == 'pass'
        self._event('caption_gate', video, 'pending', 'awaiting_caption_gate')
        frames = self.media.gate_frames(video)
        media = [{'type': 'image', 'id': f'frame_{index:06d}', **item} for index, item in enumerate(frames)]
        context = {'video_id': video['id'], 'duration': video['duration'], 'l3': bundle['l3'],
                   'frames': [{k: v for k, v in item.items() if k != 'path'} for item in media]}
        try:
            output, request_id = self.gateway.call('C_GATE', 'l3_gate', video, self.prompts['caption_gate'], context, media)
            passed, reason = validate_gate(output, media)
        except (ProtocolError, TypeError, ValueError, KeyError):
            output, request_id = {}, None
            passed, reason = False, 'invalid_caption_gate_response'
        self.store.put(key, 'caption_gate', video['id'], {'decision': 'pass' if passed else 'reject',
                                                       'reason': reason, 'response': output, 'request_id': request_id})
        if not passed:
            self.store.reject('caption', video['id'], video['id'],
                              {'video_id': video['id'], 'reason': reason, 'l3': bundle['l3'], 'response': output})
        self._event('caption_gate', video, 'pass' if passed else 'reject', reason)
        return passed

    def context(self, bundle):
        # Only final L2 + L3, not all cumulative versions, to avoid quadratic
        # repetition. Keep every L1 local description and every evidence window.
        return {'captions': bundle['l1'] + [bundle['l2'][-1], bundle['l3']], 'windows': bundle['windows']}

    def _quality(self, video, candidate):
        key = 'quality:' + candidate['id']
        cached = self.store.get(key)
        if cached:
            if cached['decision'] == 'reject':
                self.store.reject('audit', candidate['id'], video['id'], {'candidate': candidate, 'quality': cached})
            return cached
        self._event('audit', video, 'pending', 'awaiting_audit', entity=candidate['id'], unit='qa',
                    detail={'branch': candidate['branch'], 'task': candidate['task']})
        # Original full MP4 plus corresponding text, never inferred 256 images.
        self.media.unchanged(video)
        media = [{'type': 'video', 'id': 'original', 'path': video['path'], 'sha256': video['sha256'],
                  'start': 0, 'end': video['duration']}]
        context = {'video_id': video['id'], 'duration': video['duration'],
                   'time_basis': 'original_video_zero_normalized_pts', 'candidate': candidate}
        try:
            output, request_id = self.gateway.call('A7', candidate['id'], video, self.prompts['audit'], context, media)
            passed, reason = validate_audit(output, candidate, video)
            value = {'decision': 'pass' if passed else 'reject', 'reason': reason,
                     'response': output, 'request_id': request_id}
        except (ProtocolError, TypeError, ValueError, KeyError):
            value = {'decision': 'reject', 'reason': 'invalid_audit_response'}
        self.store.put(key, 'quality', video['id'], value)
        if value['decision'] == 'reject':
            self.scheduler.observe(candidate, -1)
            self.store.reject('audit', candidate['id'], video['id'], {'candidate': candidate, 'quality': value})
        self._event('audit', video, value['decision'], value['reason'], entity=candidate['id'], unit='qa',
                    detail={'branch': candidate['branch'], 'task': candidate['task']})
        self._event('retention', video, value['decision'], 'retain_all_passed' if value['decision'] == 'pass' else value['reason'],
                    entity=candidate['id'], unit='qa')
        return value

    def generate_branch(self, video, bundle, branch):
        self._event('branch', video, 'pending', 'awaiting_generation', entity=video['id'] + ':' + branch, unit='branch')
        context = self.context(bundle)
        blocked_tasks, blocked_combinations = set(), set()
        target = 3 if branch == 'general' else 2
        role = 'A3' if branch == 'general' else 'A5'
        limit = self.config.data['generation'][branch + '_balance_attempts']
        emitted_balance = 0
        attempted = 0
        for phase in ('fit', 'balance'):
            count = 1 if phase == 'fit' else limit
            for index in range(count):
                if phase == 'balance' and emitted_balance >= target:
                    break
                plan = self.scheduler.plan(video, branch, phase, index, blocked_tasks, blocked_combinations)
                if plan is None:
                    break
                if phase == 'balance':
                    attempted += 1
                emitted = [r['payload'] for r in self.store.records('candidate', video['id'])]
                payload = {**plan, **context, 'already_emitted_questions_and_evidence':
                           [{'question': c['question'], 'evidence_window_ids': c['evidence_window_ids']} for c in emitted]}
                # Persist the complete dispatch payload once. On restart later
                # questions must not change an earlier paid request's context.
                payload_key = 'generation_input:' + plan['request_id']
                payload = self.store.get(payload_key) or self.store.put(payload_key, 'generation_input', video['id'], payload)
                for slot in plan['assigned_slots']:
                    self._event('generation_slots', video, 'pending', 'awaiting_generation',
                                entity=plan['request_id'] + ':' + slot['slot_id'], unit='candidate_slot', detail={'branch': branch})
                response, request_id = self.gateway.call(role, plan['request_id'], video, self.generation_prompt, payload)
                response_key = 'generation_response:' + plan['request_id']
                self.store.put(response_key, 'generation_response', video['id'], response)
                try:
                    validate_envelope(response, plan)
                except (ProtocolError, TypeError, ValueError, KeyError) as error:
                    for slot in plan['assigned_slots']:
                        self._event('generation_slots', video, 'reject', 'generation_protocol_error',
                                    entity=plan['request_id'] + ':' + slot['slot_id'], unit='candidate_slot', detail={'branch': branch})
                    raise ProtocolError('Invalid generation envelope; no refill') from error
                if phase == 'balance':
                    emitted_balance += len(response['candidates'])  # reject still consumes this slot
                for raw in response['candidates']:
                    self._event('generation_slots', video, 'pass', 'qa_emitted',
                                entity=plan['request_id'] + ':' + raw['slot_id'], unit='candidate_slot', detail={'branch': branch})
                    ident = digest([video['id'], plan['request_id'], raw['slot_id']])[:32]
                    existing = self.store.get('candidate:' + ident)
                    if existing:
                        self._quality(video, existing)
                        continue
                    local_rejected = self.store.get('local_reject:' + ident)
                    if local_rejected:
                        self.store.reject('local', ident, video['id'], local_rejected)
                        continue
                    self._event('generation', video, 'pass', 'qa_emitted', entity=ident, unit='qa',
                                detail={'branch': branch, 'phase': phase, 'request_id': request_id})
                    try:
                        candidate = prepare_candidate(deepcopy(raw), response['facts'], plan, video, context,
                                                      self.scheduler.tasks, int(digest([self.config.data['run']['seed'], ident]), 16))
                        # Q5: exact textual duplicate check only; no cross-branch
                        # semantic representative-selection policy is introduced.
                        if any(c['branch'] == branch and normalized(c['question']) == normalized(candidate['question']) for c in emitted):
                            raise ProtocolError('Repeated question in branch')
                    except (ProtocolError, KeyError, ValueError, TypeError, StopIteration) as error:
                        local_reject = {'id': ident, 'branch': branch, 'reason': 'local_validation_failed',
                                        'error_class': type(error).__name__, 'raw': raw, 'request_id': request_id}
                        self.store.put('local_reject:' + ident, 'local_reject', video['id'], local_reject)
                        self.store.reject('local', ident, video['id'], local_reject)
                        self._event('local_quality', video, 'reject', 'local_validation_failed', entity=ident, unit='qa',
                                    detail={'branch': branch})
                        continue
                    self.store.put('candidate:' + ident, 'candidate', video['id'], candidate)
                    self.scheduler.observe(candidate, 1)
                    emitted.append(candidate)
                    self._event('local_quality', video, 'pass', 'local_checks_pass', entity=ident, unit='qa',
                                detail={'branch': branch})
                    self._quality(video, candidate)
                for abstain in response['abstained_slots']:
                    slot = next(s for s in plan['assigned_slots'] if s['slot_id'] == abstain['slot_id'])
                    self._event('generation_slots', video, 'reject', abstain['reason_code'],
                                entity=plan['request_id'] + ':' + slot['slot_id'], unit='candidate_slot', detail={'branch': branch})
                    if phase != 'balance':
                        continue  # fit shortfall never transfers to balance
                    if abstain['reason_code'] in ('task_inapplicable', 'evidence_exhausted'):
                        blocked_tasks.add(slot['task'])
                    else:
                        blocked_combinations.add((slot['task'], slot['language'], slot['question_type'], slot['num_options']))
        self._event('branch', video, 'pass', 'branch_complete', entity=video['id'] + ':' + branch, unit='branch',
                    detail={'branch': branch, 'balance_emitted': emitted_balance, 'balance_attempts': attempted,
                            'attempt_limit_reached': attempted == limit and emitted_balance < target})

    def run(self, *, through='all'):
        if through not in ('prepare', 'caption', 'all'):
            raise ValueError('Unknown pipeline boundary')
        videos = self.prepare()
        if through == 'prepare':
            return videos
        for video in videos:
            try:
                self.media.unchanged(video)
                if self.store.get('video_done:' + video['id']):
                    continue
                bundle = self.caption(video)
                if not self.caption_gate(video, bundle):
                    self.store.put('video_done:' + video['id'], 'video_done', video['id'], {'status': 'caption_rejected'})
                    self._event('execution', video, 'reject', 'caption_rejected')
                    continue
                if through == 'caption':
                    self._event('execution', video, 'pass', 'caption_stage_complete')
                    continue
                for branch in ('general', 'long'):
                    try:
                        self.generate_branch(video, bundle, branch)
                    except ProtocolError:
                        self._event('branch', video, 'reject', 'generation_protocol_error',
                                    entity=video['id'] + ':' + branch, unit='branch')
                self.store.put('video_done:' + video['id'], 'video_done', video['id'], {'status': 'complete'})
                self._event('execution', video, 'pass', 'video_complete')
            except (UnknownExecution, BudgetBreach):
                self._event('execution', video, 'pending', 'unresolved_execution_or_billing_breach')
                raise
            except Blocked as error:
                self._event('execution', video, 'pending', str(error))
            except PipelineError as error:
                self._event('execution', video, 'pending', 'technical_error', detail={'error_class': type(error).__name__})
        return videos
