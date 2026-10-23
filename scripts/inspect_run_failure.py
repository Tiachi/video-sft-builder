#!/usr/bin/env python3
"""Read-only, bounded diagnosis of ONE explicit pipeline build.

Reads runtime/status/identity JSON and a SQLite read-only transaction. Never
imports Store, reads private credentials, prints response bodies/URLs, decodes
media, calls a network endpoint, changes billing or resumes a model request.
No files are created. Execute as a child process; do not source in a shell.
"""
import argparse
import ast
from contextlib import closing
from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import subprocess
import sys
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
JSON_LIMIT=2*1024*1024
DB_LIMIT=256*1024*1024


def read_json(path):
    if path.stat().st_size>JSON_LIMIT:raise ValueError('json_size_limit')
    value=json.loads(path.read_text(encoding='utf8'))
    if not isinstance(value,dict):raise ValueError('expected_json_object')
    return value


def label(value,limit=160):
    """Only identifier-shaped metadata, never raw exception messages."""
    if not isinstance(value,str) or len(value)>limit or not re.fullmatch(r'[A-Za-z0-9_./:+ -]+',value):
        return 'unavailable_or_redacted'
    return value


def asset_identity(build):
    path=build/'code_and_asset_identity.json'
    if not path.is_file():return dict(status='unavailable',reason='saved_identity_missing')
    saved=read_json(path);differences=[]
    for group in ('code','assets'):
        entries=saved.get(group)
        if not isinstance(entries,dict) or len(entries)>256:raise ValueError('identity_shape_limit')
        for name,expected in entries.items():
            p=PurePosixPath(name)
            if (p.is_absolute() or '..' in p.parts or '\\' in name
                    or (group=='code' and (len(p.parts)!=1 or p.suffix!='.py'))
                    or (group=='assets' and (not p.parts or p.parts[0] not in ('configs','prompts')))):
                raise ValueError('unsafe_saved_identity_path')
            target=(ROOT/'src/video_sft_builder'/name if group=='code' else ROOT/name).resolve()
            if not target.is_relative_to(ROOT):raise ValueError('identity_path_outside_checkout')
            if not target.is_file() or target.stat().st_size>JSON_LIMIT:
                differences.append(name);continue
            if hashlib.sha256(target.read_bytes()).hexdigest()!=expected:differences.append(name)
    actual=list((ROOT/'src/video_sft_builder').glob('*.py'))
    if len(actual)>256:raise ValueError('code_inventory_limit')
    differences+=['new_code:'+p.name for p in actual if p.name not in saved['code']]
    return dict(status='match' if not differences else 'mismatch',differences=differences,
                note='This inspector does not change runtime code/assets or authorize retries.')


def provider_info(cfg,role):
    role=role if role in ('A1','A2','C_GATE','A3','A5','A7') else 'A7'
    route=cfg.get('execution',{}).get('routes',{}).get(role,'default')
    settings=(cfg.get('execution',{}).get('providers',{}).get(route,{})
              if cfg.get('schema_version')==2 else cfg.get('teacher',{}))
    try:
        endpoint=urlsplit(settings.get('base_url',''))
        host=label(endpoint.hostname or '')
    except ValueError:host='unavailable_or_redacted'
    profile=cfg.get('teacher',{}).get('roles',{}).get(role,{})
    return dict(role=role,provider_id=label(route),model=label(settings.get('model')),
                endpoint_host=host,transport=label(settings.get('transport')),
                timeout_seconds=settings.get('timeout_seconds'),
                limits={k:settings.get(k) for k in ('max_video_bytes','max_payload_bytes','max_response_bytes')},
                profile={k:profile.get(k) for k in ('mode','fps','max_frames','max_pixels','total_pixels',
                                                    'input_token_limit','max_completion_tokens')})


def failure_meaning(error_class):
    return {
      'UnknownExecution':'network_failure_wrapped_original_transport_details_not_saved',
      'PipelineError':'service_failure_wrapped_original_http_status_not_saved',
      'TimeoutError':'timeout_execution_and_billing_still_unknown',
      'IncompleteRead':'http_response_body_incomplete_execution_and_billing_unknown',
      'RemoteDisconnected':'peer_disconnected_execution_and_billing_unknown',
    }.get(error_class,'exception_class_only_not_a_root_cause')


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def _git_blob(revision,asset):
    """Read a small local Git blob only; no fetch, worktree edits or subprocess shell."""
    if not isinstance(revision,str) or not re.fullmatch(r'[0-9a-fA-F]{40}',revision):raise ValueError('invalid_saved_git_revision')
    if asset not in ('prompts/benchmark/audit.en.txt','prompts/runtime/audit.txt'):raise ValueError('invalid_prompt_asset')
    ref=revision+':'+asset
    size=subprocess.run(['git','cat-file','-s',ref],cwd=ROOT,capture_output=True,timeout=10,check=True)
    if not 0<int(size.stdout)<=JSON_LIMIT:raise ValueError('saved_git_asset_size_limit')
    result=subprocess.run(['git','--no-pager','show',ref],cwd=ROOT,capture_output=True,timeout=10,check=True)
    return result.stdout


