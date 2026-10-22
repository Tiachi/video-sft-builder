"""Private relay tests: synthetic payloads, fake GitHub, no real uploads."""
import hashlib
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('relay_evidence', PROJECT / 'scripts/relay_evidence.py')
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)


class FakeGitHub:
    def __init__(self, private=True):
        self.is_private = private
        self.assets = {}
        self.mutations = []

    def private(self):
        if not self.is_private:
            raise ValueError('PRIVATE repository required')

    def call(self, path, *, body=None, upload=False, **kwargs):
        if path.endswith('/releases'):
            self.mutations.append('create')
            return {'id': 1, 'tag_name': json.loads(body)['tag_name'], 'html_url': 'https://github.com/' + relay.RELAY + '/releases/tag/test'}
        if path.endswith('/releases/1'):
            return {'id': 1, 'tag_name': self.tag, 'html_url': 'https://github.com/' + relay.RELAY + '/releases/tag/test'}
        if 'per_page=100' in path:
            return list(self.assets.values())
        if upload:
            name = relay.urllib.parse.parse_qs(relay.urllib.parse.urlsplit(path).query)['name'][0]
            self.mutations.append(name)
            value = {'name': name, 'size': len(body), 'digest': 'sha256:' + hashlib.sha256(body).hexdigest()}
            self.assets[name] = value
            return value
        raise AssertionError('Unexpected API request')


