"""Offline design/arithmetical checks; not a production scheduler or model test."""
from fractions import Fraction
import heapq
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('scheduler_design_checks', ROOT / 'scripts/validate_design.py')
DESIGN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DESIGN)


class TaskSchedulerContractTests(unittest.TestCase):
    def setUp(self):
        self.cfg = DESIGN.load('configs/task_scheduler.example.json')
        self.example = DESIGN.load('examples/task_scheduler_contract.synthetic.json')

    def test_contract(self):
        DESIGN.validate_task_scheduler(self.cfg)

    def test_min_heap_uses_pending_and_reserved_not_only_passes(self):
        example = self.example['heap_example']
        heap = [(sum(c[k] for k in ['passed', 'pending_generated', 'reserved']), task)
                for task, c in example['tasks'].items()]
        heapq.heapify(heap)
        self.assertEqual(heapq.heappop(heap)[1], example['expected_min_effective_task'])

    def test_language_form_and_mcq_conditional_deficit_examples(self):
        for example in self.example['marginal_examples']:
            counts, weights = example['effective_counts'], example['target_weights']
            total = sum(counts.values())
            deficit = {key: Fraction(weight, sum(weights.values())) * (total + 1) - counts[key]
                       for key, weight in weights.items()}
            self.assertEqual(max(deficit, key=deficit.get), example['expected_choice'])

    def test_fit_stage_can_make_uniform_target_impossible(self):
        e = self.example['balance_impossibility_example']
        self.assertGreater(e['accepted_fit_share'] * e['fit_action_share'], e['target_action_share'])

    def test_attempt_budgets_are_distinct_from_emitted_candidate_caps(self):
        for e in self.example['attempt_budget_examples'].values():
            self.assertEqual(e['active_task_count'] + e['balance_slots'], e['derived_attempt_limit'])
            self.assertGreater(e['derived_attempt_limit'], e['max_emitted_candidates'])

    def test_quality_failure_must_not_be_a_refill_opportunity(self):
        self.cfg['fallback']['allow_refill_after_emitted_candidate_rejection'] = True
        with self.assertRaisesRegex(ValueError, 'never QA reject refill'):
            DESIGN.validate_task_scheduler(self.cfg)

    def test_independent_branch_ratios_are_not_the_global_contract(self):
        self.cfg['marginal_targets']['scope'] = 'each_branch_separately'
        with self.assertRaisesRegex(ValueError, 'batch-global'):
            DESIGN.validate_task_scheduler(self.cfg)

    def test_raw_accepted_only_heap_is_rejected(self):
        self.cfg['task_target']['heap_count_components'] = ['passed']
        with self.assertRaisesRegex(ValueError, 'pending and reserved'):
            DESIGN.validate_task_scheduler(self.cfg)
