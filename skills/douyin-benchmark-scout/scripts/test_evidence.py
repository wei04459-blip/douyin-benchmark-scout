"""Regression checks for false completion; fixtures never touch production data."""
import copy
import json
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import verify_evidence as v

class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.video=self.root/'video.mp4'; self.video.write_bytes(b'fixture')
        self.txt=self.root/'speech.txt'; self.txt.write_text('今天演示一个真实操作。结果需要自己验证。')
        self.txt.with_suffix('.json').write_text(json.dumps({'segments':[{'start':0,'end':2,'text':self.txt.read_text()}]}))
        self.manifest=self.root/'manifest.json'
        self.manifest.write_text(json.dumps({'items':[{'aweme_id':'123','video_path':str(self.video),'transcript_path':str(self.txt)}]}))
        self.analysis=self.root/'analysis.json'
        self.data={'items':{'123':{f:'测试说明' for f in v.FIELDS}}}
        self.data['items']['123']['evidence_review']={
            'reviewer':'test fixture','reviewed_at':'2026-09-07T00:00:00Z','quality_notes':'Synthetic fixture only',
            'media_sha256':v.digest(self.video),'transcript_sha256':v.digest(self.txt),
            **{x:True for x in ['transcript_checked','identity_checked','full_content_checked','claims_checked']},
            'references':[{'field':f,'quote':'今天演示一个真实操作','start':0,'end':2} for f in v.GROUNDED_FIELDS]}
        self.media_patch=patch.object(v,'check_media',return_value=(None,v.digest(self.video)));self.media_patch.start()
    def tearDown(self):
        self.media_patch.stop();self.tmp.cleanup()
    def check(self):
        self.analysis.write_text(json.dumps(self.data));return v.audit(self.manifest,self.analysis)
    def test_short_reviewed_speech_passes(self):
        self.assertTrue(self.check()['ready'])
    def test_credit_only_fails(self):
        self.txt.write_text('字幕by索兰娅')
        self.data['items']['123']['evidence_review']['transcript_sha256']=v.digest(self.txt)
        result=self.check();self.assertFalse(result['ready'])
        self.assertTrue(any('署名' in e for e in result['items'][0]['errors']))
    def test_empty_and_missing_transcript_fail(self):
        self.txt.write_text('');self.assertFalse(self.check()['ready'])
        self.txt.unlink();self.assertFalse(self.check()['ready'])
    def test_missing_media_fails(self):
        self.video.unlink();self.assertFalse(self.check()['ready'])
    def test_stale_review_and_invented_quote_fail(self):
        original=copy.deepcopy(self.data)
        self.data['items']['123']['evidence_review']['transcript_sha256']='stale'
        self.assertFalse(self.check()['ready']);self.data=original
        self.data['items']['123']['evidence_review']['references'][0]['quote']='不存在的原话'
        self.assertFalse(self.check()['ready'])
    def test_wrong_timestamp_fails(self):
        self.data['items']['123']['evidence_review']['references'][0].update(start=10,end=20)
        self.assertFalse(self.check()['ready'])
    def test_legacy_and_skipped_media_fail(self):
        self.check();self.assertFalse(v.audit(self.manifest,self.analysis,False)['ready'])
        del self.data['items']['123']['evidence_review'];self.assertFalse(self.check()['ready'])
    def test_empty_and_duplicate_batches_fail(self):
        self.manifest.write_text('{"items": []}');self.assertFalse(self.check()['ready'])
        self.manifest.write_text(json.dumps({'items':[{'aweme_id':'123'},{'aweme_id':'123'}]}))
        self.assertFalse(self.check()['ready'])
    def test_failure_preserves_media_and_state(self):
        import run
        self.data['items']['123'].pop('evidence_review');self.check()
        (self.root/'待分析数据.json').write_bytes(self.manifest.read_bytes())
        state=self.root/'state.json';state.write_text('{"keyword_cursor": 2}');original=state.read_bytes()
        from types import SimpleNamespace
        args=SimpleNamespace(run=self.root,analysis=self.analysis,input_workbook=None)
        config={'paths':{'workbook_python':sys.executable,'workbook_template':''},'cleanup':{'delete_video_after_analysis_and_excel':True}}
        with patch.object(run,'STATE_PATH',state):
            with self.assertRaises(RuntimeError):run.finalize(args,config)
        self.assertEqual(state.read_bytes(),original);self.assertTrue(self.video.exists())
        self.assertEqual(list(self.root.glob('*.xlsx')),[])
        self.assertFalse((self.root/'批次状态.json').exists())
    def test_cleanup_is_disabled(self):
        import run
        with self.assertRaises(RuntimeError):run.delete_processed_videos(self.manifest,self.analysis,self.root/'book.xlsx')
        self.assertTrue(self.video.exists())

    def test_real_decoder_and_successful_finalize(self):
        self.media_patch.stop()
        ffmpeg=v.ffmpeg_path()
        self.assertTrue(ffmpeg, 'Install FFmpeg before running integration checks')
        subprocess.run([ffmpeg,'-nostdin','-v','error','-f','lavfi','-i','color=c=black:s=64x64:r=5',
                        '-f','lavfi','-i','sine=frequency=440:sample_rate=16000','-t','2',
                        '-c:v','mpeg4','-c:a','aac','-threads','1','-y',str(self.video)],check=True)
        self.data['items']['123']['evidence_review']['media_sha256']=v.digest(self.video)
        self.assertTrue(self.check()['ready'])
        import run
        from types import SimpleNamespace
        from openpyxl import load_workbook
        (self.root/'待分析数据.json').write_bytes(self.manifest.read_bytes())
        (self.root/'批次状态.json').write_text('{"status":"awaiting_analysis","next_keyword_cursor":6}')
        state=self.root/'state.json';state.write_text('{"keyword_cursor":2}')
        args=SimpleNamespace(run=self.root,analysis=self.analysis,input_workbook=None)
        config={'paths':{'workbook_python':sys.executable,'workbook_template':''},'cleanup':{'delete_video_after_analysis_and_excel':True}}
        with patch.object(run,'STATE_PATH',state):run.finalize(args,config)
        self.assertTrue(self.video.exists())
        self.assertEqual(json.loads(state.read_text())['keyword_cursor'],6)
        self.assertIn('123',json.loads(state.read_text())['processed_aweme_ids'])
        status=json.loads((self.root/'批次状态.json').read_text())
        self.assertEqual(status['media_retention'],'retained')
        book=load_workbook(next(self.root.glob('*.xlsx')))
        self.assertEqual(book['竞品选题分析']['Z2'].value,'已完成材料审核，原视频保留')
        # A truncated media copy must fail even when the old review was valid.
        self.video.write_bytes(self.video.read_bytes()[:100])
        self.assertFalse(self.check()['ready'])

if __name__=='__main__':unittest.main()