class RelayTests(unittest.TestCase):
    def setUp(self):
        base = PROJECT.parent / 'video-sft-relay-tests'
        base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.build = self.root / 'test_build'
        self.build.mkdir()
        (self.build / 'runtime.json').write_text(json.dumps({'caption': {'l1_seconds': 10, 'l2_seconds': 30}, 'execution': {'credential_file': '/private/config.json'}}))
        (self.build / 'build.json').write_text('{}')
        self.video = self.root / 'source.mp4'
        self.video.write_bytes(b'fake-original-video-not-playable')
        media = self.build / 'media/video'
        media.mkdir(parents=True)
        (media / 'w_000000.mp4').write_bytes(b'first fake clip')
        (media / 'w_000001.mp4').write_bytes(b'second fake clip')
        state = self.build / 'state'
        state.mkdir()
        self.db_path = state / 'state.sqlite3'
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.executescript('''CREATE TABLE records(key TEXT PRIMARY KEY,kind TEXT,payload TEXT);
                CREATE TABLE requests(id TEXT,role TEXT,status TEXT,actual TEXT,reservation TEXT,usage TEXT,error_code TEXT,response TEXT,created_at TEXT);
                CREATE TABLE upload_cache(key TEXT,resource TEXT);
                CREATE TABLE events(seq INTEGER,stage TEXT,entity_type TEXT,entity_id TEXT,video_id TEXT,decision TEXT,reason TEXT,detail TEXT);''')
            db.execute('INSERT INTO records VALUES(?,?,?)', ('v', 'video', json.dumps({'id': 'video', 'duration': 60, 'fps': 25})))
            db.execute('INSERT INTO records VALUES(?,?,?)', ('c', 'caption', json.dumps({'id': 'l1_w_000000'})))
            db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?,?,?)', ('r', 'A1', 'done', '0.01', '0.8', '{}', None,
                       json.dumps({'choices': [{'finish_reason': 'stop'}], 'api_key': 'opaque-secret-test'}), 'now'))
            db.execute('INSERT INTO upload_cache VALUES(?,?)', ('x', 'https://private.test/source?Signature=secret-value'))
            db.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?)', (1, 'execution', 'video', 'v', 'v', 'pending', 'technical_error', '{}'))

    def packet(self):
        with patch.object(relay.shutil, 'which', return_value=None):
            return relay.pack(self.build, self.video)

    def test_snapshot_preserves_original_and_redacts_only_diagnostic_copy(self):
        original_db, original_video = relay.sha(self.db_path), relay.sha(self.video)
        packet = self.packet()
        self.assertEqual(relay.sha(self.db_path), original_db)
        self.assertEqual(relay.sha(self.video), original_video)
        snapshot = packet / 'snapshot/build/state/state.sqlite3'
        with closing(sqlite3.connect(snapshot)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM upload_cache').fetchone()[0], 0)
            self.assertNotIn('opaque-secret-test', db.execute('SELECT response FROM requests').fetchone()[0])
        self.assertNotIn(b'opaque-secret-test', snapshot.read_bytes())
        self.assertNotIn(b'Signature=secret-value', snapshot.read_bytes())
        diagnosis = json.loads((packet / 'diagnosis.json').read_text())
        self.assertEqual(diagnosis['videos'][0]['expected_l1'], 6)
        self.assertEqual(diagnosis['videos'][0]['expected_l2'], 2)
        self.assertEqual(diagnosis['caption_counts'], {'l1': 1})
        self.assertEqual(diagnosis['pending_events'][0]['reason'], 'technical_error')
        manifest = json.loads((packet / 'manifest.json').read_text())
        self.assertEqual(manifest['repository'], relay.RELAY)
        for entry in manifest['files']:
            self.assertEqual(relay.sha(packet / 'snapshot' / entry['path']), entry['sha256'])
        for part in manifest['parts']:
            self.assertEqual(relay.sha(packet / part['name']), part['sha256'])

    def test_token_fields_and_signed_urls_are_removed(self):
        value = {'api_key': 'opaque', 'headers': {'Authorization': 'Bearer sensitive'},
                 'media': 'https://user:pass@example.com/v.mp4?Signature=secret#fragment'}
        safe = relay.scrub(value)
        self.assertEqual(safe['api_key'], '[REDACTED]')
        self.assertEqual(safe['headers']['Authorization'], '[REDACTED]')
        self.assertEqual(safe['media'], 'https://example.com/v.mp4')

    def test_private_key_material_refused(self):
        with self.assertRaises(ValueError):
            relay.scrub('-----BEGIN OPENSSH PRIVATE KEY-----')

    def test_config_files_outside_allowlist_are_not_copied(self):
        (self.build / 'my_api_config.json').write_text('{"api_key":"private"}')
        (self.build / '.env').write_text('secret')
        packet = self.packet()
        self.assertFalse((packet / 'snapshot/build/.env').exists())
        self.assertFalse((packet / 'snapshot/build/my_api_config.json').exists())

    def test_size_limit_stops_before_upload(self):
        with patch.object(relay, 'MAX_BYTES', 1), self.assertRaises(ValueError):
            self.packet()

    def test_active_pipeline_refuses_snapshot(self):
        with relay.coordinator_lock(self.build / 'coordinator.lock'):
            with self.assertRaises(relay.PipelineError):
                self.packet()

    def test_public_upload_is_rejected_before_any_mutation(self):
        packet = self.packet()
        client = FakeGitHub(private=False)
        with self.assertRaises(ValueError):
            relay.upload(packet, client)
        self.assertEqual(client.mutations, [])

    def test_private_upload_manifest_last_and_resume_without_reupload(self):
        packet = self.packet()
        client = FakeGitHub()
        client.tag = json.loads((packet / 'manifest.json').read_text())['tag']
        relay.upload(packet, client)
        self.assertEqual(client.mutations[-1], 'manifest.json')
        previous = list(client.mutations)
        relay.upload(packet, client)
        self.assertEqual(client.mutations, previous)

    def test_modified_packet_fails_without_sending_part(self):
        packet = self.packet()
        manifest = json.loads((packet / 'manifest.json').read_text())
        (packet / manifest['parts'][0]['name']).write_bytes(b'tampered')
        client = FakeGitHub()
        with self.assertRaises(ValueError):
            relay.upload(packet, client)
        self.assertEqual(client.mutations, ['create'])

    def test_api_can_never_target_public_or_similarly_named_repo(self):
        client = relay.GitHub('synthetic-token')
        for path in ('/repos/' + relay.PUBLIC, '/repos/' + relay.RELAY + '-wrong/releases'):
            with self.assertRaises(ValueError):
                client.call(path, body=b'never-sent')
        self.assertIsNone(relay.NoRedirect().redirect_request(None, None, None, None, None, None))

    def test_server_push_guard_changes_only_local_push_url(self):
        code = self.root / 'code'
        code.mkdir()
        subprocess.run(['git', 'init', str(code)], capture_output=True, check=True, timeout=30)
        subprocess.run(['git', '-C', str(code), 'remote', 'add', 'origin', 'https://github.com/' + relay.PUBLIC + '.git'], check=True, timeout=30)
        relay.protect_public_checkout(code)
        self.assertEqual(relay.git(code, 'config', '--get', 'remote.origin.url'), 'https://github.com/' + relay.PUBLIC + '.git')
        self.assertEqual(relay.git(code, 'remote', 'get-url', '--push', 'origin'), relay.DISABLED_PUSH)


if __name__ == '__main__':
    unittest.main()
