"""Immutable candidate snapshots and readable source-by-stage audit reports."""
from collections import Counter, defaultdict
import csv
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import tempfile

from .errors import PipelineError
from .completion import completion
from .scheduler import BRANCH_PIPELINE
from .abilities import benchmark_recipe, branches, registry
from .util import asset, atomic_write, canonical, digest, file_digest, read_json, write_json

FINAL_FIELDS = {'id', 'source', 'conversations', 'task', 'question_type', 'media_info', 'media',
                'modal_mask', 'quality', 'cot', 'language', 'tokens'}


def _report_file(path, content):
    """Recover partial report publication without clobbering a different file."""
    encoded = content.encode('utf-8') if isinstance(content, str) else content
    if path.exists():
        if path.read_bytes() != encoded:
            raise PipelineError('Existing report artifact content mismatch')
    else:
        atomic_write(path, encoded)


def final_record(candidate, video, task):
    question = candidate['question']
    if candidate['question_type'] == 'mcq':
        question += '\n' + '\n'.join(o['id'] + '. ' + o['text'] for o in candidate['options'])
    record = {
        'id': candidate['id'],
        'source': {'dataset': video['source'], 'original_id': video['original_id']},
        'conversations': [{'from': 'human', 'value': '<video>\n' + question}, {'from': 'gpt', 'value': candidate['answer']}],
        'task': {'pipeline': 'benchmark_'+candidate['branch']+'_v1' if candidate.get('ability_recipe') else BRANCH_PIPELINE[candidate['branch']], 'family': task['family'],
                 'name': candidate['task'], 'benchmark_refs': []},
        'question_type': {'type': candidate['question_type'], 'num_options': candidate['num_options'],
                          'options': candidate['options'], 'correct_option_id': candidate['correct_option_id']},
        'media_info': {'video_duration_sec': video['duration'], 'video_start_sec': 0.0,
                       'video_end_sec': video['duration'], 'caption_sampling':
                       {'num_frames': None, 'frame_width': None, 'frame_height': None}, 'audio_duration_sec': None},
        'media': {'videos': [video['relative_path']], 'audios': [], 'images': []},
        'modal_mask': 4, 'quality': {'score': None, 'verify': 'auto_pass'}, 'cot': None,
        'language': {'question': candidate['language'], 'answer': candidate['language']},
        'tokens': {'status': 'pending', 'video': None, 'audio': 0, 'image': 0,
                   'text_input': None, 'text_output': None, 'supervised': None, 'total': None}}
    if set(record) != FINAL_FIELDS:
        raise PipelineError('Final record top-level fields changed')
    return record


def candidate_records(store):
    videos = {r['video_id']: r['payload'] for r in store.records('video')}
    tasks = {t['name']: t for t in registry(store.config)['tasks']}
    rows = {branch:[] for branch in branches(store.config)}
    for entry in store.records('candidate'):
        candidate = entry['payload']
        quality = store.get('quality:' + candidate['id'])
        if quality and quality['decision'] == 'pass':
            rows[candidate['branch']].append(final_record(candidate, videos[candidate['video_id']], tasks[candidate['task']]))
    return rows