def audit_json_check(conn,build,cfg,row,view):
    """Reconstruct message TEXT hashes only; never print private candidate text."""
    def unavailable(reason):return dict(status='unavailable',reason=reason)
    entry=conn.execute('SELECT payload FROM records WHERE key=?',('candidate:'+str(view.get('unit_id')),)).fetchone()
    video=conn.execute("SELECT payload FROM records WHERE kind='video' AND video_id=? LIMIT 1",(row['video_id'],)).fetchone()
    if not entry or not video or not view.get('system_hash') or not view.get('context_hash'):
        return unavailable('candidate_or_message_hash_missing')
    if max(len(entry['payload']),len(video['payload']))>JSON_LIMIT:raise ValueError('saved_context_size_limit')
    candidate=json.loads(entry['payload']);metadata=json.loads(video['payload'])
    context=dict(video_id=row['video_id'],duration=metadata['duration'],
                 time_basis='original_video_zero_normalized_pts',candidate=candidate)
    asset=('prompts/benchmark/audit.en.txt' if cfg.get('generation',{}).get('ability_recipe')=='benchmark_v1'
           else 'prompts/runtime/audit.txt')
    identity=read_json(build/'code_and_asset_identity.json')
    expected=identity.get('assets',{}).get(asset)
    try:
        path=ROOT/asset
        raw=path.read_bytes() if path.is_file() and path.stat().st_size<=JSON_LIMIT else b''
        source='matching_checkout_asset'
        if hashlib.sha256(raw).hexdigest()!=expected:
            provenance=read_json(build/'execution_provenance.json')
            raw=_git_blob(provenance.get('git_commit',''),asset);source='saved_git_revision'
        if hashlib.sha256(raw).hexdigest()!=expected:return unavailable('saved_prompt_asset_hash_mismatch')
        system=raw.decode('utf8').replace('\r\n','\n').replace('\r','\n')
    except (OSError,ValueError,UnicodeError,subprocess.SubprocessError):
        return unavailable('saved_prompt_not_available_from_verified_local_assets')
    text=canonical(context)
    system_match=hashlib.sha256(canonical(system).encode()).hexdigest()==view['system_hash']
    context_match=hashlib.sha256(text.encode()).hexdigest()==view['context_hash']
    verified=system_match and context_match
    return dict(status='verified' if verified else 'message_hash_mismatch',prompt_source=source,
                system_hash_match=system_match,context_hash_match=context_match,
                frozen_prompt_has_json='json' in system.casefold(),frozen_context_has_json='json' in text.casefold(),
                violates_json_object_prerequisite=('json' not in (system+text).casefold()) if verified else None,
                network_requests=0,private_text_displayed=False)


def validation_reason(message):
    """Expose only error literals from owned validators; omit dynamic/untrusted text."""
    if not isinstance(message,str):return 'unavailable'
    for name in ('quality.py','abilities.py'):
        path=ROOT/'src/video_sft_builder'/name
        if path.stat().st_size>JSON_LIMIT:raise ValueError('validator_source_size_limit')
        tree=ast.parse(path.read_text(encoding='utf8'))
        for node in ast.walk(tree):
            if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Name):continue
            n=0 if node.func.id=='ProtocolError' else 1 if node.func.id=='_require' else -1
            if n<0 or len(node.args)<=n:continue
            arg=node.args[n]
            if isinstance(arg,ast.Constant) and isinstance(arg.value,str) and message==arg.value:return arg.value
            if isinstance(arg,ast.BinOp) and isinstance(arg.left,ast.Constant) and isinstance(arg.left.value,str):
                if message.startswith(arg.left.value):return arg.left.value+'<field>'
    return 'nonliteral_error_detail_redacted'


