"""Local deterministic checks, timestamp rendering, option compilation and audit gates."""
from html import unescape
from html.parser import HTMLParser
from copy import deepcopy
import itertools
import math
import random
import re
import unicodedata

from .errors import ProtocolError
from .util import digest

CHECKS = ('question_answerable', 'answer_support', 'qa_consistency', 'task_validity',
          'multi_segment_necessity', 'mcq_unique', 'temporal_grounding', 'entity_identity',
          'language', 'non_template', 'answer_not_leaked')
TIME_MARKER = re.compile(r'\[\[TIME:([A-Za-z0-9_-]+)\]\]')
NUMERIC_TIME = re.compile(r'\b\d{1,2}:\d{2}(?::\d{2})?\b|\b\d+(?:\.\d+)?\s*(?:seconds?|secs?|秒)\b', re.I)


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        elif tag in ('br', 'p', 'div', 'li'):
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.hidden:
            self.hidden -= 1

    def handle_data(self, value):
        if not self.hidden:
            self.parts.append(value)


def clean_text(value):
    if not isinstance(value, str):
        raise ProtocolError('Text field is not a string')
    parser = PlainText()
    parser.feed(unescape(value))
    text = ''.join(c for c in ''.join(parser.parts) if not unicodedata.category(c).startswith('C') or c in '\n\t')
    return re.sub(r'\s+', ' ', text).strip()


def normalized(value):
    return re.sub(r'\W+', '', unicodedata.normalize('NFKC', value).casefold())


def clock(seconds):
    seconds = int(seconds)
    return f'{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}'


def render_time(value, windows, language, seed):
    if NUMERIC_TIME.search(TIME_MARKER.sub('', value)):
        raise ProtocolError('Model invented a numeric time; use an existing TIME window reference')
    def render(match):
        if match.group(1) not in windows:
            raise ProtocolError('Unknown absolute time window')
        window = windows[match.group(1)]
        a, b = clock(window['start']), clock(window['end'])
        styles = ([f'原片{a}至{b}这一段', f'视频{a}—{b}片段', f'{a}到{b}这段画面'] if language == 'zh'
                  else [f'the {a}–{b} segment of the original video', f'the video segment from {a} to {b}',
                        f'the {a}–{b} interval'])
        return styles[int(digest([seed, match.group(1)]), 16) % len(styles)]
    output = TIME_MARKER.sub(render, value)
    if '[[' in output or ']]' in output:
        raise ProtocolError('Unresolved time/template marker')
    return output


def validate_envelope(response, plan):
    if set(response) != {'request_id', 'video_id', 'facts', 'candidates', 'abstained_slots'}:
        raise ProtocolError('Generation envelope fields mismatch')
    if response['request_id'] != plan['request_id'] or response['video_id'] != plan['video_id']:
        raise ProtocolError('Generation identity mismatch')
    if not all(isinstance(response[k], list) for k in ('facts', 'candidates', 'abstained_slots')):
        raise ProtocolError('Generation lists missing')
    expected = {s['slot_id'] for s in plan['assigned_slots']}
    if any(not isinstance(s, dict) or not isinstance(s.get('slot_id'), str)
           for s in response['candidates'] + response['abstained_slots']):
        raise ProtocolError('Generation slot must be an identified object')
    actual = [s.get('slot_id') for s in response['candidates'] + response['abstained_slots']]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ProtocolError('Every assigned slot must appear exactly once')
    for abstain in response['abstained_slots']:
        if abstain.get('reason_code') not in ('task_inapplicable', 'form_inapplicable', 'evidence_exhausted'):
            raise ProtocolError('Invalid abstention reason')


