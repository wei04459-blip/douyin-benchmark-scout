import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import material_queue as q
from installed_downloader import normalize, ProviderError

class QueueTests(unittest.TestCase):
    def test_shell_and_challenge_not_success(self):
        for html, code in [('<script>window._ROUTER_DATA={"loaderData":{"video_layout":null,"video_(id)/page":{"itemId":"1234567890123"}}}</script>','metadata_unavailable'),
                           ('<script>byted_acrawler.sign()</script>','access_restricted')]:
            with self.assertRaises(q.MaterialError) as c:q.parse_public_page(html,'1234567890123')
            self.assertEqual(c.exception.code,code)

    def test_identity_and_missing_duration_rejected(self):
        for payload,code in [({},'missing_video_data'),
                ({'aweme_detail':{'aweme_id':'999'}},'identity_mismatch'),
                ({'aweme_detail':{'aweme_id':'1234567890123','video':{}}},'incomplete_video_metadata')]:
            with self.assertRaises(ProviderError) as c:normalize(payload,'1234567890123')
            self.assertEqual(c.exception.code,code)

    def test_nullable_metrics_are_not_zero(self):
        v=normalize({'aweme_detail':{'aweme_id':'1234567890123','video':{'duration':180000,'play_addr':{'url_list':['https://example.com/video']}}}},'1234567890123')
        self.assertIsNone(v['metrics']);self.assertEqual(v['source_duration_seconds'],180)

    def test_failure_survives_restart_and_duplicate_add(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source={'local_video':str(root/'missing.mp4')}
            q.enqueue(root,source);q.enqueue(root,source)
            first=q.prepare(root,'unused',Path('/missing'))
            self.assertEqual(len(first['jobs']),1)
            self.assertEqual(first['jobs'][0]['error']['code'],'local_file_missing')
            q.prepare(root,'unused',Path('/missing'))
            self.assertEqual(len(q.read(root/'材料队列.json')['jobs'][0]['attempts']),1)

    def test_failed_job_does_not_block_other_jobs_and_resume_reuses_media(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);video=root/'source.mp4';video.write_bytes(b'fixture-media')
            q.enqueue(root,{'local_video':str(root/'missing')})
            q.enqueue(root,{'local_video':str(video),'source_duration_seconds':10})
            calls=[]
            def transcribe(media,out,cache):
                calls.append(str(media))
                out.mkdir()
                (out/'transcript.txt').write_text('真实的测试口播文字')
                q.save(out/'transcript.json',{'media_sha256':q.digest(video),'segments':[{'start':0,'end':10,'text':'真实的测试口播文字'}]})
                return {"transcript":str(out/"transcript.txt"),"incomplete_chunks":[]}
            class Worker:
                def __init__(self,*args):pass
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def transcribe(self,media,out,cache):return transcribe(media,out,cache)
            with patch.object(q,'TranscriptionWorker',Worker),patch.object(q,'check_media' ,side_effect=lambda p,f:(None,q.digest(p))),patch.object(q,'probe_duration',return_value=10):
                result=q.prepare(root,'unused',Path('/model'))
                self.assertEqual([j['status'] for j in result['jobs']],['failed','pending_review'])
                q.prepare(root,'unused',Path('/model'))
                self.assertEqual(len(calls),1)
                job=result['jobs'][1];original_media=job['artifacts']['video_path']
                Path(job['artifacts']['transcript_path']).write_text('tampered')
                result=q.prepare(root,'unused',Path('/model'))
                self.assertEqual(result['jobs'][1]['error']['code'],'artifact_changed')
                result=q.prepare(root,'unused',Path('/model'),True)
                self.assertEqual(result['jobs'][1]['status'],'pending_review')
                self.assertEqual(result['jobs'][1]['artifacts']['video_path'],original_media)
                self.assertEqual(len(calls),2)

    def test_lock_prevents_duplicate_workers(self):
        with tempfile.TemporaryDirectory() as d:
            with q.locked(Path(d)):
                with self.assertRaises(q.MaterialError):
                    with q.locked(Path(d)):pass

if __name__=='__main__':unittest.main()
