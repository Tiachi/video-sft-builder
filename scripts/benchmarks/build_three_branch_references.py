"""Read pinned annotations; export reference QA outside the code checkout.

No network, media decoding, model API, or training-data export. Static screening
is deliberately not called visual verification. Original annotations are read-only.
Output is no-clobber and published by a same-parent directory rename.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile

CODE_ROOT = Path(__file__).resolve().parents[2]
TARGET = 10
SEED = 'three-branches-20261022-v1'
V2_DEFER = {
    'Basic Counting': '精确计数；需对象检测/跟踪与计数专项',
    'Repetitive Action Counting': '重复动作次数；需密集时序计数专项',
    'Numerical Calculation': '数值/公式读取与计算；需结构化数理专项',
    'Audio-Guided Visual Description': '依赖音频引导；当前纯视觉不消费音轨',
    'Vision-Guided Audio Description': '答案依赖音频内容',
    'Cross-Modal Semantic Consistency': '要求音画语义对齐',
    'Visual-Audio Collaborative Reasoning': '要求音画联合推理',
    'Fine-Grained Action Recognition': '精细手脚姿态/短暂运动；当前caption不保证保真',
    'Motion Trajectory Estimation': '精确轨迹与方向细节；需轨迹专项',
    'Entity Persistence Tracking': '遮挡/换位下持续身份跟踪；需跟踪专项',
    'Temporal Action Localization': '精确动作起止；需细粒度grounding专项',
    'Temporal Periodicity Detection': '周期/重复间隔；需密集时序专项',
}
RULES = {
    'counting': r'\bhow many\b|\bnumber of\b|\bquantity\b|\bdegree\(s\) of freedom\b|\btotal (?:number|count)\b|\bcount(?:ing)? (?:the|all)\b',
    'audio_dialogue': r'\b(?:hear|heard|says?|said|saying|spoken|speaker|narrat(?:or|ion)|dialogue|lyrics?|soundtrack|sing(?:s|ing)?|song|music|pronounc\w*|accent|conversation|interview\w*|debate|discuss\w*|told|mentioned|announc\w*|remarks|speech|whisper|voice)\b|\baccording to (?:the )?(?:host|lecturer|instructor|commentator)\b|\b(?:talk|talks|talking|explain(?:s|ed|ing)?) about\b',
    'ocr_text': r'\b(?:subtitle|caption|inscription|written|reads?|printed|spelled|text|words?|letters?|flashcards?|license plate|phone number|serial number|scoreboard|font)\b|\b(?:name|title) of (?:the )?(?:book|article|newspaper|website|magazine)\b',
    'exact_time': r'\b(?:at what|what exact|which exact) (?:time|timestamp|second|minute)\b|\bhow (?:long|much time)\b|\b(?:duration|seconds? apart|minutes? apart|frame rate)\b',
    'numeric_readout': r'\b(?:calculate|computation|numerical|value of|what is the value|how much|how far|how fast|what percentage|what percent|what fraction|what ratio|what angle|what distance|what speed|what voltage|what current|what temperature|what pressure|how many grams|how many moles)\b|\b(?:answer|result) (?:in|to) (?:meters|metres|seconds|decimal)\b',
    'external_query_image': r'<image\s*\d*>|\b(?:figure|diagram|image|picture) (?:below|above|provided|attached)\b|\bas shown in (?:the )?(?:figure|diagram)\b',
    'fine_visual': r'\b(?:microscop\w*|radiograph\w*|x-ray|MRI|CT scan|ECG|electrocardiogram|histolog\w*|electrophoresis|spectrogram|oscilloscope)\b',
    'chart_or_instrument': r'\b(?:bar chart|line chart|graph labeled|green curve|yellow curve|histogram|spectrum analyzer|voltage measurements|data analysis|display on|watch.*display|measurements)\b',
    'score_readout': r'\b(?:score (?:is|was|of|between)|when the score|laps to go|number \d+|wears? (?:number|a number)|athletes? with number)\b',
    'named_identity': r'\b(?:what is the name|what.s the name|what is the nationality|which country|which countries|what letter|what specific time|specific time in the video|construction year|calendar|days of the week)\b',
    'verbal_or_hidden_premise': r'\b(?:wants? to|wishes? to|promis\w*|booed|charged the audience|refuse\w*|request\w*|claims?|claiming|suggested treatment|treatment for|what.*think of|life journey|borned|life story|biography|verse|sponsors?|birthplace|grew up|unspoken|unshown|implicit|conscience|opinion|negotiation|referendums|budget|debt|cash flow|GDP|fragrances|phone call|answering the phone|main content.*explains)\b',
    'precision_comparison': r'\bdistances? (?:in order|between)\b|\b(?:8|3|1) meters\b|\binvestment\b|\bnet present values\b',
    'symbolic_problem': r'\b(?:correct option|correct answer for question|problem-solving logic|formulas shown|fill in the superscripts|subscripts|neuron in layer|point B|\bKeq\b)\b',
    'fine_sports_or_trick': r'\b(?:topspin|backspin|racket face|brush the (?:bottom|top)|10th and 11th strokes|coin disappearance|magician secretly|hand speed|secretly took|hidden inside|pre-hidden)\b',
}
COMPILED = {k: re.compile(v, re.I) for k, v in RULES.items()}


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path, algorithm='sha256'):
    h = hashlib.new(algorithm)
    with path.open('rb') as f:
        if algorithm == 'sha1':
            h.update(f'blob {path.stat().st_size}\0'.encode())
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def options_map(value):
    if isinstance(value, dict):
        return {k: v for k, v in value.items() if v}
    if isinstance(value, str):
        chunks = re.split(r'(?:^|\n)\s*([A-Z])[.)]\s*', value)
        if len(chunks) > 1:
            return {chunks[i]: chunks[i + 1].strip() for i in range(1, len(chunks), 2)}
        raise ValueError('unparseable_options_string')
    if isinstance(value, list):
        result = {}
        for i, item in enumerate(value):
            m = re.match(r'^\s*\(?([A-Z])[.)]\s*', item)
            label = chr(65 + i)
            if m and m.group(1) == label:
                item = item[m.end():]
            result[label] = item
        return result
    if value is None:
        return {}
    raise ValueError('unknown_option_type')


def row(branch, dataset, subclass, qid, question, options, answer, source_file,
        source_row, video_key, **extra):
    opts = options_map(options)
    answer = str(answer)
    if opts and answer not in opts:
        raise ValueError(f'answer_missing_in_options: {dataset}/{qid}/{answer}')
    return dict(branch=branch, dataset=dataset, subclass=subclass,
                source_id=str(qid), question=question, options=opts,
                answer=answer, answer_text=opts.get(answer, answer),
                source_file=source_file, source_row=source_row,
                video_key=str(video_key), **extra)


def read_inputs(root):
    import pyarrow.parquet as pq
    result = []
    files = []
    plan = load_json(root / 'download_plan.json')
    pinned = {(d['name'], f['path']): f for d in plan['datasets'] for f in d['files']}

    def read(name, rel):
        path = root / name / rel
        item = pinned[(name, rel)]
        algorithm = 'sha256' if item.get('sha256') else 'sha1'
        expected = item.get('sha256') or item['blob_id']
        if path.stat().st_size != item['size'] or digest(path, algorithm) != expected:
            raise ValueError(f'input_checksum_mismatch: {name}/{rel}')
        files.append(dict(dataset=name, path=rel, sha256=digest(path),
                          revision=item['revision'], repository=item['repository']))
        if path.suffix == '.parquet':
            return pq.read_table(path).to_pylist()
        if path.suffix == '.jsonl':
            return [json.loads(s) for s in path.read_text(encoding='utf8').splitlines() if s]
        return load_json(path)

    rel = 'videomme/test-00000-of-00001.parquet'
    for i, r in enumerate(read('Video-MME', rel)):
        args = ('Video-MME', r['task_type'], r['question_id'], r['question'],
                r['options'], r['answer'], 'Video-MME/' + rel, i, r['videoID'])
        result.append(row('general', *args, duration_subset=r['duration']))
        if r['duration'] == 'long':
            result.append(row('long', 'Video-MME-long', *args[1:], duration_subset='long'))
    for i, r in enumerate(read('Video-MME-v2', 'test.parquet')):
        result.append(row('general', 'Video-MME-v2', r['third_head'], r['question_id'],
                          r['question'], r['options'], r['answer'],
                          'Video-MME-v2/test.parquet', i, r['video_id'],
                          source_hierarchy=[r['level'], r['second_head'], r['third_head']],
                          source_group_type=r['group_type'], source_group_structure=r['group_structure']))
    for i, r in enumerate(read('LVBench', 'video_info.meta.jsonl')):
        for j, qa in enumerate(r['qa']):
            # LVBench embeds options in the original question. Keep that text intact.
            pieces = re.split(r'\(([A-D])\)\s*', qa['question'])
            if len(pieces) != 9:
                raise ValueError(f'lvbench_option_parse: {qa["uid"]}')
            opts = {pieces[k]: pieces[k + 1].strip() for k in range(1, 9, 2)}
            for cat in qa['question_type']:
                result.append(row('long', 'LVBench', cat, qa['uid'], qa['question'],
                                  opts, qa['answer'], 'LVBench/video_info.meta.jsonl', i,
                                  r['key'], source_qa_index=j, source_labels=qa['question_type'],
                                  source_time_reference=qa.get('time_reference'),
                                  question_stem=pieces[0],
                                  options_embedded=True))
    for track in ('Perception', 'Comprehension', 'Adaptation'):
        rel = f'{track}/test-00000-of-00001.parquet'
        for i, r in enumerate(read('Video-MMMU', rel)):
            opts = r['options'] if r['question_type'] == 'multiple-choice' else None
            result.append(row('knowledge', 'Video-MMMU', r['qa_type'], r['id'],
                              r['question'], opts, r['answer'], 'Video-MMMU/' + rel, i,
                              r['link_selected'], track=track,
                              query_image_present=bool(r.get('image')),
                              original_question_type=r['question_type']))
    for i, r in enumerate(read('MMVU', 'validation.json')):
        result.append(row('knowledge', 'MMVU', r['metadata']['subject'], r['id'],
                          r['question'], r['choices'], r['answer'], 'MMVU/validation.json',
                          i, r['video'], source_subject=r['metadata']['subject']))
    return result, files


def category_policy(dataset, cat):
    if dataset.startswith('Video-MME') and dataset != 'Video-MME-v2':
        if cat == 'Counting Problem':
            return 'deferred', '精确计数，需计数专项'
        if cat == 'OCR Problems':
            return 'deferred', '文字精读，需OCR专项'
    if dataset == 'Video-MME-v2' and cat in V2_DEFER:
        return 'deferred', V2_DEFER[cat]
    if dataset == 'Video-MMMU':
        if cat in ('OCR', 'ASR'):
            return 'deferred', '分别依赖精确读字/音频转写'
        if cat in ('Case Study Analysis', 'Problem-solving Adaptation'):
            return 'deferred', '本地该类全部含额外查询图片；当前MP4-only输入不覆盖'
        if cat == 'Problem-solving Comprehension':
            return 'deferred', '本地主要是改参数重算/公式/图结构解题；当前通用caption不保证必要结构，首版暂缓'
        return 'conditional', '仅定性概念/解题原理；剔除对白、精确公式/数值读取及计算题'
    if dataset == 'MMVU':
        return 'conditional', '学科维度；仅视频可观察现象+专业知识推理，逐题排除细粒度/数值/读字依赖'
    return 'conditional', 'caption明确记录所有必要观察才能使用；本轮仅文本静态筛选'


def static_flags(r):
    flags = []
    q = r.get('question_stem', r['question'])
    # Distractors mentioning speech or numbers do not alone imply that dependency.
    text = q + '\n' + r['answer_text']
    if r.get('query_image_present'):
        flags.append('external_query_image')
    for key, pattern in COMPILED.items():
        if pattern.search(text) and key not in flags:
            flags.append(key)
    if re.search(r'\d{1,3}:\d{2}', r['answer_text']):
        flags.append('exact_time_or_score_answer')
    if r['dataset']=='Video-MMMU' and re.search(r'formula|equation|superscript|subscript|\bNPV\b|_[a-zA-Z0-9]|\\(?:frac|omega|alpha|beta)|in-video quiz|main focus|order of the video|entire tree|leaf nodes|portfolio|beta|quiz|lecture|video suggested|video implied|statements.*correct',text,re.I):
        flags.append('lecture_symbolic_structure')
    if re.fullmatch(r'[\s$\\{}()\[\]\d.,%+\-*/^=°a-zA-ZΩμ²³]+', r['answer_text']) and re.search(r'\d', r['answer_text']):
        flags.append('numeric_answer')
    if r.get('original_question_type') == 'None':
        flags.append('source_question_type_missing')
    return flags


def group_key(r):
    return (r['branch'], r['dataset'], r['subclass'])


def identity(r):
    # General Video-MME and Long's alias refer to the same physical source QA.
    return (r['source_file'], r['source_id'])


def rank(r):
    value = '|'.join([SEED, *group_key(r), r['source_id']])
    # Prefer overt visual observations over an unqualified random draw from lecture
    # and news questions. This is prioritization, not a proof of video dependence.
    text=r['question']+' '+r['answer_text']
    visual=len(re.findall(r'\b(?:color|colour|wear\w*|cloth\w*|left|right|front|behind|inside|outside|moves?|movement|jump\w*|cook\w*|food|animal\w*|dog\w*|cat\w*|bird\w*|water|ball\w*|table|door|window|tree|paint\w*|fold\w*|scene|stage|sequence|steps|perform\w*|machine|experiment|motion|phenomenon)\b',text,re.I))
    textual=len(re.findall(r'\b(?:theory|government|economic\w*|financial|country|countries|political|policy|lecture|ancient|history|historical|news|opinion|legitimacy|birthplace|named|name|asked|ask|comments|debt|cash flow|said|motivation|implicit|hidden|secret)\b',text,re.I))
    return (textual-min(visual,6), hashlib.sha256(value.encode()).hexdigest())


def select(rows, overrides=None):
    groups = collections.defaultdict(list)
    for r in rows:
        groups[group_key(r)].append(r)
    summaries, selected, screened = [], [], []
    overrides = overrides or {}
    for key, items in sorted(groups.items()):
        status, reason = category_policy(key[1], key[2])
        candidates = []
        for r in items:
            uid = '|'.join([*key, r['source_id']])
            flags = static_flags(r)
            override = overrides.get(uid)
            if override:
                if override['action'] != 'exclude' or not override['reason']:
                    raise ValueError('only_documented_exclusions_allowed')
                flags.append('curation_exclusion:' + override['reason'])
            r = dict(r, static_flags=flags,
                     verification='text_static_screen_only_video_caption_unverified',
                     category_status=status, category_reason=reason)
            screened.append(r)
            if status != 'deferred' and not flags:
                candidates.append(r)
        chosen, videos, qids = [], set(), set()
        # Prefer different videos; only relax video diversity, never unique-QA identity.
        for distinct in (True, False):
            for r in sorted(candidates, key=rank):
                if len(chosen) == TARGET:
                    break
                if identity(r) in qids or (distinct and r['video_key'] in videos):
                    continue
                chosen.append(r)
                videos.add(r['video_key'])
                qids.add(identity(r))
        selected.extend(chosen)
        summaries.append(dict(branch=key[0], dataset=key[1], subclass=key[2],
                              status=status, reason=reason, source_count=len(items),
                              static_candidate_count=len(candidates), selected_count=len(chosen),
                              target=0 if status == 'deferred' else TARGET,
                              shortage=0 if status == 'deferred' else TARGET-len(chosen),
                              selected_unique_videos=len(videos),
                              rejection_flags=dict(collections.Counter(f for r in screened[-len(items):] for f in r['static_flags']))))
    if len(summaries) != 96:
        raise ValueError(f'expected_96_requested_groups_got_{len(summaries)}')
    return summaries, selected, screened


def cell(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('|', '&#124;').replace('\r', '').replace('\n', '<br>')


def qa_table(rows):
    lines = ['| 管线 | 数据集 | 子类 | Q（原文及原选项） | A（原答案） | 原题ID |',
             '|---|---|---|---|---|---|']
    for r in rows:
        q = r['question']
        if r['options'] and not r.get('options_embedded'):
            q += '\n' + '\n'.join(k + '. ' + v for k, v in r['options'].items())
        a = r['answer'] + '. ' + r['answer_text'] if r['options'] else r['answer_text']
        lines.append('| ' + ' | '.join(cell(v) for v in [r['branch'], r['dataset'], r['subclass'], q, a, r['source_id']]) + ' |')
    return '\n'.join(lines) + '\n'


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf8')


def export(root, output, overrides_file=None):
    root, output = root.resolve(), output.resolve()
    if output == CODE_ROOT or CODE_ROOT in output.parents:
        raise ValueError('qa_payload_must_be_outside_code_checkout')
    if output == root or root in output.parents or output in root.parents:
        raise ValueError('output_must_not_overlap_immutable_inputs')
    if output.exists():
        raise FileExistsError('output_exists_no_clobber')
    rows, inputs = read_inputs(root)
    overrides = load_json(overrides_file) if overrides_file else {}
    valid = {'|'.join([*group_key(r), r['source_id']]) for r in rows}
    if set(overrides) - valid:
        raise ValueError('curation_contains_unknown_ids')
    summaries, selected, screened = select(rows, overrides)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=output.name+'.staging-', dir=output.parent))
    write_json(stage/'category_summary.json', summaries)
    (stage/'selected_qa.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in selected), encoding='utf8')
    (stage/'screened_inventory.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in screened), encoding='utf8')
    header = ('# 三管线 benchmark QA 参考样例\n\n'
              '原始标注只读提取，每个保留子类目标10题；不足不补造。Q/A与选项保留原文，未翻译/改写。'
              '本轮只完成文本静态筛选，未查看对应视频、未生成其caption，不能视为视觉验证通过或直接投产白名单。'
              'Long允许长上下文单段检索；Knowledge允许专业知识但必须依赖视频。\n\n'
              '这是benchmark风格参考库，不是你的MP4训练数据。选项数保留原版（包括5/8/10项），'
              '不代表生产合同已改；生产仍仅3/4/6选一。完整题目追溯见selected_qa.jsonl及manifest.json。\n\n')
    (stage/'all_qa_examples.md').write_text(header+qa_table(selected), encoding='utf8')
    for branch in ('general', 'long', 'knowledge'):
        (stage/f'{branch}_qa_examples.md').write_text(header+qa_table([r for r in selected if r['branch']==branch]), encoding='utf8')
    with (stage/'all_qa_examples.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer=csv.DictWriter(f, fieldnames=['branch','dataset','subclass','source_id','question','options','answer','answer_text','source_file','source_row','verification'])
        writer.writeheader()
        for r in selected:
            writer.writerow({k: json.dumps(r[k],ensure_ascii=False) if k=='options' else r[k] for k in writer.fieldnames})
    lines=['# 全部96个请求分类的筛选与缺口\n',
           '条件保留表示能力可参考，具体题目仍需视频/caption验证；静态候选数不是高质量数据可产数量。\n',
           '|管线|数据集|子类|状态|源题数|静态候选|入表|缺口|理由|',
           '|---|---|---|---|---:|---:|---:|---:|---|']
    for r in summaries:
        lines.append('| '+' | '.join(cell(r[k]) for k in ['branch','dataset','subclass','status','source_count','static_candidate_count','selected_count','shortage','reason'])+' |')
    (stage/'category_screening_and_shortages.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    deferred=[r for r in screened if r['category_status']=='deferred' or r['static_flags']]
    (stage/'deferred_qa.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in deferred),encoding='utf8')
    representatives={}
    for r in deferred:
        reasons=['category:'+r['subclass']] if r['category_status']=='deferred' else r['static_flags']
        for reason in reasons:
            representatives.setdefault(reason,[])
            if len(representatives[reason])<3:
                representatives[reason].append(r)
    excluded=['# 后续专项管线的排除原因与原题例子\n']
    for reason, examples in sorted(representatives.items()):
        excluded.extend(['\n## '+reason+'\n',qa_table(examples)])
    (stage/'deferred_examples.md').write_text('\n'.join(excluded),encoding='utf8')
    manifest=dict(status='complete_static_reference_export_not_training_release',
                  input_root=str(root), source_files=inputs, script_sha256=digest(Path(__file__)),
                  seed=SEED,target_per_retained_category=TARGET,
                  category_count=len(summaries), selected_rows=len(selected),
                  selected_by_branch=dict(collections.Counter(r['branch'] for r in selected)),
                  selected_by_reference_pool=dict(collections.Counter(r['dataset'] for r in selected)),
                  selected_unique_source_qa=len({identity(r) for r in selected}),
                  selected_repeated_source_occurrences=len(selected)-len({identity(r) for r in selected}),
                  selected_cross_branch_shared_source_qa=sum(len({r['branch'] for r in selected if identity(r)==key})>1 for key in {identity(r) for r in selected}),
                  deferred_category_count=sum(r['status']=='deferred' for r in summaries),
                  short_categories=[r for r in summaries if r['shortage']],
                  visual_verification=False,caption_sufficiency_verified=False,
                  human_review_performed=False,model_api_calls=0,
                  curation_sha256=digest(overrides_file) if overrides_file else None)
    manifest['outputs']={p.name:dict(bytes=p.stat().st_size,sha256=digest(p)) for p in stage.iterdir() if p.is_file()}
    write_json(stage/'manifest.json',manifest)
    # No overwrite: an existing non-empty destination makes rename fail.
    if output.exists():
        raise FileExistsError('output_appeared_during_export')
    stage.rename(output)
    return manifest


def validate_export(root, output, overrides_file=None):
    manifest=load_json(output/'manifest.json')
    if manifest['script_sha256'] != digest(Path(__file__)):
        raise ValueError('script_revision_mismatch')
    for name, meta in manifest['outputs'].items():
        path=output/name
        if path.stat().st_size!=meta['bytes'] or digest(path)!=meta['sha256']:
            raise ValueError('output_checksum_mismatch: '+name)
    rows, inputs=read_inputs(root)
    if inputs!=manifest['source_files']:
        raise ValueError('source_manifest_mismatch')
    if manifest['curation_sha256']!=(digest(overrides_file) if overrides_file else None):
        raise ValueError('curation_revision_mismatch')
    expected_summary, expected_selected, _=select(rows,load_json(overrides_file) if overrides_file else {})
    actual=[json.loads(s) for s in (output/'selected_qa.jsonl').read_text(encoding='utf8').splitlines()]
    if actual!=expected_selected or load_json(output/'category_summary.json')!=expected_summary:
        raise ValueError('deterministic_selection_mismatch')
    for r in actual:
        if r['static_flags'] or r['category_status']=='deferred':
            raise ValueError('excluded_record_in_selected_table')
    if len(actual)!=manifest['selected_rows'] or len({identity(r) for r in actual})!=manifest['selected_unique_source_qa']:
        raise ValueError('record_count_mismatch')
    with (output/'all_qa_examples.csv').open(encoding='utf-8-sig',newline='') as f:
        table=list(csv.DictReader(f))
    if len(table)!=len(actual):
        raise ValueError('csv_row_count_mismatch')
    for a,b in zip(actual,table):
        for key in ('branch','dataset','subclass','source_id','question','answer','answer_text','source_file'):
            if str(a[key])!=b[key]:
                raise ValueError('csv_value_mismatch: '+key)
        if json.loads(b['options'])!=a['options']:
            raise ValueError('csv_options_mismatch')
    md=(output/'all_qa_examples.md').read_text(encoding='utf8')
    if not md.endswith(qa_table(actual)):
        raise ValueError('markdown_table_mismatch')
    return dict(status='PASS',categories=len(expected_summary),selected_rows=len(actual),
                unique_source_qa=manifest['selected_unique_source_qa'],
                verified_outputs=len(manifest['outputs']),model_api_calls=0,
                checks='pinned_inputs_outputs_replay_original_questions_options_answers_csv_markdown_counts')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-root',required=True,type=Path)
    p.add_argument('--output-root',required=True,type=Path)
    p.add_argument('--dependency-dir',type=Path,help='Optional existing pyarrow package directory')
    p.add_argument('--curation',type=Path,help='External JSON: documented additional exclusions only')
    p.add_argument('--validate-only',action='store_true',help='Read-only checksum and exact selection/table replay')
    a=p.parse_args()
    if a.dependency_dir:
        sys.path.insert(0,str(a.dependency_dir.resolve()))
    try:
        if a.validate_only:
            print('PASS:',json.dumps(validate_export(a.input_root,a.output_root,a.curation)))
            return 0
        m=export(a.input_root,a.output_root,a.curation)
    except Exception as e:
        print('FAIL:',str(e),file=sys.stderr)
        return 1
    print('PASS:',json.dumps({k:m[k] for k in ('category_count','selected_rows','selected_by_branch','deferred_category_count','model_api_calls')}))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