def inspect(build,max_requests=20):
    build=Path(build).expanduser().resolve(strict=True)
    if not 1<=max_requests<=100:raise ValueError('request_display_limit')
    cfg=read_json(build/'runtime.json')
    status=read_json(build/'status.json') if (build/'status.json').is_file() else {}
    state=Path(cfg['run']['state_root']).expanduser().resolve()
    # Contained builds put state_root directly at <build>/state. Older layouts
    # are deliberately refused: never inspect an unrelated shared state tree.
    if (cfg.get('schema_version')!=2 or state!=build/'state'
            or (Path(cfg['run']['output_root'])/cfg['run']['id']).resolve()!=build):
        raise ValueError('expected_contained_build_state')
    db=state/'state.sqlite3'
    if not db.is_file() or db.stat().st_size>DB_LIMIT:raise ValueError('database_missing_or_size_limit')
    with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=2)) as conn:
        conn.row_factory=sqlite3.Row
        conn.execute('PRAGMA query_only=ON');conn.execute('BEGIN')
        counts=[dict(r) for r in conn.execute('SELECT role,status,COUNT(*) count FROM requests GROUP BY role,status')]
        totals=conn.execute('SELECT COUNT(*) count,SUM(CASE WHEN status!=\'done\' THEN 1 ELSE 0 END) unresolved FROM requests').fetchone()
        rows=conn.execute('''SELECT id,video_id,role,status,reservation,actual,error_code,created_at,
                            response IS NOT NULL response_saved FROM requests WHERE status!='done'
                            ORDER BY created_at,id LIMIT ?''',(max_requests,)).fetchall()
        pending=[]
        for row in rows:
            item={k:row[k] for k in ('id','role','status','reservation','actual','created_at','response_saved')}
            item['error_class']=label(row['error_code'])
            item['interpretation']=failure_meaning(row['error_code'])
            entry=conn.execute('SELECT payload FROM records WHERE key=?',('request_view:'+row['id'],)).fetchone()
            if entry:
                if len(entry['payload'])>JSON_LIMIT:raise ValueError('request_view_size_limit')
                view=json.loads(entry['payload'])
                item['unit_id']=label(view.get('unit_id'))
                item['branch']=label(view.get('branch'))
                item['media_count']=len(view.get('media',[]))
                if row['role']=='A7':item['json_mode_check']=audit_json_check(conn,build,cfg,row,view)
            failure=conn.execute('SELECT payload FROM records WHERE key=?',('request_failure:'+row['id'],)).fetchone()
            if failure:
                if len(failure['payload'])>JSON_LIMIT:raise ValueError('failure_record_size_limit')
                detail=json.loads(failure['payload'])
                if type(detail.get('http_status')) is int:
                    item['http_status']=detail['http_status']
                    item['interpretation']='http_error_recorded_execution_and_billing_still_unknown'
            video=conn.execute("SELECT payload FROM records WHERE kind='video' AND video_id=? LIMIT 1",(row['video_id'],)).fetchone()
            if video:
                if len(video['payload'])>JSON_LIMIT:raise ValueError('video_metadata_size_limit')
                value=json.loads(video['payload'])
                item['video']={k:value.get(k) for k in ('duration','width','height','fps','bytes')}
            event=conn.execute("SELECT recorded_at FROM events WHERE video_id=? AND stage='execution' AND decision='pending' ORDER BY seq DESC LIMIT 1",
                               (row['video_id'],)).fetchone()
            if event:
                try:item['reservation_to_latest_pending_seconds']=round((datetime.fromisoformat(event['recorded_at'].replace('Z','+00:00'))-
                                    datetime.fromisoformat(row['created_at'].replace('Z','+00:00'))).total_seconds(),3)
                except (ValueError,TypeError):pass
            item['provider']=provider_info(cfg,row['role'])
            pending.append(item)
        gate_rows=conn.execute("SELECT video_id,payload FROM records WHERE kind='caption_gate' LIMIT 101").fetchall()
        if len(gate_rows)>100:raise ValueError('gate_review_limit')
        gates=[]
        for row in gate_rows:
            if len(row['payload'])>JSON_LIMIT:raise ValueError('gate_record_size_limit')
            gate=json.loads(row['payload'])
            gates.append({k:label(gate.get(k)) for k in ('decision','reason','policy')})
        kinds={r['kind']:r['count'] for r in conn.execute("SELECT kind,COUNT(*) count FROM records WHERE kind IN ('caption','caption_bundle','candidate','quality','local_reject') GROUP BY kind")}
        rejects=conn.execute("SELECT payload FROM records WHERE kind='local_reject' LIMIT 101").fetchall()
        if len(rejects)>100:raise ValueError('local_reject_display_limit')
        local=[]
        for reject in rejects:
            if len(reject['payload'])>JSON_LIMIT:raise ValueError('local_reject_record_size_limit')
            value=json.loads(reject['payload']);raw=value.get('raw',{})
            raw=raw if isinstance(raw,dict) else {}
            local.append(dict(branch=label(value.get('branch')),task=label(raw.get('task')),
                              reason=validation_reason(value.get('error_code')),error_class=label(value.get('error_class'))))
        conn.rollback()
    return dict(run_id=label(cfg['run']['id']),recorded_status=label(status.get('status')),
                counts_by_role_status=counts,total_requests=totals['count'],unresolved_requests=totals['unresolved'] or 0,
                displayed_requests=len(pending),omitted_requests=max(0,(totals['unresolved'] or 0)-len(pending)),
                unresolved=pending,caption_gates=gates,artifact_counts=kinds,local_rejections=local,
                current_runtime_assets=asset_identity(build),network_requests=0,model_requests=0,files_written=0,
                request_bodies_read=False,credentials_read=False,
                next_action='Preserve this build. Do not resend unresolved paid requests or change SQLite. '
                            'Check provider-side execution/billing logs before selecting a recovery action.')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',required=True,type=Path)
    parser.add_argument('--max-requests',type=int,default=20)
    args=parser.parse_args(argv)
    try:
        result=inspect(args.build,args.max_requests)
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):
        print('FAIL: read-only inspection failed; check explicit build path, stopped writer and format. No retry or state change.',file=sys.stderr)
        return 1
    print(json.dumps(result,ensure_ascii=False,indent=2))
    print('PASS: read-only inspection complete; no inference, credentials or billing changes.')
    return 0


if __name__=='__main__':raise SystemExit(main())