def compile_ordering(candidate, seed):
    ordering = candidate.get('ordering')
    if ordering is None:
        return
    if candidate['task'] != 'event_order' or not isinstance(ordering, dict):
        raise ProtocolError('Ordering metadata only allowed for event_order')
    items, correct = ordering.get('items'), ordering.get('correct_order')
    if not isinstance(items, list) or not 3 <= len(items) <= 6 or not isinstance(correct, list):
        raise ProtocolError('Ordering requires 3-6 uniquely identified events')
    ids = [item.get('id') for item in items]
    if len(set(ids)) != len(ids) or len(correct) != len(ids) or set(correct) != set(ids):
        raise ProtocolError('Invalid ordering permutation')
    rng = random.Random(seed)
    rng.shuffle(items)
    labels = {item['id']: chr(65 + index) for index, item in enumerate(items)}
    candidate['question'] += ' ' + '; '.join(labels[item['id']] + ': ' + clean_text(item['text']) for item in items)
    answer = ' → '.join(labels[item] for item in correct)
    if candidate['question_type'] == 'oe':
        candidate['answer'] = answer
        return
    permutations = [p for p in itertools.permutations(ids) if list(p) != correct]
    options = [answer] + [' → '.join(labels[item] for item in p)
                          for p in rng.sample(permutations, candidate['num_options'] - 1)]
    candidate['options'] = [{'id': chr(65 + index), 'text': text} for index, text in enumerate(options)]
    candidate['correct_option_id'] = candidate['answer'] = 'A'


def prepare_candidate(raw, facts, plan, video, context, registry, seed):
    c = deepcopy(raw)
    fields = {'slot_id', 'task', 'language', 'question_type', 'num_options', 'question', 'answer', 'options',
              'correct_option_id', 'required_fact_ids', 'evidence_window_ids', 'template_id'}
    declared=registry.get(c.get('task'),{})
    benchmark=declared.get('contract_version')==1
    extra={'ordering','assessment'} if benchmark else {'ordering'}
    if not fields <= set(c) or set(c) - fields - extra:
        raise ProtocolError('Candidate fields mismatch')
    if type(c['num_options']) is not int:
        raise ProtocolError('Option count must be an integer, not a boolean')
    slot = next(s for s in plan['assigned_slots'] if s['slot_id'] == c['slot_id'])
    if c['task'] not in slot['allowed_tasks'] or (slot['task'] and slot['task'] != c['task']):
        raise ProtocolError('Model changed the assigned task')
    for key in ('language', 'question_type', 'num_options'):
        if c[key] != slot[key]:
            raise ProtocolError('Model changed assigned ' + key)
    task = registry[c['task']]
    if c['question_type'] not in task['question_types'] or task['branch'] != plan['branch']:
        raise ProtocolError('Task/form compatibility failed')
    templates = {t['template_id']: t for t in plan['template_candidates']}
    template = templates.get(c['template_id'])
    if (not template or template['task'] != c['task'] or template['language'] != c['language']
            or c['question_type'] not in template['supported_question_types']):
        raise ProtocolError('Unknown/incompatible template')
    window_map = {w['id']: w for w in context['windows']}
    caption_ids = {caption['id'] for caption in context['captions']}
    fact_map = {}
    for fact in facts:
        if set(fact) != {'fact_id', 'claim', 'caption_ids', 'evidence_window_ids'} or fact['fact_id'] in fact_map:
            raise ProtocolError('Invalid/duplicate fact')
        if not fact['caption_ids'] or not set(fact['caption_ids']) <= caption_ids:
            raise ProtocolError('Fact references unknown captions')
        if not fact['evidence_window_ids'] or not set(fact['evidence_window_ids']) <= set(window_map):
            raise ProtocolError('Fact references unknown evidence windows')
        if not clean_text(fact['claim']):
            raise ProtocolError('Empty supporting fact')
        fact_map[fact['fact_id']] = fact
    required = c['required_fact_ids']
    evidence = c['evidence_window_ids']
    if (not isinstance(required, list) or len(set(required)) != len(required)
            or len(set(required)) < task['minimum_fact_count'] or not set(required) <= set(fact_map)):
        raise ProtocolError('Insufficient/invalid required facts')
    if not evidence or not set(evidence) <= set(window_map):
        raise ProtocolError('Invalid candidate evidence')
    covered = {w for fact_id in required for w in fact_map[fact_id]['evidence_window_ids']}
    if set(evidence) != covered:
        raise ProtocolError('Candidate evidence and required facts disagree')
    selected = sorted((window_map[w] for w in set(evidence)), key=lambda w: w['start'])
    nonoverlap = []
    for window in selected:
        if not nonoverlap or window['start'] >= nonoverlap[-1]['end']:
            nonoverlap.append(window)
    minimum_windows = task.get('minimum_windows',3 if c['task'] in ('event_timeline', 'hierarchical_summary') else 2 if plan['branch'] == 'long' else 1)
    if len(nonoverlap) < minimum_windows:
        raise ProtocolError('Task lacks distinct evidence windows')
    if task.get('global_coverage',c['task']=='hierarchical_summary'):
        if {min(2, int(((w['start'] + w['end']) / 2) / (video['duration'] / 3))) for w in selected} != {0, 1, 2}:
            raise ProtocolError('Hierarchical summary lacks beginning/middle/end coverage')
    if benchmark:
        from .abilities import validate_assessment, compile_location, compile_ordering as compile_benchmark_ordering
        validate_assessment(c,task,fact_map,context)
        if task['operation']=='sequence_ordering':
            compile_benchmark_ordering(c,fact_map,seed)
        elif task['operation']=='coarse_location':
            compile_location(c,context,seed)
        c['question_style']=template['question_style']
        c['ability_recipe']='benchmark_v1'
    else:
        compile_ordering(c, seed)
    c['question'] = render_time(clean_text(c['question']), window_map, c['language'], seed)
    c['answer'] = render_time(clean_text(c['answer']), window_map, c['language'], seed)
    if not c['question'] or not c['answer'] or '<video>' in c['question']:
        raise ProtocolError('Empty/leaked media marker in candidate')
    if c['question_type'] == 'oe':
        if c['num_options'] != 0 or c['options'] != [] or c['correct_option_id'] is not None:
            raise ProtocolError('OE options must be empty')
    else:
        if c['num_options'] not in (3, 4, 6) or not isinstance(c['options'], list) or len(c['options']) != c['num_options']:
            raise ProtocolError('Invalid single-choice options')
        ids = [chr(65 + i) for i in range(c['num_options'])]
        if [option.get('id') for option in c['options']] != ids or c['answer'] != c['correct_option_id'] or c['answer'] not in ids:
            raise ProtocolError('MCQ answer/option identity mismatch')
        for option in c['options']:
            option['text'] = render_time(clean_text(option['text']), window_map, c['language'], seed)
        if any(not o['text'] for o in c['options']) or len({normalized(o['text']) for o in c['options']}) != c['num_options']:
            raise ProtocolError('Duplicate/empty MCQ options')
        right = next(o for o in c['options'] if o['id'] == c['correct_option_id'])
        old_ids={id(o):o['id'] for o in c['options']}
        rng = random.Random(seed)
        rng.shuffle(c['options'])
        for index, option in enumerate(c['options']):
            option['id'] = ids[index]
        c['correct_option_id'] = c['answer'] = right['id']
        if benchmark:
            from .abilities import remap_distractors
            remap_distractors(c,{old_ids[id(o)]:o['id'] for o in c['options']})
    c.update({'id': digest([video['id'], plan['request_id'], c['slot_id']])[:32],
              'branch': plan['branch'], 'phase': plan['phase'], 'video_id': video['id'],
              'facts': [fact_map[key] for key in required], 'evidence_windows': selected})
    return c


