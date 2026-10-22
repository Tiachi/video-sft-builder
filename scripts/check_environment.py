"""Local dependency/self-test only. Never opens settings, user media or model APIs."""
import argparse
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

# The source checkout is the startup entry; share exactly the same capability
# selection with real clipping, before PYTHONPATH is set by run_pipeline.sh.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_sft_builder.errors import PipelineError
from video_sft_builder.ffmpeg_compat import passthrough_args


def run(args):
    try:
        result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                                timeout=20, check=False)
    except FileNotFoundError:
        raise RuntimeError(f'{Path(args[0]).name}: executable not found on PATH') from None
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f'{Path(args[0]).name}: cannot start or timed out ({type(error).__name__})') from None
    if result.returncode:
        # No user input/credentials are used in this test; bounded native diagnostics help
        # distinguish missing shared libraries and unavailable codecs from absent tools.
        detail = result.stderr.decode(errors='replace')[-1200:]
        raise RuntimeError(f'{Path(args[0]).name}: exit={result.returncode}: {detail}')
    return result.stdout


def check(media=True):
    if sys.version_info < (3, 11):
        raise RuntimeError('Python >=3.11 required')
    for name in ('sqlite3', 'ssl', 'urllib.request', 'decimal', 'json'):
        importlib.import_module(name)
    print(f'PASS: Python {sys.version.split()[0]} + SQLite/SSL/standard library', flush=True)
    if not media:
        return
    for name in ('ffmpeg', 'ffprobe'):
        path = shutil.which(name)
        if not path:
            raise RuntimeError(f'{name}: executable not found on PATH')
        version = run([path, '-version']).decode(errors='replace').splitlines()[0]
        print(f'PASS: {name}: {version}', flush=True)
    # Exercise the UI's actual libx264/passthrough recipe; a codec-restricted
    # FFmpeg build can have working -version but still fail the real pipeline.
    sync = passthrough_args(run(['ffmpeg', '-hide_banner', '-h', 'full']))
    print('PASS: FFmpeg timing mode: ' + ' '.join(sync), flush=True)
    with tempfile.TemporaryDirectory(prefix='video-sft-env-') as directory:
        path = Path(directory) / 'selftest.mp4'
        run(['ffmpeg', '-nostdin', '-v', 'error', '-n', '-f', 'lavfi', '-i',
             'color=c=blue:s=64x64:r=4:d=0.5', '-an', '-c:v', 'libx264',
             '-preset', 'fast', '-crf', '18', *sync, str(path)])
        metadata = json.loads(run(['ffprobe', '-v', 'error', '-show_streams',
                                   '-show_format', '-of', 'json', str(path)]))
        if not any(s.get('codec_type') == 'video' for s in metadata.get('streams', [])):
            raise RuntimeError('ffprobe self-test did not find a video stream')
        gray = run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(path),
                    '-frames:v', '1', '-vf', 'scale=32:32,format=gray',
                    '-f', 'rawvideo', '-pix_fmt', 'gray', 'pipe:1'])
        jpeg = run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(path),
                    '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'mjpeg', 'pipe:1'])
        if len(gray) != 32 * 32 or not jpeg.startswith(b'\xff\xd8'):
            raise RuntimeError('FFmpeg frame extraction/codec self-test failed')
    print('PASS: synthetic MP4 encode/probe/decode/gray/JPEG self-test', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-media', action='store_true')
    args = parser.parse_args()
    try:
        check(media=not args.no_media)
    except (RuntimeError, ImportError, ValueError, OSError, PipelineError) as error:
        print(f'FAIL: environment: {error}', file=sys.stderr)
        raise SystemExit(1)
