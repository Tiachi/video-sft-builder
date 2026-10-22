"""Explicit new-build fork of a caption-only run. Original state stays intact."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import json
import sqlite3

from .config import RuntimeConfig, validate_config
from .errors import PipelineError
from .provider import ModelGateway
from .settings import validate_run_name
from .state import Store
from .util import canonical, coordinator_lock, digest, file_digest, read_json, repository_provenance, write_json


def recover_build(old_root, name, *, now=None, require_clean=True):
    """No model/network calls; import known charges and exact caption responses only.

    Scope: one explicit old build's JSON/readonly SQLite and its manifest MP4s.
    Writes a NEW sibling build plus an advisory lock in the old build directory.
    Never rewrite old responses, SQLite, media, config or artifacts.
    """
    old_root = Path(old_root).expanduser().resolve(strict=True)
    manifest, old_data = read_json(old_root / 'build.json'), read_json(old_root / 'runtime.json')
    if old_data['schema_version'] != 2 or old_root.name != old_data['run']['id']:
        raise PipelineError('Recovery requires a v2 named build')
    if not manifest['synthetic'] and require_clean and repository_provenance()['git_dirty'] is not False:
        raise PipelineError('Recovery requires clean committed source')
    validate_run_name(name)
    ident = name + '_' + (now or datetime.now().astimezone()).strftime('%Y%m%d_%H%M')
    validate_run_name(ident)
    new_root = old_root.parent / ident
    if new_root.exists():
        raise PipelineError('Recovery destination already exists; choose another name')
    db_path = old_root / 'state/state.sqlite3'
    if db_path.stat().st_size > 512 * 1024 * 1024:
        raise PipelineError('Recovery database exceeds bounded inspection limit')
    with coordinator_lock(old_root / 'coordinator.lock'):
        db = sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN')
            old_hash = db.execute("SELECT value FROM metadata WHERE key='config_hash'").fetchone()['value']
            old_identity = read_json(old_root / 'code_and_asset_identity.json')
            if old_hash != digest([old_data, old_identity]):
                raise PipelineError('Old runtime/code identity does not match its ledger')
            requests = [dict(r) for r in db.execute('SELECT * FROM requests LIMIT 10001')]
            if not requests or len(requests) > 10000 or any(r['status'] != 'done' or r['role'] not in ('A1', 'A2') for r in requests):
                raise PipelineError('Recovery only supports resolved caption-only requests; unresolved requests are never retried')
            def record(key):
                row = db.execute('SELECT payload FROM records WHERE key=?', (key,)).fetchone()
                if not row:
                    raise PipelineError('Recovery source is missing a required ledger record')
                return json.loads(row['payload'])
            videos = {v['id']: v for v in record('input_manifest')['videos']}
            views = {r['id']: record('request_view:' + r['id']) for r in requests}
        finally:
            db.close()
        for video in videos.values():
            if file_digest(Path(video['path'])) != video['sha256']:
                raise PipelineError('Original MP4 changed; recovery refused')
        for r in requests:
            if r['video_id'] not in videos or r['actual'] is None or r['usage'] is None:
                raise PipelineError('Recovery accounting/video identity is incomplete')
            ModelGateway._decode(json.loads(r['response']), role=r['role'])
        data = deepcopy(old_data)
        data['run'].update(id=ident, output_root=str(old_root.parent), state_root=str(new_root / 'state'))
        # A downloaded source belongs to the immutable old run; no redownload.
        validate_config(data, allow_synthetic=manifest['synthetic'])
        cfg = RuntimeConfig(data, new_root / 'runtime.json')
        if cfg.code_and_asset_identity['assets'] != old_identity['assets']:
            raise PipelineError('Prompt/task assets changed; caption recovery requires unchanged assets')
        total = sum((Decimal(r['actual']) for r in requests), Decimal(0))
        if total > Decimal(str(data['budgets']['max_cost'])) or len(requests) > data['budgets']['max_requests']:
            raise PipelineError('Historical charges exceed frozen run budget')
        new_root.mkdir(mode=0o700, exist_ok=False)
        marker = new_root / 'RECOVERY_NOT_READY.json'
        write_json(marker, {'status': 'initializing'})
        write_json(new_root / 'runtime.json', data)
        write_json(new_root / 'build.json', {**manifest, 'name': name, 'run_id': ident,
                   'created_at': (now or datetime.now().astimezone()).isoformat(),
                   'source': {**manifest['source'], 'kind': 'recovered_local'}, 'recovered_from': str(old_root)})
        store = Store(cfg)
        try:
            # One transaction: charges and their reuse indexes enter together.
            with store.db:
                for r in requests:
                    store.db.execute('INSERT INTO requests (' + ','.join(r) + ') VALUES (' + ','.join('?' for _ in r) + ')', tuple(r.values()))
                    value = {'request_id': r['id'], 'video_sha256': videos[r['video_id']]['sha256'], 'view': views[r['id']]}
                    store.db.execute('INSERT INTO records VALUES (?,?,?,?)',
                                     ('recovered_request:' + r['id'], 'recovered_request', r['video_id'], canonical(value)))
            store.put('recovery_provenance', 'recovery_provenance', None,
                      {'old_run_id': old_data['run']['id'], 'old_config_hash': old_hash,
                       'source_database_sha256': file_digest(db_path), 'historical_request_count': len(requests),
                       'historical_cost': str(total), 'new_api_calls': 0,
                       'reuse_rule': 'exact_video_hash_role_profile_provider_prompt_context_media_range_match',
                       'raw_responses_preserved': True, 'old_build_modified': False})
        finally:
            store.close()
        marker.unlink()
    return new_root
