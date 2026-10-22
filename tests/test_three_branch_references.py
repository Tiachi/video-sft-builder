import importlib.util
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'scripts/benchmarks/build_three_branch_references.py'
SPEC = importlib.util.spec_from_file_location('three_branch_references', SOURCE)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class ReferenceExtractionTests(unittest.TestCase):
    def test_options_keep_original_count_and_decode_answer(self):
        r = m.row('general', 'synthetic', 'visual', 'q1', 'What color?',
                  'A. Red\nB. Blue\nC. Green\nD. Gray\nE. White', 'E', 'fixture', 0, 'v1')
        self.assertEqual(len(r['options']), 5)
        self.assertEqual(r['answer_text'], 'White')
        self.assertEqual(m.options_map(['A. First', 'B. Second']), {'A':'First','B':'Second'})
        with self.assertRaisesRegex(ValueError, 'answer_missing'):
            m.row('general','synthetic','x','q','q',['red','blue'],'C','fixture',0,'v')

    def test_oe_empty_choice_placeholders_are_not_mcq(self):
        r=m.row('knowledge','MMVU','synthetic','q','What process?',
                {'A':'','B':'','C':'','D':'','E':''},'convection','fixture',0,'v')
        self.assertEqual(r['options'], {})
        self.assertEqual(r['answer_text'],'convection')

    def test_query_images_counting_and_exact_time_are_deferred(self):
        base=m.row('knowledge','Video-MMMU','Concept Comprehension','q',
                   'Which process?', ['red','blue'],'A','fixture',0,'v')
        self.assertIn('external_query_image',m.static_flags(dict(base,query_image_present=True)))
        self.assertIn('counting',m.static_flags(dict(base,question='How many birds appear?')))
        self.assertIn('exact_time_or_score_answer',m.static_flags(dict(base,answer_text='12:23')))
        self.assertEqual(m.category_policy('Video-MMMU','Case Study Analysis')[0],'deferred')
        self.assertEqual(m.category_policy('Video-MME-long','Counting Problem')[0],'deferred')

    def test_audio_distractor_does_not_exclude_visual_answer(self):
        r=m.row('general','synthetic','x','q','What does the person hold?',
                ['a red ball','a music player'],'A','fixture',0,'v')
        self.assertNotIn('audio_dialogue',m.static_flags(r))

    def test_payload_table_preserves_text_and_escapes_markdown(self):
        r=m.row('general','synthetic','x','q','Which <item>|?',
                ['left','right'],'B','fixture',0,'v')
        table=m.qa_table([r])
        self.assertIn('&lt;item&gt;&#124;',table)
        self.assertIn('B. right',table)
        self.assertEqual(r['question'],'Which <item>|?')

    def test_caption_friendly_visuals_are_prioritized_but_not_verified(self):
        base=m.row('general','synthetic','x','q','What happens?',None,'blue','fixture',0,'v')
        visual=dict(base,question='What color clothing does the person wear on the left?')
        news=dict(base,question='What is the financial policy of the government?')
        self.assertLess(m.rank(visual),m.rank(news))

    def test_same_video_mme_source_is_identical_across_branch_alias(self):
        base=m.row('general','Video-MME','x','q','What color?',
                   ['red','blue'],'A','Video-MME/fixture',0,'v')
        alias=dict(base,branch='long',dataset='Video-MME-long')
        self.assertEqual(m.identity(base),m.identity(alias))
        other=dict(base,source_file='another/fixture')
        self.assertNotEqual(m.identity(base),m.identity(other))

    def test_short_groups_never_borrow_pad_or_duplicate_questions(self):
        rows=[]
        for i in range(96):
            rows.append(m.row('general','synthetic',f'category_{i}','q',
                              'What color is the ball?', ['red','blue'],'A','fixture',i,'v'))
        rows.append(dict(rows[0]))
        summary,selected,_=m.select(rows)
        self.assertEqual(len(summary),96)
        self.assertEqual(len(selected),96)
        self.assertTrue(all(r['selected_count']==1 and r['shortage']==9 for r in summary))

    def test_export_refuses_code_checkout_and_input_overlap_before_io(self):
        with self.assertRaisesRegex(ValueError,'outside_code_checkout'):
            m.export(Path('missing-input'),m.CODE_ROOT/'exports')
        with self.assertRaisesRegex(ValueError,'overlap_immutable_inputs'):
            root=m.CODE_ROOT.parent/'missing-input'
            m.export(root,root/'derived')


if __name__=='__main__':
    unittest.main()
