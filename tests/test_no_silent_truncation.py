"""Incident regressions with synthetic media/responses only; no model APIs."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_sft_builder.builds import create_build, execute_build, load_build
from video_sft_builder.caption_plan import caption_plan, preflight
from video_sft_builder.completion import completion
from video_sft_builder.config import RuntimeConfig
from video_sft_builder.errors import Blocked, PipelineError, ProtocolError, UnknownExecution
from video_sft_builder.media import enumerate_mp4
from video_sft_builder.pipeline import Pipeline
from video_sft_builder.provider import ModelGateway
from video_sft_builder.recovery import recover_build
from video_sft_builder.reporting import export_candidates, report
from video_sft_builder.settings import Settings
from video_sft_builder.state import Store
from video_sft_builder.synthetic import SyntheticMedia, SyntheticProvider, create_inputs
from video_sft_builder.terminal import Console, Workbench
from video_sft_builder.util import canonical, digest, file_digest, read_json, strict_json, write_json


class SecondResponse(SyntheticProvider):
    def __init__(self, *, recoverable=True):
        super().__init__()
        self.recoverable = recoverable

    def send(self, body):
        raw = super().send(body)
        if body['role'] == 'A1' and body['context']['visual_window']['id'] == 'w_000001':
            raw['choices'][0]['message']['content'] = (
                '{"description":"synthetic second clip", "uncertain_details":["unreadable detail"], "uncertain_details":[]}'
                if self.recoverable else '{"description":"first", "description":"conflicting", "uncertain_details":[]}')
        return raw


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[2] / 'video-sft-integrity-tests'
        base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = Settings(self.root / 'private/config.json')
        self.settings.data['output_dir'] = str(self.root / 'builds')
        self.settings.save()
        self.build = create_build(self.settings, 'test', synthetic=True, now=datetime(2026, 10, 22, 9, 6))
        _, _, self.cfg = load_build(self.build)
        create_inputs(self.cfg)
        # Isolate exactly one 60.026693-second synthetic source.
        data = deepcopy(self.cfg.data)
        data['input']['allowlist'] = ['simulation_60.mp4']
        self.cfg = RuntimeConfig(data, self.cfg.path)
        self.cfg.path.write_text(canonical(data), encoding='utf-8')
        source = Path(data['input']['root']) / 'simulation_60.mp4'
        source.write_text(canonical({'duration': 60.026693, 'synthetic_not_a_playable_video': True}), encoding='utf-8')

    def store(self, cfg=None):
        value = Store(cfg or self.cfg)
        self.addCleanup(value.close)
        return value

    def test_complete_plan_merges_tail_without_dropping_time_or_changing_fps(self):
        p = caption_plan(self.cfg, {'id': 'v', 'duration': 60.026693})
        self.assertEqual((len(p['l1']), len(p['l2'])), (6, 2))
        self.assertEqual(p['l1'][-1], {'id': 'w_000005', 'start': 50, 'end': 60.026693})
        self.assertEqual(p['l2'][-1], {'id': 'b_000001', 'start': 30, 'end': 60.026693})
        for duration in (2, 9, 10, 10.01, 20.1, 29.999, 30, 30.001, 31.9, 32, 59, 60, 60.026693, 3600.04):
            p = caption_plan(self.cfg, {'id': 'v', 'duration': duration})
            for level in ('l1', 'l2'):
                self.assertEqual(p[level][0]['start'], 0)
                self.assertEqual(p[level][-1]['end'], duration)
                self.assertAlmostEqual(sum(w['end'] - w['start'] for w in p[level]), duration)
                self.assertTrue(all(a['end'] == b['start'] for a, b in zip(p[level], p[level][1:])))

    def test_duplicate_uncertainty_is_lossless_and_other_fields_stay_strict(self):
        text = '{"description":"synthetic", "uncertain_details":["a","b"], "uncertain_details":["b","c"]}'
        with self.assertRaises(ValueError):
            strict_json(text)
        raw = {'choices': [{'finish_reason': 'stop', 'message': {'content': text}}]}
        value = ModelGateway._decode(raw, role='A1')
        self.assertEqual(value['uncertain_details'], ['a', 'b', 'c'])
        self.assertTrue(value.normalization)
        for role in (None, 'A3', 'A7'):
            with self.assertRaises(ProtocolError):
                ModelGateway._decode(raw, role=role)
        for text in ('{"description":"a","description":"b","uncertain_details":[]}',
                     '{"description":"a","uncertain_details":[1],"uncertain_details":[]}',
                     '{"description":"a","uncertain_details":{"x":1,"x":2}}'):
            raw['choices'][0]['message']['content'] = text
            with self.assertRaises(ProtocolError):
                ModelGateway._decode(raw, role='A1')

    def test_original_failure_shape_now_finishes_full_coverage_no_retry(self):
        store, provider = self.store(), SecondResponse()
        pipe = Pipeline(self.cfg, store, media=SyntheticMedia(self.cfg), provider=provider)
        pipe.run()
        roles = [b['role'] for b in provider.sent]
        self.assertEqual((roles.count('A1'), roles.count('A2')), (6, 2))
        self.assertEqual(completion(store)['status'], 'complete')
        self.assertEqual(len(store.records('response_normalization')), 1)
        bundle = store.records('caption_bundle')[0]['payload']
        self.assertEqual(bundle['l3']['end'], 60.026693)
        self.assertEqual(bundle['l1'][1]['uncertain_details'], ['unreadable detail'])
        raw = store.request(bundle['l1'][1]['request_id'])['response']['choices'][0]['message']['content']
        self.assertEqual(raw.count('"uncertain_details"'), 2)
        calls = len(provider.sent)
        pipe.run()
        self.assertEqual(len(provider.sent), calls)

    def test_conflicting_description_stops_and_reports_missing_units(self):
        store, provider = self.store(), SecondResponse(recoverable=False)
        Pipeline(self.cfg, store, media=SyntheticMedia(self.cfg), provider=provider).run()
        self.assertEqual(len(provider.sent), 2)
        p = completion(store)
        self.assertEqual(p['status'], 'incomplete')
        v = p['videos'][0]
        self.assertEqual((v['l1_completed'], v['l1_expected'], v['l2_completed'], v['l2_expected']), (1, 6, 0, 2))
        self.assertEqual(v['stop']['unit_id'], 'w_000001')
        self.assertEqual(v['stop']['role'], 'A1')
        directory, summary = report(store)
        self.assertIn('INCOMPLETE', (directory / 'report.md').read_text(encoding='utf-8'))
        exported = export_candidates(store)
        self.assertEqual(read_json(exported / 'manifest.json')['execution_status'], 'incomplete')
        # Missing events alone may never make an incomplete build green.
        store.db.execute('DELETE FROM events')
        store.db.commit()
        self.assertEqual(completion(store)['status'], 'incomplete')

    def test_all_windows_preflight_before_any_paid_call(self):
        data = deepcopy(self.cfg.data)
        data['teacher']['roles']['A2']['max_frames'] = 60
        cfg = RuntimeConfig(data, self.cfg.path)
        store, provider = self.store(cfg), SyntheticProvider()
        Pipeline(cfg, store, media=SyntheticMedia(cfg), provider=provider).run(through='caption')
        # Final L2 30.026693 * 2 exceeds 60: blocked upfront, never drop tail.
        self.assertEqual(provider.sent, [])
        self.assertEqual(completion(store)['status'], 'incomplete')

    def test_incomplete_cached_bundle_cannot_enter_gate_or_qa(self):
        store, provider = self.store(), SyntheticProvider()
        pipe = Pipeline(self.cfg, store, media=SyntheticMedia(self.cfg), provider=provider)
        video = pipe.prepare()[0]
        bundle = pipe.caption(video)
        broken = deepcopy(bundle)
        broken['l1'].pop()
        store.db.execute('UPDATE records SET payload=? WHERE key=?', (canonical(broken), 'caption_bundle:' + video['id']))
        store.db.commit()
        pipe.run()
        self.assertNotIn('C_GATE', [b['role'] for b in provider.sent])
        self.assertEqual(completion(store)['status'], 'incomplete')

    def test_input_limit_is_explicit_failure_not_silent_first_n(self):
        data = deepcopy(self.cfg.data)
        data['input']['allowlist'] = []
        data['run']['max_videos'] = 1
        with self.assertRaisesRegex(Blocked, 'input_exceeds_max_videos'):
            enumerate_mp4(RuntimeConfig(data, self.cfg.path))

    def test_ui_failure_panel_and_nonzero_exit_after_incomplete_run(self):
        commands = iter(['/run all', '/quit'])
        output = io.StringIO()
        ui = Workbench(self.settings, console=Console(output=output, plain=True), input_fn=lambda _: next(commands))
        ui.current = self.build
        outcome = {'status': 'incomplete', 'auto_passed': 0, 'pending_entities': 2, 'export': 'exports', 'report': 'reports',
                   'completion': {'failures': [{'role': 'A1', 'unit_id': 'w_000001'}]}}
        with patch('video_sft_builder.terminal.execute_build', return_value=outcome):
            code = ui.loop()
        self.assertEqual(code, 2)
        self.assertIn('未完成', output.getvalue())
        self.assertNotIn('本阶段完成', output.getvalue())

    def test_execute_build_persists_incomplete_status_and_stop_location(self):
        with patch('video_sft_builder.builds.SyntheticProvider', return_value=SecondResponse(recoverable=False)):
            value = execute_build(self.build)
        self.assertEqual(value['status'], 'incomplete')
        saved = read_json(self.build / 'status.json')
        self.assertEqual(saved['completion']['videos'][0]['stop']['unit_id'], 'w_000001')
        self.assertEqual(saved['completion']['videos'][0]['l1_completed'], 1)

    def test_ui_frozen_config_failure_also_returns_nonzero(self):
        commands = iter(['/run all', '/quit'])
        ui = Workbench(self.settings, console=Console(output=io.StringIO(), plain=True), input_fn=lambda _: next(commands))
        ui.current = self.build
        with patch('video_sft_builder.terminal.load_build', side_effect=PipelineError('frozen_config_invalid')):
            self.assertEqual(ui.loop(), 2)

    def test_initialization_error_cannot_leave_previous_success_status(self):
        write_json(self.build / 'status.json', {'status': 'complete', 'through': 'prepare'})
        with patch('video_sft_builder.builds.create_inputs', side_effect=PipelineError('synthetic_initialization_failed')):
            with self.assertRaises(PipelineError):
                execute_build(self.build)
        saved = read_json(self.build / 'status.json')
        self.assertEqual(saved['status'], 'error')
        self.assertEqual(saved['through'], 'all')
        self.assertEqual(saved['error_code'], 'synthetic_initialization_failed')

    def test_missing_branch_marker_never_passes_completion_even_with_video_done(self):
        store = self.store()
        Pipeline(self.cfg, store, media=SyntheticMedia(self.cfg), provider=SyntheticProvider()).run()
        self.assertEqual(completion(store)['status'], 'complete')
        store.db.execute("DELETE FROM events WHERE stage='branch'")
        store.db.commit()
        self.assertEqual(completion(store)['status'], 'incomplete')

    def test_truncated_caption_response_cannot_produce_l3_or_gate(self):
        class Truncated(SyntheticProvider):
            def send(self, body):
                raw = super().send(body)
                raw['choices'][0]['finish_reason'] = 'length'
                return raw
        store, provider = self.store(), Truncated()
        Pipeline(self.cfg, store, media=SyntheticMedia(self.cfg), provider=provider).run()
        self.assertEqual(len(provider.sent), 1)
        self.assertEqual(store.records('caption_bundle'), [])
        self.assertEqual(completion(store)['status'], 'incomplete')

    def test_old_paid_caption_recovery_keeps_charges_and_raw_state(self):
        store, provider = self.store(), SecondResponse()
        # Simulate old strict parser stopping after the malformed second reply.
        original = ModelGateway._decode
        def old_decode(raw, *, role=None):
            return original(raw)
        with patch.object(ModelGateway, '_decode', side_effect=old_decode):
            Pipeline(self.cfg, store, media=SyntheticMedia(self.cfg), provider=provider).run()
        self.assertEqual(len(provider.sent), 2)
        db_path = self.cfg.state_dir / 'state.sqlite3'
        # Simulate an actual code-upgrade fingerprint, without bypassing it.
        old_identity = read_json(self.build / 'code_and_asset_identity.json')
        old_identity['code']['pipeline.py'] = 'old-implementation-hash'
        (self.build / 'code_and_asset_identity.json').write_text(canonical(old_identity), encoding='utf-8')
        with store.db:
            store.db.execute("UPDATE metadata SET value=? WHERE key='config_hash'", (digest([self.cfg.data, old_identity]),))
        old_checksum = file_digest(db_path)
        new_root = recover_build(self.build, 'fixed', now=datetime(2026, 10, 22, 12), require_clean=False)
        self.assertEqual(file_digest(db_path), old_checksum)
        _, _, cfg = load_build(new_root)
        new_store, new_provider = self.store(cfg), SyntheticProvider()
        Pipeline(cfg, new_store, media=SyntheticMedia(cfg), provider=new_provider).run()
        # Eight caption units; exactly two reused, six new requests.
        self.assertEqual(sum(b['role'] in ('A1', 'A2') for b in new_provider.sent), 6)
        self.assertEqual(completion(new_store)['status'], 'complete')
        self.assertEqual(len(new_store.records('response_normalization')), 1)
        self.assertEqual(len(new_store.request_rows()), len(new_provider.sent) + 2)
        self.assertEqual(file_digest(db_path), old_checksum)
        self.assertEqual(read_json(new_root / 'artifacts/recovery_provenance.json')['historical_request_count'], 2)
        for old in store.request_rows():
            new = next(r for r in new_store.request_rows() if r['id'] == old['id'])
            self.assertEqual(new, old)

    def test_recovery_context_mismatch_blocks_without_new_calls(self):
        store, provider = self.store(), SecondResponse()
        original = ModelGateway._decode
        with patch.object(ModelGateway, '_decode', side_effect=lambda raw, **_: original(raw)):
            Pipeline(self.cfg, store, media=SyntheticMedia(self.cfg), provider=provider).run()
        new_root = recover_build(self.build, 'changed_context', require_clean=False)
        _, _, cfg = load_build(new_root)
        new_store, new_provider = self.store(cfg), SyntheticProvider()
        pipe = Pipeline(cfg, new_store, media=SyntheticMedia(cfg), provider=new_provider)
        pipe.prompts['caption'] += '\nCHANGED PROMPT'
        pipe.run()
        self.assertEqual(new_provider.sent, [])
        self.assertEqual(completion(new_store)['status'], 'incomplete')
        self.assertIn('no_automatic_rebill', completion(new_store)['failures'][0]['reason'])

    def test_unknown_paid_execution_cannot_be_recovered_or_resent(self):
        store = self.store()
        class Uncertain(SyntheticProvider):
            def send(self, body):
                super().send(body)
                raise TimeoutError()
        with self.assertRaises(UnknownExecution):
            Pipeline(self.cfg, store, media=SyntheticMedia(self.cfg), provider=Uncertain()).run()
        with self.assertRaisesRegex(PipelineError, 'resolved caption-only'):
            recover_build(self.build, 'refused', require_clean=False)

    def test_readonly_evidence_script_replays_without_rewriting_source(self):
        import subprocess
        store = self.store()
        Pipeline(self.cfg, store, media=SyntheticMedia(self.cfg), provider=SecondResponse()).run(through='caption')
        checksum = file_digest(self.cfg.state_dir / 'state.sqlite3')
        script = Path(__file__).resolve().parents[1] / 'scripts/check_caption_evidence.py'
        result = subprocess.run([sys.executable, str(script), '--build', str(self.build)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout.splitlines()[0])
        self.assertEqual(value['new_model_calls'], 0)
        self.assertEqual(sum(r['normalized'] for r in value['responses']), 1)
        self.assertEqual(file_digest(self.cfg.state_dir / 'state.sqlite3'), checksum)
