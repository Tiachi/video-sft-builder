"""Transactional metadata, immutable artifacts and conservative request accounting."""
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3

from .errors import Blocked, BudgetBreach, PipelineError, UnknownExecution
from .util import canonical, digest, repository_provenance, utcnow, write_json


class Store:
    def __init__(self, config, *, observer=None):
        self.config = config
        self.observer = observer
        config.state_dir.mkdir(parents=True, exist_ok=True)
        config.output.mkdir(parents=True, exist_ok=True)
        self.db_path = config.state_dir / 'state.sqlite3'
        self.db = sqlite3.connect(self.db_path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=DELETE;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS records (
                key TEXT PRIMARY KEY, kind TEXT NOT NULL, video_id TEXT, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL,
                stage TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
                video_id TEXT NOT NULL, source TEXT NOT NULL, decision TEXT NOT NULL,
                reason TEXT NOT NULL, detail TEXT NOT NULL, recorded_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS requests (
                id TEXT PRIMARY KEY, video_id TEXT NOT NULL, role TEXT NOT NULL,
                status TEXT NOT NULL, reservation TEXT NOT NULL, actual TEXT,
                response TEXT, usage TEXT, error_code TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS auxiliary (
                id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
                bytes INTEGER NOT NULL, status TEXT NOT NULL, recorded_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS upload_cache (
                key TEXT PRIMARY KEY, resource TEXT NOT NULL, expires REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS records_kind_video ON records(kind,video_id);
        ''')
        try:
            os.chmod(self.db_path, 0o600)
            os.chmod(config.state_dir, 0o700)
            os.chmod(config.output, 0o700)
        except OSError:
            pass
        existing = self.db.execute("SELECT value FROM metadata WHERE key='config_hash'").fetchone()
        if existing and existing['value'] != config.fingerprint:
            self.close()
            raise PipelineError('Run configuration changed; use a new run ID, never silently reuse paid requests')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO metadata VALUES (?,?)', ('config_hash', config.fingerprint))
            self.db.execute('INSERT OR IGNORE INTO metadata VALUES (?,?)', ('started_at', utcnow()))
        snapshot = config.output / 'resolved_config.json'
        if not snapshot.exists():
            write_json(snapshot, config.data)
        if not (config.output / 'code_and_asset_identity.json').exists():
            write_json(config.output / 'code_and_asset_identity.json', config.code_and_asset_identity)
        if not (config.output / 'execution_provenance.json').exists():
            write_json(config.output / 'execution_provenance.json', repository_provenance())
        if self.observer:
            rows = self.request_rows()
            self.notify('snapshot', done=sum(r['status'] == 'done' for r in rows),
                        cost=str(sum((Decimal(r['actual']) for r in rows if r['actual'] is not None), Decimal(0))),
                        passed=sum(r['payload'].get('decision') == 'pass' for r in self.records('quality')))

    def close(self):
        self.db.close()

    def notify(self, kind, **value):
        if self.observer:
            try:
                self.observer({'kind': kind, **value})
            except Exception:
                pass  # Display failures may never change paid-request accounting.

    def get(self, key):
        row = self.db.execute('SELECT payload FROM records WHERE key=?', (key,)).fetchone()
        if not row:
            return None
        value = json.loads(row['payload'])
        # SQLite is authoritative. Recover a crash between committing the row
        # and publishing its JSON mirror without making another model call.
        path = self.config.output / 'artifacts' / (key.replace(':', '/') + '.json')
        if not path.exists():
            write_json(path, value)
        return value

    def put(self, key, kind, video_id, payload):
        if any(part in ('', '.', '..') or '/' in part or '\\' in part for part in key.split(':')):
            raise PipelineError('Unsafe immutable artifact key')
        encoded = canonical(payload)
        with self.db:
            existing = self.db.execute('SELECT payload FROM records WHERE key=?', (key,)).fetchone()
            if existing and existing['payload'] != encoded:
                raise PipelineError('Refusing to overwrite immutable artifact: ' + key)
            self.db.execute('INSERT OR IGNORE INTO records VALUES (?,?,?,?)', (key, kind, video_id, encoded))
        path = self.config.output / 'artifacts' / (key.replace(':', '/') + '.json')
        if not path.exists():
            write_json(path, payload)
        return payload

    def records(self, kind=None, video_id=None):
        sql, args = 'SELECT key,kind,video_id,payload FROM records', ()
        clauses = []
        if kind:
            clauses.append('kind=?')
            args += (kind,)
        if video_id:
            clauses.append('video_id=?')
            args += (video_id,)
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        return [dict(row, payload=json.loads(row['payload'])) for row in self.db.execute(sql + ' ORDER BY key', args)]

    def reject(self, category, entity_id, video_id, payload):
        from .util import safe_name
        safe_name(category)
        safe_name(entity_id)
        value = self.put('reject:' + category + ':' + entity_id, 'reject', video_id, payload)
        path = self.config.output / 'reject' / category / (entity_id + '.json')
        if not path.exists():
            write_json(path, value)
        return value

    def event(self, stage, entity_type, entity_id, video, decision, reason, detail=None):
        body = [stage, entity_type, entity_id, video['id'], decision, reason]
        with self.db:
            self.db.execute('''INSERT OR IGNORE INTO events
                (event_id,stage,entity_type,entity_id,video_id,source,decision,reason,detail,recorded_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (digest(body), stage, entity_type, entity_id, video['id'], video['source'],
                 decision, reason, canonical(detail or {}), utcnow()))
        self.notify('stage', stage=stage, video_id=video['id'], decision=decision, reason=reason,
                    entity_id=entity_id, source=video['source'], detail=detail or {})

    def latest_events(self):
        return [dict(row, detail=json.loads(row['detail'])) for row in self.db.execute('''
            SELECT e.* FROM events e JOIN
              (SELECT stage,entity_type,entity_id,video_id,MAX(seq) seq FROM events
               GROUP BY stage,entity_type,entity_id,video_id) last
            ON e.seq=last.seq ORDER BY e.seq''')]

    def request_rows(self):
        return [dict(row) for row in self.db.execute('SELECT * FROM requests ORDER BY created_at,id')]

    def request(self, request_id):
        row = self.db.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
        if not row:
            return None
        value = dict(row)
        if value['status'] in ('sent', 'unknown_execution'):
            raise UnknownExecution('A previously sent request is unresolved; refusing to resend ' + request_id)
        if value['status'] == 'budget_breach':
            raise BudgetBreach('Previous billing breach is unresolved; refusing to continue this run')
        if value['status'] in ('error', 'billing_unknown'):
            raise PipelineError('Previous request is terminal: ' + value['status'] + ' ' + request_id)
        if value['response']:
            value['response'] = json.loads(value['response'])
        return value

    def reserve(self, request_id, video_id, role, amount):
        """Reserve worst-case amount and an inference slot before upload or inference."""
        limits = self.config.data['budgets']
        self.db.execute('BEGIN IMMEDIATE')
        try:
            existing = self.db.execute('SELECT id FROM requests WHERE id=?', (request_id,)).fetchone()
            if existing:
                self.db.commit()
                return
            rows = self.request_rows()
            committed = sum((Decimal(r['actual'] if r['actual'] is not None else r['reservation']) for r in rows), Decimal(0))
            video_count = sum(r['video_id'] == video_id for r in rows)
            if len(rows) >= limits['max_requests'] or video_count >= limits['per_video_max_requests']:
                raise Blocked('request_budget_exhausted')
            if committed + amount > Decimal(str(limits['max_cost'])):
                raise Blocked('cost_budget_exhausted')
            self.db.execute('''INSERT INTO requests
                (id,video_id,role,status,reservation,created_at) VALUES (?,?,?,?,?,?)''',
                (request_id, video_id, role, 'reserved', str(amount), utcnow()))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def sent(self, request_id):
        with self.db:
            changed = self.db.execute("UPDATE requests SET status='sent' WHERE id=? AND status='reserved'", (request_id,)).rowcount
            if changed != 1:
                raise UnknownExecution('Inference slot was already sent; refusing duplicate')
        row = self.db.execute('SELECT role,video_id FROM requests WHERE id=?', (request_id,)).fetchone()
        self.notify('request_start', request_id=request_id, role=row['role'], video_id=row['video_id'])

    def fail(self, request_id, code, *, uncertain=True):
        with self.db:
            self.db.execute('UPDATE requests SET status=?,error_code=? WHERE id=?',
                            ('unknown_execution' if uncertain else 'error', code, request_id))

    def complete(self, request_id, response, usage):
        limits = self.config.data['budgets']
        valid = isinstance(usage, dict) and all(isinstance(usage.get(k), int) and not isinstance(usage.get(k), bool)
                                               and usage[k] >= 0 for k in ('input_tokens', 'output_tokens'))
        if not valid:
            with self.db:
                self.db.execute("UPDATE requests SET status='billing_unknown',response=? WHERE id=?",
                                (canonical(response), request_id))
            raise PipelineError('API response lacked valid usage; reservation retained and chain stopped')
        request = self.db.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
        rates = self.config.prices(request['role'])
        actual = (Decimal(usage['input_tokens']) * Decimal(str(rates['input_per_million']))
                  + Decimal(usage['output_tokens']) * Decimal(str(rates['output_per_million']))) / 1_000_000
        profile = self.config.profile(request['role'])
        over = (usage['input_tokens'] > profile['input_token_limit']
                or usage['output_tokens'] > profile['max_completion_tokens'] + 10
                or actual > Decimal(request['reservation']))
        with self.db:
            self.db.execute('UPDATE requests SET status=?,actual=?,response=?,usage=? WHERE id=?',
                            ('budget_breach' if over else 'done', str(actual), canonical(response), canonical(usage), request_id))
        if over:
            raise BudgetBreach('Observed API usage exceeded configured billing bounds; run stopped')
        self.notify('request_done', request_id=request_id, role=request['role'], video_id=request['video_id'],
                    input_tokens=usage['input_tokens'], output_tokens=usage['output_tokens'], cost=str(actual))

    def auxiliary(self, kind, byte_count=0):
        limits = self.config.data['budgets']
        with self.db:
            row = self.db.execute('SELECT COUNT(*) n,COALESCE(SUM(bytes),0) b FROM auxiliary').fetchone()
            if row['n'] >= limits['max_aux_requests'] or row['b'] + byte_count > limits['max_upload_bytes']:
                raise Blocked('auxiliary_upload_budget_exhausted')
            cursor = self.db.execute('INSERT INTO auxiliary(kind,bytes,status,recorded_at) VALUES (?,?,?,?)',
                                     (kind, byte_count, 'started', utcnow()))
            return cursor.lastrowid

    def auxiliary_done(self, ident):
        with self.db:
            self.db.execute("UPDATE auxiliary SET status='done' WHERE id=?", (ident,))

    def cache(self, key, *, resource=None, expires=None):
        if resource is None:
            row = self.db.execute('SELECT * FROM upload_cache WHERE key=?', (key,)).fetchone()
            return dict(row) if row else None
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO upload_cache VALUES (?,?,?)', (key, resource, expires))
