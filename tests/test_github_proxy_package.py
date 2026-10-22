"""Offline bounded packaging: fake core, synthetic secret, no network/server."""
import gzip
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/git'))
import github_only_proxy as helper
import package_github_proxy as packager


class PrivatePackageTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT.parent / 'github_proxy_package_tests'
        parent.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / 'core.gz'
        self.archive.write_bytes(gzip.compress(b'synthetic-non-executable-core'))
        self.config = self.root / 'config.json'
        helper.private_json(self.config, helper.make_config({'name': 'synthetic', 'type': 'anytls',
                           'server': 'fixture.invalid', 'port': 443, 'password': 'synthetic-secret'}))
        self.release = self.root / 'release.json'
        self.metadata = {'version': 'v1.19.33', 'name': 'mihomo-linux-arm64-v1.19.33.gz',
                         'size': self.archive.stat().st_size, 'digest': 'sha256:' + helper.sha256(self.archive),
                         'url': 'https://github.com/MetaCubeX/mihomo/releases/download/v1.19.33/mihomo-linux-arm64-v1.19.33.gz'}
        helper.private_json(self.release, self.metadata)
        self.output = self.root / 'private.zip'

    def package(self):
        def git_result(command, **kwargs):
            output = '' if 'status' in command else 'a' * 40 + '\n'
            return subprocess.CompletedProcess(command, 0, stdout=output)
        with patch.object(packager.subprocess, 'run', side_effect=git_result):
            return packager.package(self.archive, self.release, self.config, self.output)

    def test_exact_bundle_and_unchanged_inputs(self):
        before = self.config.read_bytes()
        result = self.package()
        self.assertTrue(result['contains_secret'])
        self.assertEqual(before, self.config.read_bytes())
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual({Path(name).name for name in archive.namelist()},
                             {'mihomo', 'config.json', 'core.sha256', 'github_only_proxy.py',
                              'setup_github_only_proxy.sh', 'deployment_provenance.json'})
            value = json.loads(archive.read(packager.BUNDLE + '/config.json'))
            helper.validate_config(value)
            self.assertEqual(value['proxies'][0]['password'], 'synthetic-secret')
            self.assertIsNone(archive.testzip())

    def test_wrong_release_hash_refused_before_output(self):
        self.metadata['digest'] = 'sha256:' + '0' * 64
        self.release.write_text(json.dumps(self.metadata))
        with self.assertRaises(ValueError):
            self.package()
        self.assertFalse(self.output.exists())

    def test_existing_output_not_overwritten(self):
        self.output.write_bytes(b'user-owned')
        with self.assertRaises(ValueError):
            self.package()
        self.assertEqual(self.output.read_bytes(), b'user-owned')

    def test_output_inside_source_repo_refused(self):
        self.output = ROOT / 'x_temp/forbidden-secret.zip'
        with self.assertRaises(ValueError):
            self.package()
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
