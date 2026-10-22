"""Regression tests for Ubuntu 22.04/FFmpeg 4.4 and modern sync options."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'src'))
from video_sft_builder.errors import PipelineError
from video_sft_builder.ffmpeg_compat import passthrough_args
from video_sft_builder.media import FFmpegMedia
from video_sft_builder.util import file_digest

spec = importlib.util.spec_from_file_location('compat_environment', PROJECT / 'scripts/check_environment.py')
environment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(environment)

OLD_HELP = b'Advanced options:\n-vsync parameter    video sync method\n'
NEW_HELP = b'Advanced options:\n-vsync parameter    deprecated\n-fps_mode mode      set framerate mode\n'


class CompatibilityTests(unittest.TestCase):
    def test_ffmpeg44_selects_vsync_zero(self):
        self.assertEqual(passthrough_args(OLD_HELP), ('-vsync', '0'))

    def test_modern_prefers_fps_mode(self):
        self.assertEqual(passthrough_args(NEW_HELP), ('-fps_mode', 'passthrough'))

    def test_modern_without_legacy_option(self):
        self.assertEqual(passthrough_args('-fps_mode[:stream] mode\n'), ('-fps_mode', 'passthrough'))

    def test_prose_or_unknown_options_do_not_silently_change_timing(self):
        for text in ('', 'Unrecognized option -fps_mode', '-fps_mode_other value',
                     'The option -vsync is mentioned here'):
            with self.subTest(text=text), self.assertRaises(PipelineError):
                passthrough_args(text)

    def test_media_capability_check_is_cached(self):
        media = FFmpegMedia(SimpleNamespace(data={'media': {'ffmpeg': 'ffmpeg'}}))
        with patch.object(media, 'command', return_value=OLD_HELP) as command:
            self.assertEqual(media.sync_args, ('-vsync', '0'))
            self.assertEqual(media.sync_args, ('-vsync', '0'))
            command.assert_called_once_with(['ffmpeg', '-hide_banner', '-h', 'full'])

    def test_startup_selftest_uses_same_old_and_new_options(self):
        for help_text, expected in ((OLD_HELP, ('-vsync', '0')),
                                    (NEW_HELP, ('-fps_mode', 'passthrough'))):
            calls = []

            def fake_run(args):
                calls.append(args)
                if '-version' in args:
                    return b'ffmpeg test version\n'
                if '-h' in args:
                    return help_text
                if 'lavfi' in args:
                    index = args.index(expected[0])
                    self.assertEqual(tuple(args[index:index + 2]), expected)
                    if expected[0] == '-vsync':
                        self.assertNotIn('-fps_mode', args)
                    Path(args[-1]).write_bytes(b'synthetic test fixture')
                    return b''
                if '-show_streams' in args:
                    return b'{"streams":[{"codec_type":"video"}]}'
                if 'rawvideo' in args:
                    return bytes(1024)
                if 'image2pipe' in args:
                    return b'\xff\xd8fake-jpeg'
                self.fail('Unexpected environment subprocess')

            with self.subTest(expected=expected), \
                    patch.object(environment.shutil, 'which', side_effect=lambda name: name), \
                    patch.object(environment, 'run', side_effect=fake_run):
                environment.check()
                self.assertEqual(sum('lavfi' in args for args in calls), 1)

    def test_real_clipping_command_uses_legacy_option_and_preserves_source(self):
        # Exercise actual FFmpegMedia.clip staging/publishing and time sidecar;
        # only the external executable/probe are replaced, no model is involved.
        base = PROJECT / 'x_temp/compat_tests'
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as directory:
            root = Path(directory)
            source = root / 'original.mp4'
            original = b'original synthetic immutable fixture'
            source.write_bytes(original)
            stat = source.stat()
            video = {'id': 'video1', 'path': str(source), 'sha256': file_digest(source),
                     'stat_size': stat.st_size, 'stat_mtime_ns': stat.st_mtime_ns}
            config = SimpleNamespace(output=root / 'build', data={'media': {
                'ffmpeg': 'ffmpeg', 'codec': 'libx264', 'preset': 'fast', 'crf': 18,
                'timeout_seconds': 20, 'clip_duration_tolerance_seconds': 0.2}})
            media = FFmpegMedia(config)
            calls = []

            def fake_command(args):
                calls.append(args)
                if '-h' in args:
                    return OLD_HELP
                self.assertNotIn('-fps_mode', args)
                index = args.index('-vsync')
                self.assertEqual(args[index + 1], '0')
                self.assertEqual(args[args.index('-ss') + 1], '1')
                self.assertEqual(args[args.index('-t') + 1], '2')
                Path(args[-1]).write_bytes(b'derived synthetic fixture')
                return b''

            with patch.object(media, 'command', side_effect=fake_command), \
                    patch.object(media, 'probe', return_value={'duration': 2}):
                clip = media.clip(video, {'id': 'window1', 'start': 1, 'end': 3})
                self.assertTrue(clip.is_file())
                self.assertEqual(source.read_bytes(), original)
                sidecar = json.loads(clip.with_suffix('.json').read_text())
                self.assertEqual(sidecar['source_start_seconds'], 1)
                self.assertEqual(sidecar['time_mapping'], 'source_start_plus_clip_time')
                self.assertEqual(len(calls), 2)
                # Resume a published clip without any new subprocess.
                self.assertEqual(media.clip(video, {'id': 'window1', 'start': 1, 'end': 3}), clip)
                self.assertEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()
