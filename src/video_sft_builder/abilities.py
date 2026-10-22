"""Benchmark recipe selection and evidence-operation contracts; no model calls.

Legacy configs remain legacy. New candidate metadata is external audit material,
not supervised CoT and not additional top-level fields in the training JSON.
"""
from copy import deepcopy
from collections import Counter
import itertools
import random

from .errors import ConfigError, ProtocolError
from .util import asset, read_json

RECIPE='benchmark_v1'
CAPABILITY_CHECKS=('operation_match','caption_faithfulness','video_necessity',
                   'answer_contract','reasoning_validity','knowledge_rule_validity',
                   'distractor_validity','retrieval_scope')


def benchmark_recipe(config):
    return config.data['generation'].get('ability_recipe','legacy_v1')==RECIPE


def registry(config):
    return read_json(asset('configs/benchmark_task_registry.json' if benchmark_recipe(config) else 'configs/task_registry.json'))


def template_asset(config):
    return 'configs/benchmark_question_templates.json' if benchmark_recipe(config) else 'configs/question_templates.json'


def branches(config):
    return ('general','long','knowledge') if benchmark_recipe(config) else ('general','long')


def branch_plan(config, branch):
    if branch not in branches(config):
        raise ConfigError('Branch not enabled in this recipe: '+branch)
    fit,balance=(1,2) if branch=='long' else (2,3)
    return {'fit':fit,'balance':balance,'role':'A5' if branch=='long' else 'A3',
            'attempts':config.data['generation'][branch+'_balance_attempts']}


def call_bounds(config,l1,l2):
    roles=Counter(A1=l1,A2=l2,C_GATE=1)
    normal=l1+l2+1
    plans={}
    for branch in branches(config):
        p=branch_plan(config,branch);plans[branch]=p
        roles[p['role']]+=1+p['attempts']
        roles['A7']+=p['fit']+p['balance']
        normal+=1+p['balance']+p['fit']+p['balance']
    return dict(success_path_inferences=normal,configured_attempt_bound=sum(roles.values()),
                role_attempt_bounds=dict(roles),branch_plans=plans)


def validate_recipe(data):
    g=data['generation']
    recipe=g.get('ability_recipe','legacy_v1')
    if recipe not in ('legacy_v1',RECIPE):
        raise ConfigError('Unknown ability_recipe; no implicit migration')
    if recipe==RECIPE:
        value=g.get('knowledge_balance_attempts')
        if type(value) is not int or value<3:
            raise ConfigError('benchmark_v1 requires explicit knowledge_balance_attempts >=3')


def _require(condition,message):
    if not condition: raise ProtocolError(message)


def validate_assessment(c, task, fact_map, context):
    """Validate checkable role/ID constraints; semantic correctness remains A7's job."""
    a=c.get('assessment')
    _require(isinstance(a,dict) and set(a)=={'operation','roles','criterion','video_necessity','knowledge','distractors'},
             'Missing/invalid benchmark ability assessment')
    _require(a['operation']==task['operation'],'Task operation mismatch')
    _require(isinstance(a['criterion'],str) and a['criterion'].strip(),'Missing task-specific criterion')
    _require(isinstance(a['video_necessity'],str) and a['video_necessity'].strip(),'Missing video necessity statement')
    required=set(c['required_fact_ids'])
    groups=a['roles']
    _require(isinstance(groups,dict) and set(groups)==set(task['role_groups']),'Evidence role groups mismatch')
    used=set()
    for name,minimum in task['role_groups'].items():
        ids=groups[name]
        _require(isinstance(ids,list) and all(isinstance(v,str) for v in ids) and len(set(ids))==len(ids)
                 and len(ids)>=minimum and set(ids)<=required,'Invalid evidence role: '+name)
        _require(not used.intersection(ids),'Evidence roles reuse the same observation')
        used.update(ids)
    _require(used==required,'Required facts must all serve the claimed operation')
    claims=[' '.join(fact_map[k]['claim'].casefold().split()) for k in required]
    _require(len(set(claims))==len(claims),'Repeated claims cannot simulate multiple observations')
    if task['branch']=='knowledge':
        k=a['knowledge']
        fields={'domain','concept','rule','rule_source','premise_fact_ids','applicability_note'}
        _require(isinstance(k,dict) and set(k)==fields,'Knowledge requires separate domain rule and observed premises')
        _require(all(isinstance(k[v],str) and k[v].strip() for v in fields-{'premise_fact_ids'}),'Empty knowledge rule metadata')
        _require(k['rule_source']=='model_prior_unverified','Do not impersonate a textbook or verified expert source')
        _require(isinstance(k['premise_fact_ids'],list) and len(k['premise_fact_ids'])==len(set(k['premise_fact_ids']))
                 and set(k['premise_fact_ids'])==required,'Knowledge rule must use all necessary observed premises')
    else:
        _require(a['knowledge'] is None,'Non-Knowledge tasks cannot introduce an external domain rule')
    _require(isinstance(a['distractors'],list),'Distractor metadata must be an array')
    if c['question_type']=='oe':
        _require(a['distractors']==[],'OE cannot contain MCQ distractors')
    elif task['operation'] not in ('sequence_ordering','coarse_location'):
        expected={chr(65+i) for i in range(c['num_options'])}-{c['correct_option_id']}
        ids=[]
        for d in a['distractors']:
            _require(isinstance(d,dict) and set(d)=={'option_id','error_type','basis_fact_ids','why_wrong'},'Invalid distractor contract')
            _require(d['error_type'] in task['allowed_distractor_types'],'Distractor does not test the assigned capability')
            _require(isinstance(d['why_wrong'],str) and d['why_wrong'].strip(),'Missing distractor falsifier')
            _require(isinstance(d['basis_fact_ids'],list) and d['basis_fact_ids'] and set(d['basis_fact_ids'])<=required,
                     'Distractor must be checked against actual required evidence')
            ids.append(d['option_id'])
        _require(len(ids)==len(expected) and set(ids)==expected,'Every wrong option needs one identified falsifier')
    if task['operation']=='coarse_location':
        _require(len(c['evidence_window_ids'])==1,'Coarse location requires one unambiguous supported window')
        if c['question_type']=='oe':
            _require(any('[[TIME:'+w+']]' in c['answer'] for w in c['evidence_window_ids']),
                     'Location answer does not reference the supported evidence window')
    if task['operation']=='sequence_ordering':
        _require(isinstance(c.get('ordering'),dict),'Ordering tasks require program-compiled event permutations')
    elif c.get('ordering') is not None:
        raise ProtocolError('Ordering metadata is not valid for this operation')
    caption_map={r['id']:r for r in context['captions']}
    used_captions={v for f in required for v in fact_map[f]['caption_ids']}
    c['caption_evidence']=[deepcopy(caption_map[v]) for v in sorted(used_captions)]
    c['task_contract']={key:deepcopy(task[key]) for key in ('contract_version','operation','minimum_windows',
                        'global_coverage','answer_contract','required_capability_checks','role_groups')}


