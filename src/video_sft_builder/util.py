from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import platform
import subprocess
import sysconfig
import uuid

from .errors import ConfigError, PipelineError


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def strict_json(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Non-finite JSON number')))


def read_json(path):
    try:
        return strict_json(Path(path).read_text(encoding='utf-8'))
    except ValueError:
        raise ConfigError('Invalid JSON, duplicate key or non-finite number in configuration/asset') from None


def asset(relative):
    checkout = Path(__file__).resolve().parents[2]
    if (checkout / 'configs/task_registry.json').is_file():
        return checkout / relative
    installed = Path(sysconfig.get_path('data')) / 'share/video-sft-builder' / relative
    if not installed.is_file():
        raise ConfigError('Packaged asset missing: ' + relative)
    return installed


def within(path, root):
    return Path(path).resolve().is_relative_to(Path(root).resolve())


def publish_file(staging, target):
    staging, target = Path(staging).resolve(), Path(target).resolve()
    if staging.parent != target.parent:
        raise PipelineError('Publication must stay in the verified staging directory')
    if os.name == 'nt':
        # Windows rename is atomic and fails if target exists. Hard links may
        # be disallowed by managed desktop filesystem policies.
        os.rename(staging, target)
    else:
        os.link(staging, target)


def atomic_write(path, content, *, replace=False):
    """Same-directory staging; exclusive publication unless replacement is explicit."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.part')
    try:
        with tmp.open('xb') as stream:
            stream.write(content.encode('utf-8') if isinstance(content, str) else content)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(tmp, path)
        else:
            # A hard link provides no-clobber publication on POSIX and Windows.
            publish_file(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def write_json(path, value, *, replace=False):
    atomic_write(path, canonical(value) + '\n', replace=replace)


def safe_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', value):
        raise ConfigError('Identifier must be 1-96 safe ASCII characters')
    return value


def repository_provenance():
    root = asset('configs/task_registry.json').parent.parent
    value = {'python': platform.python_version(), 'platform': platform.system(),
             'git_commit': None, 'git_branch': None, 'git_dirty': None}
    try:
        def git(*args):
            result = subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                                    text=True, timeout=10, check=True)
            return result.stdout.strip()
        if Path(git('rev-parse', '--show-toplevel')).resolve() != root.resolve():
            return value
        value.update(git_commit=git('rev-parse', 'HEAD'), git_branch=git('branch', '--show-current'),
                     git_dirty=bool(git('status', '--porcelain')))
    except (OSError, subprocess.SubprocessError):
        pass
    return value


@contextmanager
def coordinator_lock(path):
    """OS advisory lock, released after crashes; one coordinator per run."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open('a+b')
    acquired = False
    try:
        if os.name == 'nt':
            import msvcrt
            if stream.seek(0, 2) == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise PipelineError('Run already has an active coordinator') from None
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise PipelineError('Run already has an active coordinator') from None
        acquired = True
        yield
    finally:
        if acquired:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()
