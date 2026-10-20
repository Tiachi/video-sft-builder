"""Read-only design contract checks. No media, network, model or dataset validation.

Run as a child process: python3 scripts/validate_design.py
Reads the explicit repository configuration and tiny synthetic fixture only.
Writes nothing; emits PASS/FAIL. Safe to rerun; never produces a release.
"""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ('input', 'passed', 'rejected', 'pending', 'selection_excluded')


def load(relative):
    return json.loads((ROOT / relative).read_text(encoding='utf-8'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_config(cfg, registry, library):
    recipe, pipeline = cfg['dataset_recipe'], cfg['pipeline']
    for key, expected in [('language_weights', {'zh': 3, 'en': 7}),
                          ('question_type_weights', {'oe': 7, 'mcq': 3}),
                          ('mcq_option_count_weights', {'3': 1, '4': 7, '6': 2})]:
        require(recipe[key] == expected, 'User ratio changed: ' + key)
    require(recipe['pipeline_weights'] is None, 'Branch ratio was not confirmed')
    require(recipe['mcq_correct_answers'] == 1, 'MCQ must be single-answer')
    require(not pipeline['a4_enabled'] and not pipeline['a10_enabled'], 'Removed API role enabled')
    for key in ['repair_rejected_samples', 'rewatch_after_audit_failure', 'regenerate_after_audit_failure']:
        require(pipeline[key] is False, 'Forbidden failure loop: ' + key)
    require(pipeline['audit_max_requests_per_sample'] == 1 and pipeline['audit_sdk_retries'] == 0,
            'QA audit must be at most one request without SDK retry')
    require(pipeline['caption_gate_max_requests_per_video'] == 1
            and pipeline['caption_gate_sdk_retries'] == 0, 'Caption check request policy')
    caption, synthesis = cfg['caption'], cfg['synthesis']
    require(caption['l2_visual'] and caption['l2_scope'] == 'cumulative_original_prefix', 'L2 visual scope')
    require(caption['l3_sparse_visual_check'] and pipeline['caption_gate_before_qa'], 'L3 gate missing')
    require(caption['gate_failure_qa_count'] == 0, 'Caption reject must precede QA')
    require(synthesis['long_candidate_slots'] == 3 and synthesis['long_final_max_per_original_video'] == 1,
            'Long 3 candidates / max 1 final contract')
    require(synthesis['general_candidates_per_video'] is None, 'General count is not yet decided')
    require(not synthesis['regenerate_to_fill_slots'], 'No slot refilling')
    require(cfg['cot']['method'] is None and cfg['cot']['supervised'] is None, 'CoT pending contract')
    require(cfg['teacher_api']['model'] is None, 'Example model is not production configuration')
    require(cfg['output']['top_level_field_count'] == 12, 'Final field count')
    names = [t['name'] for t in registry['tasks']]
    require(len(names) == len(set(names)) == 17, '17 unique compatible task names required')
    families = {'visual_perception', 'action_understanding', 'temporal_understanding',
                'evidence_reasoning', 'long_video_understanding', 'temporal_retrieval'}
    require(all(t.get('family') in families and 'category' not in t for t in registry['tasks']),
            'Use existing task.family contract, not a new category field')
    enabled = {t['name']: t for t in registry['tasks'] if t['status'] == 'proposed_enabled'}
    require(len(enabled) == 12, 'Expected 12 proposed enabled tasks')
    for branch, count in [('general', 9), ('long', 3)]:
        group = [t for t in enabled.values() if t['branch'] == branch]
        require(len(group) == count and sum(t['target_weight'] for t in group) == 100,
                'Branch tasks/soft weights mismatch: ' + branch)
    require(all(t['name'] not in enabled for t in registry['tasks']
                if t['name'] in {'visible_text', 'fine_grained_motion', 'action_count'}), 'Unsupported task enabled')
    templates = library['templates']
    require(len(templates) == 192, 'Expected 192 authored stems, not 384 unique stems')
    require(len({t['template_id'] for t in templates}) == len(templates), 'Duplicate template ID')
    for name in enabled:
        for language in ['zh', 'en']:
            group = [t for t in templates if t['task'] == name and t['language'] == language]
            require(len(group) == 8 and len({t['stem'] for t in group}) == 8, '8 distinct stems per task/language')
    for template in templates:
        require(template['task'] in enabled, 'Template for disabled/unknown task')
        slots = set(re.findall(r'\{([a-z_]+)\}', template['stem']))
        require(slots == set(template['required_slots']), 'Placeholder contract: ' + template['template_id'])
        require(set(template['supported_question_types']) == {'oe', 'mcq'}, 'Question form contract')


def validate_metrics(metrics):
    require(metrics['synthetic'] and not metrics['production_run'], 'Fixture must be explicitly synthetic')
    stages = {row['stage']: row for row in metrics['stages']}
    require(len(stages) == len(metrics['stages']), 'Duplicate stage summary')
    source_keys = [(r['source'], r['stage']) for r in metrics['source_stage']]
    require(len(set(source_keys)) == len(source_keys), 'Duplicate source-stage cell')
    for row in metrics['stages'] + metrics['source_stage']:
        require(all(type(row[k]) is int and row[k] >= 0 for k in FIELDS), 'Counts must be nonnegative integers')
        require(row['input'] == sum(row[k] for k in FIELDS if k != 'input'), 'Stage conservation: ' + row['stage'])
    for name, row in stages.items():
        grouped = [r for r in metrics['source_stage'] if r['stage'] == name]
        require(grouped and all(r['unit'] == row['unit'] for r in grouped), 'Stage units')
        for key in FIELDS:
            require(sum(r[key] for r in grouped) == row[key], 'Source pivot mismatch: ' + name + '/' + key)
    require(all(r['stage'] in stages for r in metrics['source_stage']), 'Unknown source stage')
    videos = {v['video_id']: v for v in metrics['videos']}
    require(len(videos) == len(metrics['videos']), 'Duplicate video identity')
    for video in videos.values():
        require(all(type(video[k]) is int and video[k] >= 0 for k in ['general_generated', 'long_generated']), 'QA counts')
        if not video['caption_passed']:
            require(video['general_generated'] + video['long_generated'] == 0, 'QA generated after caption reject')
    require(len(videos) == stages['caption_gate']['input'], 'Caption video denominator')
    require(sum(v['caption_passed'] for v in videos.values()) == stages['caption_gate']['passed'], 'Caption passes')
    require(sum(v['general_generated'] + v['long_generated'] for v in videos.values()) == stages['qa_local']['input'],
            'QA expansion count')
    for row in metrics['long_by_video']:
        require(row['video_id'] in videos, 'Unknown Long video')
        require(row['requested_slots'] == 3, 'Long requested slots')
        require(row['generated'] == videos[row['video_id']]['long_generated'], 'Long generated identity')
        require(row['generated'] + row['abstained_slots'] + row['technical_missing_slots'] == 3, 'Long slot conservation')
        require(row['generated'] == row['passed'] + row['quality_rejected'], 'Long quality conservation')
        require(row['selected'] <= 1 and row['selected'] == min(row['passed'], 1), 'Long final max / selection')
        require(row['passed'] == row['selected'] + row['selection_excluded'], 'Long selection accounting')
    require(stages['qa_local']['passed'] == stages['qa_audit']['input'], 'Local to A7')
    require(stages['qa_audit']['passed'] == stages['qa_selection']['input'], 'A7 to selection')
    selected = metrics['selected']
    require(selected['total'] == stages['qa_selection']['passed'], 'Selected total')
    for dimension in ['branch', 'language', 'question_type']:
        require(sum(selected[dimension].values()) == selected['total'], 'Final marginal: ' + dimension)
    require(sum(selected['mcq_options'].values()) == selected['question_type']['mcq'], 'MCQ conditional denominator')
    require(sum(r['selected'] for r in metrics['long_by_video']) == selected['branch']['long'], 'Long branch total')
    require(metrics['api']['qa_audit_requests'] <= stages['qa_audit']['input'], 'More than one audit per QA')
    require(metrics['api']['caption_gate_requests'] <= stages['caption_gate']['input'], 'More than one caption gate')
    require(not metrics['complete_release'] and metrics['release_blockers'], 'Synthetic example cannot release')


def main():
    try:
        validate_config(load('configs/project.example.json'), load('configs/task_registry.json'),
                        load('configs/question_templates.json'))
        validate_metrics(load('examples/synthetic_run_metrics.json'))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print('FAIL: design/fixture consistency:', exc)
        return 1
    print('PASS: design configuration, 17 task entries, 192 template stems, synthetic accounting')
    print('SCOPE: no production media/API/CoT/processor or training-data quality validation')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
