"""Independent completion checks: absence of pending events is not completion."""
from .caption_plan import caption_plan, validate_bundle
from .errors import PipelineError


def completion(store, through=None):
    boundary = store.db.execute("SELECT value FROM metadata WHERE key='requested_through'").fetchone()
    through = through or (boundary['value'] if boundary else 'all')
    manifest = store.get('input_manifest')
    events = store.latest_events()
    failures = []
    rows = []
    if not manifest:
        failures.append({'stage': 'prepare', 'reason': 'input_manifest_missing'})
    for video in (manifest or {}).get('videos', []):
        ident = video['id']
        missing = []
        row = {'video_id': ident, 'relative_path': video['relative_path'], 'duration': video['duration'],
               'l1_expected': 0, 'l1_completed': 0, 'l2_expected': 0, 'l2_completed': 0,
               'l3_complete': False, 'gate': None, 'branches': {}, 'missing': missing}
        if through != 'prepare':
            try:
                plan = caption_plan(store.config, video)
                for level, role in (('l1', 'A1'), ('l2', 'A2')):
                    row[level + '_expected'] = len(plan[level])
                    row[level + '_completed'] = sum(store.get(f'caption:{ident}:{role}:{w["id"]}') is not None for w in plan[level])
                bundle = store.get('caption_bundle:' + ident)
                if bundle:
                    validate_bundle(bundle, plan)
                    row['l3_complete'] = True
                else:
                    missing.append('complete_caption_bundle')
            except PipelineError:
                missing.append('valid_caption_coverage')
            for level in ('l1', 'l2'):
                if row[level + '_completed'] != row[level + '_expected']:
                    missing.append(level + '_units')
            gate = store.get('caption_gate:' + ident)
            row['gate'] = (gate or {}).get('decision')
            if not gate or gate.get('decision') not in ('pass', 'reject'):
                missing.append('caption_gate')
            if through == 'all' and row['gate'] != 'reject':
                for branch in ('general', 'long'):
                    terminal = next((e for e in events if e['stage'] == 'branch' and e['entity_id'] == ident + ':' + branch), None)
                    row['branches'][branch] = terminal['reason'] if terminal else 'not_started'
                    if not terminal or terminal['decision'] != 'pass':
                        missing.append(branch + '_branch')
                if (store.get('video_done:' + ident) or {}).get('status') != 'complete':
                    missing.append('video_complete')
                for candidate in store.records('candidate', ident):
                    if not store.get('quality:' + candidate['payload']['id']):
                        missing.append('candidate_audit:' + candidate['payload']['id'])
        stop = next((e for e in events if e['stage'] == 'execution' and e['video_id'] == ident and e['decision'] == 'pending'), None)
        if stop:
            row['stop'] = {'reason': stop['reason'], **stop['detail']}
            failures.append({'video_id': ident, **row['stop']})
        if missing:
            failures.append({'video_id': ident, 'stage': 'completion_check', 'reason': 'required_outputs_missing', 'missing': missing})
        rows.append(row)
    pending = [e for e in events if e['decision'] == 'pending']
    unresolved = [r for r in store.request_rows() if r['status'] != 'done']
    if pending and not failures:
        failures.append({'stage': 'completion_check', 'reason': 'pending_entities', 'count': len(pending)})
    if unresolved:
        failures.append({'stage': 'accounting', 'reason': 'requests_not_resolved',
                         'requests': [{'id': r['id'], 'status': r['status']} for r in unresolved]})
    return {'status': 'incomplete' if failures else 'complete', 'through': through,
            'pending_entities': len(pending), 'failures': failures, 'videos': rows}
