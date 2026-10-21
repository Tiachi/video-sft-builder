"""Local directory/file and bounded direct-MP4 downloads. No page scraping."""
import os
import http.client
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .errors import ConfigError, PipelineError
from .util import digest, file_digest, publish_file, read_json, write_json


def public_url(value):
    parsed = urllib.parse.urlsplit(value)
    host = parsed.hostname or ''
    if ':' in host:
        host = '[' + host + ']'
    try:
        if parsed.port:
            host += ':' + str(parsed.port)
    except ValueError:
        pass
    return urllib.parse.urlunsplit((parsed.scheme, host, parsed.path, '', ''))


def describe_source(value, run_root):
    if not isinstance(value, str) or not value.strip():
        raise ConfigError('Provide a source MP4 directory, MP4 file or direct MP4 URL')
    if value.startswith(('http://', 'https://')):
        parsed = urllib.parse.urlsplit(value)
        if parsed.username or parsed.password or not parsed.hostname or not parsed.path.lower().endswith('.mp4'):
            raise ConfigError('Source URL must be a direct .mp4 link without embedded username/password')
        return {'kind': 'url', 'public_source': public_url(value), 'source_hash': digest(value),
                'input_root': str(Path(run_root) / 'inputs'), 'allowlist': ['source.mp4']}
    path = Path(value).expanduser().resolve()
    if path.is_file() and path.suffix.lower() == '.mp4':
        return {'kind': 'file', 'public_source': str(path), 'source_hash': digest(str(path)),
                'input_root': str(path.parent), 'allowlist': [path.name]}
    if path.is_dir():
        return {'kind': 'directory', 'public_source': str(path), 'source_hash': digest(str(path)),
                'input_root': str(path), 'allowlist': []}
    raise ConfigError('Source is not an existing MP4 file or directory')


def acquire_url(url, run_root, limits):
    target = Path(run_root) / 'inputs/source.mp4'
    receipt = target.parent / 'download.json'
    if receipt.exists():
        saved = read_json(receipt)
        if saved['source_hash'] != digest(url) or not target.is_file() or file_digest(target) != saved['sha256']:
            raise PipelineError('Downloaded source identity mismatch')
        return target
    if target.exists():
        raise PipelineError('Uncommitted source download exists; inspect it rather than overwrite')
    max_bytes, timeout = limits['max_bytes'], limits['timeout_seconds']
    if type(max_bytes) is not int or max_bytes <= 0 or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ConfigError('Download size and timeout limits must be positive')
    def validate(value):
        p = urllib.parse.urlsplit(value)
        if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or (p.scheme == 'http' and not limits['allow_http']):
            raise ConfigError('HTTP downloads require explicit download.allow_http; use a trusted direct MP4 URL')
    validate(url)
    class Redirects(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            validate(newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    opener = urllib.request.build_opener(Redirects())
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name('.download-' + uuid.uuid4().hex + '.part')
    started, count = time.monotonic(), 0
    try:
        fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as output:
            with opener.open(urllib.request.Request(url, headers={'User-Agent': 'video-sft-builder/0.2'}), timeout=timeout) as response:
                length = response.headers.get('Content-Length')
                if length and int(length) > max_bytes:
                    raise PipelineError('Source download exceeds configured byte limit')
                while chunk := response.read(1024 * 1024):
                    count += len(chunk)
                    if count > max_bytes or time.monotonic() - started > timeout:
                        raise PipelineError('Source download exceeds byte/time limit')
                    output.write(chunk)
                if length and count != int(length):
                    raise PipelineError('Source download was truncated')
            output.flush()
            os.fsync(output.fileno())
        checksum = file_digest(staging)
        publish_file(staging, target)
        write_json(receipt, {'source': public_url(url), 'source_hash': digest(url), 'bytes': count, 'sha256': checksum})
        return target
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException):
        # Never echo a signed URL, headers, service body or credentials.
        raise PipelineError('Source download failed; private address omitted') from None
    finally:
        staging.unlink(missing_ok=True)