def validate_gate(response, frames):
    if not isinstance(response, dict) or response.get('decision') not in ('pass', 'reject', 'uncertain'):
        return False, 'invalid_caption_gate_decision'
    claims = response.get('claims')
    ids = {item['id'] for item in frames}
    if not isinstance(claims, list) or not claims:
        return False, 'incomplete_caption_gate'
    for claim in claims:
        if (not isinstance(claim, dict) or not isinstance(claim.get('claim'), str) or not claim['claim'].strip()
                or claim.get('status') not in ('supported', 'contradicted', 'insufficient')
                or not isinstance(claim.get('frame_ids'), list)
                or any(not isinstance(frame_id, str) for frame_id in claim['frame_ids'])
                or not set(claim['frame_ids']) <= ids
                or (claim['status'] != 'insufficient' and not claim['frame_ids'])):
            return False, 'invalid_caption_gate_claim'
    if response['decision'] != 'pass':
        return False, str(response.get('primary_reason') or 'caption_visual_reject')[:160]
    if response.get('critical_claims_complete') is not True:
        return False, 'incomplete_caption_gate'
    if any(claim['status'] != 'supported' for claim in claims):
        return False, 'unsupported_caption_claim'
    return True, 'caption_gate_pass'


def covered_by_windows(start, end, windows):
    """Require full coverage by this fact's windows, without bridging any gap."""
    start, end = float(start), float(end)
    if not math.isfinite(start) or not math.isfinite(end) or start >= end:
        return False
    intervals = sorted((float(w['start']), float(w['end'])) for w in windows)
    if any(not math.isfinite(a) or not math.isfinite(b) or a >= b for a, b in intervals):
        return False
    cursor = start
    for a, b in intervals:
        if b <= cursor:
            continue
        if a > cursor:
            return False
        cursor = max(cursor, b)
        if cursor >= end:
            return True
    return False


