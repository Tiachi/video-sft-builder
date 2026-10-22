"""Terminal/settings/routing and localhost HTTP contract tests. No paid APIs."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_sft_builder.builds import build_status, create_build, execute_build, load_build
from video_sft_builder.config import RuntimeConfig, load_config, validate_config
from video_sft_builder.errors import Blocked, ConfigError, PipelineError
from video_sft_builder.provider import CompatibleProvider, ModelGateway, ProviderRouter
from video_sft_builder.settings import Settings, private_write_json, validate_run_name
from video_sft_builder.sources import acquire_url, describe_source
from video_sft_builder.state import Store
from video_sft_builder.terminal import Console, Workbench, Progress, visible
from video_sft_builder.util import canonical, coordinator_lock, read_json


class LocalService:
    def __init__(self):
        self.posts, self.gets = [], []
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.posts.append((self.path, dict(self.headers), body))
                value = {'id': 'localhost-contract', 'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}],
                         'usage': {'prompt_tokens': 1000, 'completion_tokens': 200}}
                data = json.dumps(value).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def do_GET(self):
                owner.gets.append(self.path)
                if self.path == '/v1/models':
                    value = json.dumps({'data': [{'id': 'local-vision'}]}).encode()
                else:
                    value = b'fake-MP4-for-bounded-download-only'
                self.send_response(200)
                self.send_header('Content-Length', '10000' if self.path.startswith('/large') else str(len(value)))
                self.end_headers()
                self.wfile.write(value)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class TerminalTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[2] / 'video-sft-terminal-tests'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='terminal-', dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = Settings(self.root / 'private/config.json')
        source = self.root / 'input'
        source.mkdir()
        (source / 'one.mp4').write_bytes(b'not-a-real-video-test-only')
        self.settings.data.update(source=str(source), output_dir=str(self.root / 'builds'))
        self.settings.save()
        self.clock = datetime(2026, 10, 21, 16, 51, tzinfo=timezone(timedelta(hours=8)))

    def compile(self):
        return self.settings.compile('unit_20261021_1651', self.root / 'input')

    def service(self):
        value = LocalService()
        self.addCleanup(value.close)
        return value

    def vllm(self, service, **updates):
        self.settings.data['models']['vllm'].update(base_url=service.url + '/v1', model='local-vision', sampling_verified=True, **updates)
        self.settings.data['active_model'] = 'vllm'
        self.settings.save()
        return self.compile()

    def test_private_key_persists_without_appearing_in_public_runtime(self):
        secret = 'FAKE_PERSISTENT_KEY_123456'
        self.settings.data['models']['qwen3.8-flash']['api_key'] = secret
        self.settings.save()
        self.assertEqual(Settings(self.settings.path).data['models']['qwen3.8-flash']['api_key'], secret)
        cfg = self.compile()
        self.assertEqual(cfg.credentials['qwen3.8-flash'], secret)
        self.assertNotIn(secret, canonical(cfg.data))
        self.assertNotIn(secret, repr(cfg))
        self.assertNotIn(secret, canonical(self.settings.redacted()))
        if os.name != 'nt':
            self.assertEqual(self.settings.path.stat().st_mode & 0o777, 0o600)

    def test_key_rotation_does_not_change_frozen_request_identity(self):
        cfg = self.compile()
        cfg.output.mkdir(parents=True)
        private_write_json(cfg.path, cfg.data)
        previous = cfg.fingerprint
        self.settings.data['models']['qwen3.8-flash']['api_key'] = 'FAKE_ROTATED_KEY'
        self.settings.save()
        loaded = load_config(cfg.path)
        self.assertEqual(loaded.fingerprint, previous)
        self.assertEqual(loaded.credentials['qwen3.8-flash'], 'FAKE_ROTATED_KEY')

    def test_build_name_timestamp_unicode_and_collision_no_clobber(self):
        root = create_build(self.settings, '动作集', now=self.clock)
        self.assertEqual(root.name, '动作集_20261021_1651')
        original = (root / 'runtime.json').read_bytes()
        with self.assertRaises(ConfigError):
            create_build(self.settings, '动作集', now=self.clock)
        self.assertEqual((root / 'runtime.json').read_bytes(), original)
        _, _, config = load_build(root)
        self.assertEqual(config.state_dir, root / 'state')
        self.assertEqual(config.output, root)
        for name in ('../escape', '.hidden', 'bad/name', 'bad\\name', 'bad\x1bname', ''):
            with self.assertRaises(ConfigError):
                validate_run_name(name)

    def test_single_mp4_source_uses_allowlist_without_copying_original(self):
        source = self.root / 'input/one.mp4'
        value = describe_source(str(source), self.root / 'builds/x')
        self.assertEqual(value['allowlist'], ['one.mp4'])
        self.settings.data['source'] = str(source)
        self.settings.save()
        root = create_build(self.settings, 'file', now=self.clock)
        _, _, cfg = load_build(root)
        self.assertEqual(cfg.data['input']['root'], str(source.parent))
        self.assertFalse((root / 'inputs/one.mp4').exists())
        self.assertEqual(source.read_bytes(), b'not-a-real-video-test-only')

    def test_deepseek_default_rejects_video_then_explicit_hybrid_route_works(self):
        self.settings.data['active_model'] = 'deepseek-v4.1-flash'
        self.settings.save()
        with self.assertRaisesRegex(ConfigError, 'native_video'):
            self.compile()
        self.settings.data['routes'] = {role: 'qwen3.8-flash' for role in ('A1', 'A2', 'A7')}
        self.settings.save()
        cfg = self.compile()
        self.assertEqual(cfg.provider_id('A7'), 'qwen3.8-flash')
        self.assertEqual(cfg.provider_settings('A3')['model'], 'deepseek-flash')
        self.assertEqual(cfg.provider_id('C_GATE'), 'deepseek-v4.1-flash')

    def test_vllm_requires_declared_sampling_and_served_name(self):
        self.settings.data['active_model'] = 'vllm'
        self.settings.save()
        with self.assertRaises(ConfigError):
            self.compile()
        self.settings.data['models']['vllm']['sampling_verified'] = True
        self.settings.save()
        with self.assertRaisesRegex(ConfigError, 'placeholder'):
            self.compile()

    def test_vllm_native_request_reaches_localhost_and_contains_no_qwen_fields(self):
        service = self.service()
        cfg = self.vllm(service)
        store = Store(cfg)
        self.addCleanup(store.close)
        client = ProviderRouter(cfg, store).client('A7')
        media = [{'type': 'video', 'path': str(self.root / 'input/one.mp4'), 'start': 0, 'end': 3600}]
        body = client.build_body('A7', 'return JSON', {}, media, cfg.profile('A7'))
        raw = client.send(body)
        self.assertEqual(raw['id'], 'localhost-contract')
        path, headers, sent = service.posts[-1]
        self.assertEqual(path, '/v1/chat/completions')
        self.assertEqual(sent['model'], 'local-vision')
        video = sent['messages'][1]['content'][1]
        self.assertEqual(video['type'], 'video_url')
        self.assertTrue(video['video_url']['url'].startswith('data:video/mp4;base64,'))
        self.assertEqual(sent['media_io_kwargs']['video'], {'fps': 2, 'num_frames': 7201, 'max_duration': 3601})
        for key in ('enable_thinking', 'thinking_budget', 'vl_high_resolution_images'):
            self.assertNotIn(key, sent)
        self.assertNotIn('max_pixels', video)
        self.assertNotIn('X-DashScope-OssResourceResolve', headers)
        self.assertEqual(sent['chat_template_kwargs'], {'enable_thinking': False})

    def test_vllm_shared_file_uri_mapping_and_scope_guard(self):
        service = self.service()
        cfg = self.vllm(service, transport='file_uri', local_media_root=str(self.root), server_media_root='/shared/video-sft')
        store = Store(cfg)
        self.addCleanup(store.close)
        client = ProviderRouter(cfg, store).client('A1')
        self.assertEqual(client.materialize(self.root / 'input/one.mp4', media_type='video'), 'file:///shared/video-sft/input/one.mp4')
        outside = self.root.parent / 'outside.mp4'
        with self.assertRaises(Blocked):
            client.materialize(outside, media_type='video')

    def test_deepseek_json_dialect_and_direct_video_rejection(self):
        service = self.service()
        self.settings.data['active_model'] = 'deepseek-v4.1-flash'
        self.settings.data['models']['deepseek-v4.1-flash'].update(base_url=service.url, allow_http=True, api_key='FAKE_DEEPSEEK_KEY')
        self.settings.data['routes'] = {role: 'qwen3.8-flash' for role in ('A1', 'A2', 'A7')}
        self.settings.save()
        cfg = self.compile()
        store = Store(cfg)
        self.addCleanup(store.close)
        client = ProviderRouter(cfg, store).client('A3')
        body = client.build_body('A3', 'return JSON', {'test': True}, [], cfg.profile('A3'))
        client.send(body)
        path, headers, sent = service.posts[-1]
        self.assertEqual(path, '/chat/completions')
        self.assertEqual(sent['thinking'], {'type': 'disabled'})
        self.assertIn('max_tokens', sent)
        self.assertNotIn('max_completion_tokens', sent)
        self.assertNotIn('enable_thinking', sent)
        self.assertEqual(headers['Authorization'], 'Bearer FAKE_DEEPSEEK_KEY')
        with self.assertRaises(ConfigError):
            client.build_body('A7', 'return JSON', {}, [{'type': 'video', 'path': 'unused.mp4'}], cfg.profile('A7'))

    def test_per_role_pricing_and_gateway_single_send_over_http(self):
        service = self.service()
        cfg = self.vllm(service, rates={'input_per_million': '2', 'output_per_million': '8'})
        store = Store(cfg)
        self.addCleanup(store.close)
        gateway = ModelGateway(cfg, store, None)
        video = {'id': 'unit_video', 'fps': 25}
        first, _ = gateway.call('A3', 'unit', video, 'return JSON', {})
        second, _ = gateway.call('A3', 'unit', video, 'return JSON', {})
        self.assertEqual((first, second), ({'ok': True}, {'ok': True}))
        self.assertEqual(len(service.posts), 1)
        self.assertEqual(Decimal(store.request_rows()[0]['actual']), Decimal('0.0036'))

    def test_direct_url_is_bounded_cached_and_signed_query_not_exported(self):
        service = self.service()
        root = self.root / 'url-build'
        url = service.url + '/source.mp4?signature=FAKE_PRIVATE_QUERY'
        limits = {'allow_http': True, 'max_bytes': 1024, 'timeout_seconds': 3}
        path = acquire_url(url, root, limits)
        self.assertEqual(acquire_url(url, root, limits), path)
        self.assertEqual(len(service.gets), 1)
        self.assertNotIn('FAKE_PRIVATE_QUERY', (root / 'inputs/download.json').read_text())
        self.assertEqual(describe_source(url, root)['public_source'], service.url + '/source.mp4')
        with self.assertRaises(PipelineError):
            acquire_url(service.url + '/large.mp4', self.root / 'large-build', limits)
        self.assertFalse((self.root / 'large-build/inputs/source.mp4').exists())
        self.assertEqual(list((self.root / 'large-build/inputs').glob('*.part')), [])
        with self.assertRaises(ConfigError):
            acquire_url(url, self.root / 'not-allowed', {**limits, 'allow_http': False})

    def test_ui_changes_persist_and_configuration_views_redact_keys(self):
        self.settings.data['models']['qwen3.8-flash']['api_key'] = 'FAKE_SECRET_NOT_IN_TERMINAL'
        self.settings.save()
        output = io.StringIO()
        ui = Workbench(self.settings, console=Console(output, plain=True))
        ui.dispatch('/model 2')
        ui.dispatch('/route video qwen3.8-flash')
        ui.dispatch('/set limits.max_cost_cny 12')
        ui.dispatch('/models')
        ui.dispatch('/config')
        reloaded = Settings(self.settings.path)
        self.assertEqual(reloaded.data['active_model'], 'deepseek-v4.1-flash')
        self.assertEqual(reloaded.data['limits']['max_cost_cny'], 12)
        self.assertEqual(reloaded.routes()['A7'], 'qwen3.8-flash')
        self.assertNotIn('FAKE_SECRET_NOT_IN_TERMINAL', output.getvalue())
        self.assertNotIn('\x1b', output.getvalue())
        with self.assertRaises(ConfigError):
            ui.dispatch('/model set qwen3.8-flash api_key unsafe-key-in-command')

    def test_bad_settings_update_does_not_overwrite_valid_private_file(self):
        previous = self.settings.path.read_bytes()
        self.settings.data['models']['qwen3.8-flash']['extra_body'] = {'messages': []}
        with self.assertRaises(ConfigError):
            self.settings.save()
        self.assertEqual(self.settings.path.read_bytes(), previous)
        self.settings.reload()
        self.settings.data['recipe']['l2_seconds'] = 31
        with self.assertRaises(ConfigError):
            self.settings.save()
        self.assertEqual(self.settings.path.read_bytes(), previous)

    def test_get_models_is_an_explicit_readonly_connectivity_check(self):
        service = self.service()
        self.vllm(service)
        ui = Workbench(self.settings, console=Console(io.StringIO(), plain=True))
        ui.dispatch('/models ping vllm')
        self.assertEqual(service.gets, ['/v1/models'])
        self.assertEqual(service.posts, [])

    def test_contained_full_demo_and_resume_keep_every_artifact_in_named_folder(self):
        self.settings.data['models']['qwen3.8-flash']['api_key'] = 'FAKE_NO_KEY_IN_BUILD_ARTIFACTS'
        self.settings.save()
        root = create_build(self.settings, 'complete', now=self.clock, synthetic=True)
        events = []
        first = execute_build(root, observer=events.append)
        self.assertEqual(first['auto_passed'], 26)
        self.assertTrue((root / 'state/state.sqlite3').exists())
        self.assertTrue((root / 'runtime.json').exists())
        self.assertTrue((root / 'build.json').exists())
        self.assertTrue(Path(first['export']).is_relative_to(root))
        events.clear()
        second = execute_build(root, observer=events.append)
        self.assertEqual(second['export'], first['export'])
        self.assertEqual(second['report'], first['report'])
        self.assertFalse(any(e['kind'] == 'request_start' for e in events))
        status = build_status(root)
        self.assertEqual((status['requests'], status['auto_passed']), (62, 26))
        self.assertEqual((status['status'], status['through']), ('complete', 'all'))
        self.assertTrue(status['synthetic'])
        for path in root.rglob('*'):
            if path.is_file():
                self.assertNotIn(b'FAKE_NO_KEY_IN_BUILD_ARTIFACTS', path.read_bytes())
        # Generic live run/config validation must never interpret a demo as real.
        with self.assertRaises(ConfigError):
            load_config(root / 'runtime.json')

    def test_ui_and_legacy_cli_share_the_same_contained_build_lock(self):
        root = create_build(self.settings, 'locked', now=self.clock, synthetic=True)
        _, _, cfg = load_build(root)
        self.assertEqual(cfg.lock_path, root / 'coordinator.lock')
        with coordinator_lock(cfg.lock_path):
            with self.assertRaises(PipelineError):
                execute_build(root)

    def test_frozen_build_routes_survive_changes_to_default_model(self):
        root = create_build(self.settings, 'frozen', now=self.clock)
        original = (root / 'runtime.json').read_bytes()
        self.settings.data['active_model'] = 'deepseek-v4.1-flash'
        self.settings.save()
        _, _, config = load_build(root)
        self.assertEqual(config.provider_id('A3'), 'qwen3.8-flash')
        self.assertEqual((root / 'runtime.json').read_bytes(), original)

    def test_terminal_control_characters_are_removed(self):
        self.assertNotIn('\x1b', visible('\x1b[2Jmalicious\x07'))


if __name__ == '__main__':
    unittest.main()
