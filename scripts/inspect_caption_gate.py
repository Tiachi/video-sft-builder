#!/usr/bin/env python3
"""Offline inspection of one explicitly selected original and gate rejection.

Reads one MP4, its manifest, and one pasted JSON rejection. Verifies source SHA256
and video ID. Writes only a NEW private inspection directory outside source Git.
Reconstructs bounded reference JPEGs using the production sampling formula, not
the actual server/API request pixels. No network/API/state/media modifications.
Requires Pillow and a caller-supplied FFmpeg. Safe no-clobber publication.
"""
import argparse
from collections import Counter
import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def gate_times(duration, fps, count):
    if not 1 <= count <= 64 or not math.isfinite(duration) or not math.isfinite(fps) or duration <= 0 or fps <= 0:
        raise ValueError('Invalid bounded sampling metadata')
    return [index * max(0, duration - 1 / fps) / max(1, count - 1) for index in range(count)]


def rejection(path):
    path = Path(path)
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('Rejection text too large')
    text = path.read_text(encoding='utf-8-sig')
    for line in text.splitlines():
        if line.lstrip().startswith('{'):
            value = json.loads(line)
            if {'video_id', 'l3', 'response', 'reason'} <= set(value):
                return value
    raise ValueError('No single-line gate rejection JSON found')


def sheet(images, destination):
    from PIL import Image, ImageDraw, ImageFont
    width, height = 640, 360
    canvas = Image.new('RGB', (2 * width, 4 * (height + 28)), 'white')
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype('arial.ttf', 18)
    except OSError:
        font = ImageFont.load_default()
    for index, (label, encoded) in enumerate(images):
        x, y = index % 2 * width, index // 2 * (height + 28)
        draw.text((x + 6, y + 3), label, fill='black', font=font)
        with Image.open(io.BytesIO(encoded)) as frame:
            frame.thumbnail((width, height))
            canvas.paste(frame, (x, y + 28))
    canvas.save(destination)


def inspect(video, manifest, rejected, output, ffmpeg, count=32, extras=()):
    video, manifest, rejected = (Path(path).resolve(strict=True) for path in (video, manifest, rejected))
    output = Path(output).resolve()
    if output.exists() or output.is_relative_to(ROOT) or not output.parent.is_dir():
        raise ValueError('Use a NEW inspection directory outside the source checkout')
    metadata, audit = json.loads(manifest.read_text()), rejection(rejected)
    before = video.stat()
    original_digest = digest(video)
    if original_digest != metadata['sha256'] or metadata['id'] != audit['video_id']:
        raise ValueError('Source video identity mismatch')
    times = gate_times(metadata['duration'], metadata['fps'], count)
    extras = list(extras)
    if len(extras) > 128 or any(not math.isfinite(t) or not 0 <= t < metadata['duration'] for t in extras):
        raise ValueError('Extra reference time bound exceeded')
    frames = [(f'frame_{i:06d}', t) for i, t in enumerate(times)] + [(f'extra_{i:06d}', t) for i, t in enumerate(extras)]
    version = subprocess.run([str(ffmpeg), '-version'], capture_output=True, timeout=10, check=True).stdout.decode(errors='replace').splitlines()[0]
    with tempfile.TemporaryDirectory(prefix='.gate-inspection-', dir=output.parent) as directory:
        staging = Path(directory)
        if not staging.resolve().is_relative_to(output.parent):
            raise ValueError('Staging containment failure')
        os.chmod(staging, 0o700)
        (staging / 'frames').mkdir()
        records, pending = [], []
        for index, (name, timestamp) in enumerate(frames):
            command = [str(ffmpeg), '-nostdin', '-v', 'error', '-ss', f'{timestamp:.6f}', '-i', str(video),
                       '-map', '0:v:0', '-an', '-sn', '-dn', '-frames:v', '1', '-vf',
                       f'scale={metadata["width"]}:{metadata["height"]}:force_original_aspect_ratio=decrease',
                       '-f', 'image2pipe', '-vcodec', 'mjpeg', '-q:v', '3', 'pipe:1']
            encoded = subprocess.run(command, capture_output=True, timeout=20, check=True).stdout
            if not encoded or len(encoded) > 16 * 1024 * 1024:
                raise ValueError('Decoded reference frame size invalid')
            (staging / 'frames' / (name + '.jpg')).write_bytes(encoded)
            records.append({'id': name, 'time': timestamp, 'sha256': hashlib.sha256(encoded).hexdigest()})
            pending.append((f'{name}  t={timestamp:.6f}s', encoded))
            if len(pending) == 8 or index == len(frames) - 1:
                sheet(pending, staging / f'sheet_{index // 8:02d}.png')
                pending = []
        if (video.stat().st_size, video.stat().st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            raise ValueError('Source changed during inspection')
        claims = audit['response'].get('claims', [])
        result = {'video_id': metadata['id'], 'original_sha256': original_digest, 'duration': metadata['duration'],
                  'ffmpeg': version, 'frames': records, 'gate_decision': audit['response'].get('decision'),
                  'gate_reason': audit['reason'], 'claim_status_counts': dict(Counter(c.get('status') for c in claims)),
                  'model_calls': 0, 'actual_server_frames_obtained': False,
                  'visibility': 'local_reconstruction_same_source_and_sampling_formula_not_identical_API_pixels'}
        (staging / 'inspection.json').write_text(json.dumps(result, indent=2) + '\n')
        os.rename(staging, output)
    return {key: value for key, value in result.items() if key != 'frames'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('video', 'manifest', 'rejection', 'output', 'ffmpeg'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--frame-count', type=int, default=32)
    parser.add_argument('--extra-times', default='')
    args = parser.parse_args()
    try:
        extras = [float(t) for t in args.extra_times.split(',')] if args.extra_times else []
        result = inspect(args.video, args.manifest, args.rejection, args.output, args.ffmpeg, args.frame_count, extras)
        print(json.dumps(result))
        print('PASS: offline local reconstruction only; no model calls or source writes')
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        print('FAIL: offline reconstruction failed; source unchanged; inspect paths/tools', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
