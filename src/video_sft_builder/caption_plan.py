"""Complete, contiguous caption coverage; never drop a fractional tail."""
from .errors import Blocked, ProtocolError
from .media import windows


def caption_plan(config, video):
    cfg = config.data['caption']
    local = windows(video['duration'], cfg['l1_seconds'], 'w')
    blocks = windows(video['duration'], cfg['l2_seconds'], 'b')
    merges = []
    for role, units in (('A1', local), ('A2', blocks)):
        minimum = config.profile(role)['min_video_seconds']
        if len(units) > 1 and units[-1]['end'] - units[-1]['start'] < minimum:
            tail = units.pop()
            units[-1]['end'] = tail['end']
            merges.append({'role': role, 'merged_tail': tail, 'into': units[-1]['id']})
    # L1 must fit wholly inside exactly one visual L2 block.
    if any(sum(b['start'] <= w['start'] and w['end'] <= b['end'] for b in blocks) != 1 for w in local):
        raise Blocked('caption_window_alignment_impossible')
    return {'video_id': video['id'], 'duration': video['duration'], 'l1': local, 'l2': blocks,
            'tail_merges': merges, 'coverage': 'full_original_range', 'fps_reduced': False}


def preflight(config, video, plan):
    for role, units in (('A1', plan['l1']), ('A2', plan['l2'])):
        p, provider = config.profile(role), config.provider_settings(role)
        margin = 1 if provider.get('backend') == 'vllm' and provider.get('request_mm_kwargs') else 0
        for unit in units:
            duration = unit['end'] - unit['start']
            if duration < p['min_video_seconds']:
                raise Blocked('caption_plan_segment_below_provider_minimum')
            if duration * p['fps'] + margin > p['max_frames'] or video['fps'] < p['fps']:
                raise Blocked('fixed_fps_cannot_be_preserved')


def validate_bundle(bundle, plan):
    """Check persisted records against the full plan before any downstream call."""
    try:
        if bundle['video_id'] != plan['video_id'] or bundle['windows'] != plan['l1']:
            raise ValueError()
        for level in ('l1', 'l2'):
            records, expected = bundle[level], plan[level]
            if len(records) != len(expected):
                raise ValueError()
            for record, window in zip(records, expected):
                start = window['start'] if level == 'l1' else 0
                if (record['id'], record['start'], record['end']) != (level + '_' + window['id'], start, window['end']):
                    raise ValueError()
                if not record['description'].strip() or not record['request_id']:
                    raise ValueError()
                if level == 'l2' and record['visual_window'] != window:
                    raise ValueError()
        last = bundle['l2'][-1]
        expected_l3 = {**last, 'id': 'l3', 'derived_from': last['id']}
        if bundle['l3'] != expected_l3 or bundle['l3']['end'] != plan['duration']:
            raise ValueError()
    except (KeyError, TypeError, IndexError, ValueError, AttributeError):
        raise ProtocolError('caption_bundle_incomplete_or_coverage_mismatch') from None
