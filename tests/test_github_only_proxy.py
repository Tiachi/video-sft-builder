"""Offline policy and actual temporary Git scope/rollback tests; no proxy traffic."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('github_only_helper', ROOT / 'scripts/git/github_only_proxy.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
NODE = {'name': 'synthetic', 'type': 'anytls', 'server': 'proxy.invalid', 'port': 443, 'password': 'fixture-only'}


class GithubOnlyTests(unittest.TestCase):
    def setUp(self):
        directory = ROOT / 'x_temp/github_only_tests'
        directory.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=directory)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        subprocess.run(['git', 'init', '--initial-branch=main', str(self.repo)], capture_output=True, check=True)
        self.home = self.root / 'service'
        self.home.mkdir()
        self.global_config = self.root / 'global-config'
        self.global_config.write_text('', encoding='utf-8')
        environment = {key: '' for key in helper.PROXY_ENV}
        environment.update(GIT_CONFIG_GLOBAL=str(self.global_config), GIT_CONFIG_NOSYSTEM='1')
        self.environment = patch.dict(os.environ, environment)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        helper.git(self.repo, 'remote', 'add', 'origin', 'https://github.com/Tiachi/video-sft-builder.git')
        helper.git(self.repo, 'config', 'remote.origin.pushurl', 'disabled-public-push://video-sft-builder')

    def enable(self, probe_error=None):
        original_git = helper.git
        def intercepted(repo, *args, **kwargs):
            if 'ls-remote' in args:
                if probe_error:
                    raise probe_error
                return 'a' * 40 + '\trefs/heads/main'
            return original_git(repo, *args, **kwargs)
        with patch.object(helper, 'service', return_value=self.home), patch.object(helper, 'owned_pid', return_value=123), \
                patch.object(helper, 'listening', return_value=True), patch.object(helper, 'git', side_effect=intercepted):
            return helper.git_configure(self.home, self.repo)

    def test_exact_policy_has_no_background_or_non_github_routes(self):
        config = helper.make_config(NODE)
        helper.validate_config(config)
        self.assertEqual(config['rules'][-1], 'MATCH,REJECT')
        self.assertEqual(len(config['proxies']), 1)
        self.assertFalse(config['allow-lan'])
        self.assertFalse(config['tun']['enable'])
        self.assertFalse(config['geo-auto-update'])
        self.assertNotIn('proxy-groups', config)
        self.assertNotIn('proxy-providers', config)
        self.assertEqual(config['external-controller'], '')
        self.assertEqual(NODE['name'], 'synthetic')
        for mutation in (lambda c: c['rules'].insert(0, 'DOMAIN-SUFFIX,huggingface.co,GITHUB_NODE'),
                         lambda c: c.update(mode='global'), lambda c: c.update(**{'external-controller': '0.0.0.0:9090'}),
                         lambda c: c.update(**{'allow-lan': True}), lambda c: c['rules'].__setitem__(-1, 'MATCH,GITHUB_NODE')):
            bad = deepcopy(config)
            mutation(bad)
            with self.assertRaises(ValueError):
                helper.validate_config(bad)

    def test_extra_node_import_or_chain_is_refused(self):
        for extra in ({'dialer-proxy': 'other'}, {'certificate': '/secret/path'}, {'type': 'direct'}):
            with self.assertRaises(ValueError):
                helper.make_config({**NODE, **extra})

    def test_duplicate_config_and_no_clobber(self):
        path = self.root / 'duplicate.json'
        path.write_text('{"rules":[],"rules":["MATCH,GLOBAL"]}')
        with self.assertRaises(ValueError):
            helper.read_json(path)
        with self.assertRaises(FileExistsError):
            helper.private_json(path, {})

    def test_real_git_url_scope_and_restore_preserve_push_guard(self):
        self.enable()
        self.enable()
        self.assertEqual(helper.git(self.repo, 'config', '--get-urlmatch', 'http.proxy', 'https://github.com/Tiachi/any.git'),
                         'http://127.0.0.1:' + str(helper.PORT))
        for url in ('https://huggingface.co/data', 'https://pypi.org/simple', 'https://github.com.evil.invalid/x'):
            self.assertEqual(helper.git(self.repo, 'config', '--get-urlmatch', 'http.proxy', url, missing=True), '')
        self.assertEqual(helper.git(self.repo, 'config', '--get', 'remote.origin.pushurl'), 'disabled-public-push://video-sft-builder')
        with patch.object(helper, 'service', return_value=self.home):
            helper.git_configure(self.home, self.repo, disable=True)
        self.assertEqual(helper.git_values(self.repo, helper.KEYS[0]), [])
        self.assertEqual(self.global_config.read_text(), '')

    def test_failed_probe_leaves_git_byte_identical(self):
        before = (self.repo / '.git/config').read_bytes()
        with self.assertRaises(ValueError):
            self.enable(ValueError('fixture network failure'))
        self.assertEqual((self.repo / '.git/config').read_bytes(), before)
        self.assertFalse((self.repo / '.git/github-only-proxy-backup.json').exists())

    def test_manual_changes_are_not_overwritten_on_disable(self):
        self.enable()
        helper.git(self.repo, 'config', helper.KEYS[0], 'http://127.0.0.1:19999')
        with patch.object(helper, 'service', return_value=self.home), self.assertRaises(ValueError):
            helper.git_configure(self.home, self.repo, disable=True)
        self.assertEqual(helper.git_values(self.repo, helper.KEYS[0]), ['http://127.0.0.1:19999'])

    def test_environment_and_existing_broad_proxy_refused(self):
        with patch.dict(os.environ, HTTPS_PROXY='http://proxy.invalid:1'), self.assertRaises(ValueError):
            self.enable()
        helper.git(self.repo, 'config', 'http.proxy', 'http://proxy.invalid:2')
        with self.assertRaises(ValueError):
            self.enable()
        self.assertEqual(helper.git(self.repo, 'config', '--get', 'http.proxy'), 'http://proxy.invalid:2')


if __name__ == '__main__':
    unittest.main()
