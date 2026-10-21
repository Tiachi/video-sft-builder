"""Named build directories and execution, shared by the terminal UI and tests."""
from datetime import datetime
from pathlib import Path

from .config import load_config, RuntimeConfig, validate_config
from .errors import ConfigError, PipelineError
from .media import FFmpegMedia
from .pipeline import Pipeline
from .reporting import export_candidates, report
from .settings import Settings, private_write_json
from .sources import acquire_url, describe_source
from .state import Store
from .synthetic import SyntheticMedia, SyntheticProvider, create_inputs
from .util import asset, coordinator_lock, file_digest, read_json, repository_provenance, write_json


def create_build(settings, name, *, now=None, synthetic=False):
    if not settings.data['output_dir'] or not Path(settings.data['output_dir']).expanduser().is_absolute():
        raise ConfigError('Set an absolute output_dir once before creating a build')
    started = now or datetime.now().astimezone()
    run_id = settings.build_id(name, now=started)
    root = Path(settings.data['output_dir']).expanduser().resolve() / run_id
    if root.exists():
        raise ConfigError('This name/time directory already exists; resume it or choose a different name')
    source = ({'kind': 'synthetic', 'public_source': 'synthetic_demo', 'source_hash': 'synthetic',
               'input_root': str(root / 'inputs'), 'allowlist': []} if synthetic
              else describe_source(settings.data['source'], root))
    compiler = settings
    if synthetic:
        compiler = object.__new__(Settings)
        compiler.path = settings.path
        compiler.data = read_json(asset('configs/terminal.example.json'))
        compiler.data['output_dir'] = settings.data['output_dir']
    config = compiler.compile(run_id, source['input_root'], allowlist=source['allowlist'])
    if synthetic:
        config.data['teacher']['backend'] = 'synthetic'
        config.data['run']['max_videos'] = 2
        validate_config(config.data, allow_synthetic=True)
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    write_json(root / 'runtime.json', config.data)
    write_json(root / 'build.json', {'name': name, 'run_id': run_id, 'created_at': started.isoformat(),
                                   'source': source, 'synthetic': synthetic,
                                   'download_limits': settings.data['download']})
    return root


def load_build(root):
    root = Path(root).expanduser().resolve()
    manifest = read_json(root / 'build.json')
    config = load_config(root / 'runtime.json', allow_synthetic=manifest['synthetic'])
    if root != config.output or root.name != manifest['run_id']:
        raise ConfigError('Build directory identity does not match its frozen runtime file')
    return root, manifest, config


def execute_build(root, *, through='all', observer=None, require_clean=True):
    if through not in ('prepare', 'caption', 'all'):
        raise ConfigError('Stage must be all, prepare or caption')
    root, manifest, config = load_build(root)
    synthetic = manifest['synthetic']
    if not synthetic and require_clean and repository_provenance()['git_dirty'] is not False:
        raise PipelineError('Formal builds require clean committed source; synchronize code first')
    # A single lock spans acquisition, SQLite mutation, exports and reports.
    with coordinator_lock(root / 'coordinator.lock'):
        source = manifest['source']
        if synthetic:
            create_inputs(config)
        elif source['kind'] == 'url':
            receipt = root / 'inputs/download.json'
            if receipt.is_file():
                downloaded = read_json(receipt)
                if downloaded['source_hash'] != source['source_hash'] or file_digest(root / 'inputs/source.mp4') != downloaded['sha256']:
                    raise PipelineError('Cached download identity mismatch')
            else:
                private = read_json(config.data['execution']['credential_file'])
                from .util import digest
                locator = private['source']
                if digest(locator) != source['source_hash']:
                    raise ConfigError('Restore this build source address in private settings before resuming URL acquisition')
                acquire_url(locator, root, manifest['download_limits'])
        if not synthetic:
            FFmpegMedia(config).doctor()
        store = Store(config, observer=observer)
        try:
            provider = SyntheticProvider() if synthetic else None
            if not synthetic and through != 'prepare':
                from .provider import ProviderRouter
                provider = ProviderRouter(config, store)
                for role in (('A1', 'A2', 'C_GATE') if through == 'caption' else ('A1', 'A2', 'C_GATE', 'A3', 'A5', 'A7')):
                    provider.client(role)  # Credential readiness only; no HTTP.
            try:
                Pipeline(config, store, media=SyntheticMedia(config) if synthetic else None,
                         provider=provider).run(through=through)
            finally:
                # Preserve inspectable accounting even after interruption/errors.
                report_dir, summary = report(store)
            export_dir = export_candidates(store)
            pending = sum(e['decision'] == 'pending' for e in store.latest_events())
            value = {'status': 'pending' if pending else 'complete', 'through': through, 'synthetic': synthetic,
                     'auto_passed': summary['auto_passed'], 'report': str(report_dir), 'export': str(export_dir),
                     'pending_entities': pending}
            private_write_json(root / 'status.json', value, replace=True)
            return value
        except BaseException as error:
            private_write_json(root / 'status.json', {'status': 'interrupted' if isinstance(error, KeyboardInterrupt) else 'error',
                               'error_class': type(error).__name__, 'synthetic': synthetic}, replace=True)
            raise
        finally:
            store.close()


def build_status(root):
    root, manifest, config = load_build(root)
    recorded = read_json(root / 'status.json') if (root / 'status.json').exists() else {'status': 'created'}
    db = config.state_dir / 'state.sqlite3'
    if not db.exists():
        return {**recorded, 'run_id': manifest['run_id'], 'synthetic': manifest['synthetic']}
    # Reports/inspection use the same coordinator lock, never initialize state.
    with coordinator_lock(root / 'coordinator.lock'):
        store = Store(config)
        try:
            directory, summary = report(store)
            return {'status': recorded['status'], 'through': recorded.get('through'),
                    'run_id': manifest['run_id'], 'report': str(directory), 'auto_passed': summary['auto_passed'],
                    'cost': summary['actual_cost'], 'held': summary['held_unknown_or_reserved_cost'],
                    'synthetic': manifest['synthetic'], 'requests': len(store.request_rows())}
        finally:
            store.close()
