"""Offline JSON Object API prerequisites and safe failure observability."""
from contextlib import closing
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from video_sft_builder.errors import PipelineError,ProtocolError,UnknownExecution
from video_sft_builder.provider import ModelGateway
from video_sft_builder.state import Store
from video_sft_builder.synthetic import SyntheticProvider,demo_config
from video_sft_builder.util import asset


class TextProvider(SyntheticProvider):
    def send(self,body):
        self.sent.append(body)
        return dict(choices=[dict(finish_reason='stop',message=dict(content='{}'))],
                    usage=dict(prompt_tokens=100,completion_tokens=10))


class JSONContractTests(unittest.TestCase):
    def setUp(self):
        base=ROOT.parent/'json-contract-tests';base.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup)
        self.cfg=demo_config(Path(self.temp.name))
        self.store=Store(self.cfg);self.addCleanup(self.store.close)
        self.video=dict(id='synthetic_video',source='synthetic')

    def test_all_runtime_system_prompts_explicitly_request_json(self):
        names=['prompts/runtime/'+n+'.txt' for n in ('caption','caption_gate','audit')]
        names+=['prompts/task_scheduler/generation.system.'+lang+'.txt' for lang in ('en','zh')]
        names+=['prompts/benchmark/'+n+'.txt' for n in ('generation.system.en','generation.system.zh','audit.en','audit.zh')]
        for name in names:
            with self.subTest(asset=name):self.assertIn('json',asset(name).read_text(encoding='utf8').casefold())

    def test_missing_keyword_fails_before_reservation_or_provider_send(self):
        p=TextProvider();gateway=ModelGateway(self.cfg,self.store,p)
        with self.assertRaisesRegex(ProtocolError,'no request sent'):
            gateway.call('A3','missing',self.video,'Return exactly {decision,checks}.',{})
        self.assertEqual(p.sent,[]);self.assertEqual(self.store.request_rows(),[])

    def test_repaired_audit_and_explicit_user_json_satisfy_contract(self):
        p=TextProvider();gateway=ModelGateway(self.cfg,self.store,p)
        system=asset('prompts/benchmark/audit.en.txt').read_text(encoding='utf8')
        gateway.call('A3','repaired',self.video,system,{})
        gateway.call('A3','user_keyword',self.video,'Return an object.',dict(format='JSON'))
        self.assertEqual(len(p.sent),2)

    def test_http_status_saved_without_releasing_unknown_request_or_retrying(self):
        class Reject(TextProvider):
            def send(self,body):
                self.sent.append(body);raise PipelineError('HTTP service returned status 400')
        p=Reject();gateway=ModelGateway(self.cfg,self.store,p)
        with self.assertRaisesRegex(UnknownExecution,'HTTP 400'):
            gateway.call('A3','http_error',self.video,'Return JSON.',{})
        row=self.store.request_rows()[0]
        self.assertEqual((row['status'],row['actual']),('unknown_execution',None))
        self.assertEqual(self.store.get('request_failure:'+row['id']),dict(exception_class='PipelineError',http_status=400))
        with self.assertRaises(UnknownExecution):gateway.call('A3','http_error',self.video,'Return JSON.',{})
        self.assertEqual(len(p.sent),1)

    def test_arbitrary_exception_message_is_not_recorded_or_displayed(self):
        class Reject(TextProvider):
            def send(self,body):raise PipelineError('FAKE_SECRET_ERROR_WITH_PRIVATE_URL')
        gateway=ModelGateway(self.cfg,self.store,Reject())
        with self.assertRaises(UnknownExecution) as caught:gateway.call('A3','private_error',self.video,'Return JSON.',{})
        self.assertNotIn('FAKE_SECRET',str(caught.exception))
        row=self.store.request_rows()[0]
        self.assertEqual(self.store.get('request_failure:'+row['id']),dict(exception_class='PipelineError'))


if __name__=='__main__':unittest.main()
