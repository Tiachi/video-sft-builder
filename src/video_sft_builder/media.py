"""Bounded, sequential ffprobe/FFmpeg IO; originals are immutable inputs."""
from fractions import Fraction
from functools import cached_property
import json
import math
import os
from pathlib import Path
import subprocess
import uuid

from .errors import Blocked, PipelineError
from .ffmpeg_compat import passthrough_args
from .util import digest, file_digest, publish_file, within, write_json


def enumerate_mp4(config):
    source = config.data['input']
    # Managed Windows desktops may deny directory-handle canonicalization.
    # Only the explicit synthetic adapter can use the lexical fallback;
    # production media still requires strict physical-path resolution.
    root = Path(source['root']).resolve(strict=config.data['teacher']['backend'] != 'synthetic')
    if not root.is_dir():
        raise PipelineError('input.root is not a directory')
    allowlist = source.get('allowlist')
    if allowlist:
        paths = []
        for name in allowlist:
            path = (root / name).resolve(strict=True)
            if not within(path, root) or path.suffix.lower() != '.mp4' or not path.is_file():
                raise PipelineError('Invalid media allowlist entry')
            paths.append(path)
        if len(paths) != len(set(paths)):
            raise PipelineError('Duplicate paths in allowlist')
        if len(paths) > config.data['run']['max_videos']:
            raise Blocked('allowlist_exceeds_max_videos')
        return sorted(paths)
    pending, found, entries = [root], [], 0
    while pending:
        directory = pending.pop(0)
        with os.scandir(directory) as stream:
            children = []
            for item in stream:
                entries += 1
                if entries > source['max_scan_entries']:
                    raise Blocked('directory_scan_entry_limit')
                children.append(item)
        for item in sorted(children, key=lambda item: item.name):
            if item.is_symlink():
                continue
            if item.is_dir(follow_symlinks=False) and source['recursive']:
                pending.append(Path(item.path))
            elif item.is_file(follow_symlinks=False) and item.name.lower().endswith('.mp4'):
                found.append(Path(item.path))
                if len(found) > config.data['run']['max_videos']:
                    raise Blocked('input_exceeds_max_videos_use_explicit_allowlist')
    return found


def windows(duration, step, prefix):
    count = math.ceil(duration / step)
    return [{'id': f'{prefix}_{index:06d}', 'start': index * step,
             'end': min(duration, (index + 1) * step)} for index in range(count)]


