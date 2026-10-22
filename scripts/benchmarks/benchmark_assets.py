"""Pinned benchmark acquisition and annotation counting, outside the training pipeline.

Reads only configured existing assets; writes only root/snapshots and root/reports.
No recursive shared-storage inventory, source mutation, model API, or personal proxy.
Archives are retained as downloaded, NOT silently declared extracted/evaluation-ready.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
from urllib.parse import urlparse


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + '.part')
    part.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    os.replace(part, path)  # Only our own report/control files, never original assets.


def read_rows(path):
    path = Path(path)
    if path.suffix == '.parquet':
        import pyarrow.parquet as pq
        return pq.read_table(path).to_pylist()
    if path.suffix == '.jsonl':
        return [json.loads(line) for line in path.read_text(encoding='utf8').splitlines() if line.strip()]
    obj = json.loads(path.read_text(encoding='utf8'))
    if isinstance(obj, list):
        return obj
    raise ValueError('Expected an explicit list of annotation records: ' + path.name)


def frequency(rows, key):
    return dict(sorted(Counter(str(row.get(key, 'MISSING')) for row in rows).items()))


def summarize(kind, rows, filename=''):
    """One question is the unit; LVBench labels are explicitly multi-label."""
    result = {'questions': len(rows), 'category_axes': {}}
    axes = result['category_axes']
    if kind == 'lvbench' and rows and 'qa' in rows[0]:
        questions = [q for row in rows for q in row['qa']]
        result['questions'] = len(questions)
        axes['question_type_multilabel'] = dict(sorted(Counter(
            t for q in questions for t in q['question_type']).items()))
        result['label_assignments'] = sum(axes['question_type_multilabel'].values())
    elif kind == 'motionbench':
        questions = [dict(q, question_type=row.get('question_type')) for row in rows for q in row['qa']]
        result['questions'] = len(questions)
        labeled = [q for q in questions if q.get('answer') in {'A','B','C','D'}]
        result['labeled_questions'] = len(labeled)
        axes['question_type_all'] = frequency(questions, 'question_type')
        axes['question_type_labeled'] = frequency(labeled, 'question_type')
        axes['answer_availability'] = frequency(questions, 'answer')
    elif kind == 'mmvu':
        axes['subject'] = dict(sorted(Counter(r['metadata']['subject'] for r in rows).items()))
        axes['question_type'] = frequency(rows, 'question_type')
    elif kind == 'mvbench':
        axes['task_file'] = {Path(filename).stem: len(rows)}
    else:
        keys = ('task_type','domain','sub_category','duration') if kind == 'videomme' else (
            ('level','second_head','third_head','group_type') if kind == 'videomme_v2' else
            ('question_category','category','level','task_type','question_type','subject','discipline','task'))
        for key in keys:
            if rows and key in rows[0]:
                # Preserve list-valued labels instead of treating the list as a single class.
                if any(isinstance(r.get(key), list) for r in rows):
                    axes[key+'_multilabel'] = dict(sorted(Counter(
                        str(v) for r in rows for v in (r.get(key) or [])).items()))
                else:
                    axes[key] = frequency(rows, key)
        if kind == 'mlvu' and not axes:
            axes['task_file'] = {Path(filename).stem: len(rows)}
    return result


def safe_relative(value):
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or '\\' in value or ':' in value:
        raise ValueError('Unsafe remote asset path')
    return p


def candidate_paths(relative, roots):
    p = safe_relative(relative)
    suffixes = [p]
    # Remove only known repository packaging prefixes; never basename-search trees.
    for prefix in ('MLVU/', 'MotionBench/', 'videos/'):
        if relative.startswith(prefix):
            suffixes.append(PurePosixPath(relative[len(prefix):]))
    for root in roots:
        for suffix in suffixes:
            yield Path(root).joinpath(*suffix.parts)


def exact_existing(relative, size, roots):
    for p in candidate_paths(relative, roots):
        if p.is_file() and p.stat().st_size == size and size > 0:
            return p
    return None


def references(kind, rows):
    refs = set()
    for r in rows:
        if kind == 'videomme':
            v = r.get('videoID')
            if v: refs.add(str(v)+'.mp4')
        elif kind == 'videomme_v2':
            if r.get('video_id'): refs.add(str(r['video_id'])+'.mp4')
        elif kind == 'lvbench':
            v = r.get('key') or r.get('video_id')
            if v: refs.add(str(v)+'.mp4')
        elif kind == 'longvideobench':
            if r.get('video_path'): refs.add(r['video_path'])
        elif kind == 'video_mmmu':
            for key in ('video','video_path'):
                if isinstance(r.get(key),str) and r[key].endswith('.mp4'):
                    refs.add(r[key])
    return refs


def all_references_present(spec, annotation_paths):
    """Skip video archives only with full expected annotation coverage, never a val subset."""
    if spec['kind'] not in {'videomme','videomme_v2','lvbench','longvideobench','video_mmmu'}:
        return False, {'state':'not_applicable'}
    refs = set()
    for p in annotation_paths:
        refs.update(references(spec['kind'], read_rows(p)))
    missing=[]
    for ref in sorted(refs):
        if not any(p.is_file() and p.stat().st_size > 0 for p in candidate_paths(ref,spec['media_roots'])):
            missing.append(ref)
    ok = len(refs) >= spec['minimum_references'] and not missing
    return ok, {'references':len(refs),'missing':len(missing),
        'minimum_expected_references':spec['minimum_references'],'checked':'existence_and_positive_size_only',
        'decode_verified':False,'missing_examples':missing[:10]}


def digest_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''): h.update(block)
    return h.hexdigest()


def scan_annotations(spec, paths):
    result=[]
    for p in paths:
        if not p.is_file():continue
        try:
            rows=read_rows(p)
            result.append({'path':str(p),'sha256':digest_file(p),'summary':summarize(spec['kind'],rows,p.name)})
        except (ValueError,KeyError,TypeError) as exc:
            result.append({'path':str(p),'state':'unsupported_annotation_schema','error_type':type(exc).__name__})
    # Separate files/representations deliberately: do not add JSON and Parquet counts together.
    return result


def saved_annotations(spec, root):
    """Only our pinned snapshot and its registered patterns, not the shared data tree."""
    snapshot=root/'snapshots'/spec['name']/spec['revision']
    paths=set()
    for pattern in spec['include']:
        for p in snapshot.glob(pattern):
            if p.is_file() and p.suffix in {'.json','.jsonl','.parquet'}:paths.add(p)
    return sorted(paths)


def download_dataset(spec, root, progress):
    from huggingface_hub import HfApi, hf_hub_download, get_token
    token = get_token()
    endpoint='https://huggingface.co'
    try:
        info=HfApi(endpoint=endpoint).dataset_info(spec['repo'],revision=spec['revision'],files_metadata=True,token=token or False,timeout=15)
    except Exception:
        # Public, anonymous mirror only. Never send the user's HF token to a third-party host.
        endpoint='https://hf-mirror.com'
        info=HfApi(endpoint=endpoint).dataset_info(spec['repo'],revision=spec['revision'],files_metadata=True,token=False,timeout=15)
        if info.gated:
            raise RuntimeError('gated_requires_authorized_official_hf_connection') from None
        token=False
    if info.sha != spec['revision']:
        raise RuntimeError('revision_mismatch')
    destination=root/'snapshots'/spec['name']/spec['revision']
    destination.mkdir(parents=True,exist_ok=True)
    entries=[f for f in info.siblings if any(fnmatch.fnmatchcase(f.rfilename,p) for p in spec['include'])]
    if not entries:raise RuntimeError('empty_official_file_plan')
    progress.update({'endpoint':endpoint,'repository':info.id,'revision':info.sha,'files_expected':len(entries),'files':[]})
    annotation_paths=[]
    selected=sorted(entries,key=lambda f:(not f.rfilename.endswith(('.json','.jsonl','.parquet','.txt','.md')),f.rfilename))
    media_complete=False
    for index,f in enumerate(selected):
        relative=f.rfilename
        progress['active_file']=relative
        safe_relative(relative)
        annotation=relative.endswith(('.json','.jsonl','.parquet'))
        archive=('.zip' in relative or '.tar' in relative)
        # Reuse only video archives; subtitle archives and question-only baselines remain required.
        video_archive=archive and ('video' in relative.lower() or relative in ('Art.zip','Business.zip','Science.zip','Medicine.zip','Humanities.zip','Engineering.zip')) and 'question_only' not in relative
        if video_archive and not progress.get('reuse_checked'):
            media_complete,coverage=all_references_present(spec,annotation_paths)
            progress['reuse_coverage']=coverage
            progress['reuse_checked']=True
        if video_archive and media_complete:
            progress['files'].append({'path':relative,'state':'existing_extracted_media','verification':'reference_existence_only'})
            continue
        existing=exact_existing(relative,f.size or 0,spec['media_roots'])
        if existing:
            progress['files'].append({'path':relative,'state':'existing_size_match','source':str(existing),'bytes':f.size})
            if annotation:annotation_paths.append(existing)
            continue
        output=destination.joinpath(*safe_relative(relative).parts)
        if root.resolve() not in output.resolve().parents:
            raise RuntimeError('snapshot_path_escapes_data_root')
        reused_snapshot=output.exists()
        if reused_snapshot:
            if not output.is_file() or f.size is None or output.stat().st_size != f.size:
                raise RuntimeError('existing_snapshot_file_conflict_preserved')
            path=str(output)
        else:
            if f.size is not None and shutil.disk_usage(root).free < f.size + 1024**3:
                raise RuntimeError('insufficient_disk_space_preserved')
            path=hf_hub_download(repo_id=spec['repo'],repo_type='dataset',filename=relative,
                revision=spec['revision'],endpoint=endpoint,token=token or False,
                local_dir=str(destination),cache_dir=str(root/'_cache'))
        if not Path(path).is_file() or (f.size is not None and Path(path).stat().st_size!=f.size):
            raise RuntimeError('download_size_mismatch')
        progress['files'].append({'path':relative,'state':'existing_snapshot_size_match' if reused_snapshot else 'downloaded_or_hf_cache','bytes':Path(path).stat().st_size})
        if annotation:annotation_paths.append(Path(path))
        print(f"  {spec['name']}: {index+1}/{len(selected)} {relative}",flush=True)
    progress['annotations']=scan_annotations(spec,annotation_paths)
    progress.pop('active_file',None)
    progress['snapshot_path']=str(destination)
    progress['archive_extraction']='not_performed'
    progress['media_decode_verification']='not_performed'
    progress['download_status']='available_snapshot_files_complete'
    blockers=[]
    if spec.get('youtube_missing'):
        complete,coverage=all_references_present(spec,annotation_paths)
        progress['reuse_coverage']=coverage
        if not complete:
            # Original LVBench offers YouTube IDs, not an official hosted video archive.
            target=destination/'videos';target.mkdir(exist_ok=True)
            ids=set()
            for p in annotation_paths:
                for r in read_rows(p):
                    if r.get('key'):ids.add(r['key'])
            failed=[]
            for video_id in sorted(ids):
                if not all(c in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in video_id):
                    raise RuntimeError('invalid_youtube_id')
                if any(p.is_file() and p.stat().st_size>0 for p in candidate_paths(video_id+'.mp4',spec['media_roots'])):continue
                cmd=[sys.executable,'-m','yt_dlp','--proxy','','--no-playlist','--no-overwrites','--continue',
                     '--socket-timeout','20','--retries','2','--merge-output-format','mp4','-f','bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
                     '-o',str(target/(video_id+'.%(ext)s')),'https://www.youtube.com/watch?v='+video_id]
                with (target/(video_id+'.download.log')).open('ab') as log:
                    try:rc=subprocess.run(cmd,stdout=log,stderr=log,timeout=1800).returncode
                    except subprocess.TimeoutExpired:rc=124
                if rc:failed.append(video_id)
            progress['youtube_failed_ids']=failed
            if failed:blockers.append('youtube_videos_unavailable')
    if spec.get('external_ntu'):
        listing=destination/'video/MVBench_videos_ntu.txt'
        if listing.is_file():
            ntu=[x.strip() for x in listing.read_text().splitlines() if x.strip()]
            missing=[v for v in ntu if not any(p.is_file() and p.stat().st_size>0 for p in candidate_paths(v,[str(Path(r)/'video/nturgbd') for r in spec['media_roots']]+[str(Path(r)/'nturgbd') for r in spec['media_roots']]))]
            progress['ntu']={'listed':len(ntu),'missing':len(missing),'missing_examples':missing[:10]}
            if missing:blockers.append('ntu_original_provider_access_needed')
        else:blockers.append('ntu_inventory_unavailable')
    if spec.get('hidden_test'):progress['hidden_test']='not_publicly_downloadable'
    progress['blockers']=blockers
    return not blockers


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['inventory','download'])
    parser.add_argument('--config',required=True)
    parser.add_argument('--root',type=Path)
    parser.add_argument('--only',nargs='+')
    args=parser.parse_args()
    config=json.loads(Path(args.config).read_text(encoding='utf8'))
    if args.only and set(args.only)-{s['name'] for s in config['datasets']}:
        parser.error('Unknown benchmark in --only.')
    root=(args.root or Path(config['data_root'])).resolve()
    code_root=Path(__file__).resolve().parents[2]
    if root==code_root or code_root in root.parents:
        parser.error('Dataset output must be outside the code checkout.')
    proxy_names=[k for k in os.environ if k.lower() in ('http_proxy','https_proxy','all_proxy')]
    for name in proxy_names:os.environ.pop(name,None)
    os.environ.update(NO_PROXY='*',no_proxy='*',HF_HUB_DISABLE_XET='1',HF_HUB_DISABLE_IMPLICIT_TOKEN='1')
    report_dir=root/'reports'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    report_dir.mkdir(parents=True,exist_ok=False)
    report={'action':args.action,'proxy_variable_names_ignored':proxy_names,'personal_proxy':False,
            'archive_extraction':'not_performed','datasets':[]}
    try:report['code_commit']=subprocess.check_output(['git','-C',str(code_root),'rev-parse','HEAD'],text=True,timeout=5).strip()
    except (OSError,subprocess.SubprocessError):report['code_commit']='unknown'
    report_path=report_dir/'report.json'
    print('REPORT '+str(report_path),flush=True)
    ok=True
    for spec in config['datasets']:
        if args.only and spec['name'] not in args.only:continue
        item={'name':spec['name'],'state':'running','repository':spec['repo'],'revision':spec['revision']}
        report['datasets'].append(item)
        print('BEGIN '+spec['name'],flush=True)
        write_json(report_path,report)
        try:
            item['existing_annotations']=scan_annotations(spec,[Path(p) for p in spec['existing_annotations']])
            item['saved_snapshot_annotations']=scan_annotations(spec,saved_annotations(spec,root))
            item['media_root_existence']={p:Path(p).is_dir() for p in spec['media_roots']}
            if args.action=='download':
                success=download_dataset(spec,root,item)
                if not success:ok=False
                item['state']='downloaded_with_blockers' if not success else 'downloaded'
            else:item['state']='inventory_only'
        except Exception as exc:
            # Network exceptions may include signed URLs or auth details: never print their text.
            item['state']='blocked'
            item['error_type']=type(exc).__name__
            item['reason']=str(exc) if isinstance(exc,RuntimeError) and str(exc).replace('_','').isalnum() else 'network_authorization_or_file_error'
            status=getattr(getattr(exc,'response',None),'status_code',None)
            if status in {401,403}:item['http_status']=status;item['reason']='official_access_or_authorization_required'
            ok=False
        write_json(report_path,report)
        print(item['state'].upper()+' '+spec['name'],flush=True)
    report['status']='complete_for_requested_action' if ok else 'incomplete'
    write_json(report_path,report)
    write_json(root/'latest_report.json',{'report':str(report_path),'status':report['status']})
    print(('PASS' if ok else 'FAIL')+': '+str(report_path),flush=True)
    return 0 if ok else 1


if __name__=='__main__':
    raise SystemExit(main())