def export_candidates(store):
    """Export ALL automatic passes. These are not processor-validated releases."""
    for entry in store.records('video'):
        video = entry['payload']
        info = Path(video['path']).stat()
        if (info.st_size, info.st_mtime_ns) != (video['stat_size'], video['stat_mtime_ns']):
            raise PipelineError('Original media identity changed; refusing candidate export')
    records = candidate_records(store)
    progress = completion(store)
    evidence=ability_evidence(store) if benchmark_recipe(store.config) else []
    version = digest([store.config.fingerprint, records, progress, evidence] if evidence else [store.config.fingerprint, records, progress])[:20]
    root = store.config.output / 'exports'
    root.mkdir(parents=True, exist_ok=True)
    destination = root / version
    if destination.exists():
        manifest = read_json(destination / 'manifest.json')
        for branch in records:
            if file_digest(destination / (branch + '.jsonl')) != manifest['sha256'][branch]:
                raise PipelineError('Candidate export checksum mismatch')
        for name,checksum in manifest.get('sidecars',{}).items():
            if Path(name).name!=name or file_digest(destination/name)!=checksum:
                raise PipelineError('Candidate evidence sidecar checksum mismatch')
        return destination
    stage = Path(tempfile.mkdtemp(prefix='.export-', dir=root))
    try:
        checksums = {}
        for branch, values in records.items():
            output = stage / (branch + '.jsonl')
            atomic_write(output, ''.join(canonical(row) + '\n' for row in values))
            checksums[branch] = file_digest(output)
        sidecars={}
        if benchmark_recipe(store.config):
            path=stage/'ability_evidence.jsonl'
            atomic_write(path,''.join(canonical(r)+'\n' for r in evidence))
            sidecars[path.name]=file_digest(path)
        write_json(stage / 'manifest.json', {'version': version, 'run_id': store.config.run_id,
                   'config_hash': store.config.fingerprint, 'stage': 'auto_audited_candidates',
                   'synthetic': store.config.data['teacher']['backend'] == 'synthetic',
                   'counts': {k: len(v) for k, v in records.items()}, 'sha256': checksums,
                   'student_processor_validation': 'not_performed', 'human_review': 'not_scheduled',
                   'training_release': False, 'media_root': store.config.data['input']['root'],
                   'execution_status': progress['status'], 'requested_through': progress['through'],
                   'completion_failures': progress['failures'],
                   'ability_recipe':'benchmark_v1' if benchmark_recipe(store.config) else 'legacy_v1',
                   'sidecars':sidecars})
        atomic_write(stage / 'README.md', '# Automatically audited QA candidates\n\n'
                     'These records have not passed GLM processor/token/evidence-visibility validation.\n'
                     'Human review was not scheduled. Synthetic demo exports are never training data.\n'
                     'Media paths resolve under the external media_root in manifest.json.\n')
        os.rename(stage, destination)
    finally:
        if stage.exists():
            # Only remove files created in this unique staging directory.
            for child in stage.iterdir():
                child.unlink()
            stage.rmdir()
    return destination


