"""Meaningful negative checks for user contracts and statistical failure modes."""
import importlib.util
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('validate_design', ROOT / 'scripts/validate_design.py')
DESIGN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DESIGN)


class DesignTests(unittest.TestCase):
    def setUp(self):
        self.config = DESIGN.load('configs/project.example.json')
        self.registry = DESIGN.load('configs/task_registry.json')
        self.templates = DESIGN.load('configs/question_templates.json')
        self.metrics = DESIGN.load('examples/synthetic_run_metrics.json')
        self.cot_config = DESIGN.load('configs/cot_pipeline.example.json')

    def check_config(self):
        DESIGN.validate_config(self.config, self.registry, self.templates)

    def test_baseline(self):
        self.check_config()
        DESIGN.validate_cot_contract(self.cot_config)
        DESIGN.validate_metrics(self.metrics)

    def test_qa_release_cannot_depend_on_cot(self):
        self.config['cot']['required_for_qa_release'] = True
        with self.assertRaisesRegex(ValueError, 'without a CoT dependency'):
            self.check_config()

    def test_cot_cannot_overwrite_source_qa(self):
        self.cot_config['output']['overwrite_source_qa'] = True
        with self.assertRaisesRegex(ValueError, 'must not overwrite'):
            DESIGN.validate_cot_contract(self.cot_config)

    def test_cot_failure_does_not_invalidate_qa(self):
        self.cot_config['invariants']['cot_failure_affects_source_qa'] = True
        with self.assertRaisesRegex(ValueError, 'cannot invalidate'):
            DESIGN.validate_cot_contract(self.cot_config)

    def test_qa_example_retains_twelve_fields_and_null_cot(self):
        text = (ROOT / 'docs/video_sft_final_json_format_2026-10-20.md').read_text(encoding='utf-8')
        example = json.loads(re.search(r'```json\s*(.*?)\s*```', text, re.S).group(1))
        self.assertEqual(set(example), {'id', 'source', 'conversations', 'task', 'question_type',
                                      'media_info', 'media', 'modal_mask', 'quality', 'cot', 'language', 'tokens'})
        self.assertIsNone(example['cot'])

    def test_caption_reject_cannot_generate_qa(self):
        self.metrics['videos'][1]['general_generated'] = 1
        with self.assertRaisesRegex(ValueError, 'after caption reject'):
            DESIGN.validate_metrics(self.metrics)

    def test_local_only_l2_is_rejected(self):
        self.config['caption']['l2_scope'] = 'last_segment_only'
        with self.assertRaisesRegex(ValueError, 'L2 visual scope'):
            self.check_config()

    def test_long_quality_pass_cannot_be_counted_as_quality_reject(self):
        row = self.metrics['long_by_video'][0]
        row['quality_rejected'] += 1
        with self.assertRaisesRegex(ValueError, 'Long quality conservation'):
            DESIGN.validate_metrics(self.metrics)

    def test_source_pivot_cannot_hide_rejects(self):
        row = self.metrics['source_stage'][8]
        row['passed'], row['rejected'] = 0, 1
        with self.assertRaisesRegex(ValueError, 'Source pivot mismatch'):
            DESIGN.validate_metrics(self.metrics)

    def test_long_cannot_drop_passes_to_the_old_one_sample_cap(self):
        row = self.metrics['long_by_video'][0]
        row['selected'], row['selection_excluded'] = 1, 1
        with self.assertRaisesRegex(ValueError, 'All quality-passed'):
            DESIGN.validate_metrics(self.metrics)

    def test_general_five_and_long_three_can_all_be_retained(self):
        self.assertEqual(self.config['synthesis']['general_candidates_per_video'], 5)
        self.assertEqual(self.config['synthesis']['long_candidate_slots'], 3)
        DESIGN.validate_retention(5, 5, 0)
        DESIGN.validate_retention(3, 3, 0)
        DESIGN.validate_retention(0, 0, 0)

    def test_cannot_restore_the_long_one_sample_cap(self):
        self.config['synthesis']['long_final_max_per_original_video'] = 1
        with self.assertRaisesRegex(ValueError, 'No final per-video retention cap'):
            self.check_config()

    def test_cannot_restore_the_general_three_sample_cap(self):
        self.config['synthesis']['general_final_max_per_original_video'] = 3
        with self.assertRaisesRegex(ValueError, 'No final per-video retention cap'):
            self.check_config()

    def test_cannot_drop_passed_samples_for_quotas(self):
        self.config['synthesis']['drop_quality_passed_for_quotas'] = True
        with self.assertRaisesRegex(ValueError, 'Retain all final quality-passed'):
            self.check_config()

    def test_no_repair_or_retry_restoration(self):
        self.config['pipeline']['audit_sdk_retries'] = 1
        with self.assertRaisesRegex(ValueError, 'without SDK retry'):
            self.check_config()

    def test_template_slot_errors_fail_closed(self):
        self.templates['templates'][0]['required_slots'] = []
        with self.assertRaisesRegex(ValueError, 'Placeholder contract'):
            self.check_config()


if __name__ == '__main__':
    unittest.main()