def compile_location(c,context,seed):
    if c['question_type']=='oe': return
    correct=c['evidence_window_ids'][0]
    wrong=[w['id'] for w in context['windows'] if w['id']!=correct]
    _require(len(wrong)>=c['num_options']-1,'Not enough supported windows for assigned MCQ option count')
    rng=random.Random(seed)
    windows=[correct]+rng.sample(wrong,c['num_options']-1)
    c['options']=[dict(id=chr(65+i),text='[[TIME:'+w+']]') for i,w in enumerate(windows)]
    c['answer']=c['correct_option_id']='A'
    c['assessment']['distractors']=[dict(option_id=chr(65+i),error_type='scope_mismatch',
        basis_fact_ids=c['required_fact_ids'],why_wrong='This window is not the uniquely supported location of the requested event.')
        for i in range(1,len(windows))]


def compile_ordering(c, facts, seed):
    ordering=c['ordering'];items=ordering.get('items');correct=ordering.get('correct_order')
    _require(set(ordering)=={'items','correct_order'} and isinstance(items,list) and 3<=len(items)<=6,
             'Ordering needs 3-6 events')
    _require(all(isinstance(i,dict) and set(i)=={'id','text','fact_id'} for i in items),'Ordering events need fact attribution')
    ids=[i['id'] for i in items]
    _require(all(isinstance(v,str) for v in ids) and len(set(ids))==len(ids) and isinstance(correct,list)
             and len(correct)==len(ids) and set(correct)==set(ids),'Invalid event permutation')
    by_id={i['id']:i for i in items}
    _require([by_id[v]['fact_id'] for v in correct]==c['assessment']['roles']['ordered_events'],
             'Ordering answer and temporal evidence roles disagree')
    for i in items:
        _require(i['fact_id'] in c['required_fact_ids'] and i['text']==facts[i['fact_id']]['claim'],
                 'Ordering event is not the attributed observation')
    rng=random.Random(seed);rng.shuffle(items)
    labels={i['id']:'E'+str(n+1) for n,i in enumerate(items)}
    c['question']+=' '+ '; '.join(labels[i['id']]+': '+i['text'] for i in items)
    answer=' → '.join(labels[v] for v in correct)
    if c['question_type']=='oe': c['answer']=answer;return
    alternatives=[p for p in itertools.permutations(ids) if list(p)!=correct]
    permutations=[tuple(correct)]+rng.sample(alternatives,c['num_options']-1)
    c['options']=[dict(id=chr(65+n),text=' → '.join(labels[v] for v in p)) for n,p in enumerate(permutations)]
    c['answer']=c['correct_option_id']='A'
    c['assessment']['distractors']=[dict(option_id=chr(65+n),error_type='temporal_swap',
         basis_fact_ids=c['required_fact_ids'],why_wrong='This permutation contradicts the supported event order.')
         for n in range(1,len(permutations))]


def remap_distractors(c, mapping):
    if 'assessment' in c:
        for d in c['assessment']['distractors']:
            d['option_id']=mapping[d['option_id']]


def validate_capability_audit(response,candidate):
    if 'task_contract' not in candidate: return True,'legacy_audit'
    checks=response.get('capability_checks')
    if not isinstance(checks,dict) or set(checks)!=set(CAPABILITY_CHECKS):
        return False,'incomplete_capability_audit'
    needed=set(candidate['task_contract']['required_capability_checks'])
    if candidate['question_type']=='mcq': needed.add('distractor_validity')
    if any(v not in ('pass','not_applicable') for v in checks.values()) or any(checks[k]!='pass' for k in needed):
        return False,'failed_or_insufficient_capability_check'
    return True,'capability_audit_pass'
