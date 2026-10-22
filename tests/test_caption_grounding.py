"""Caption incident regressions with fictional text and synthetic media only."""
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_sft_builder.pipeline import Pipeline
from video_sft_builder.quality import validate_gate
from video_sft_builder.state import Store
from video_sft_builder.synthetic import SyntheticMedia, SyntheticProvider, create_inputs, demo_config


class CaptionGroundingTests(unittest.TestCase):
    def test_previous_summary_uncertainty_and_source_reach_both_roles_without_extra_calls(self):
        base = Path(__file__).resolve().parents[2] / 'video-sft-grounding-tests'
        base.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as folder:
            cfg = demo_config(Path(folder))
            create_inputs(cfg)

            class Provider(SyntheticProvider):
                def send(self, body):
                    raw = super().send(body)
                    if body['role'] == 'A2' and body['context']['visual_window']['start'] == 0:
                        result = json.loads(raw['choices'][0]['message']['content'])
                        result['uncertain_details'] = ['Synthetic early label cannot be read.']
                        raw['choices'][0]['message']['content'] = json.dumps(result)
                    return raw

            provider = Provider()
            with closing(Store(cfg)) as store:
                pipe = Pipeline(cfg, store, media=SyntheticMedia(cfg), provider=provider)
                video = next(v for v in pipe.prepare() if v['duration'] == 60)
                bundle = pipe.caption(video)
                prior = bundle['l2'][0]
                following = [b for b in provider.sent if b['context']['visual_window']['start'] >= 30]
                self.assertEqual({b['role'] for b in following}, {'A1', 'A2'})
                for body in following:
                    self.assertEqual(body['context']['previous_l2'], prior)
                    self.assertEqual(body['context']['previous_l2']['uncertain_details'],
                                     ['Synthetic early label cannot be read.'])
                    self.assertIn('request_id', body['context']['previous_l2'])
                self.assertEqual(len(provider.sent), 8)  # 6 A1 + 2 A2, unchanged.
                self.assertEqual([(b['media'][0]['start'], b['media'][0]['end'])
                                  for b in provider.sent if b['role'] == 'A2'], [(0, 30), (30, 60)])
                self.assertEqual(bundle['l3']['request_id'], bundle['l2'][-1]['request_id'])
                pipe.caption(video)
                self.assertEqual(len(provider.sent), 8)  # exact resume reuses paid units.

    def test_gate_three_way_contract_never_promotes_insufficient_to_pass(self):
        frames = [{'id': 'frame_000000'}]
        good = {'decision': 'pass', 'critical_claims_complete': True,
                'claims': [{'claim': 'A fictional red object.', 'status': 'supported',
                            'frame_ids': ['frame_000000']}], 'primary_reason': 'supported'}
        self.assertEqual(validate_gate(good, frames), (True, 'caption_gate_pass'))
        for status, decision, frame_ids in [('insufficient', 'uncertain', []),
                                             ('contradicted', 'reject', ['frame_000000'])]:
            with self.subTest(status=status):
                value = deepcopy(good)
                value['decision'], value['primary_reason'] = decision, status
                value['claims'][0].update(status=status, frame_ids=frame_ids)
                self.assertEqual(validate_gate(value, frames), (False, status))
                value['decision'] = 'pass'
                self.assertEqual(validate_gate(value, frames), (False, 'unsupported_caption_claim'))

    def test_malformed_or_invented_gate_labels_fail_closed(self):
        frames = [{'id': 'frame_000000'}]
        good = {'decision': 'reject', 'critical_claims_complete': True,
                'claims': [{'claim': 'A fictional object.', 'status': 'contradicted',
                            'frame_ids': ['frame_000000']}], 'primary_reason': 'contradiction'}
        for field, value in [('status', 'partially_supported'), ('status', 'unsupported'),
                             ('status', ['supported']), ('claim', ''), ('frame_ids', []),
                             ('frame_ids', 'frame_000000'), ('frame_ids', ['not_a_frame']),
                             ('frame_ids', [{}])]:
            with self.subTest(field=field, value=value):
                bad = deepcopy(good)
                bad['claims'][0][field] = value
                self.assertEqual(validate_gate(bad, frames), (False, 'invalid_caption_gate_claim'))
        for bad in (None, {}, {'decision': 'insufficient'}, {'decision': ['pass']}):
            self.assertEqual(validate_gate(bad, frames), (False, 'invalid_caption_gate_decision'))

    def test_insufficient_gate_stops_qa_without_a_rewatch(self):
        base = Path(__file__).resolve().parents[2] / 'video-sft-grounding-tests'
        base.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as folder:
            cfg = demo_config(Path(folder))
            create_inputs(cfg)

            class Provider(SyntheticProvider):
                def send(self, body):
                    raw = super().send(body)
                    if body['role'] == 'C_GATE':
                        result = {'decision': 'uncertain', 'critical_claims_complete': True,
                                  'claims': [{'claim': 'A fictional moment between samples.',
                                              'status': 'insufficient', 'frame_ids': []}],
                                  'primary_reason': 'insufficient_sampled_evidence'}
                        raw['choices'][0]['message']['content'] = json.dumps(result)
                    return raw

            provider = Provider()
            with closing(Store(cfg)) as store:
                pipe = Pipeline(cfg, store, media=SyntheticMedia(cfg), provider=provider)
                video = next(v for v in pipe.prepare() if v['duration'] == 60)
                bundle = pipe.caption(video)
                self.assertFalse(pipe.caption_gate(video, bundle))
                self.assertFalse(pipe.caption_gate(video, bundle))
                self.assertEqual(len(provider.sent), 9)  # 6 A1 + 2 A2 + 1 gate.
                self.assertFalse(store.records('candidate'))
                self.assertEqual(store.get('caption_gate:' + video['id'])['reason'],
                                 'insufficient_sampled_evidence')


if __name__ == '__main__':
    unittest.main()
