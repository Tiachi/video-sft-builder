import importlib.util
from pathlib import Path
import tempfile
import unittest

source=Path(__file__).resolve().parents[1]/'scripts/benchmarks/nonvideo_local.py'
spec=importlib.util.spec_from_file_location('nonvideo_local',source)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class NonVideoLocalTests(unittest.TestCase):
    def test_limit_is_whole_batch_decimal_gb(self):
        self.assertEqual(m.bounded_total([{'size':m.CAP}]),m.CAP)
        with self.assertRaisesRegex(ValueError,'exceeds_1GB'):
            m.bounded_total([{'size':600_000_000},{'size':500_000_000}])

    def test_unknown_size_is_not_permission_to_download(self):
        with self.assertRaises(ValueError):m.bounded_total([{'size':None}])

    def test_only_reviewed_subtitle_archives_are_nonvideo(self):
        self.assertEqual(m.classify('Video-MME','subtitle.zip'),'nonvideo')
        self.assertEqual(m.classify('Video-MME','videos_chunked_01.zip'),'video')
        self.assertEqual(m.classify('Video-MMMU','Art.zip'),'video')
        with self.assertRaises(ValueError):m.classify('Video-MMMU','unknown.zip')

    def test_video_extensions_and_unsafe_paths(self):
        self.assertEqual(m.classify('Video-MME-v2','assets/demo.mp4'),'video')
        for p in ('../secret.txt','/absolute.txt','C:/secret.txt'):
            with self.assertRaises(ValueError):m.classify('LVBench',p)

    def test_git_blob_verification_and_preserve_conflict(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);src=root/'source';src.write_bytes(b'abc')
            item={'size':3,'blob_id':m.hashlib.sha1(b'blob 3\0abc').hexdigest()}
            out=root/'output'
            m.publish_copy(src,out,item)
            self.assertTrue(m.verified(out,item))
            out.write_bytes(b'xyz')
            with self.assertRaisesRegex(ValueError,'conflict'):m.publish_copy(src,out,item)
            self.assertEqual(out.read_bytes(),b'xyz')


if __name__=='__main__':unittest.main()
