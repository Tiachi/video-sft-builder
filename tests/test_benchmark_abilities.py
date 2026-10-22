"""Capability contracts and three-branch accounting; synthetic only, no paid API."""
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import json
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from video_sft_builder.abilities import (CAPABILITY_CHECKS,branches,call_bounds,registry,
                                        validate_capability_audit)
from video_sft_builder.completion import completion
from video_sft_builder.config import RuntimeConfig,validate_config
from video_sft_builder.errors import ConfigError,PipelineError,ProtocolError
from video_sft_builder.pipeline import Pipeline
from video_sft_builder.quality import prepare_candidate,validate_audit
from video_sft_builder.reporting import FINAL_FIELDS,candidate_records,export_candidates,report
from video_sft_builder.scheduler import Scheduler
from video_sft_builder.settings import Settings
from video_sft_builder.state import Store
from video_sft_builder.synthetic import SyntheticMedia,SyntheticProvider,create_inputs,demo_config
from video_sft_builder.util import asset,read_json


class AbilityTests(unittest.TestCase):
    def setUp(self):
        base=Path(__file__).resolve().parents[2]/'benchmark-ability-tests'
        base.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        legacy=demo_config(self.root)
        data=deepcopy(legacy.data)
        data['generation'].update(ability_recipe='benchmark_v1',knowledge_balance_attempts=9)
        validate_config(data,allow_synthetic=True)
        self.cfg=RuntimeConfig(data,legacy.path)
        self.tasks={t['name']:t for t in registry(self.cfg)['tasks']}

    def opened(self):
        create_inputs(self.cfg)
        store=Store(self.cfg);self.addCleanup(store.close)
        return store

    def fixture(self,name='knowledge_mechanism_explanation',form='oe',n=0):
        task=self.tasks[name];windows=[dict(id='w'+str(i),start=i*10,end=(i+1)*10) for i in range(6)]
        slot=dict(slot_id='unit',task=name,allowed_tasks=[name],language='en',question_type=form,num_options=n)
        templates=[t for t in read_json(asset('configs/benchmark_question_templates.json'))['templates']
                   if t['task']==name and t['language']=='en'][:1]
        context=dict(request_id='request',video_id='video',branch=task['branch'],phase='balance',assigned_slots=[slot],
            allowed_tasks=[task],template_candidates=templates,windows=windows,
            captions=[dict(id='l1_'+w['id'],description='Synthetic observation '+str(i)) for i,w in enumerate(windows)])
        result=SyntheticProvider.generate(context)
        video=dict(id='video',duration=60)
        return result['candidates'][0],result['facts'],context,video

    def prepare(self,fixture):
        c,f,ctx,v=fixture
        return prepare_candidate(c,f,ctx,v,ctx,self.tasks,123)

    def test_inventory_and_coverage_are_not_subject_tasks(self):
        self.assertEqual(Counter(t['branch'] for t in self.tasks.values()),dict(general=18,long=8,knowledge=6))
        self.assertEqual(len(read_json(asset('configs/benchmark_capability_coverage.json'))['coverage']),96)
        templates=read_json(asset('configs/benchmark_question_templates.json'))['templates']
        self.assertEqual(len(templates),256)
        self.assertTrue(all(t['question_types']==['oe'] for t in self.tasks.values() if t['name'] in ('event_timeline','hierarchical_summary')))
        self.assertFalse(registry(self.cfg)['source_context']['domains_are_tasks'])

    def test_compiled_assets_and_example_do_not_drift(self):
        script=Path(__file__).resolve().parents[1]/'scripts/build_benchmark_recipe.py'
        spec=importlib.util.spec_from_file_location('benchmark_recipe_compiler',script)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        for name,expected in module.compile_assets().items():
            self.assertEqual(read_json(asset('configs/'+name)),expected)
        example=read_json(asset('configs/benchmark_recipe.example.json'))
        plans=call_bounds(self.cfg,0,0)['branch_plans']
        for name,p in plans.items():
            self.assertEqual((example['branches'][name]['fit'],example['branches'][name]['balance'],
                              example['branches'][name]['balance_attempts']),
                             (p['fit'],p['balance'],p['attempts']))

    def test_bounds_make_added_knowledge_cost_explicit(self):
        current=call_bounds(self.cfg,6,2)
        self.assertEqual((current['success_path_inferences'],current['configured_attempt_bound']),(33,51))
        self.assertEqual(current['role_attempt_bounds'],dict(A1=6,A2=2,C_GATE=1,A3=23,A5=6,A7=13))
        old=call_bounds(demo_config(self.root),6,2)
        self.assertEqual((old['success_path_inferences'],old['configured_attempt_bound']),(24,36))

    def test_every_contract_and_form_can_compile(self):
        for name,task in self.tasks.items():
            for form in task['question_types']:
                with self.subTest(task=name,form=form):
                    c=self.prepare(self.fixture(name,form,4 if form=='mcq' else 0))
                    self.assertEqual(c['task_contract']['operation'],task['operation'])
                    self.assertEqual(c['ability_recipe'],'benchmark_v1')

    def test_operation_and_necessary_evidence_cannot_be_relabelled(self):
        for mutation in ('operation','reused_fact','same_claim','missing_premise','fake_source'):
            fx=self.fixture();c,f,ctx,v=fx
            if mutation=='operation':c['assessment']['operation']='action_recognition'
            if mutation=='reused_fact':c['assessment']['roles']['observed_result']=c['assessment']['roles']['conditions']
            if mutation=='same_claim':f[1]['claim']=f[0]['claim']
            if mutation=='missing_premise':c['assessment']['knowledge']['premise_fact_ids']=[]
            if mutation=='fake_source':c['assessment']['knowledge']['rule_source']='expert_verified'
            with self.subTest(mutation=mutation),self.assertRaises(ProtocolError):self.prepare(fx)

    def test_mcq_falsifiers_and_shuffle_identity(self):
        fx=self.fixture(form='mcq',n=6)
        c=self.prepare(fx)
        self.assertEqual({d['option_id'] for d in c['assessment']['distractors']},set('ABCDEF')-{c['answer']})
        fx[0]['assessment']['distractors']=[]
        with self.assertRaises(ProtocolError):self.prepare(fx)

    def test_ordering_is_fact_attributed_and_program_permuted(self):
        for n in (3,4,6):
            c=self.prepare(self.fixture('long_event_order','mcq',n))
            self.assertIn('E1:',c['question'])
            self.assertEqual(len({o['text'] for o in c['options']}),n)
            self.assertEqual({d['option_id'] for d in c['assessment']['distractors']},set('ABCDEF'[:n])-{c['answer']})
        fx=self.fixture('event_order');fx[0].pop('ordering')
        with self.assertRaises(ProtocolError):self.prepare(fx)
        fx=self.fixture('event_order');fx[0]['ordering']['items'][0]['text']='invented event'
        with self.assertRaises(ProtocolError):self.prepare(fx)

    def test_location_uses_program_absolute_windows(self):
        c=self.prepare(self.fixture('segment_retrieval','mcq',6))
        self.assertEqual(len(c['options']),6)
        self.assertTrue(all('00:' in o['text'] for o in c['options']))
        fx=self.fixture('segment_retrieval');fx[0]['answer']='Some time later'
        with self.assertRaises(ProtocolError):self.prepare(fx)

    def test_audit_rejects_missing_or_uncertain_capability(self):
        c=self.prepare(self.fixture())
        self.assertFalse(validate_capability_audit({},c)[0])
        response=dict(capability_checks={k:'pass' for k in CAPABILITY_CHECKS})
        self.assertTrue(validate_capability_audit(response,c)[0])
        for key in ('video_necessity','knowledge_rule_validity','operation_match'):
            bad=deepcopy(response);bad['capability_checks'][key]='insufficient'
            self.assertFalse(validate_capability_audit(bad,c)[0])

    def test_retrieval_audit_can_use_one_window_but_cross_segment_cannot(self):
        for name,expected in (('long_context_retrieval',True),('cross_segment_qa',False)):
            c=self.prepare(self.fixture(name));ctx=dict(candidate=c,duration=60)
            raw=SyntheticProvider().send(dict(role='A7',context=ctx))
            result=json.loads(raw['choices'][0]['message']['content'])
            if not expected:
                # Collapse both supports into the first window, beyond fact 2's own scope.
                for item in result['evidence']:item.update(start=0,end=10)
            self.assertEqual(validate_audit(result,c,dict(duration=60))[0],expected)

    def test_old_settings_remain_legacy_until_explicit_selection(self):
        s=Settings(self.root/'private.json');s.data['recipe'].pop('qa_recipe');s.data['recipe'].pop('knowledge_balance_attempts')
        s.save();before=s.path.read_bytes();loaded=Settings(s.path)
        self.assertEqual(s.path.read_bytes(),before)
        self.assertNotIn('qa_recipe',loaded.data['recipe'])
        loaded.select_recipe('benchmark_v1')
        self.assertEqual(loaded.data['recipe']['knowledge_balance_attempts'],9)
        data=deepcopy(self.cfg.data);data['generation'].pop('knowledge_balance_attempts')
        with self.assertRaises(ConfigError):validate_config(data,allow_synthetic=True)

    def test_scheduler_does_not_pay_for_impossible_location_options(self):
        store=self.opened();scheduler=Scheduler(self.cfg,store)
        scheduler.forms['oe']=100  # force the next feasible choice to be MCQ
        scheduler.options[4]=100;scheduler.options[3]=100  # six would otherwise be preferred
        video=dict(id='plan_video')
        excluded={n for n,t in scheduler.tasks.items() if t['branch']=='long' and n!='segment_retrieval'}
        plan=scheduler.plan(video,'long','balance',0,excluded,set(),windows=[dict(id=str(i)) for i in range(3)])
        self.assertEqual(plan['assigned_slots'][0]['num_options'],3)
        self.assertFalse(store.request_rows())

    def test_caption_gate_reject_stops_all_three_branches(self):
        class RejectGate(SyntheticProvider):
            def send(self,body):
                raw=super().send(body)
                if body['role']=='C_GATE':
                    value=json.loads(raw['choices'][0]['message']['content']);value['decision']='reject'
                    raw['choices'][0]['message']['content']=json.dumps(value)
                return raw
        store=self.opened();p=RejectGate()
        Pipeline(self.cfg,store,media=SyntheticMedia(self.cfg),provider=p).run()
        self.assertEqual(set(b['role'] for b in p.sent),{'A1','A2','C_GATE'})
        self.assertFalse(store.records('candidate'))
        self.assertEqual(completion(store)['status'],'complete')

    def test_knowledge_pre_qa_abstention_has_bounded_text_calls_no_audit(self):
        class AbstainKnowledge(SyntheticProvider):
            def send(self,body):
                raw=super().send(body)
                if body['context'].get('branch')=='knowledge':
                    value=json.loads(raw['choices'][0]['message']['content'])
                    value['candidates']=[]
                    value['abstained_slots']=[dict(slot_id=s['slot_id'],reason_code='task_inapplicable')
                                               for s in body['context']['assigned_slots']]
                    raw['choices'][0]['message']['content']=json.dumps(value)
                return raw
        store=self.opened();p=AbstainKnowledge()
        Pipeline(self.cfg,store,media=SyntheticMedia(self.cfg),provider=p).run()
        calls=[b for b in p.sent if b['context'].get('branch')=='knowledge']
        self.assertEqual(len(calls),14)  # 2 videos * (one fit + six exhausted tasks)
        self.assertFalse(any(b['role']=='A7' and b['context']['candidate']['branch']=='knowledge' for b in p.sent))
        self.assertEqual(candidate_records(store)['knowledge'],[])
        self.assertEqual(completion(store)['status'],'complete')

    def test_full_three_branch_pipeline_export_cost_resume_and_completion(self):
        store=self.opened();p=SyntheticProvider();pipeline=Pipeline(self.cfg,store,media=SyntheticMedia(self.cfg),provider=p)
        pipeline.run()
        self.assertEqual(Counter(b['role'] for b in p.sent),dict(A1=9,A2=3,C_GATE=2,A3=16,A5=6,A7=26))
        rows=candidate_records(store)
        self.assertEqual({k:len(v) for k,v in rows.items()},dict(general=10,long=6,knowledge=10))
        for values in rows.values():
            for row in values:self.assertEqual(set(row),FINAL_FIELDS);self.assertIsNone(row['cot'])
        dest=export_candidates(store);root,summary=report(store)
        costs=summary['abilities']['cost_by_branch']
        self.assertEqual({k:v['requests'] for k,v in costs.items()},dict(shared_caption=14,general=18,long=12,knowledge=18,unattributed=0))
        self.assertEqual(sum((Decimal(v['actual_cost']) for v in costs.values()),Decimal(0)),Decimal(summary['actual_cost']))
        self.assertEqual(completion(store)['status'],'complete')
        pipeline.run();self.assertEqual(len(p.sent),62)
        self.assertEqual(export_candidates(store),dest);self.assertEqual(report(store)[0],root)
        sidecar=dest/'ability_evidence.jsonl';self.assertEqual(len(sidecar.read_text(encoding='utf8').splitlines()),26)
        sidecar.write_text('tampered\n')
        with self.assertRaises(PipelineError):export_candidates(store)
        store.db.execute("DELETE FROM events WHERE stage='branch' AND entity_id LIKE '%:knowledge'");store.db.commit()
        self.assertEqual(completion(store)['status'],'incomplete')

    def test_knowledge_quality_rejection_never_refills(self):
        class RejectKnowledge(SyntheticProvider):
            def send(self,body):
                raw=super().send(body)
                if body['role']=='A7' and body['context']['candidate']['branch']=='knowledge':
                    value=json.loads(raw['choices'][0]['message']['content']);value['capability_checks']['knowledge_rule_validity']='insufficient'
                    raw['choices'][0]['message']['content']=json.dumps(value)
                return raw
        store=self.opened();p=RejectKnowledge()
        Pipeline(self.cfg,store,media=SyntheticMedia(self.cfg),provider=p).run()
        self.assertEqual(len(p.sent),62);self.assertEqual(candidate_records(store)['knowledge'],[])
        self.assertEqual(len([r for r in store.records('candidate') if r['payload']['branch']=='knowledge']),10)


if __name__=='__main__':unittest.main()
