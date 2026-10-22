"""Fictional interval regressions; no videos, production payloads or API calls."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_sft_builder.quality import CHECKS, covered_by_windows, render_time, validate_audit


def summary_fixture():
    windows = [{'id': str(i), 'start': i * 15, 'end': (i + 1) * 15} for i in range(6)]
    candidate = {'branch': 'long', 'task': 'hierarchical_summary', 'question_type': 'oe',
                 'facts': [{'fact_id': f'f{i}', 'evidence_window_ids': [str(2 * i), str(2 * i + 1)]}
                           for i in range(3)], 'evidence_windows': windows}
    response = {'decision': 'pass', 'checks': {k: 'pass' for k in CHECKS},
                'evidence': [{'fact_id': f'f{i}', 'start': i * 30, 'end': (i + 1) * 30}
                             for i in range(3)]}
    return candidate, response, {'duration': 90}


class AuditWindowTests(unittest.TestCase):
    def test_adjacent_overlapping_and_unsorted_windows_cover_full_interval(self):
        for windows in ([{'start': 8, 'end': 16}, {'start': 0, 'end': 8}],
                        [{'start': 0, 'end': 10}, {'start': 6, 'end': 16}]):
            self.assertTrue(covered_by_windows(2, 15, windows))
            self.assertTrue(covered_by_windows(0, 16, windows))
            self.assertFalse(covered_by_windows(0, 16.000001, windows))

    def test_gaps_empty_ranges_and_nonfinite_values_are_not_covered(self):
        windows = [{'start': 0, 'end': 8}, {'start': 9, 'end': 16}]
        self.assertFalse(covered_by_windows(0, 16, windows))
        self.assertTrue(covered_by_windows(10, 15, windows))
        self.assertFalse(covered_by_windows(0, 1, []))
        for a, b in ((1, 1), (2, 1), (float('nan'), 1), (0, float('inf'))):
            self.assertFalse(covered_by_windows(a, b, windows))
        self.assertFalse(covered_by_windows(0, 1, [{'start': 0, 'end': float('nan')}]))

    def test_summary_evidence_can_span_adjacent_windows_of_same_fact(self):
        candidate, response, video = summary_fixture()
        self.assertEqual(validate_audit(response, candidate, video), (True, 'visual_audit_pass'))
        for evidence, interval in zip(response['evidence'], [(3, 27), (35, 57), (67, 85)]):
            evidence.update(start=interval[0], end=interval[1])
        self.assertEqual(validate_audit(response, candidate, video), (True, 'visual_audit_pass'))

    def test_no_borrowing_other_facts_windows_and_no_boundary_tolerance(self):
        candidate, response, video = summary_fixture()
        response['evidence'][0]['end'] = 30.000001
        self.assertEqual(validate_audit(response, candidate, video),
                         (False, 'audit_support_outside_claimed_window'))
        response['evidence'][0]['end'] = 30
        candidate['facts'][0]['evidence_window_ids'] = ['0']
        self.assertEqual(validate_audit(response, candidate, video),
                         (False, 'audit_support_outside_claimed_window'))

    def test_declared_gap_cannot_be_filled_by_bounding_box(self):
        candidate, response, video = summary_fixture()
        candidate['evidence_windows'][0]['end'] = 10
        self.assertEqual(validate_audit(response, candidate, video),
                         (False, 'audit_support_outside_claimed_window'))

    def test_original_bounds_and_model_reject_still_apply(self):
        candidate, response, video = summary_fixture()
        response['evidence'][2]['end'] = 90.1
        self.assertEqual(validate_audit(response, candidate, video), (False, 'audit_time_out_of_bounds'))
        response['evidence'][2]['end'] = 90
        response.update(decision='reject', primary_reason='synthetic_visual_reject')
        self.assertEqual(validate_audit(response, candidate, video), (False, 'synthetic_visual_reject'))

    def test_absolute_time_noun_phrases_do_not_add_duplicate_prepositions(self):
        windows = {'later': {'start': 75, 'end': 85}}
        for seed in range(30):
            zh = render_time('在[[TIME:later]]中，物体有什么变化？', windows, 'zh', seed)
            en = render_time('What changes in [[TIME:later]]?', windows, 'en', seed)
            self.assertNotIn('在在', zh)
            self.assertNotIn('in in', en)
            self.assertIn('00:01:15', zh)
            self.assertIn('00:01:25', en)
            self.assertNotIn('[[', zh + en)


if __name__ == '__main__':
    unittest.main()
