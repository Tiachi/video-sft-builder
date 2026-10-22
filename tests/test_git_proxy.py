"""Local temporary Git config tests; no SSH, real proxy or network required."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('git_proxy_helper', ROOT / 'scripts/git/configure_proxy.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class ProxyTests(unittest.TestCase):
    def setUp(self):
        directory = ROOT / 'x_temp' / 'proxy_tests'
        directory.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=directory)
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        subprocess.run(['git', 'init', '--initial-branch=main', str(self.repo)], check=True, capture_output=True)
        helper.git(self.repo, 'remote', 'add', 'origin', helper.ORIGIN)
        helper.git(self.repo, 'config', 'remote.origin.pushurl', 'disabled-public-push://video-sft-builder')
        self.backup = self.repo / '.git/video-sft-proxy-backup.json'

    def verify_guard(self):
        self.assertEqual(helper.git(self.repo, 'config', '--get', 'remote.origin.pushurl').strip(),
                         'disabled-public-push://video-sft-builder')
        self.assertEqual(helper.git(self.repo, 'config', '--get', 'remote.origin.url').strip(), helper.ORIGIN)

    def test_configure_is_rerunnable_and_restore_preserves_push_guard(self):
        helper.git(self.repo, 'config', 'http.version', 'HTTP/2')
        with patch.object(helper, 'probe', return_value='a' * 40):
            self.assertIn('PASS:', helper.configure(self.repo))
            helper.configure(self.repo)
        self.assertEqual(helper.get_values(self.repo, 'remote.origin.proxy'), ['http://127.0.0.1:17897'])
        self.assertEqual(helper.get_values(self.repo, 'http.version'), ['HTTP/1.1'])
        self.verify_guard()
        helper.configure(self.repo, restore=True)
        self.assertEqual(helper.get_values(self.repo, 'remote.origin.proxy'), [])
        self.assertEqual(helper.get_values(self.repo, 'http.version'), ['HTTP/2'])
        self.assertFalse(self.backup.exists())
        self.verify_guard()

    def test_failed_connectivity_never_changes_configuration(self):
        original = (self.repo / '.git/config').read_bytes()
        with patch.object(helper, 'probe', side_effect=ValueError('tunnel unavailable')):
            with self.assertRaises(ValueError):
                helper.configure(self.repo)
        self.assertEqual((self.repo / '.git/config').read_bytes(), original)
        self.assertFalse(self.backup.exists())

    def test_check_has_no_writes(self):
        original = (self.repo / '.git/config').read_bytes()
        with patch.object(helper, 'probe', return_value='a' * 40):
            helper.configure(self.repo, check=True)
        self.assertEqual((self.repo / '.git/config').read_bytes(), original)
        self.assertFalse(self.backup.exists())

    def test_concurrent_manual_change_during_probe_is_preserved(self):
        def changed(*_):
            helper.git(self.repo, 'config', 'http.version', 'HTTP/2')
            return 'a' * 40
        with patch.object(helper, 'probe', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'during connectivity check'):
                helper.configure(self.repo)
        self.assertEqual(helper.get_values(self.repo, 'http.version'), ['HTTP/2'])
        self.assertFalse(self.backup.exists())

    def test_manual_config_changes_are_not_overwritten(self):
        with patch.object(helper, 'probe', return_value='a' * 40):
            helper.configure(self.repo)
        helper.git(self.repo, 'config', 'http.version', 'HTTP/2')
        with self.assertRaisesRegex(ValueError, 'manually changed'):
            helper.configure(self.repo, restore=True)
        self.assertEqual(helper.get_values(self.repo, 'http.version'), ['HTTP/2'])

    def test_wrong_repository_and_invalid_port_refused(self):
        with self.assertRaisesRegex(ValueError, 'port'):
            helper.configure(self.repo, 0)
        helper.git(self.repo, 'remote', 'set-url', 'origin', 'https://github.com/other/repository.git')
        with self.assertRaisesRegex(ValueError, 'canonical'):
            helper.configure(self.repo)
        self.assertFalse(self.backup.exists())

    def test_original_proxy_values_preserved_privately(self):
        secret = 'http://fake-user:fake-password@localhost:8765'
        helper.git(self.repo, 'config', 'remote.origin.proxy', secret)
        with patch.object(helper, 'probe', return_value='a' * 40):
            helper.configure(self.repo)
        helper.configure(self.repo, restore=True)
        self.assertEqual(helper.get_values(self.repo, 'remote.origin.proxy'), [secret])

    def test_probe_requires_actual_main_ref_and_passes_loopback_proxy(self):
        with patch.object(helper, 'git', return_value='a' * 40 + '\trefs/heads/main\n') as git:
            self.assertEqual(helper.probe(self.repo, 'http://127.0.0.1:17897'), 'a' * 40)
        args = git.call_args.args
        self.assertIn('remote.origin.proxy=http://127.0.0.1:17897', args)
        self.assertIn('origin', args)
        with patch.object(helper, 'git', return_value='not a Git main ref'):
            with self.assertRaises(ValueError):
                helper.probe(self.repo, 'http://127.0.0.1:17897')
