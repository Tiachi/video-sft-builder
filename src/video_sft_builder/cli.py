import argparse
import json
from decimal import Decimal
from pathlib import Path
import sys

from .config import load_config, template
from .errors import PipelineError
from .media import FFmpegMedia, enumerate_mp4
from .caption_plan import caption_plan, preflight
from .pipeline import Pipeline
from .reporting import export_candidates, report
from .state import Store
from .synthetic import SyntheticMedia, SyntheticProvider, create_inputs, demo_config
from .util import coordinator_lock, repository_provenance, write_json


def parser():
    result = argparse.ArgumentParser(prog='video-sft', description='Budgeted, resumable MP4-to-QA candidates')
    sub = result.add_subparsers(dest='command', required=True)
    ui = sub.add_parser('ui', help='Interactive terminal workbench with persistent private settings')
    ui.add_argument('--settings', type=Path)
    ui.add_argument('--plain', action='store_true', help='Disable ANSI rendering')
    init = sub.add_parser('init-config', help='Write an incomplete configuration without overwriting')
    init.add_argument('--output', type=Path, required=True)
    demo = sub.add_parser('demo', help='Synthetic full-pipeline simulation; no real media or API calls')
    demo.add_argument('--output-root', type=Path, required=True)
    demo.add_argument('--run-id', default='demo')
    recover = sub.add_parser('recover', help='Create a new build reusing exact paid responses from a stopped caption-only build; no API calls')
    recover.add_argument('--build', type=Path, required=True)
    recover.add_argument('--name', required=True)
    for command in ('validate-config', 'doctor', 'plan', 'run', 'report', 'export'):
        child = sub.add_parser(command)
        child.add_argument('--config', type=Path, required=True)
        if command == 'run':
            child.add_argument('--through', choices=('prepare', 'caption', 'all'), default='all',
                               help='Stop after pre-cleaning, caption/gate, or the full pipeline')
    return result


def execute(args):
    if args.command == 'ui':
        from .terminal import launch
        return launch(args.settings, plain=args.plain)
    if args.command == 'init-config':
        write_json(args.output, template())
        print('PASS: incomplete template created; fill all required runtime settings before production')
        return 0
    if args.command == 'recover':
        from .recovery import recover_build
        root = recover_build(args.build, args.name)
        print('PASS: recovery build created; no model calls. Historical charges remain in its budget.')
        print('/resume ' + str(root))
        print('Then /run all in the terminal workbench. The original build remains intact.')
        return 0
    if args.command == 'demo':
        config = demo_config(args.output_root, run_id=args.run_id)
        create_inputs(config)
        with coordinator_lock(config.lock_path):
            store = Store(config)
            try:
                Pipeline(config, store, media=SyntheticMedia(config), provider=SyntheticProvider()).run()
                exported = export_candidates(store)
                report_dir, summary = report(store)
                print('PASS: synthetic simulation only; no real model/media/GLM validation')
                print(json.dumps({'candidates': str(exported), 'report': str(report_dir), 'auto_passed': summary['auto_passed']}, ensure_ascii=False))
            finally:
                store.close()
        return 0
    config = load_config(args.config)
    if args.command == 'validate-config':
        print('PASS: runtime configuration structure is valid; no API/media verification')
        return 0
    if args.command == 'doctor':
        print(json.dumps(FFmpegMedia(config).doctor(), ensure_ascii=False))
        print('PASS: local executable checks only; no paid connectivity test')
        return 0
    if args.command == 'plan':
        media = FFmpegMedia(config)
        result = []
        for path in enumerate_mp4(config):
            metadata = media.probe(path)
            caption = caption_plan(config, {**metadata, 'id': 'plan_only'})
            preflight(config, metadata, caption)
            l1, l2 = len(caption['l1']), len(caption['l2'])
            normal = l1 + l2 + 16
            attempted = l1 + l2 + 1 + 2 + config.data['generation']['general_balance_attempts'] + config.data['generation']['long_balance_attempts'] + 8
            roles = {'A1': l1, 'A2': l2, 'C_GATE': 1,
                     'A3': 1 + config.data['generation']['general_balance_attempts'],
                     'A5': 1 + config.data['generation']['long_balance_attempts'], 'A7': 8}
            reservation = sum(Decimal(n) * (Decimal(config.profile(role)['input_token_limit']) * Decimal(str(config.prices(role)['input_per_million']))
                              + Decimal(config.profile(role)['max_completion_tokens'] + 10) * Decimal(str(config.prices(role)['output_per_million'])))
                              / 1_000_000 for role, n in roles.items())
            result.append({'relative_path': path.relative_to(Path(config.data['input']['root'])).as_posix(),
                           'duration': metadata['duration'], 'l1_calls': l1, 'l2_calls': l2, 'caption_plan': caption,
                           'success_path_inferences': normal, 'configured_attempt_bound': attempted,
                           'role_attempt_bounds': roles, 'worst_case_reservations_cny': str(reservation)})
        print(json.dumps({'videos': result, 'paid_calls': 0, 'run_cost_cap_cny': config.data['budgets']['max_cost'],
                          'note': 'Counts exclude uploads; reservations are conservative limits, not cost predictions; earlier gates/budgets can block'}, ensure_ascii=False, indent=2))
        return 0
    if args.command == 'run':
        provenance = repository_provenance()
        if provenance['git_dirty'] is not False or not provenance['git_commit']:
            raise PipelineError('Formal runs require a clean source Git checkout; commit/sync first')
    with coordinator_lock(config.lock_path):
        if args.command in ('report', 'export') and not (config.state_dir / 'state.sqlite3').is_file():
            raise PipelineError('No existing run state; report/export never initializes a new run')
        store = Store(config)
        try:
            if args.command == 'run':
                try:
                    Pipeline(config, store).run(through=args.through)
                finally:
                    # Always make progress and held reservations inspectable.
                    report(store)
                exported = export_candidates(store)
                report_dir, summary = report(store)
                progress = summary['completion']
                print(json.dumps({'candidates': str(exported), 'report': str(report_dir),
                                  'auto_passed': summary['auto_passed'], 'completion': progress}, ensure_ascii=False))
                print('PASS: requested pipeline boundary completed' if progress['status'] == 'complete' else 'FAIL: INCOMPLETE; partial results preserved; inspect coverage and stop reason')
                return 0 if progress['status'] == 'complete' else 2
            if args.command == 'export':
                print('PASS: candidate snapshot: ' + str(export_candidates(store)))
            else:
                directory, _ = report(store)
                print('PASS: report: ' + str(directory))
        finally:
            store.close()
    return 0


def main(argv=None):
    try:
        arguments = sys.argv[1:] if argv is None else list(argv)
        return execute(parser().parse_args(arguments or ['ui']))
    except (PipelineError, FileExistsError, FileNotFoundError, PermissionError, KeyError, ValueError) as error:
        # Provider/media adapters already redact details; avoid tracebacks that
        # could expose authentication material or signed media URLs.
        print('FAIL: ' + type(error).__name__ + ': ' + str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('FAIL: interrupted; sent requests remain unresolved and will not auto-resend', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
