"""Private diagnostic snapshots. No model calls, original writes, or public uploads."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import getpass
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request
import uuid

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'src'))
from video_sft_builder.util import coordinator_lock
from video_sft_builder.errors import PipelineError

RELAY = 'Tiachi/video-sft-builder-relay'
PUBLIC = 'Tiachi/video-sft-builder'
DISABLED_PUSH = 'disabled-public-push://video-sft-builder'
MAX_BYTES = 2 * 1024**3
MAX_FILES = 10000
PART_BYTES = 32 * 1024**2
TEXT_EXT = {'.json', '.jsonl', '.md', '.csv'}
MEDIA_EXT = {'.mp4', '.jpg', '.jpeg', '.png'}
ROOT_FILES = {'runtime.json', 'build.json', 'status.json', 'resolved_config.json',
              'code_and_asset_identity.json', 'execution_provenance.json', 'terminal.events.jsonl'}
SUBDIRS = {'artifacts', 'reports', 'exports', 'reject', 'media', 'inputs'}
SECRET_FIELD = re.compile(r'(?i)^(?:x-api-key|api[_-]?key|api_secret|authorization|access[_-]?token|refresh[_-]?token|token|password|secret|secret_key|client_secret|private_key|credential_file|cookie|signature|policy|accesskeyid|accesskeysecret|security_token|aws_access_key_id|aws_secret_access_key|x-oss-security-token)$')
TOKEN = re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9_-]{20,})\b')
URL = re.compile(r'https?://[^\s<>"\x27]+')


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024**2), b''):
            digest.update(chunk)
    return digest.hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def scrub(value):
    if isinstance(value, dict):
        return {key: '[REDACTED]' if SECRET_FIELD.match(str(key)) else scrub(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if not isinstance(value, str):
        return value
    value = TOKEN.sub('[REDACTED_TOKEN]', value)
    value = re.sub(r'(?i)\bBearer\s+[A-Za-z0-9_.-]+', 'Bearer [REDACTED]', value)
    def clean_url(match):
        parsed = urllib.parse.urlsplit(match.group())
        host = parsed.hostname or ''
        if ':' in host:
            host = '[' + host + ']'
        if parsed.port:
            host += ':' + str(parsed.port)
        return urllib.parse.urlunsplit((parsed.scheme, host, parsed.path, '', ''))
    value = URL.sub(clean_url, value)
    if '-----BEGIN ' in value and 'PRIVATE KEY-----' in value:
        raise ValueError('Private key material encountered; refusing snapshot')
    return value


def scrub_text(data, suffix):
    text = data.decode('utf-8')
    if suffix == '.json':
        return json.dumps(scrub(json.loads(text)), ensure_ascii=False, indent=2).encode()
    if suffix == '.jsonl':
        return ''.join(json.dumps(scrub(json.loads(line)), ensure_ascii=False) + '\n'
                       for line in text.splitlines() if line.strip()).encode()
    # Reports should not contain credentials, but redact common assignment syntax
    # as well as key-shaped tokens and signed URL queries in diagnostic copies.
    text = re.sub(r'(?im)(["\x27]?(?:api_key|access_token|password|authorization)["\x27]?\s*[:=]\s*)[^\r\n]+',
                  r'\1[REDACTED]', text)
    return scrub(text).encode()


def sqlite_snapshot(source, target):
    # Backup from a read-only handle; VACUUM removes old pages after redaction.
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as incoming, closing(sqlite3.connect(target)) as output:
        incoming.backup(output)
        tables = {row[0] for row in output.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        allowed = {'metadata', 'records', 'events', 'requests', 'auxiliary', 'upload_cache', 'sqlite_sequence'}
        if tables - allowed:
            raise ValueError('Unexpected SQLite tables; refusing automatic transfer')
        output.execute('PRAGMA secure_delete=ON')
        if 'upload_cache' in tables:
            output.execute('DELETE FROM upload_cache')
        for table in sorted(tables - {'upload_cache', 'sqlite_sequence'}):
            columns = [row[1] for row in output.execute(f'PRAGMA table_info("{table}")') if row[2] == 'TEXT']
            for column in columns:
                if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', column):
                    raise ValueError('Unexpected SQLite column')
                rows = output.execute(f'SELECT rowid,"{column}" FROM "{table}"').fetchall()
                for rowid, text in rows:
                    if text is None:
                        continue
                    try:
                        safe = json.dumps(scrub(json.loads(text)), ensure_ascii=False)
                    except json.JSONDecodeError:
                        safe = scrub(text)
                    if safe != text:
                        output.execute(f'UPDATE "{table}" SET "{column}"=? WHERE rowid=?', (safe, rowid))
        output.commit()
        output.execute('VACUUM')
        if output.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Diagnostic SQLite snapshot failed integrity check')


def summarize(snapshot):
    runtime = json.loads((snapshot / 'build/runtime.json').read_text(encoding='utf-8'))
    result = {'status': 'diagnostic_only_not_resumable_state', 'models_called': False,
              'pending_events': [], 'requests': [], 'caption_counts': {}, 'videos': []}
    db_path = snapshot / 'build/state/state.sqlite3'
    if not db_path.exists():
        return dict(result, note='No SQLite request ledger found')
    with closing(sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        captions = Counter()
        for row in db.execute('SELECT kind,payload FROM records'):
            value = json.loads(row['payload'])
            if row['kind'] == 'caption':
                captions['l1' if value.get('id', '').startswith('l1_') else 'l2'] += 1
            if row['kind'] == 'video':
                duration = value['duration']
                result['videos'].append({key: value.get(key) for key in ('id', 'relative_path', 'duration', 'fps', 'width', 'height')})
                result['videos'][-1].update(expected_l1=math.ceil(duration / runtime['caption']['l1_seconds']),
                                            expected_l2=math.ceil(duration / runtime['caption']['l2_seconds']))
        result['caption_counts'] = dict(captions)
        for row in db.execute('SELECT * FROM requests ORDER BY created_at,id'):
            value = {key: row[key] for key in ('id', 'role', 'status', 'actual', 'reservation', 'usage', 'error_code')}
            response = json.loads(row['response']) if row['response'] else {}
            value['finish_reasons'] = [item.get('finish_reason') for item in response.get('choices', [])]
            result['requests'].append(value)
        result['pending_events'] = [dict(row) for row in db.execute('''SELECT e.stage,e.entity_id,e.reason,e.detail FROM events e
            JOIN (SELECT stage,entity_type,entity_id,video_id,MAX(seq) seq FROM events
                  GROUP BY stage,entity_type,entity_id,video_id) last ON e.seq=last.seq
            WHERE e.decision='pending' ORDER BY e.seq''')]
    result['media_files'] = [str(path.relative_to(snapshot / 'build')) for path in sorted((snapshot / 'build/media').rglob('*')) if path.is_file()]
    return result


def pack(build, video, destination=None):
    build = Path(build).expanduser().resolve(strict=True)
    if not build.is_dir() or not (build / 'runtime.json').is_file() or not (build / 'build.json').is_file():
        raise ValueError('Select one build directory containing build.json and runtime.json')
    with coordinator_lock(build / 'coordinator.lock'):
        return _pack_locked(build, video, destination)


def _pack_locked(build, video, destination=None):
    build, video = Path(build).expanduser().resolve(strict=True), Path(video).expanduser().resolve(strict=True)
    if not build.is_dir() or not (build / 'runtime.json').is_file() or not (build / 'build.json').is_file():
        raise ValueError('Select one build directory containing build.json and runtime.json')
    if not video.is_file() or video.suffix.lower() != '.mp4':
        raise ValueError('Select exactly one original MP4')
    identifier = 'evidence-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    destination = Path(destination).expanduser().resolve() if destination else build.parent / '_private_relay' / identifier
    if destination == build or build in destination.parents or destination == PROJECT or PROJECT in destination.parents:
        raise ValueError('Relay staging must be outside the build and public code checkout')
    destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    snapshot = destination / 'snapshot'
    snapshot.mkdir(mode=0o700)
    entries, excluded, total = [], [], 0
    # Scanning is bounded and restricted to this named run, not its parent/storage.
    selected = []
    queue = [build]
    scanned = 0
    while queue:
        directory = queue.pop(0)
        with os.scandir(directory) as stream:
            for entry in stream:
                scanned += 1
                if scanned > MAX_FILES:
                    raise ValueError('Selected build exceeds the bounded scan limit')
                path = Path(entry.path)
                relative = path.relative_to(build)
                if entry.is_symlink():
                    excluded.append({'path': str(relative), 'reason': 'symlink'})
                elif entry.is_dir(follow_symlinks=False):
                    if relative.parts[0] in SUBDIRS | {'state'}:
                        queue.append(path)
                    else:
                        excluded.append({'path': str(relative), 'reason': 'directory_not_allowlisted'})
                elif entry.is_file(follow_symlinks=False):
                    approved = (len(relative.parts) == 1 and path.name in ROOT_FILES or
                                len(relative.parts) > 1 and relative.parts[0] in SUBDIRS and path.suffix in TEXT_EXT | MEDIA_EXT or
                                relative.as_posix() == 'state/state.sqlite3')
                    if approved:
                        selected.append((path, 'build/' + relative.as_posix()))
                    else:
                        excluded.append({'path': str(relative), 'reason': 'not_allowlisted'})
    selected.append((video, 'original/source.mp4'))
    for source, relative in sorted(selected, key=lambda pair: pair[1]):
        before = source.stat()
        total += before.st_size
        if total > MAX_BYTES:
            raise ValueError('Selected evidence exceeds 2GiB; refuse unbounded transfer')
        if source.is_symlink():
            raise ValueError('Source changed into a symlink')
        target = snapshot / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        source_sha = sha(source)
        if source.suffix in TEXT_EXT:
            if before.st_size > 32 * 1024**2:
                raise ValueError('One diagnostic text file exceeds 32MiB')
            target.write_bytes(scrub_text(source.read_bytes(), source.suffix))
        elif relative == 'build/state/state.sqlite3':
            sqlite_snapshot(source, target)
        else:
            shutil.copyfile(source, target)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or source_sha != sha(source):
            raise ValueError('Source changed during diagnostic snapshot; retry only after stopping the build')
        entries.append({'path': relative, 'source_sha256': source_sha, 'sha256': sha(target), 'bytes': target.stat().st_size})
    diagnosis = summarize(snapshot)
    if shutil.which('ffprobe'):
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-show_streams',
                                '-of', 'json', str(video)], capture_output=True, timeout=30)
        if probe.returncode == 0 and len(probe.stdout) <= 8 * 1024**2:
            diagnosis['original_ffprobe'] = scrub(json.loads(probe.stdout))
        else:
            diagnosis['original_ffprobe'] = {'status': 'failed', 'exit_code': probe.returncode}
    save(destination / 'diagnosis.json', diagnosis)
    (snapshot / 'diagnosis.json').write_bytes((destination / 'diagnosis.json').read_bytes())
    entries.append({'path': 'diagnosis.json', 'sha256': sha(snapshot / 'diagnosis.json'), 'bytes': (snapshot / 'diagnosis.json').stat().st_size})
    archive = destination / 'evidence.tar.gz'
    with tarfile.open(archive, 'x:gz') as tar:
        for entry in entries:
            tar.add(snapshot / entry['path'], arcname=entry['path'], recursive=False)
    parts = []
    with archive.open('rb') as stream:
        while data := stream.read(PART_BYTES):
            part = destination / f'evidence.tar.gz.part{len(parts):04d}'
            part.write_bytes(data)
            parts.append({'name': part.name, 'sha256': sha(part), 'bytes': len(data)})
    provenance = snapshot / 'build/execution_provenance.json'
    subject = json.loads(provenance.read_text(encoding='utf-8')).get('git_commit') if provenance.exists() else None
    manifest = {'schema_version': 1, 'repository': RELAY, 'private_only': True,
                'tag': identifier, 'run_id': build.name, 'build_path': str(build), 'original_video_path': str(video),
                'producer_commit': git(PROJECT, 'rev-parse', 'HEAD'), 'subject_commit': subject or 'unknown',
                'producer_script_sha256': sha(Path(__file__)), 'files': entries, 'excluded': excluded,
                'archive_sha256': sha(archive), 'parts': parts,
                'redactions': ['credential fields/tokens/URL userinfo and query', 'SQLite upload_cache emptied, secure_delete + VACUUM'],
                'diagnostic_copy_not_for_resume': True}
    save(destination / 'manifest.json', manifest)
    print(f'PASS: snapshot ready, {len(entries)} files, {total} input bytes, {len(parts)} upload parts: {destination}', flush=True)
    return destination


def git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError('Git identity/protection check failed')
    return result.stdout.strip()


def protect_public_checkout(root=PROJECT):
    if Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != Path(root).resolve():
        raise ValueError('Not the standalone code repository')
    origin = git(root, 'config', '--get', 'remote.origin.url')
    if origin not in ('https://github.com/' + PUBLIC + '.git', 'https://github.com/' + PUBLIC,
                      'git@github.com:' + PUBLIC + '.git', 'ssh://git@ssh.github.com:443/' + PUBLIC + '.git'):
        raise ValueError('Unexpected public origin; refusing to modify repository settings')
    git(root, 'config', '--local', '--replace-all', 'remote.origin.pushurl', DISABLED_PUSH)
    if git(root, 'remote', 'get-url', '--push', 'origin') != DISABLED_PUSH:
        raise ValueError('Could not disable public pushes')
    print('PASS: this server checkout is pull-only; public origin push URL disabled', flush=True)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # Never forward an authenticated request to another host.


class GitHub:
    def __init__(self, token):
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect())

    def call(self, path, *, body=None, upload=False, content_type='application/json'):
        prefix = '/repos/' + RELAY
        if path != prefix and not path.startswith(prefix + '/'):
            raise ValueError('Refusing any API path outside the private relay')
        host = 'uploads.github.com' if upload else 'api.github.com'
        request = urllib.request.Request('https://' + host + path, data=body,
            headers={'Authorization': 'Bearer ' + self.token, 'User-Agent': 'video-sft-private-relay',
                     'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
                     'Content-Type': content_type})
        try:
            with self.opener.open(request, timeout=600) as response:
                data = response.read(8 * 1024**2 + 1)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise ValueError('GitHub HTTP 404: token cannot access this private repo, or resource is absent') from None
            raise ValueError(f'GitHub HTTP {error.code}; no credential or response body printed') from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ValueError('GitHub network request failed; local packet preserved for resume') from None
        if len(data) > 8 * 1024**2:
            raise ValueError('GitHub response size limit')
        return json.loads(data)

    def private(self):
        info = self.call('/repos/' + RELAY)
        if info.get('full_name') != RELAY or info.get('private') is not True:
            raise ValueError('Relay is not the exact expected PRIVATE repository; no uploads allowed')
        if info.get('permissions', {}).get('push') is False:
            raise ValueError('Token has no write permission to the private relay')
        return info


def credentials():
    path = Path.home() / '.config/video-sft-builder-relay/token'
    token = os.environ.get('VIDEO_SFT_RELAY_TOKEN', '').strip()
    new = False
    if path.is_symlink():
        raise ValueError('Relay token file must not be a symlink')
    if not token and path.is_file():
        if os.name != 'nt' and path.stat().st_mode & 0o077:
            raise ValueError('Relay token file permissions must be 600')
        token = path.read_text(encoding='utf-8').strip()
    if not token and shutil.which('gh'):
        result = subprocess.run(['gh', 'auth', 'token'], capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            token = result.stdout.strip()
    if not token:
        if not sys.stdin.isatty():
            raise ValueError('First upload requires an interactive terminal for a repo-scoped GitHub token (not a model API Key)')
        token = getpass.getpass('Private relay GitHub Token (hidden, saved once outside repo): ').strip()
        new = True
    if not token:
        raise ValueError('Empty GitHub token')
    client = GitHub(token)
    client.private()
    if new:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(token)
    return client


def upload(directory, client):
    directory = Path(directory).resolve(strict=True)
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('repository') != RELAY or manifest.get('private_only') is not True:
        raise ValueError('Invalid relay packet identity')
    client.private()  # Must succeed before creating a release or transmitting bytes.
    receipt = directory / 'release.json'
    if receipt.exists():
        release = client.call('/repos/' + RELAY + '/releases/' + str(json.loads(receipt.read_text())['id']))
        if release['tag_name'] != manifest['tag']:
            raise ValueError('Release receipt mismatch')
    else:
        release = client.call('/repos/' + RELAY + '/releases', body=json.dumps({
            'tag_name': manifest['tag'], 'target_commitish': 'main', 'name': manifest['run_id'],
            'body': 'Explicitly authorized private diagnostic snapshot. manifest.json is the completion marker.',
            'draft': False, 'prerelease': True}).encode())
        save(receipt, {'id': release['id'], 'html_url': release['html_url']})
    assets = {item['name']: item for item in client.call('/repos/' + RELAY + '/releases/' + str(release['id']) + '/assets?per_page=100')}
    if len(manifest['parts']) > 90:
        raise ValueError('Too many packet parts')
    files = manifest['parts'] + [dict(name='diagnosis.json', sha256=sha(directory / 'diagnosis.json')),
                                 dict(name='manifest.json', sha256=sha(directory / 'manifest.json'))]
    for entry in files:
        name = entry['name']
        if Path(name).name != name or '/' in name or '\\' in name:
            raise ValueError('Unsafe packet asset name')
        path = directory / name
        if sha(path) != entry['sha256'] or path.stat().st_size > PART_BYTES:
            raise ValueError('Packet asset changed or exceeds upload size limit')
        if name in assets:
            remote = assets[name]
            if remote.get('digest') == 'sha256:' + entry['sha256'] and remote['size'] == path.stat().st_size:
                print('PASS: already uploaded ' + name, flush=True)
                continue
            raise ValueError('Existing asset digest differs or cannot be verified; no overwrite/delete')
        client.private()
        asset = client.call('/repos/' + RELAY + '/releases/' + str(release['id']) + '/assets?name=' + urllib.parse.quote(name),
                            body=path.read_bytes(), upload=True, content_type='application/octet-stream')
        if asset.get('size') != path.stat().st_size or asset.get('digest') != 'sha256:' + entry['sha256']:
            raise ValueError('GitHub asset digest verification failed; packet kept locally')
        print(f'PASS: private asset verified {name} ({path.stat().st_size} bytes)', flush=True)
    print('PASS: private relay upload complete: ' + release['html_url'], flush=True)
    print('Send this release URL back for inspection. No public git push or model calls occurred.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path)
    parser.add_argument('--video', type=Path)
    parser.add_argument('--resume', type=Path, help='Resume an existing diagnostic packet, not a production run')
    parser.add_argument('--pack-only', action='store_true', help='Offline snapshot, no authentication/public config changes/upload')
    args = parser.parse_args()
    if not args.resume and (not args.build or not args.video):
        parser.error('--build and --video are required unless --resume is used')
    try:
        if not args.pack_only:
            protect_public_checkout()
        directory = args.resume or pack(args.build, args.video)
        if not args.pack_only:
            print('If interrupted, resume with: bash scripts/relay_current_run.sh --resume ' + str(directory), flush=True)
            upload(directory, credentials())
        return 0
    except (ValueError, OSError, sqlite3.Error, json.JSONDecodeError, RuntimeError, PipelineError, subprocess.TimeoutExpired) as error:
        print('FAIL: ' + str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('FAIL: interrupted; diagnostic packet preserved; original run unchanged', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