def validate_audit(response, candidate, video):
    if response.get('decision') != 'pass':
        return False, str(response.get('primary_reason') or 'visual_audit_reject')[:160]
    checks = response.get('checks')
    if not isinstance(checks, dict) or set(checks) != set(CHECKS):
        return False, 'incomplete_audit_checks'
    must_pass = set(CHECKS) - {'multi_segment_necessity', 'mcq_unique', 'temporal_grounding', 'entity_identity'}
    contract=candidate.get('task_contract')
    required_windows=contract['minimum_windows'] if contract else (3 if candidate['task'] in ('event_timeline','hierarchical_summary') else 2 if candidate['branch']=='long' else 1)
    if required_windows>1:
        must_pass.add('multi_segment_necessity')
    if candidate['question_type'] == 'mcq':
        must_pass.add('mcq_unique')
    if candidate['task'] in ('event_order', 'state_change', 'temporal_comparison', 'cross_segment_qa', 'event_timeline', 'hierarchical_summary'):
        must_pass.add('temporal_grounding')
    if candidate['task'] in ('entity_attribute', 'spatial_relation', 'state_change', 'temporal_comparison', 'cross_segment_qa'):
        must_pass.add('entity_identity')
    if contract:
        if required_windows>1 or contract['operation'] in ('sequence_ordering','state_change','comparison','qualitative_motion',
                      'causal_link','interaction','turning_point','coarse_location','timeline','hierarchical_summary'):
            must_pass.add('temporal_grounding')
        if contract['operation'] not in ('synopsis','hierarchical_summary','timeline'):
            must_pass.add('entity_identity')
    if any(value not in ('pass', 'not_applicable') for value in checks.values()) or any(checks[key] != 'pass' for key in must_pass):
        return False, 'failed_or_insufficient_audit_check'
    evidence = response.get('evidence')
    if not isinstance(evidence, list) or not evidence:
        return False, 'missing_visual_support'
    try:
        if any(not 0 <= float(item['start']) < float(item['end']) <= video['duration'] for item in evidence):
            return False, 'audit_time_out_of_bounds'
        if {item['fact_id'] for item in evidence} != {f['fact_id'] for f in candidate['facts']}:
            return False, 'audit_missing_required_fact_support'
        window_map = {w['id']: w for w in candidate['evidence_windows']}
        fact_map = {f['fact_id']: f for f in candidate['facts']}
        for item in evidence:
            supported = [window_map[w] for w in fact_map[item['fact_id']]['evidence_window_ids']]
            if not covered_by_windows(item['start'], item['end'], supported):
                return False, 'audit_support_outside_claimed_window'
        if candidate['branch'] == 'long' or contract:
            required_count = required_windows
            nonoverlap = []
            for item in sorted(evidence, key=lambda v: float(v['start'])):
                if not nonoverlap or float(item['start']) >= float(nonoverlap[-1]['end']):
                    nonoverlap.append(item)
            if len(nonoverlap) < required_count:
                return False, 'audit_missing_distinct_necessary_segments'
            if (contract or {}).get('global_coverage',candidate['task']=='hierarchical_summary'):
                thirds = {min(2, int((float(w['start']) + float(w['end'])) / 2 / (video['duration'] / 3))) for w in evidence}
                if thirds != {0, 1, 2}:
                    return False, 'audit_missing_global_coverage'
    except (KeyError, TypeError, ValueError):
        return False, 'invalid_visual_support'
    from .abilities import validate_capability_audit
    valid,reason=validate_capability_audit(response,candidate)
    return (True,'visual_audit_pass') if valid else (False,reason)
