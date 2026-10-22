"""Initialization failure injection: package managers are stubs, never real installs."""
import importlib.util
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_environment', PROJECT / 'scripts/check_environment.py')
environment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(environment)


def shell_path(path):
    value = Path(path).as_posix()
    return '/' + value[0].lower() + value[2:] if os.name == 'nt' else value


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        # Git's bin/bash.exe launcher prepends real tools to PATH; use the actual
        # interpreter so isolated fixtures cannot accidentally reach an installer.
        self.bash = ('C:/Program Files/Git/usr/bin/bash.exe' if os.name == 'nt' else shutil.which('bash'))
        if not self.bash or not Path(self.bash).exists():
            self.skipTest('Bash required')
        base = PROJECT / 'x_temp/bootstrap_tests'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.log = self.root / 'commands.log'
        self.ready = self.root / 'media.ready'
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('VIDEO_SFT_', 'CONDA_'))}
        self.env.update(VIDEO_SFT_TEST_LOG=self.log.as_posix(),
                        VIDEO_SFT_TEST_READY=self.ready.as_posix())
        # Isolated PATH: no system package manager or media executable is reachable.
        self.stub('bash', f'exec {shlex.quote(self.bash)} "$@"')
        self.stub('dirname', 'exec /usr/bin/dirname "$@"')
        self.stub('env', 'exec /usr/bin/env "$@"')
        self.stub('uname', 'echo Linux')
        self.stub('id', 'echo 0')
        self.stub('python3', '''
if [[ "${1:-}" == -c ]]; then
  if [[ "$2" == *subprocess* ]]; then [[ -f "$VIDEO_SFT_TEST_READY" ]]; else exit 0; fi
elif [[ "${1:-}" == -m ]]; then
  printf 'LAUNCH %s\\n' "$*" >> "$VIDEO_SFT_TEST_LOG"
else
  printf 'CHECK %s\\n' "$*" >> "$VIDEO_SFT_TEST_LOG"
  [[ "${VIDEO_SFT_TEST_CODEC_FAIL:-0}" != 1 || "${2:-}" == --no-media ]]
fi
''')

    def stub(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/bash\n' + body + '\n', encoding='utf-8', newline='\n')
        path.chmod(0o755)
        return path

    def manager(self, name='apt-get', fail=False):
        self.stub(name, '''printf 'INSTALL %s\\n' "$*" >> "$VIDEO_SFT_TEST_LOG"
''' + ('exit 8' if fail else '''if [[ "$*" == *install* ]]; then : > "$VIDEO_SFT_TEST_READY"; fi'''))

    def call(self, *args, launcher=False, source=False):
        target = PROJECT / 'scripts' / ('run_pipeline.sh' if launcher else 'bootstrap.sh')
        action = ('source "$2"; code=$?; echo parent_survived; exit $code' if source
                  else 'shift; bash "$@"')
        return subprocess.run([self.bash, '-c', 'export PATH="$1"; ' + action,
                               'test', shell_path(self.bin), target.as_posix(), *args],
                              env=self.env, text=True, capture_output=True, timeout=30)

    def logged(self):
        return self.log.read_text(encoding='utf-8') if self.log.exists() else ''

    def test_missing_media_installed_and_repeat_does_not_install(self):
        self.manager()
        result = self.call('--print-python')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.strip().splitlines()), 1)
        self.assertIn('python3', result.stdout)
        self.assertIn('install -y --no-install-recommends ffmpeg', self.logged())
        installs = self.logged().count('INSTALL')
        self.assertEqual(self.call().returncode, 0)
        self.assertEqual(self.logged().count('INSTALL'), installs)

    def test_check_only_never_installs(self):
        self.manager()
        result = self.call('--check')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('installation disabled', result.stderr)
        self.assertNotIn('INSTALL', self.logged())

    def test_startup_failure_never_launches_application(self):
        self.manager(fail=True)
        result = self.call(launcher=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('LAUNCH', self.logged())

    def test_nonroot_without_sudo_fails_clearly(self):
        self.manager()
        self.stub('id', 'echo 1000')
        result = self.call()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('root or sudo', result.stderr)
        self.assertNotIn('INSTALL', self.logged())

    def test_startup_checks_media_before_launch(self):
        self.ready.touch()
        result = self.call('ui', '--plain', launcher=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('LAUNCH -m video_sft_builder ui --plain', self.logged())
        self.assertLess(self.logged().index('CHECK'), self.logged().index('LAUNCH'))

    def test_demo_and_help_do_not_install_media(self):
        for command in ('demo', '--help', 'report'):
            result = self.call(command, launcher=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('INSTALL', self.logged())

    def test_unusable_codecs_stop_before_ui(self):
        self.ready.touch()
        self.env['VIDEO_SFT_TEST_CODEC_FAIL'] = '1'
        result = self.call(launcher=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('LAUNCH', self.logged())

    def test_invalid_explicit_python_does_not_install(self):
        self.manager()
        self.env['VIDEO_SFT_PYTHON'] = '/not/a/python'
        result = self.call()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('VIDEO_SFT_PYTHON', result.stderr)
        self.assertNotIn('INSTALL', self.logged())

    def test_dnf_full_ffmpeg_package(self):
        self.manager('dnf')
        result = self.call()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('install -y ffmpeg ca-certificates', self.logged())

    def test_active_conda_prefix(self):
        conda = self.stub('conda', '''printf 'CONDA %s\\n' "$*" >> "$VIDEO_SFT_TEST_LOG"
: > "$VIDEO_SFT_TEST_READY"''')
        self.env.update(CONDA_EXE=conda.as_posix(), CONDA_PREFIX=shell_path(self.root))
        result = self.call()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--freeze-installed --prefix', self.logged())

    def test_sourcing_preserves_parent_shell(self):
        result = self.call(source=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('parent_survived', result.stdout)
        self.assertIn('do not source', result.stderr)

    def test_other_package_managers_use_only_requested_packages(self):
        for manager, expected in [('yum', 'install -y ffmpeg'),
                                  ('zypper', '--non-interactive install ffmpeg'),
                                  ('pacman', '-S --needed --noconfirm ffmpeg')]:
            with self.subTest(manager=manager):
                self.manager(manager)
                # zypper/pacman use different install verbs; make the stub
                # signal success for all verbs without running any OS tool.
                self.stub(manager, 'printf "INSTALL %s\\n" "$*" >> "$VIDEO_SFT_TEST_LOG"\n: > "$VIDEO_SFT_TEST_READY"')
                result = self.call()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(expected, self.logged())
                (self.bin / manager).unlink()
                self.ready.unlink()

    def test_missing_python_is_installed_before_media_check(self):
        self.manager()
        self.stub('python3', '''
if [[ "${1:-}" == -c ]]; then [[ -f "$VIDEO_SFT_TEST_READY" ]]; else exit 0; fi
''')
        result = self.call('--no-media')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('install -y --no-install-recommends python3.11', self.logged())


class EnvironmentTests(unittest.TestCase):
    def test_missing_executable_has_actionable_name(self):
        with patch.object(environment.subprocess, 'run', side_effect=FileNotFoundError):
            with self.assertRaisesRegex(RuntimeError, 'ffprobe: executable not found'):
                environment.run(['ffprobe', '-version'])

    def test_shared_library_failure_preserves_bounded_diagnostic(self):
        result = subprocess.CompletedProcess([], 127, b'', b'error while loading shared libraries')
        with patch.object(environment.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(RuntimeError, 'shared libraries'):
                environment.run(['ffmpeg', '-version'])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'real FFmpeg not installed')
    def test_real_synthetic_media_selftest(self):
        environment.check()


if __name__ == '__main__':
    unittest.main()
