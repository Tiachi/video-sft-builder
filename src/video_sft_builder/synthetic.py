"""Explicitly synthetic test/demo adapters. Never route production to these."""
from copy import deepcopy
import json
from pathlib import Path

from .config import RuntimeConfig, template, validate_config
from .quality import CHECKS
from .util import digest, file_digest, write_json


def demo_config(root, *, run_id='demo'):
    root = Path(root).resolve()
    data = template()
    data['run'].update(id=run_id, output_root=str(root / 'derived'), state_root=str(root / 'state'), max_videos=2)
    data['input'].update(root=str(root / 'synthetic_input'), source='synthetic_only', recursive=False, max_scan_entries=20)
    data['media'].update(timeout_seconds=30, preset='fast', crf=18, clip_duration_tolerance_seconds=0.2,
                         sample_count=3, sample_width=32, sample_height=32, min_width=16, min_height=16,
                         black_pixel_threshold=8, black_fraction_threshold=0.98, blur_laplacian_threshold=0)
    data['caption'].update(l1_seconds=10, l2_seconds=30, gate_frame_count=4)
    data['teacher'].update(backend='synthetic', model='synthetic-no-network', timeout_seconds=30, provider_max_input_tokens=200000,
                           max_video_bytes=10_000_000, max_payload_bytes=10_000_000, max_response_bytes=1_000_000)
    for role, profile in data['teacher']['roles'].items():
        profile.update(input_token_limit=200000, visual_token_reserve=0 if profile['mode'] == 'text' else 10000,
                       context_overhead_tokens=1000, max_completion_tokens=4096, enable_thinking=False,
                       thinking_budget=None, temperature=0)
        if profile['mode'] == 'native_video':
            profile.update(fps=2, max_frames=8000, max_pixels=655360, total_pixels=819200000,
                           min_video_seconds=2, sampling_capability_verified=True)
        elif profile['mode'] == 'ordered_images':
            profile.update(max_frames=256, max_pixels=655360)
    data['budgets'].update(max_cost='100', max_requests=1000, per_video_max_requests=300,
                           max_aux_requests=1000, max_upload_bytes=10_000_000,
                           input_per_million='0.8', output_per_million='2.7')
    data['generation'].update(general_balance_attempts=12, long_balance_attempts=5, templates_per_slot=1)
    validate_config(data, allow_synthetic=True)
    return RuntimeConfig(data, root / 'demo_config.json')


def create_inputs(config):
    root = Path(config.data['input']['root'])
    root.mkdir(parents=True, exist_ok=True)
    for name, duration in (('simulation_30.mp4', 30), ('simulation_60.mp4', 60)):
        path = root / name
        value = {'synthetic_not_a_playable_video': True, 'duration': duration, 'name': name}
        if not path.exists():
            write_json(path, value)


class SyntheticMedia:
    synthetic = True

    def __init__(self, config):
        self.config = config

    def prepare(self, path):
        value = json.loads(path.read_text(encoding='utf-8'))
        stat = path.stat()
        checksum = file_digest(path)
        return {'id': digest([path.name, checksum])[:24], 'source': self.config.source_for(path.name), 'original_id': path.name,
                'path': str(path), 'relative_path': path.name, 'sha256': checksum, 'duration': value['duration'],
                'width': 1920, 'height': 1080, 'fps': 25, 'bytes': stat.st_size,
                'stat_size': stat.st_size, 'stat_mtime_ns': stat.st_mtime_ns, 'stream_start_seconds': 0,
                'metrics': {'black_fraction': 0, 'laplacian_variance_mean': 100, 'dhashes': ['0123456789abcdef'] * 3},
                'sample_times': [1, 10, 20], 'synthetic_not_real_media': True}

    def unchanged(self, video):
        from .media import FFmpegMedia
        FFmpegMedia.unchanged(self, video)

    def clip(self, video, window):
        self.unchanged(video)
        return Path(video['path'])  # fake provider does not read/interpret video bytes

    def gate_frames(self, video):
        return [{'path': video['path'], 'time': index * video['duration'] / 4,
                 'sha256': video['sha256']} for index in range(4)]


