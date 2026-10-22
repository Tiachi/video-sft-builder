"""Offline boundary tests. No benchmark payloads or network calls."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import types

_path=Path(__file__).resolve().parents[1]/'scripts/benchmarks/benchmark_assets.py'
_spec=importlib.util.spec_from_file_location('benchmark_assets',_path)
m=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


class BenchmarkAssetsTests(unittest.TestCase):
    def test_lvbench_counts_questions_and_multilabel_assignments(self):
        r=m.summarize('lvbench',[{'qa':[{'question_type':['reasoning','entity recognition']},{'question_type':['reasoning']}]}])
        self.assertEqual(r['questions'],2)
        self.assertEqual(r['label_assignments'],3)

    def test_motion_hidden_answers_are_not_scored(self):
        r=m.summarize('motionbench',[{'question_type':'Action Order','qa':[{'answer':'A'},{'answer':'NA'}]}])
        self.assertEqual(r['questions'],2)
        self.assertEqual(r['labeled_questions'],1)

    def test_unsafe_remote_paths_fail(self):
        for p in ('../secret','/absolute','C:/secret','a\\b'):
            with self.assertRaises(ValueError):m.safe_relative(p)

    def test_partial_long_annotation_never_skips_all_archives(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'val.json';p.write_text('[{"video_path":"a.mp4"}]')
            (Path(d)/'a.mp4').write_bytes(b'video')
            spec={'kind':'longvideobench','media_roots':[d],'minimum_references':3763}
            ok,detail=m.all_references_present(spec,[p])
            self.assertFalse(ok)
            self.assertEqual(detail['missing'],0)

    def test_zero_byte_reference_is_missing(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'rows.json';p.write_text('[{"videoID":"a"}]')
            (Path(d)/'a.mp4').touch()
            ok,_=m.all_references_present({'kind':'videomme','media_roots':[d],'minimum_references':1},[p])
            self.assertFalse(ok)

    def test_exact_reuse_requires_size(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'a.mp4').write_bytes(b'abc')
            self.assertIsNotNone(m.exact_existing('MotionBench/a.mp4',3,[d]))
            self.assertIsNone(m.exact_existing('MotionBench/a.mp4',4,[d]))

    def test_mmvu_subject_and_question_form_are_separate_axes(self):
        r=m.summarize('mmvu',[{'metadata':{'subject':'Art'},'question_type':'open-ended'}])
        self.assertEqual(r['category_axes']['subject'],{'Art':1})
        self.assertEqual(r['category_axes']['question_type'],{'open-ended':1})

    def test_mirror_never_receives_hf_token_and_gated_is_blocked(self):
        api=Mock()
        api.dataset_info.side_effect=[OSError('official unreachable'),types.SimpleNamespace(gated='auto')]
        fake=types.SimpleNamespace(HfApi=Mock(return_value=api),hf_hub_download=Mock(),get_token=lambda:'SYNTHETIC_PRIVATE_TOKEN')
        spec={'repo':'example/data','revision':'abc'}
        with patch.dict('sys.modules',{'huggingface_hub':fake}):
            with self.assertRaisesRegex(RuntimeError,'gated_requires_authorized_official_hf_connection'):
                m.download_dataset(spec,Path('unused'),{})
        self.assertEqual(api.dataset_info.call_args_list[0].kwargs['token'],'SYNTHETIC_PRIVATE_TOKEN')
        self.assertIs(api.dataset_info.call_args_list[1].kwargs['token'],False)
        fake.hf_hub_download.assert_not_called()

    def test_hidden_answers_do_not_change_question_count(self):
        r=m.summarize('longvideobench',[{'correct_choice':'@','question_category':'S2E'}])
        self.assertEqual(r['questions'],1)
        self.assertEqual(r['category_axes']['question_category'],{'S2E':1})


if __name__=='__main__':unittest.main()
