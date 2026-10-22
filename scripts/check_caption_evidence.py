#!/usr/bin/env python3
"""Offline replay of one explicit build's caption responses and coverage plan.

Reads only runtime.json and readonly SQLite (<=512 MiB), no media/network/model.
Writes a new optional summary path; never changes the source build. Safe to rerun
without --output; an existing output fails closed. No raw caption text is printed.
This checks parsing/planning, not visual accuracy or real FFmpeg/API execution.
"""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_sft_builder.caption_plan import caption_plan
from video_sft_builder.config import RuntimeConfig
from video_sft_builder.errors import PipelineError
from video_sft_builder.provider import ModelGateway
from video_sft_builder.util import read_json, write_json


def check(build):
    build = Path(build).resolve(strict=True)
    path = build / 'state/state.sqlite3'
    if path.stat().st_size > 512 * 1024 * 1024:
        raise PipelineError('Database exceeds bounded inspection limit')
    cfg = RuntimeConfig(read_json(build / 'runtime.json'), build / 'runtime.json')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        rows = db.execute("SELECT role,status,response FROM requests WHERE role IN ('A1','A2') LIMIT 10001").fetchall()
        if not rows:
            raise PipelineError('No caption responses to replay')
        if len(rows) > 10000:
            raise PipelineError('Caption request inspection bound exceeded')
        results = []
        for role, status, raw in rows:
            if status != 'done':
                raise PipelineError('Unresolved caption request; no replay/retry performed')
            value = ModelGateway._decode(json.loads(raw), role=role)
            results.append({'role': role, 'normalized': bool(getattr(value, 'normalization', None)),
                            'preserved_uncertainty_count': len(value['uncertain_details'])})
        videos = db.execute("SELECT payload FROM records WHERE kind='video' LIMIT 10001").fetchall()
        if len(videos) > 10000:
            raise PipelineError('Video plan inspection bound exceeded')
        plans = [caption_plan(cfg, json.loads(row[0])) for row in videos]
        return {'status': 'offline_parser_and_plan_pass', 'new_model_calls': 0, 'media_decoded': False,
                'responses': results, 'plans': plans}
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        value = check(args.build)
        if args.output:
            if args.output.resolve().is_relative_to(args.build.resolve()):
                raise PipelineError('Diagnostic output must be outside the inspected build')
            write_json(args.output, value)
        print(json.dumps(value, ensure_ascii=False))
        print('PASS: offline parsing and full-range planning only; no model calls or source writes')
        return 0
    except (PipelineError, OSError, ValueError, KeyError, sqlite3.Error) as error:
        print('FAIL: offline caption check: ' + type(error).__name__ + ': ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
