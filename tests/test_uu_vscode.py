"""SSH/VS Code config preservation tests in temporary fixtures, no real keys."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHELL = shutil.which('pwsh') or shutil.which('powershell')


@unittest.skipUnless(SHELL, 'PowerShell required for local Windows config helper')
class VscodeSetupTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / 'x_temp' / 'vscode_setup_tests'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.key, self.seed = self.folder / 'fake.pem', self.folder / 'accepted_hosts'
        self.key.write_text('synthetic path fixture, never read as a key', encoding='utf-8')
        self.seed.write_text('audio-1-modelarts-server ssh-ed25519 SYNTHETIC_PUBLIC_FIXTURE\n', encoding='utf-8')
        self.config, self.settings = self.folder / 'config', self.folder / 'settings.json'
        self.original = 'Host existing\n    HostName example.invalid\n    Port 2222\n'
        self.config.write_text(self.original, encoding='utf-8')
        self.original_settings = '{\n  // preserve comment\n  "remote.SSH.remotePlatform": {"existing":"linux",},\n  "editor.fontSize": 17,\n}\n'
        self.settings.write_text(self.original_settings, encoding='utf-8')

    def run_helper(self):
        return subprocess.run([SHELL, '-NoProfile', '-File', str(ROOT / 'scripts/git/configure_uu_vscode.ps1'),
                               '-IdentityFile', str(self.key), '-KnownHostsSeed', str(self.seed),
                               '-SshConfig', str(self.config), '-VSCodeSettings', str(self.settings)],
                              capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20)

    def test_configure_preserves_originals_and_reruns_without_new_backups(self):
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.config.read_text(encoding='utf-8')
        self.assertTrue(text.endswith(self.original))
        self.assertIn('Host audio_1_uu audio_1_proxy', text)
        self.assertIn('Host audio_1_proxy\n    RemoteForward', text.replace('\r\n', '\n'))
        self.assertIn('StrictHostKeyChecking yes', text)
        self.assertIn('"audio_1_uu": "linux"', self.settings.read_text(encoding='utf-8'))
        self.assertIn('// preserve comment', self.settings.read_text(encoding='utf-8'))
        self.assertEqual(next(self.folder.glob('config.backup-video-sft-*')).read_text(encoding='utf-8'), self.original)
        first = sorted(p.name for p in self.folder.iterdir())
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(first, sorted(p.name for p in self.folder.iterdir()))

    def test_existing_alias_outside_managed_block_refuses_overwrite(self):
        original = self.original + 'Host audio_1_uu\n    HostName preserve.example.invalid\n'
        self.config.write_text(original, encoding='utf-8')
        result = self.run_helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.config.read_text(encoding='utf-8'), original)
        self.assertEqual(self.settings.read_text(encoding='utf-8'), self.original_settings)

    def test_custom_vscode_config_prevents_partial_ssh_change(self):
        original = '{"remote.SSH.configFile":"some-other-config","remote.SSH.remotePlatform":{}}'
        self.settings.write_text(original, encoding='utf-8')
        result = self.run_helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.config.read_text(encoding='utf-8'), self.original)
        self.assertEqual(self.settings.read_text(encoding='utf-8'), original)