def gray_metrics(frames, width, height, black_threshold):
    if not frames or any(len(frame) != width * height for frame in frames):
        raise PipelineError('Sample frame decode failed')
    black = sum(sum(pixel <= black_threshold for pixel in frame) / len(frame) for frame in frames) / len(frames)
    sharpness, hashes = [], []
    for frame in frames:
        values = []
        for y in range(1, height - 1):
            for x in range(1, width - 1):
                i = y * width + x
                values.append(4 * frame[i] - frame[i - 1] - frame[i + 1] - frame[i - width] - frame[i + width])
        mean = sum(values) / len(values)
        sharpness.append(sum((v - mean) ** 2 for v in values) / len(values))
        bits = 0
        for y in range(8):
            for x in range(8):
                a = frame[min(height - 1, y * height // 8) * width + x * width // 9]
                b = frame[min(height - 1, y * height // 8) * width + (x + 1) * width // 9]
                bits = (bits << 1) | (a > b)
        hashes.append(f'{bits:016x}')
    return {'black_fraction': black, 'laplacian_variance_mean': sum(sharpness) / len(sharpness), 'dhashes': hashes}


class FFmpegMedia:
    synthetic = False

    def __init__(self, config):
        self.config = config
        self.settings = config.data['media']

    def command(self, args):
        try:
            result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, timeout=self.settings['timeout_seconds'], check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise PipelineError('Media tool missing, failed to start or timed out') from None
        if result.returncode:
            # FFmpeg output can contain paths/URLs; retain only the exit code.
            raise PipelineError('Media subprocess failed with exit code ' + str(result.returncode))
        return result.stdout

    def doctor(self):
        return {key: self.command([self.settings[key], '-version']).decode(errors='replace').splitlines()[0]
                for key in ('ffmpeg', 'ffprobe')}

    @cached_property
    def sync_args(self):
        return passthrough_args(self.command([self.settings['ffmpeg'], '-hide_banner', '-h', 'full']))

    def probe(self, path):
        try:
            return self._probe(path)
        except (ValueError, TypeError, KeyError, ZeroDivisionError, OverflowError):
            raise PipelineError('Invalid or incomplete ffprobe metadata') from None

    def _probe(self, path):
        result = json.loads(self.command([self.settings['ffprobe'], '-v', 'error', '-print_format', 'json',
                                          '-show_format', '-show_streams', str(path)]))
        stream = next((s for s in result.get('streams', []) if s.get('codec_type') == 'video'
                       and not s.get('disposition', {}).get('attached_pic')), None)
        if not stream:
            raise PipelineError('No video stream')
        duration = float(stream.get('duration') or result.get('format', {}).get('duration') or 0)
        fps = float(Fraction(stream.get('avg_frame_rate') or '0/1'))
        start_pts = float(stream.get('start_time') or 0)
        if not all(math.isfinite(v) for v in (duration, fps, start_pts)) or duration <= 0 or fps <= 0:
            raise PipelineError('Invalid video duration or frame rate')
        return {'duration': duration, 'width': int(stream['width']), 'height': int(stream['height']),
                'fps': fps, 'stream_start_seconds': start_pts, 'bytes': Path(path).stat().st_size,
                'codec': stream.get('codec_name'), 'sampling_observation': 'not_observed_by_provider'}

    def frame(self, path, timestamp, *, width=None, height=None, jpeg=False):
        args = [self.settings['ffmpeg'], '-nostdin', '-v', 'error', '-ss', f'{timestamp:.6f}', '-i', str(path),
                '-map', '0:v:0', '-an', '-sn', '-dn', '-frames:v', '1']
        if jpeg:
            args += ['-vf', f'scale={width}:{height}:force_original_aspect_ratio=decrease',
                     '-f', 'image2pipe', '-vcodec', 'mjpeg', '-q:v', '3', 'pipe:1']
        else:
            args += ['-vf', f'scale={width}:{height},format=gray', '-f', 'rawvideo', '-pix_fmt', 'gray', 'pipe:1']
        value = self.command(args)
        if not value:
            raise PipelineError('Empty decoded frame')
        return value

    def prepare(self, path):
        before = path.stat()
        metadata = self.probe(path)
        source = self.config.data['input']
        relative = path.resolve().relative_to(Path(source['root']).resolve()).as_posix()
        source_name = self.config.source_for(relative)
        checksum = file_digest(path)
        count = self.settings['sample_count']
        times = [(index + 0.5) * metadata['duration'] / count for index in range(count)]
        frames = [self.frame(path, t, width=self.settings['sample_width'], height=self.settings['sample_height']) for t in times]
        metrics = gray_metrics(frames, self.settings['sample_width'], self.settings['sample_height'], self.settings['black_pixel_threshold'])
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise PipelineError('Input changed while preparing')
        return {'id': digest([source_name, relative, checksum])[:24], 'source': source_name,
                'relative_path': relative, 'path': str(path.resolve()), 'sha256': checksum,
                'original_id': relative, 'stat_size': after.st_size, 'stat_mtime_ns': after.st_mtime_ns,
                **metadata, 'metrics': metrics, 'sample_times': times}

    def unchanged(self, video):
        info = Path(video['path']).stat()
        if (info.st_size, info.st_mtime_ns) != (video['stat_size'], video['stat_mtime_ns']):
            raise PipelineError('Original media changed since ingestion')

    def clip(self, video, window):
        self.unchanged(video)
        directory = self.config.output / 'media' / video['id']
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / (window['id'] + '.mp4')
        sidecar = target.with_suffix('.json')
        identity = {'source_sha256': video['sha256'], 'window': window}
        if target.exists() and sidecar.exists():
            saved = json.loads(sidecar.read_text(encoding='utf-8'))
            if saved['identity'] != identity or saved['sha256'] != file_digest(target):
                raise PipelineError('Derived clip identity/checksum mismatch')
            return target
        if target.exists() or sidecar.exists():
            raise Blocked('orphan_clip_requires_inspection')
        staging = target.with_name('.' + target.stem + '.' + uuid.uuid4().hex + '.mp4')
        duration = window['end'] - window['start']
        try:
            self.command([self.settings['ffmpeg'], '-nostdin', '-v', 'error', '-n', '-ss', str(window['start']),
                          '-i', video['path'], '-t', str(duration), '-map', '0:v:0', '-an', '-sn', '-dn',
                          '-c:v', self.settings['codec'], '-preset', self.settings['preset'], '-crf', str(self.settings['crf']),
                          *self.sync_args, '-movflags', '+faststart', str(staging)])
            actual = self.probe(staging)
            if abs(actual['duration'] - duration) > self.settings['clip_duration_tolerance_seconds']:
                raise Blocked('derived_clip_duration_mismatch')
            publish_file(staging, target)
            write_json(sidecar, {'identity': identity, 'sha256': file_digest(target), 'actual': actual,
                                 'source_start_seconds': window['start'], 'time_mapping': 'source_start_plus_clip_time'})
        finally:
            staging.unlink(missing_ok=True)
        return target

    def gate_frames(self, video):
        self.unchanged(video)
        count = self.config.data['caption']['gate_frame_count']
        directory = self.config.output / 'media' / video['id'] / 'caption_gate'
        directory.mkdir(parents=True, exist_ok=True)
        values = []
        for index in range(count):
            timestamp = index * max(0, video['duration'] - 1 / video['fps']) / max(1, count - 1)
            target = directory / f'{index:06d}.jpg'
            if not target.exists():
                from .util import atomic_write
                atomic_write(target, self.frame(video['path'], timestamp, width=video['width'], height=video['height'], jpeg=True))
            values.append({'path': str(target), 'time': timestamp, 'sha256': file_digest(target)})
        return values
