"""Read-only diagnostics do not execute or reclassify an unresolved request."""
from contextlib import redirect_stdout
from decimal import Decimal
import importlib.util
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from video_sft_builder.builds import create_build,load_build
from video_sft_builder.settings import Settings
from video_sft_builder.state import Store
from video_sft_builder.util import canonical,digest

spec=importlib.util.spec_from_file_location('run_failure_inspector',ROOT/'scripts/inspect_run_failure.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)


class FailureInspectionTests(unittest.TestCase):
    def setUp(self):
        base=ROOT.parent/'run-failure-tests';base.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.settings=Settings(self.root/'private.json')
        self.settings.data['output_dir']=str(self.root/'builds')
        self.settings.data['models']['qwen3.8-flash']['api_key']='FAKE_PRIVATE_KEY_NEVER_PRINT'
        self.settings.save()
        self.build=create_build(self.settings,'inspection',synthetic=True)
        _,_,self.cfg=load_build(self.build)
        with self.opened() as store:
            store.reserve('request_1','video_1','A7',Decimal('1.2'));store.sent('request_1')
            store.put('request_view:request_1','request_view','video_1',
                      dict(branch='general',unit_id='candidate_1',media=[dict(type='video',path='/private/input.mp4')]))
            store.put('gate','caption_gate','video_1',dict(decision='pass',reason='caption_gate_no_major_mismatch',
                                                        policy='major_visual_mismatch_only_v1',response={'secret':'DO_NOT_PRINT_GATE_PAYLOAD'}))
            store.fail('request_1','UnknownExecution',uncertain=True)

    def opened(self):
        from contextlib import closing
        return closing(Store(self.cfg))

    def test_read_only_redaction_and_unchanged_runtime_fingerprint(self):
        db=self.cfg.state_dir/'state.sqlite3'
        files={p:p.read_bytes() for p in (db,self.build/'runtime.json',self.settings.path)}
        fingerprint=self.cfg.fingerprint
        before=set(self.build.rglob('*'))
        result=helper.inspect(self.build)
        text=json.dumps(result)
        for secret in ('FAKE_PRIVATE_KEY_NEVER_PRINT','DO_NOT_PRINT_GATE_PAYLOAD','/private/input.mp4'):
            self.assertNotIn(secret,text)
        self.assertEqual(result['current_runtime_assets']['status'],'match')
        self.assertEqual(result['unresolved'][0]['status'],'unknown_execution')
        self.assertEqual(result['unresolved'][0]['provider']['role'],'A7')
        self.assertEqual(result['total_requests'],1)
        self.assertEqual(result['network_requests'],0)
        self.assertEqual(result['files_written'],0)
        for p,data in files.items():self.assertEqual(p.read_bytes(),data)
        self.assertEqual(set(self.build.rglob('*')),before)
        _,_,loaded=load_build(self.build)
        self.assertEqual(loaded.fingerprint,fingerprint)

    def test_display_limit_is_explicit_and_preserves_unresolved_states(self):
        with self.opened() as store:
            store.reserve('request_2','video_1','A7',Decimal('1'));store.sent('request_2');store.fail('request_2','PipelineError')
        value=helper.inspect(self.build,max_requests=1)
        self.assertEqual((value['displayed_requests'],value['omitted_requests'],value['unresolved_requests']),(1,1,2))
        self.assertEqual(value['unresolved'][0]['interpretation'],
                         'network_failure_wrapped_original_transport_details_not_saved')

    def test_identity_drift_is_reported_not_patched(self):
        identity=self.build/'code_and_asset_identity.json'
        value=json.loads(identity.read_text());value['code']['quality.py']='0'*64
        identity.write_text(json.dumps(value));before=identity.read_bytes()
        result=helper.inspect(self.build)
        self.assertEqual(result['current_runtime_assets']['status'],'mismatch')
        self.assertIn('quality.py',result['current_runtime_assets']['differences'])
        self.assertEqual(identity.read_bytes(),before)

    def test_missing_db_does_not_create_state_or_read_private_config(self):
        missing=self.root/'missing';missing.mkdir()
        cfg=json.loads((self.build/'runtime.json').read_text())
        cfg['run'].update(id='missing',output_root=str(self.root),state_root=str(missing/'state'))
        (missing/'runtime.json').write_text(json.dumps(cfg))
        with self.assertRaises(ValueError):helper.inspect(missing)
        self.assertFalse((missing/'state').exists())

    def test_endpoint_credentials_and_query_are_never_displayed(self):
        file=self.build/'runtime.json';cfg=json.loads(file.read_text())
        for provider in cfg['execution']['providers'].values():
            provider['base_url']='https://FAKE_USER:FAKE_PASS@example.invalid/SECRET_PATH?token=FAKE_QUERY'
        file.write_text(json.dumps(cfg))
        text=json.dumps(helper.inspect(self.build))
        self.assertIn('example.invalid',text)
        for value in ('FAKE_USER','FAKE_PASS','SECRET_PATH','FAKE_QUERY'):self.assertNotIn(value,text)

    def test_safe_cli_and_unsafe_saved_identity_paths(self):
        with self.assertRaises(ValueError):helper._git_blob(None,'prompts/benchmark/audit.en.txt')
        stream=io.StringIO()
        with redirect_stdout(stream):self.assertEqual(helper.main(['--build',str(self.build)]),0)
        self.assertIn('PASS: read-only inspection',stream.getvalue())
        file=self.build/'code_and_asset_identity.json';value=json.loads(file.read_text())
        value['assets']['../private.json']='0'*64;file.write_text(json.dumps(value))
        with self.assertRaises(ValueError):helper.inspect(self.build)

    def test_old_audit_prerequisite_is_verified_against_saved_message_hashes(self):
        old=b'Return exactly {decision,checks,evidence}. No extra text.'
        candidate=dict(id='candidate_1',question='PRIVATE_QUESTION_NOT_PRINTED',answer='example')
        context=dict(video_id='video_1',duration=60,time_basis='original_video_zero_normalized_pts',candidate=candidate)
        identity=self.build/'code_and_asset_identity.json'
        saved=json.loads(identity.read_text());saved['assets']['prompts/benchmark/audit.en.txt']=hashlib.sha256(old).hexdigest()
        identity.write_text(json.dumps(saved))
        with self.opened() as store:
            store.put('candidate:candidate_1','candidate','video_1',candidate)
            store.put('video:video_1','video','video_1',dict(id='video_1',duration=60))
            view=dict(unit_id='candidate_1',branch='general',media=[],system_hash=digest(old.decode()),context_hash=digest(context))
            store.db.execute('UPDATE records SET payload=? WHERE key=?',(canonical(view),'request_view:request_1'));store.db.commit()
        before=(self.cfg.state_dir/'state.sqlite3').read_bytes()
        with patch.object(helper,'_git_blob',return_value=old):result=helper.inspect(self.build)
        check=result['unresolved'][0]['json_mode_check']
        self.assertEqual(check['status'],'verified');self.assertTrue(check['violates_json_object_prerequisite'])
        self.assertEqual(check['prompt_source'],'saved_git_revision')
        self.assertNotIn('PRIVATE_QUESTION',json.dumps(result))
        self.assertEqual((self.cfg.state_dir/'state.sqlite3').read_bytes(),before)
        with self.opened() as store:
            changed={**view,'context_hash':'0'*64}
            store.db.execute('UPDATE records SET payload=? WHERE key=?',(canonical(changed),'request_view:request_1'));store.db.commit()
        with patch.object(helper,'_git_blob',return_value=old):bad=helper.inspect(self.build)['unresolved'][0]['json_mode_check']
        self.assertEqual(bad['status'],'message_hash_mismatch');self.assertIsNone(bad['violates_json_object_prerequisite'])

    def test_local_rejection_only_exposes_owned_error_literals(self):
        with self.opened() as store:
            store.put('reject_1','local_reject','video_1',dict(branch='general',error_class='ProtocolError',
                      error_code='Candidate fields mismatch',raw=dict(task='entity_attribute',question='PRIVATE_QA')))
            store.put('request_failure:request_1','request_failure','video_1',dict(http_status=429,exception_class='PipelineError'))
        result=helper.inspect(self.build)
        self.assertEqual(result['local_rejections'][0]['reason'],'Candidate fields mismatch')
        self.assertEqual(result['unresolved'][0]['http_status'],429)
        self.assertEqual(result['unresolved'][0]['interpretation'],'http_error_recorded_execution_and_billing_still_unknown')
        self.assertNotIn('PRIVATE_QA',json.dumps(result))
        self.assertEqual(helper.validation_reason('FAKE_SECRET_PROVIDER_MESSAGE'),'nonliteral_error_detail_redacted')


if __name__=='__main__':unittest.main()