def report(store):
    events, requests = store.latest_events(), store.request_rows()
    funnel = defaultdict(Counter)
    for event in events:
        funnel[(event['source'], event['stage'], event['entity_type'])][event['decision']] += 1
    table = []
    for (source, stage, unit), counts in sorted(funnel.items()):
        table.append({'source': source, 'stage': stage, 'unit': unit, 'input': sum(counts.values()),
                      'passed': counts['pass'], 'rejected': counts['reject'], 'pending': counts['pending'],
                      'selection_excluded': 0})
    actual = sum((Decimal(r['actual']) for r in requests if r['actual'] is not None), Decimal(0))
    held = sum((Decimal(r['reservation']) for r in requests if r['actual'] is None), Decimal(0))
    role_rows = {}
    for role in sorted({r['role'] for r in requests}):
        values = [r for r in requests if r['role'] == role]
        usages = [json.loads(r['usage']) for r in values if r['usage']]
        role_rows[role] = {'reserved_slots': len(values), 'sent_requests': sum(r['status'] != 'reserved' for r in values),
                           'status_counts': dict(Counter(r['status'] for r in values)),
                           'input_tokens': sum(u['input_tokens'] for u in usages),
                           'output_tokens': sum(u['output_tokens'] for u in usages),
                           'actual_cost': str(sum((Decimal(r['actual']) for r in values if r['actual'] is not None), Decimal(0)))}
    accepted = candidate_records(store)
    rows = [r for values in accepted.values() for r in values]
    candidates = [r['payload'] for r in store.records('candidate')]
    video_progress = []
    for entry in store.records('video'):
        video = entry['payload']
        units = [e for e in events if e['video_id'] == video['id'] and e['stage'] == 'generation']
        quality_passed = [c for c in candidates if c['video_id'] == video['id']
                          and (store.get('quality:' + c['id']) or {}).get('decision') == 'pass']
        charges = [r for r in requests if r['video_id'] == video['id']]
        video_progress.append({'video_id': video['id'], 'source': video['source'], 'relative_path': video['relative_path'],
                               'duration': video['duration'], 'generated': len(units), 'auto_passed': len(quality_passed),
                               'general_passed': sum(c['branch'] == 'general' for c in quality_passed),
                               'long_passed': sum(c['branch'] == 'long' for c in quality_passed),
                               'knowledge_passed':sum(c['branch']=='knowledge' for c in quality_passed),
                               'requests': len(charges),
                               'actual_cost': str(sum((Decimal(r['actual']) for r in charges if r['actual'] is not None), Decimal(0)))})
    reasons = Counter((e['stage'], e['reason']) for e in events if e['decision'] == 'reject')
    aux = store.db.execute('SELECT COUNT(*) n,COALESCE(SUM(bytes),0) b FROM auxiliary').fetchone()
    summary = {'run_id': store.config.run_id, 'config_hash': store.config.fingerprint,
               'synthetic': store.config.data['teacher']['backend'] == 'synthetic',
               'source_by_stage': table, 'stage_by_source': sorted(table, key=lambda r: (r['stage'], r['source'])),
               'inference': role_rows, 'actual_cost': str(actual), 'held_unknown_or_reserved_cost': str(held),
               'available_budget': str(Decimal(str(store.config.data['budgets']['max_cost'])) - actual - held),
               'auxiliary_requests': aux['n'], 'upload_bytes_reserved': aux['b'],
               'actual_qa_candidates': len(candidates) + len(store.records('local_reject')),
               'video_progress': video_progress,
               'distribution_by_branch_task_language_form': [
                   {'branch': b, 'task': t, 'language': l, 'question_type': f, 'count': n}
                   for (b, t, l, f), n in sorted(Counter((c['branch'], c['task'], c['language'], c['question_type'])
                       for c in candidates if (store.get('quality:' + c['id']) or {}).get('decision') == 'pass').items())],
               'targets': {'languages': {'zh': 0.3, 'en': 0.7}, 'question_types': {'oe': 0.7, 'mcq': 0.3},
                           'mcq_option_counts': {'3': 0.1, '4': 0.7, '6': 0.2}},
               'auto_passed': len(rows), 'branches': {k: len(v) for k, v in accepted.items()},
               'tasks': dict(Counter(r['task']['name'] for r in rows)),
               'languages': dict(Counter(r['language']['question'] for r in rows)),
               'question_types': dict(Counter(r['question_type']['type'] for r in rows)),
               'mcq_option_counts': dict(Counter(str(r['question_type']['num_options']) for r in rows if r['question_type']['type'] == 'mcq')),
               'template_usage': dict(Counter(c['template_id'] for c in candidates)),
               'primary_reject_reasons': [{'stage': s, 'reason': reason, 'count': n} for (s, reason), n in sorted(reasons.items())],
               'human_review_status': 'not_scheduled', 'human_review_count': 0,
               'human_accuracy': None, 'human_false_acceptance_rate': None,
               'student_validation': 'not_performed', 'training_release': False,
               'selection_excluded': 0, 'currency': store.config.data['budgets']['currency']}
    summary['completion'] = completion(store)
    summary['ability_recipe']='benchmark_v1' if benchmark_recipe(store.config) else 'legacy_v1'
    if benchmark_recipe(store.config):
        summary['abilities']=ability_summary(store,candidates)
    summary['cost_basis'] = 'observed_usage_times_configured_flat_rates_not_provider_invoice'
    version = digest(summary)[:20]
    root = store.config.output / 'reports' / version
    root.mkdir(parents=True, exist_ok=True)
    completion_file = root / 'files.json'
    if completion_file.exists():
        for name, checksum in read_json(completion_file)['sha256'].items():
            if Path(name).name != name or file_digest(root / name) != checksum:
                raise PipelineError('Completed report checksum mismatch')
    else:
        _report_file(root / 'summary.json', canonical(summary) + '\n')
        if benchmark_recipe(store.config):
            _report_file(root/'ability_evidence.jsonl',''.join(canonical(r)+'\n' for r in ability_evidence(store)))
            _report_file(root/'benchmark_capability_coverage.json',canonical(summary['abilities'])+'\n')
        text = '# Video SFT run report\n\n'
        text += f'Run: `{store.config.run_id}`. Synthetic simulation: **{summary["synthetic"]}**.\n\n'
        text += 'Output stage: **automatically audited candidates; not a validated training release**.\n\n'
        progress = summary['completion']
        text += f'Execution: **{progress["status"]}**; requested boundary: **{progress["through"]}**.\n\n'
        if progress['failures']:
            text += '## INCOMPLETE — partial results only\n\n'
            for failure in progress['failures']:
                text += '- ' + canonical(failure) + '\n'
            text += '\n'
        text += '| Video | L1 complete / expected | L2 complete / expected | Full L3 | Missing |\n|---|---:|---:|---|---|\n'
        for row in progress['videos']:
            text += f'| {row["video_id"]} | {row["l1_completed"]}/{row["l1_expected"]} | {row["l2_completed"]}/{row["l2_expected"]} | {row["l3_complete"]} | {", ".join(row["missing"])} |\n'
        text += '\n'
        text += f'Observed usage priced at configured rates: {actual} CNY. Held reservations/unknown executions: {held} CNY.\n\n'
        text += f'QA candidates: {summary["actual_qa_candidates"]}; automatic passes: {len(rows)}.\n\n'
        text += '| Source | Stage | Unit | Input | Pass | Reject | Pending |\n|---|---|---|---:|---:|---:|---:|\n'
        for row in table:
            text += f'| {row["source"]} | {row["stage"]} | {row["unit"]} | {row["input"]} | {row["passed"]} | {row["rejected"]} | {row["pending"]} |\n'
        text += '\nLanguage target zh/en=3:7; OE/MCQ=7:3; MCQ3/4/6=1:7:2. These are soft generation targets.\n\n'
        text += '| Video | Seconds | Generated | General pass | Long pass | Knowledge pass | API slots | Actual CNY |\n|---|---:|---:|---:|---:|---:|---:|---:|\n'
        for row in video_progress:
            text += f'| {row["video_id"]} | {row["duration"]} | {row["generated"]} | {row["general_passed"]} | {row["long_passed"]} | {row["knowledge_passed"]} | {row["requests"]} | {row["actual_cost"]} |\n'
        if 'abilities' in summary:
            text+='\nAbility recipe: benchmark_v1; benchmark gains have not been measured.\n\n'
            text+='| Branch | Task | Generated | Auto pass | Local reject |\n|---|---|---:|---:|---:|\n'
            for r in summary['abilities']['task_counts']:
                text+=f'| {r["branch"]} | {r["task"]} | {r["generated"]} | {r["auto_passed"]} | {r["local_rejected"]} |\n'
        text += '\nActual accepted distributions: ' + canonical({k: summary[k] for k in ('tasks', 'languages', 'question_types', 'mcq_option_counts')}) + '\n\n'
        text += 'No quota-based removal or rejected-QA refill. Human review: not scheduled; true accuracy: unknown.\n'
        _report_file(root / 'report.md', text)
        for name, values in (('source_by_stage', table), ('stage_by_source', summary['stage_by_source'])):
            buffer = io.StringIO(newline='')
            writer = csv.DictWriter(buffer, fieldnames=['source', 'stage', 'unit', 'input', 'passed', 'rejected', 'pending', 'selection_excluded'])
            writer.writeheader()
            writer.writerows(values)
            _report_file(root / (name + '.csv'), buffer.getvalue())
        _report_file(root / 'stage_events.jsonl', ''.join(canonical(e) + '\n' for e in events))
        # Deliberately exclude response bodies, private URLs and credentials here.
        public_requests = [{**{k: v for k, v in r.items() if k != 'response'},
                            'provider_request_id': json.loads(r['response']).get('id') if r['response'] else None} for r in requests]
        _report_file(root / 'api_requests.jsonl', ''.join(canonical(r) + '\n' for r in public_requests))
        _report_file(root / 'review_index.jsonl', ''.join(canonical({'sample_id': c['id'], 'video_id': c['video_id'],
                     'branch': c['branch'], 'task': c['task'], 'question': c['question'], 'answer': c['answer'],
                     'quality': store.get('quality:' + c['id']), 'evidence_windows': c['evidence_windows']}) + '\n' for c in candidates))
        # A readable view, not a claim that human review was performed.
        review = '# Candidate inspection\n\nHuman review: not scheduled. Do not use synthetic examples for training.\n\n'
        for c in candidates:
            review += f'## {c["id"]}\n\n{c["branch"]} / {c["task"]} / {c["language"]} / {c["question_type"]}\n\n'
            value = {'question': c['question'], 'options': c['options'], 'answer': c['answer'],
                     'evidence_windows': c['evidence_windows'], 'quality': store.get('quality:' + c['id'])}
            if 'assessment' in c:
                value.update(assessment=c['assessment'],task_contract=c['task_contract'],question_style=c['question_style'])
            # JSON-escape backticks to prevent untrusted question text closing the fence.
            review += '```json\n' + json.dumps(value, ensure_ascii=False, indent=2).replace('`', '\\u0060') + '\n```\n\n'
        _report_file(root / 'review.md', review)
        names = ['summary.json', 'report.md', 'source_by_stage.csv', 'stage_by_source.csv',
                 'stage_events.jsonl', 'api_requests.jsonl', 'review_index.jsonl', 'review.md']
        if benchmark_recipe(store.config):
            names+=['ability_evidence.jsonl','benchmark_capability_coverage.json']
        write_json(completion_file, {'sha256': {name: file_digest(root / name) for name in names}})
    return root, summary