class SyntheticProvider:
    synthetic = True

    def __init__(self):
        self.sent = []

    def build_body(self, role, system, context, media, profile):
        return {'role': role, 'system': system, 'context': context, 'media': media, 'profile': profile}

    def send(self, body):
        self.sent.append(deepcopy(body))
        role, context = body['role'], body['context']
        if role in ('A1', 'A2'):
            window = context['visual_window']
            result = {'description': f'SYNTHETIC: visible stage {window["id"]}; an actor changes an object state.',
                      'uncertain_details': []}
        elif role == 'C_GATE':
            result = {'decision': 'pass', 'critical_claims_complete': True,
                      'claims': [{'claim': 'Synthetic supported stage', 'status': 'supported',
                                  'frame_ids': [context['frames'][0]['id']]}], 'primary_reason': 'synthetic_only'}
        elif role == 'A7':
            c = context['candidate']
            result = {'decision': 'pass', 'checks': {key: 'pass' for key in CHECKS},
                      'primary_reason': 'synthetic_only',
                      'evidence': [{'fact_id': fact['fact_id'],
                                    'start': next(w['start'] for w in c['evidence_windows'] if w['id'] == fact['evidence_window_ids'][0]),
                                    'end': next(w['end'] for w in c['evidence_windows'] if w['id'] == fact['evidence_window_ids'][0])}
                                   for fact in c['facts']]}
        else:
            result = self.generate(context)
        return {'id': 'synthetic_response', 'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(result)}}],
                'usage': {'prompt_tokens': 1000, 'completion_tokens': 200}}

    @staticmethod
    def generate(context):
        candidates, facts = [], []
        task_map = {task['name']: task for task in context['allowed_tasks']}
        for index, slot in enumerate(context['assigned_slots']):
            name = slot['task'] or slot['allowed_tasks'][index % len(slot['allowed_tasks'])]
            task = task_map[name]
            count = max(task['minimum_fact_count'], 3 if name in ('event_timeline', 'hierarchical_summary') else 2 if context['branch'] == 'long' else 1)
            all_windows = context['windows']
            evidence = [all_windows[round(i * (len(all_windows) - 1) / max(1, count - 1))] for i in range(count)]
            selected_facts = []
            for position, window in enumerate(evidence):
                fact_id = f'f_{slot["slot_id"]}_{position}'
                caption_id = 'l1_' + window['id']
                facts.append({'fact_id': fact_id, 'claim': 'Synthetic observation ' + str(position),
                              'caption_ids': [caption_id], 'evidence_window_ids': [window['id']]})
                selected_facts.append(fact_id)
            template = next(t for t in context['template_candidates'] if t['task'] == name and t['language'] == slot['language'])
            question = (f'合成问题：{name} {context["request_id"][:8]} {index}？' if slot['language'] == 'zh'
                        else f'Synthetic question about {name}, unit {context["request_id"][:8]}-{index}?')
            options = [{'id': chr(65 + i), 'text': 'Synthetic option ' + str(i)} for i in range(slot['num_options'])]
            candidates.append({'slot_id': slot['slot_id'], 'task': name, 'language': slot['language'],
                               'question_type': slot['question_type'], 'num_options': slot['num_options'],
                               'question': question, 'answer': 'A' if options else 'Synthetic supported answer.',
                               'options': options, 'correct_option_id': 'A' if options else None,
                               'required_fact_ids': selected_facts, 'evidence_window_ids': [w['id'] for w in evidence],
                               'template_id': template['template_id']})
        return {'request_id': context['request_id'], 'video_id': context['video_id'], 'facts': facts,
                'candidates': candidates, 'abstained_slots': []}
