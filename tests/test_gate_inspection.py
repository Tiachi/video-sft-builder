"""Reference-time and no-clobber tests; no decoder, Pillow, media or API needed."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('gate_inspection_helper', ROOT / 'scripts/inspect_caption_gate.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class GateInspectionTests(unittest.TestCase):
    def test_sampling_preserves_production_formula_and_absolute_range(self):
        times = helper.gate_times(60.026693, 29.97, 32)
        self.assertEqual(len(times), 32)
        self.assertEqual(times[0], 0)
        self.assertAlmostEqual(times[-1], 60.026693 - 1 / 29.97)
        self.assertAlmostEqual(times[5], 5 * (60.026693 - 1 / 29.97) / 31)
        self.assertTrue(all(a < b for a, b in zip(times, times[1:])))
        for arguments in ((60, 30, 65), (60, 0, 32), (float('nan'), 30, 32)):
            with self.assertRaises(ValueError):
                helper.gate_times(*arguments)

    def test_identity_mismatch_stops_before_decode_or_output(self):
        parent = ROOT.parent / 'gate_inspection_tests'
        parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            root = Path(directory)
            video, manifest, rejected = (root / n for n in ('fixture.mp4', 'manifest.json', 'rejected.txt'))
            video.write_bytes(b'synthetic-non-video')
            manifest.write_text(json.dumps({'sha256': '0' * 64, 'id': 'synthetic'}))
            value = {'video_id': 'synthetic', 'l3': {}, 'response': {}, 'reason': 'fixture'}
            rejected.write_text('shell wrapper\n' + json.dumps(value) + '\n')
            self.assertEqual(helper.rejection(rejected), value)
            with self.assertRaisesRegex(ValueError, 'identity'):
                helper.inspect(video, manifest, rejected, root / 'new', 'nonexistent-ffmpeg')
            self.assertFalse((root / 'new').exists())
            existing = root / 'existing'
            existing.mkdir()
            with self.assertRaisesRegex(ValueError, 'NEW'):
                helper.inspect(video, manifest, rejected, existing, 'nonexistent-ffmpeg')
            self.assertEqual(video.read_bytes(), b'synthetic-non-video')


if __name__ == '__main__':
    unittest.main()
