"""Behavior and failure-injection tests; all model responses/media are synthetic."""
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import json
import shutil
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_sft_builder.config import RuntimeConfig, template, validate_config
from video_sft_builder.errors import Blocked, BudgetBreach, ConfigError, PipelineError, ProtocolError, UnknownExecution
from video_sft_builder.media import FFmpegMedia, enumerate_mp4, gray_metrics, windows
from video_sft_builder.pipeline import Pipeline
from video_sft_builder.provider import ModelGateway, QwenCompatibleProvider
from video_sft_builder.quality import clean_text, compile_ordering, render_time, validate_audit
from video_sft_builder.reporting import FINAL_FIELDS, candidate_records, export_candidates, report
from video_sft_builder.scheduler import Scheduler, deficit_choice
from video_sft_builder.state import Store
from video_sft_builder.synthetic import SyntheticMedia, SyntheticProvider, create_inputs, demo_config
from video_sft_builder.util import atomic_write, coordinator_lock, strict_json


class MutatedProvider(SyntheticProvider):
    def __init__(self, mutate):
        super().__init__()
        self.mutate = mutate

    def send(self, body):
        raw = super().send(body)
        result = json.loads(raw['choices'][0]['message']['content'])
        self.mutate(body, result, raw)
        raw['choices'][0]['message']['content'] = json.dumps(result)
        return raw


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        # Tiny temporary fixtures only; no repository/user videos or network.
        base = Path(__file__).resolve().parents[2] / 'video-sft-runtime-tests'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='video-sft-unit-', dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = demo_config(self.root)
        create_inputs(self.config)
        self.store = None

    def open(self, **changes):
        data = deepcopy(self.config.data)
        for section, values in changes.items():
            data[section].update(values)
        validate_config(data, allow_synthetic=True)
        self.config = RuntimeConfig(data, self.config.path)
        self.store = Store(self.config)
        self.addCleanup(self.store.close)
        return self.store

    def pipeline(self, provider=None):
        return Pipeline(self.config, self.store, media=SyntheticMedia(self.config), provider=provider or SyntheticProvider())

    def test_full_pipeline_counts_views_and_resume_no_additional_calls(self):
        store = self.open(input={'source_by_prefix': {'simulation_30.mp4': 'source_a', 'simulation_60.mp4': 'source_b'}})
        provider = SyntheticProvider()
        self.pipeline(provider).run()
        # 30 s:3 L1+1 L2+16=20; 60 s:6+2+16=24.
        self.assertEqual(Counter(b['role'] for b in provider.sent),
                         {'A1': 9, 'A2': 3, 'C_GATE': 2, 'A3': 8, 'A5': 6, 'A7': 16})
        rows = candidate_records(store)
        self.assertEqual({k: len(v) for k, v in rows.items()}, {'general': 10, 'long': 6})
        for values in rows.values():
            for row in values:
                self.assertEqual(set(row), FINAL_FIELDS)
                self.assertEqual(row['modal_mask'], 4)
                self.assertIsNone(row['cot'])
                self.assertEqual(row['tokens']['status'], 'pending')
                self.assertIsNone(row['media_info']['caption_sampling']['num_frames'])
                if row['question_type']['type'] == 'mcq':
                    labels = [o['id'] for o in row['question_type']['options']]
                    self.assertIn(row['conversations'][1]['value'], labels)
        a2 = [b for b in provider.sent if b['role'] == 'A2']
        last = next(b for b in a2 if b['context']['visual_window']['start'] == 30)
        self.assertEqual((last['media'][0]['start'], last['media'][0]['end']), (30, 60))
        self.assertEqual(last['context']['cumulative_text_range'], {'start': 0, 'end': 60})
        for body in (b for b in provider.sent if b['role'] == 'A7'):
            self.assertEqual(len(body['media']), 1)
            self.assertEqual(body['media'][0]['start'], 0)
            self.assertEqual(body['media'][0]['end'], body['context']['duration'])
            self.assertEqual(Path(body['media'][0]['path']).parent, Path(self.config.data['input']['root']))
        destination = export_candidates(store)
        report_dir, summary = report(store)
        self.assertEqual(summary['auto_passed'], 16)
        self.assertEqual({r['source'] for r in summary['source_by_stage']}, {'source_a', 'source_b'})
        self.assertEqual(summary['actual_cost'], str(Decimal('44') * Decimal('0.00134')))
        self.assertIsNone(summary['human_accuracy'])
        self.assertEqual(summary['held_unknown_or_reserved_cost'], '0')
        for row in summary['source_by_stage']:
            self.assertEqual(row['input'], row['passed'] + row['rejected'] + row['pending'])
        self.assertFalse(any(e['decision'] == 'pending' for e in store.latest_events()))
        self.pipeline(provider).run()
        self.assertEqual(len(provider.sent), 44)
        self.assertEqual(export_candidates(store), destination)
        self.assertEqual(report(store)[0], report_dir)

    def test_caption_reject_creates_zero_qa_and_no_generation_calls(self):
        self.open()
        def reject(body, result, _):
            if body['role'] == 'C_GATE':
                result['decision'] = 'insufficient'
        p = MutatedProvider(reject)
        self.pipeline(p).run()
        self.assertFalse(self.store.records('candidate'))
        self.assertEqual(set(b['role'] for b in p.sent), {'A1', 'A2', 'C_GATE'})
        self.assertEqual(len(list((self.config.output / 'reject/caption').glob('*.json'))), 2)
        self.assertEqual([e['decision'] for e in self.store.latest_events() if e['stage'] == 'caption_gate'], ['reject', 'reject'])

    def test_audit_reject_does_not_refill(self):
        self.open()
        def reject(body, result, _):
            if body['role'] == 'A7':
                result['decision'] = 'reject'
                result['primary_reason'] = 'unsupported_answer'
        p = MutatedProvider(reject)
        self.pipeline(p).run()
        self.assertEqual(len(self.store.records('candidate')), 16)
        self.assertEqual(len(p.sent), 44)
        self.assertEqual(candidate_records(self.store), {'general': [], 'long': []})
        self.assertTrue(all(count == 0 for count in self.pipeline().scheduler.task_counts.values()))

    def test_local_invalid_qa_consumes_slot_without_paid_audit(self):
        self.open()
        def invalid(body, result, _):
            if body['role'] in ('A3', 'A5'):
                for c in result['candidates']:
                    c['question'] = ''
        p = MutatedProvider(invalid)
        self.pipeline(p).run()
        self.assertEqual(len(self.store.records('local_reject')), 16)
        self.assertNotIn('A7', {b['role'] for b in p.sent})
        self.assertEqual(len(p.sent), 28)

    def test_semantic_abstention_is_bounded_and_fit_shortfall_not_transferred(self):
        self.open(generation={'general_balance_attempts': 2, 'long_balance_attempts': 2})
        def abstain(body, result, _):
            if body['role'] in ('A3', 'A5'):
                result['abstained_slots'] = [{'slot_id': s['slot_id'], 'reason_code': 'task_inapplicable'}
                                            for s in body['context']['assigned_slots']]
                result['candidates'] = []
        p = MutatedProvider(abstain)
        self.pipeline(p).run()
        counts = Counter(b['role'] for b in p.sent)
        self.assertEqual((counts['A3'], counts['A5'], counts['A7']), (6, 6, 0))
        for video_id in {b['context']['video_id'] for b in p.sent}:
            for role in ('A3', 'A5'):
                balanced = [b for b in p.sent if b['role'] == role and b['context']['video_id'] == video_id
                            and b['context']['phase'] == 'balance']
                self.assertEqual(len({b['context']['assigned_slots'][0]['task'] for b in balanced}), 2)

    def test_timeout_unknown_execution_never_resends_on_resume(self):
        self.open()
        class TimeoutProvider(SyntheticProvider):
            def send(self, body):
                self.sent.append(body)
                raise TimeoutError()
        p = TimeoutProvider()
        with self.assertRaises(UnknownExecution):
            self.pipeline(p).run()
        self.assertEqual(len(p.sent), 1)
        replacement = SyntheticProvider()
        with self.assertRaises(UnknownExecution):
            self.pipeline(replacement).run()
        self.assertEqual(len(replacement.sent), 0)
        _, summary = report(self.store)
        self.assertGreater(Decimal(summary['held_unknown_or_reserved_cost']), 0)
        self.assertEqual(self.store.request_rows()[0]['status'], 'unknown_execution')

    def test_crash_after_paid_generation_recovers_exact_request_without_repaying(self):
        self.open()
        provider = SyntheticProvider()
        original_put = self.store.put
        def crash(key, *args):
            if key.startswith('generation_response:'):
                raise RuntimeError('simulated process crash after a paid response')
            return original_put(key, *args)
        with patch.object(self.store, 'put', side_effect=crash):
            with self.assertRaises(RuntimeError):
                self.pipeline(provider).run()
        paid_before = len(provider.sent)
        self.assertEqual(sum(b['role'] == 'A3' for b in provider.sent), 1)
        resumed = SyntheticProvider()
        self.pipeline(resumed).run()
        self.assertEqual(paid_before + len(resumed.sent), 44)
        self.assertEqual(sum(map(len, candidate_records(self.store).values())), 16)

    def test_missing_usage_holds_reservation_and_never_retries(self):
        self.open()
        provider = MutatedProvider(lambda _, __, raw: raw.pop('usage'))
        self.pipeline(provider).run()
        self.assertEqual(len(provider.sent), 2)
        self.pipeline(provider).run()
        self.assertEqual(len(provider.sent), 2)
        self.assertTrue(all(r['status'] == 'billing_unknown' for r in self.store.request_rows()))

    def test_fixed_fps_capacity_failure_never_sends_or_silently_resamples(self):
        data = deepcopy(self.config.data)
        data['teacher']['roles']['A1']['max_frames'] = 19  # 10 seconds at 2 FPS needs 20
        self.config = RuntimeConfig(data, self.config.path)
        self.open()
        provider = SyntheticProvider()
        self.pipeline(provider).run()
        self.assertEqual(provider.sent, [])
        self.assertTrue(all(e['reason'] == 'fixed_fps_cannot_be_preserved' for e in self.store.latest_events() if e['stage'] == 'execution'))

    def test_budget_blocks_before_network_and_keeps_pending_distinct_from_reject(self):
        self.open(budgets={'max_cost': '0.00001'})
        p = SyntheticProvider()
        self.pipeline(p).run()
        self.assertEqual(len(p.sent), 0)
        self.assertEqual(len(self.store.request_rows()), 0)
        execution = [e for e in self.store.latest_events() if e['stage'] == 'execution']
        self.assertTrue(all(e['decision'] == 'pending' and e['reason'] == 'cost_budget_exhausted' for e in execution))

    def test_observed_usage_breach_stops_all_further_calls(self):
        self.open()
        def breach(_, __, raw):
            raw['usage']['completion_tokens'] = 5000
        p = MutatedProvider(breach)
        with self.assertRaises(BudgetBreach):
            self.pipeline(p).run()
        self.assertEqual(len(p.sent), 1)
        self.assertEqual(self.store.request_rows()[0]['status'], 'budget_breach')
        with self.assertRaises(BudgetBreach):
            self.pipeline(p).run()
        self.assertEqual(len(p.sent), 1)

    def test_module_boundaries_resume_without_repeating_captions(self):
        self.open()
        provider = SyntheticProvider()
        self.pipeline(provider).run(through='prepare')
        self.assertEqual(provider.sent, [])
        self.pipeline(provider).run(through='caption')
        self.assertEqual(len(provider.sent), 14)
        self.assertFalse(self.store.records('candidate'))
        self.pipeline(provider).run()
        self.assertEqual(len(provider.sent), 44)

    def test_invalid_ffprobe_metadata_is_a_controlled_media_failure(self):
        media = FFmpegMedia(self.config)
        path = next(Path(self.config.data['input']['root']).glob('*.mp4'))
        for metadata in ({'streams': []}, {'streams': [{'codec_type': 'video', 'avg_frame_rate': '0/0', 'duration': 'NaN'}]}):
            with patch.object(media, 'command', return_value=json.dumps(metadata).encode()):
                with self.assertRaises(PipelineError):
                    media.probe(path)

    def test_cached_incomplete_response_is_not_called_again(self):
        self.open()
        def truncate(_, __, raw):
            raw['choices'][0]['finish_reason'] = 'length'
        p = MutatedProvider(truncate)
        self.pipeline(p).run()
        self.assertEqual(len(p.sent), 2)
        self.pipeline(p).run()
        self.assertEqual(len(p.sent), 2)
        self.assertTrue(all(r['status'] == 'done' for r in self.store.request_rows()))

    def test_original_changed_export_refuses_and_does_not_overwrite(self):
        self.open()
        self.pipeline().run()
        snapshot = export_candidates(self.store)
        original = next(Path(self.config.data['input']['root']).glob('*.mp4'))
        original.write_bytes(original.read_bytes() + b' ')
        with self.assertRaises(PipelineError):
            export_candidates(self.store)
        self.assertTrue((snapshot / 'manifest.json').is_file())

    def test_config_changes_refuse_reusing_state(self):
        self.open()
        data = deepcopy(self.config.data)
        data['run']['seed'] += 1
        with self.assertRaises(PipelineError):
            Store(RuntimeConfig(data, self.config.path))

    def test_immutable_artifact_and_crash_mirror_recovery(self):
        self.open()
        self.store.put('check:one', 'test', None, {'a': 1})
        with self.assertRaises(PipelineError):
            self.store.put('check:one', 'test', None, {'a': 2})
        mirror = self.config.output / 'artifacts/check/one.json'
        mirror.unlink()
        self.assertEqual(self.store.get('check:one'), {'a': 1})
        self.assertTrue(mirror.exists())
        with self.assertRaises(PipelineError):
            self.store.put('check:../escape', 'test', None, {})

    def test_partial_report_recovers_without_model_calls_and_detects_corruption(self):
        self.open()
        self.pipeline().run(through='prepare')
        original_write = atomic_write
        def crash(path, *args, **kwargs):
            if Path(path).name == 'review.md':
                raise RuntimeError('simulated report publication crash')
            return original_write(path, *args, **kwargs)
        with patch('video_sft_builder.reporting.atomic_write', side_effect=crash):
            with self.assertRaises(RuntimeError):
                report(self.store)
        directory, _ = report(self.store)
        self.assertTrue((directory / 'files.json').exists())
        self.assertTrue((directory / 'review.md').exists())
        self.assertEqual(self.store.request_rows(), [])
        (directory / 'report.md').write_text('corrupted', encoding='utf-8')
        with self.assertRaises(PipelineError):
            report(self.store)

    def test_long_audit_cannot_support_all_facts_with_one_segment(self):
        self.open()
        self.pipeline().run()
        c = next(r['payload'] for r in self.store.records('candidate') if r['payload']['branch'] == 'long')
        video = next(r['payload'] for r in self.store.records('video') if r['video_id'] == c['video_id'])
        response = deepcopy(self.store.get('quality:' + c['id'])['response'])
        for evidence in response['evidence']:
            evidence.update(start=0, end=1)
        for fact in c['facts']:
            fact['evidence_window_ids'] = [w['id'] for w in c['evidence_windows']]
        self.assertEqual(validate_audit(response, c, video), (False, 'audit_missing_distinct_necessary_segments'))

    def test_scheduler_fit_then_balance_uses_quality_counts(self):
        self.open()
        scheduler = Scheduler(self.config, self.store)
        video = {'id': 'fake'}
        first = scheduler.plan(video, 'long', 'balance', 0, set(), set())
        task = first['assigned_slots'][0]['task']
        scheduler.task_counts[('long', task)] = 100
        second = scheduler.plan(video, 'long', 'balance', 1, set(), set())
        self.assertNotEqual(second['assigned_slots'][0]['task'], task)
        for plan in (first, second):
            slot = plan['assigned_slots'][0]
            if slot['task'] in ('event_timeline', 'hierarchical_summary'):
                self.assertEqual(slot['question_type'], 'oe')
        # Marginal scheduling recovers specified proportions in a feasible pool.
        counts = Counter()
        for _ in range(100):
            counts[deficit_choice(counts, {'zh': 3, 'en': 7})] += 1
        self.assertEqual(counts, {'zh': 30, 'en': 70})

    def test_timestamp_is_absolute_and_program_generated(self):
        mapping = {'w_000007': {'start': 70, 'end': 80}}
        self.assertIn('00:01:10', render_time('Check [[TIME:w_000007]].', mapping, 'en', 9))
        for value in ('Check 10 seconds.', 'At 00:10.', '[[TIME:unknown]]'):
            with self.assertRaises(ProtocolError):
                render_time(value, mapping, 'en', 9)
        self.assertEqual(clean_text('<p>hello</p><script>secret()</script> world\x00'), 'hello world')

    def test_ordering_program_randomizes_and_preserves_unique_correct_permutation(self):
        c = {'task': 'event_order', 'question_type': 'mcq', 'question': 'Order events', 'num_options': 6,
             'ordering': {'items': [{'id': x, 'text': x} for x in ('first', 'middle', 'last')],
                          'correct_order': ['first', 'middle', 'last']}}
        compile_ordering(c, 17)
        self.assertEqual(len({o['text'] for o in c['options']}), 6)
        self.assertEqual(c['answer'], 'A')
        labels = {item.split(': ')[1]: item.split(': ')[0][-1] for item in c['question'].split('; ')}
        self.assertEqual(c['options'][0]['text'], ' → '.join(labels[k] for k in ('first', 'middle', 'last')))

    def test_bounded_enumeration_tail_windows_and_black_metrics(self):
        data = deepcopy(self.config.data)
        data['input']['max_scan_entries'] = 1
        with self.assertRaises(Blocked):
            enumerate_mp4(RuntimeConfig(data, self.config.path))
        self.assertEqual([(w['start'], w['end']) for w in windows(31, 30, 'b')], [(0, 30), (30, 31)])
        metrics = gray_metrics([bytes(16 * 16)], 16, 16, 8)
        self.assertEqual((metrics['black_fraction'], metrics['laplacian_variance_mean']), (1, 0))

    def test_config_refuses_unset_overlap_and_implicit_retries(self):
        with self.assertRaises(ConfigError):
            validate_config(template())
        for section, key, value in [('run', 'output_root', self.config.data['input']['root']),
                                    ('teacher', 'automatic_retries', 1),
                                    ('generation', 'refill_rejected', True)]:
            data = deepcopy(self.config.data)
            data[section][key] = value
            with self.assertRaises(ConfigError):
                validate_config(data, allow_synthetic=True)

    def test_strict_json_and_no_clobber(self):
        for value in ('{"x":1,"x":2}', '{"x":NaN}'):
            with self.assertRaises(ValueError):
                strict_json(value)
        path = self.root / 'one.txt'
        atomic_write(path, 'original')
        with self.assertRaises(FileExistsError):
            atomic_write(path, 'changed')
        self.assertEqual(path.read_text(), 'original')
        with coordinator_lock(self.root / 'coordinator.lock'):
            with self.assertRaises(PipelineError):
                with coordinator_lock(self.root / 'coordinator.lock'):
                    self.fail('Second coordinator acquired the same lock')

    def test_qwen_native_video_request_and_oss_cache_without_network(self):
        self.open()
        data = deepcopy(self.config.data)
        data['teacher'].update(transport='dashscope_oss', key_env='SYNTHETIC_TEST_CREDENTIAL', model='qwen-test',
                               base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
                               upload_policy_url='https://dashscope.aliyuncs.com/api/v1/uploads')
        cfg = RuntimeConfig(data, self.config.path)
        with patch.dict('os.environ', {'SYNTHETIC_TEST_CREDENTIAL': 'never-a-real-key'}):
            provider = QwenCompatibleProvider(cfg, self.store)
        requests, uploaded = [], []
        def fake_http(url, **kwargs):
            requests.append((url, kwargs))
            return {'data': {'upload_dir': 'temp-test', 'upload_host': 'https://test.oss-cn-beijing.aliyuncs.com/',
                             'max_file_size_mb': 100, 'policy': 'FAKE', 'signature': 'FAKE',
                             'oss_access_key_id': 'FAKE', 'x_oss_object_acl': 'private', 'x_oss_forbid_overwrite': True}}
        provider._json = fake_http
        provider._upload = lambda parsed, fields, path, mime: uploaded.append((parsed.hostname, fields))
        video = next(Path(self.config.data['input']['root']).glob('*.mp4'))
        media = [{'type': 'video', 'path': str(video), 'start': 0, 'end': 30}]
        body = provider.build_body('A7', 'audit', {'candidate': 'synthetic'}, media, cfg.profile('A7'))
        again = provider.build_body('A7', 'audit', {}, media, cfg.profile('A7'))
        self.assertEqual(len(requests), 1)
        self.assertEqual(len(uploaded), 1)
        part = body['messages'][1]['content'][1]
        self.assertEqual(part['type'], 'video_url')
        self.assertTrue(part['video_url']['url'].startswith('oss://temp-test/'))
        self.assertEqual(part['fps'], 2)
        self.assertIn('max_completion_tokens', body)
        self.assertNotIn('max_tokens', body)
        self.assertNotIn('thinking_budget', body)
        provider.send(again)
        self.assertEqual(requests[-1][1]['headers']['X-DashScope-OssResourceResolve'], 'enable')
        self.assertNotIn('Authorization', uploaded[0][1])
        self.assertNotIn('never-a-real-key', json.dumps(self.store.request_rows()))

    def test_oss_upload_is_streamed_and_counted_before_transfer(self):
        self.open()
        data = deepcopy(self.config.data)
        data['teacher']['key_env'] = 'SYNTHETIC_TEST_CREDENTIAL'
        with patch.dict('os.environ', {'SYNTHETIC_TEST_CREDENTIAL': 'not-a-real-key'}):
            provider = QwenCompatibleProvider(RuntimeConfig(data, self.config.path), self.store)
        path = self.root / 'synthetic.bin'
        path.write_bytes(b'x' * (2 * 1024 * 1024 + 17))
        class Connection:
            def __init__(self):
                self.lengths, self.headers = [], {}
            def putrequest(self, *args):
                self.request = args
            def putheader(self, key, value):
                self.headers[key] = value
            def endheaders(self):
                pass
            def send(self, chunk):
                self.lengths.append(len(chunk))
            def getresponse(self):
                class Response:
                    status = 200
                    def read(self, limit):
                        return b''
                return Response()
            def close(self):
                pass
        connection = Connection()
        from urllib.parse import urlsplit
        with patch('video_sft_builder.provider.http.client.HTTPSConnection', return_value=connection):
            provider._upload(urlsplit('https://test.oss-cn-beijing.aliyuncs.com/'), {'policy': 'FAKE'}, path, 'video/mp4')
        self.assertEqual(sum(connection.lengths), int(connection.headers['Content-Length']))
        self.assertLessEqual(max(connection.lengths), 1024 * 1024)
        self.assertNotIn('Authorization', connection.headers)
        row = self.store.db.execute('SELECT * FROM auxiliary').fetchone()
        self.assertEqual((row['kind'], row['bytes'], row['status']), ('oss_upload', path.stat().st_size, 'done'))

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Real FFmpeg/ffprobe are not installed on this host')
    def test_real_ffmpeg_derived_clip_and_original_immutability(self):
        # Optional integration path: locally generated testsrc only, never user media.
        self.open()
        media = FFmpegMedia(self.config)
        path = Path(self.config.data['input']['root']) / 'generated_testsrc.mp4'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-n', '-f', 'lavfi', '-i',
                        'testsrc2=size=320x240:rate=25:duration=4', '-c:v', 'libx264', str(path)], check=True, timeout=30)
        original = path.read_bytes()
        video = media.prepare(path)
        clip = media.clip(video, {'id': 'real_test', 'start': 1, 'end': 3})
        self.assertAlmostEqual(media.probe(clip)['duration'], 2, delta=0.2)
        self.assertEqual(path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