def ability_evidence(store):
    return [{'sample_id':c['id'],'video_id':c['video_id'],'branch':c['branch'],'task':c['task'],
             'question_style':c['question_style'],'assessment':c['assessment'],'task_contract':c['task_contract'],
             'facts':c['facts'],'evidence_windows':c['evidence_windows'],'caption_evidence':c['caption_evidence'],
             'quality':store.get('quality:'+c['id'])}
            for entry in store.records('candidate') for c in [entry['payload']] if 'assessment' in c]


def ability_summary(store,candidates):
    tasks=registry(store.config)['tasks']
    local=[r['payload'] for r in store.records('local_reject')]
    counts=[]
    for task in tasks:
        found=[c for c in candidates if c['task']==task['name']]
        counts.append(dict(branch=task['branch'],task=task['name'],operation=task['operation'],
             generated=len(found)+sum(r.get('raw',{}).get('task')==task['name'] for r in local),
             auto_passed=sum((store.get('quality:'+c['id']) or {}).get('decision')=='pass' for c in found),
             local_rejected=sum(r.get('raw',{}).get('task')==task['name'] for r in local)))
    view={r['payload']['request_id']:r['payload'].get('branch') for r in store.records('request_view')}
    cost={}
    for name in ('shared_caption','general','long','knowledge','unattributed'):
        requests=[r for r in store.request_rows() if (view.get(r['id']) or ('shared_caption' if r['role'] in ('A1','A2','C_GATE') else 'unattributed'))==name]
        cost[name]=dict(requests=len(requests),actual_cost=str(sum((Decimal(r['actual']) for r in requests if r['actual'] is not None),Decimal(0))),
                        held=str(sum((Decimal(r['reservation']) for r in requests if r['actual'] is None),Decimal(0))))
    return dict(task_counts=counts,question_styles=dict(Counter(c.get('question_style','unknown') for c in candidates)),
       knowledge_domains=dict(Counter(c['assessment']['knowledge']['domain'] for c in candidates
         if c['branch']=='knowledge' and (store.get('quality:'+c['id']) or {}).get('decision')=='pass')),
       benchmark_mapping=read_json(asset('configs/benchmark_capability_coverage.json'))['coverage'],
       cost_by_branch=cost,benchmark_gain_measured=False,expert_accuracy_unknown=True,
       source_context_is_task_taxonomy=False)
