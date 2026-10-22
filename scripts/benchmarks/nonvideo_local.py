"""Download five pinned benchmarks' non-video files with a whole-batch 1 GB gate.

No model API, credentials, source-file mutation, video downloads, or extraction.
Metadata/plan/report and datasets belong outside this code repository.
Gated files are acquired through the user's already-authorized browser and adopted
only after verification against official file size plus Git/LFS content digest.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import zipfile

NAMES=('Video-MME','Video-MME-v2','LVBench','Video-MMMU','MMVU')
ALIASES={'Video-MME':'lmms-lab/Video-MME','Video-MMMU':'lmms-lab/VideoMMMU'}
VIDEOS={'.mp4','.avi','.webm','.mkv','.mov','.mpeg','.mpg','.m4v','.ts'}
ALLOWED={'.json','.jsonl','.parquet','.md','.txt','.yaml','.yml','.csv',
 '.png','.jpg','.jpeg','.webp','.svg','.gif','.pdf','.srt','.vtt'}
CAP=1_000_000_000


def save(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    part=path.with_name(path.name+'.part')
    part.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    os.replace(part,path)


def classify(name,path):
    p=PurePosixPath(path)
    if p.is_absolute() or '..' in p.parts or '\\' in path or ':' in path:
        raise ValueError('unsafe_repository_path')
    if p.suffix.lower() in VIDEOS:return 'video'
    if p.suffix.lower() in {'.zip','.tar','.gz','.tgz','.7z'} or '.tar.' in path:
        if name in {'Video-MME','Video-MME-v2'} and path=='subtitle.zip':return 'nonvideo'
        if name=='Video-MME' and path.startswith('videos_chunked_'):return 'video'
        if name=='Video-MME-v2' and path.startswith('videos/'):return 'video'
        if name=='Video-MMMU' and path in {'Art.zip','Business.zip','Science.zip',
             'Medicine.zip','Humanities.zip','Engineering.zip','question_only_videos.zip'}:return 'video'
        raise ValueError('unclassified_archive_requires_review')
    if p.suffix.lower() in ALLOWED or p.name in {'.gitattributes','.gitignore','LICENSE','LICENSE.txt'}:
        return 'nonvideo'
    raise ValueError('unclassified_file_requires_review')


def bounded_total(items):
    sizes=[x['size'] for x in items]
    if any(not isinstance(v,int) or v<0 for v in sizes):raise ValueError('unknown_file_size')
    total=sum(sizes)
    if total>CAP:raise ValueError('batch_exceeds_1GB_no_payload_download: '+str(total)+' bytes')
    return total


def curl(url,out,size,seconds=60):
    out.parent.mkdir(parents=True,exist_ok=True)
    binary='curl.exe' if os.name=='nt' else 'curl'
    process=subprocess.run([binary,'--noproxy','*','--fail','--location','--silent',
      '--show-error','--connect-timeout','8','--max-time',str(seconds),'--retry','1',
      '--max-filesize',str(max(1,size)),url,'-o',str(out)],capture_output=True,timeout=seconds*2+25)
    if process.returncode:raise RuntimeError('curl_exit_'+str(process.returncode))


def plan_one(spec,root,metadata_dir):
    path=root/'_metadata'/(spec['name']+'.json')
    seed=metadata_dir/(spec['name']+'.json') if metadata_dir else None
    if not path.exists():
        if seed and seed.is_file():
            path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(seed,path)
        else:
            alias=ALIASES.get(spec['name'],spec['repo'])
            tmp=path.with_suffix('.part')
            curl('https://hf-mirror.com/api/datasets/'+alias+'?blobs=true',tmp,5_000_000)
            os.replace(tmp,path)
    info=json.loads(path.read_text(encoding='utf8'))
    if info['sha']!=spec['revision']:raise ValueError('metadata_revision_changed')
    files=[];excluded=[]
    for item in info['siblings']:
        if classify(spec['name'],item['rfilename'])=='video':excluded.append(item['rfilename']);continue
        if 'size' not in item:raise ValueError('metadata_missing_file_size')
        files.append({'name':spec['name'],'repository':info['id'],'revision':info['sha'],
            'path':item['rfilename'],'size':item['size'],'blob_id':item.get('blobId'),
            'sha256':(item.get('lfs') or {}).get('sha256'),'gated':bool(info.get('gated'))})
    return {'name':spec['name'],'files':files,'bytes':sum(x['size'] for x in files),'excluded_video_files':excluded}


def verified(path,item):
    if not path.is_file() or path.stat().st_size!=item['size']:return False
    h=hashlib.sha256() if item.get('sha256') else hashlib.sha1()
    if not item.get('sha256'):h.update(('blob '+str(item['size'])+'\0').encode())
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    expected=item.get('sha256') or item.get('blob_id')
    if not expected:raise ValueError('missing_official_content_digest')
    return h.hexdigest()==expected


def target(root,item):
    path=root/item['name']/item['path']
    if root.resolve() not in path.resolve().parents:raise ValueError('output_escapes_root')
    return path


def publish_copy(source,out,item):
    if out.exists():
        if not verified(out,item):raise ValueError('existing_output_conflict_preserved')
        return
    if not verified(source,item):raise ValueError('source_digest_mismatch')
    out.parent.mkdir(parents=True,exist_ok=True)
    part=out.with_name(out.name+'.part')
    shutil.copyfile(source,part)
    if not verified(part,item):raise ValueError('staged_digest_mismatch')
    os.link(part,out)  # No overwrite, including a racing publisher.
    part.unlink()


def status(root,plan):
    rows=[]
    for dataset in plan['datasets']:
        done=0;size=0;missing=[]
        for item in dataset['files']:
            if verified(target(root,item),item):done+=1;size+=item['size']
            else:missing.append(item['path'])
        rows.append({'name':dataset['name'],'expected_files':len(dataset['files']),
          'verified_files':done,'verified_bytes':size,'missing':missing})
    result={'status':'complete' if all(not r['missing'] for r in rows) else 'incomplete',
       'planned_bytes':plan['total_bytes'],'verified_bytes':sum(r['verified_bytes'] for r in rows),
       'limit_bytes':CAP,'video_files_downloaded':0,'datasets':rows}
    save(root/'download_report.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['plan','download','adopt','adopt-downloads','verify'])
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--config',type=Path,default=Path(__file__).resolve().parents[2]/'configs/benchmark_assets.json')
    p.add_argument('--metadata-dir',type=Path)
    p.add_argument('--reuse-root',type=Path)
    p.add_argument('--name',choices=NAMES)
    p.add_argument('--file')
    p.add_argument('--source',type=Path)
    p.add_argument('--only',nargs='+',choices=NAMES)
    args=p.parse_args()
    root=args.root.resolve();code=Path(__file__).resolve().parents[2]
    if root==code or code in root.parents:p.error('Data must remain outside the code repository.')
    root.mkdir(parents=True,exist_ok=True)
    if args.action=='plan':
        specs=[s for s in json.loads(args.config.read_text(encoding='utf8'))['datasets'] if s['name'] in NAMES]
        if {s['name'] for s in specs}!=set(NAMES):raise ValueError('five_dataset_registry_incomplete')
        with ThreadPoolExecutor(max_workers=2) as pool:
            datasets=list(pool.map(lambda s:plan_one(s,root,args.metadata_dir),specs))
        items=[x for d in datasets for x in d['files']]
        total=bounded_total(items)
        plan={'total_bytes':total,'limit_bytes':CAP,'datasets':datasets,'status':'under_limit_ready'}
        save(root/'download_plan.json',plan)
        print(json.dumps({'total_bytes':total,'datasets':[{k:d[k] for k in ('name','bytes')} for d in datasets]},indent=2))
        return 0
    plan=json.loads((root/'download_plan.json').read_text(encoding='utf8'))
    items=[x for d in plan['datasets'] for x in d['files']]
    if bounded_total(items)!=plan['total_bytes']:raise ValueError('plan_total_mismatch')
    if args.action=='adopt':
        matches=[x for x in items if x['name']==args.name and x['path']==args.file]
        if len(matches)!=1 or not args.source:p.error('adopt needs one planned --name/--file and --source')
        publish_copy(args.source,target(root,matches[0]),matches[0])
    if args.action=='adopt-downloads':
        if not args.source or not args.source.is_dir():p.error('--source must be the browser download directory')
        candidates=list(args.source.glob('test-00000-of-00001*.parquet'))
        if len(candidates)>30:raise ValueError('browser_candidate_count_exceeds_bounded_scope')
        for item in items:
            if item['name']!='Video-MMMU' or not item['path'].endswith('.parquet'):continue
            out=target(root,item)
            if verified(out,item):continue
            match=next((q for q in candidates if verified(q,item)),None)
            if match:publish_copy(match,out,item)
    if args.action=='download':
        for item in items:
            if args.only and item['name'] not in args.only:continue
            out=target(root,item)
            if verified(out,item):continue
            if out.exists():raise ValueError('existing_output_conflict_preserved')
            candidates=[]
            if args.reuse_root:
                alias=ALIASES.get(item['name'],item['repository'])
                candidates=[args.reuse_root/r.replace('/','__')/item['path'] for r in {alias,item['repository']}]
            reuse=next((path for path in candidates if verified(path,item)),None)
            if reuse:publish_copy(reuse,out,item);print('REUSED '+item['name']+'/'+item['path'],flush=True);continue
            if item['gated'] and item['path'] not in {'README.md','.gitattributes'}:
                print('BROWSER_REQUIRED '+item['name']+'/'+item['path'],flush=True);continue
            out.parent.mkdir(parents=True,exist_ok=True)
            part=out.with_name(out.name+'.download.part')
            try:
                route='raw' if item['gated'] else 'resolve'
                repository=ALIASES.get(item['name'],item['repository'])
                curl('https://hf-mirror.com/datasets/'+repository+'/'+route+'/'+item['revision']+'/'+item['path'],part,item['size'],90)
                if not verified(part,item):raise ValueError('download_digest_mismatch')
                if item['path'].endswith('.zip'):
                    with zipfile.ZipFile(part) as z:
                        if any(PurePosixPath(i.filename).suffix.lower() in VIDEOS for i in z.infolist()):raise ValueError('archive_contains_video')
                        if z.testzip():raise ValueError('archive_crc_failure')
                publish_copy(part,out,item)
                part.unlink()
                print('OK '+item['name']+'/'+item['path'],flush=True)
            except (RuntimeError,subprocess.SubprocessError,ValueError) as exc:
                print('BLOCKED '+item['name']+'/'+item['path']+' '+type(exc).__name__,flush=True)
    result=status(root,plan)
    return 0 if result['status']=='complete' else 1


if __name__=='__main__':
    try:raise SystemExit(main())
    except (RuntimeError,ValueError,KeyError) as e:
        print('FAIL: '+str(e),file=sys.stderr);raise SystemExit(1)
