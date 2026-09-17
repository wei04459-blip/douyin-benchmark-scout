import copy,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import research_batch as r
class BatchTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'run';r.initialize(self.root,['AI认知','AI搞钱'],'测试观察')
  self.obs={'keyword':'AI认知','query':'AI认知','observed_at':'2026-09-07','channel':'computer_use','page_url':'https://www.douyin.com/search/AI认知','evidence_text':'为你找到以下结果，测试视频','page_loaded':True,'query_confirmed':True,'cards':[{'title':'测试视频'}]}
 def tearDown(self):self.tmp.cleanup()
 def test_empty_payload_is_unknown(self):
  self.obs['cards']=[];self.assertEqual(r.classify_observation(self.obs),'retrieval_unverified')
 def test_explicit_empty_only_exact_query(self):
  self.obs.update(cards=[],evidence_text='暂无搜索结果',empty_marker='暂无搜索结果');self.assertEqual(r.classify_observation(self.obs),'confirmed_empty')
  self.obs['query']='AI';self.assertEqual(r.classify_observation(self.obs),'retrieval_unverified')
 def test_stale_and_restricted(self):
  self.obs['query_confirmed']=False;self.assertEqual(r.classify_observation(self.obs),'retrieval_unverified')
  self.obs['restriction']='需要验证';self.assertEqual(r.classify_observation(self.obs),'access_restricted')
 def test_id_cannot_be_inferred(self):
  self.obs['cards'][0]['aweme_id']='7612585746977165809'
  with self.assertRaises(ValueError):r.record_search(self.root,self.obs)
  self.assertEqual(r.read(self.root/'batch.json')['searches'],[])
 def test_failure_does_not_poison_other_keyword(self):
  failed=copy.deepcopy(self.obs);failed['error']='timeout';r.record_search(self.root,failed);r.record_search(self.root,self.obs)
  b=r.read(self.root/'batch.json');s=r.search_summary(b)
  self.assertEqual(len(b['searches']),2);self.assertEqual(s[0]['status'],'results_observed');self.assertEqual(s[1]['status'],'not_attempted')
 def test_synonym_not_exact_completion(self):
  self.obs['query']='人工智能认知';r.record_search(self.root,self.obs);self.assertEqual(r.search_summary(r.read(self.root/'batch.json'))[0]['status'],'exact_query_pending')
 def test_short_transfer_not_promoted(self):
  class Response(io.BytesIO):headers={'Content-Length':'999'}
  target=self.root/'video.mp4'
  with self.assertRaises(ValueError):r.acquire('https://example.com/video',target,opener=lambda *a,**k:Response(b'abc'))
  self.assertFalse(target.exists());self.assertFalse(target.with_suffix('.part').exists())
 def test_decodable_short_clip_rejected(self):
  class Response(io.BytesIO):headers={'Content-Length':'3'}
  target=self.root/'new.mp4';old=self.root/'old.mp4';old.write_bytes(b'old')
  with patch.object(r,'check_media',return_value=(None,'sha')),patch.object(r,'probe_duration',return_value=12):
   with self.assertRaises(ValueError):r.acquire('https://example.com/video',target,173,opener=lambda *a,**k:Response(b'abc'))
  self.assertFalse(target.exists());self.assertEqual(old.read_bytes(),b'old')
 def test_asr_must_bind_media(self):
  aid='7612585746977165809';r.select_item(self.root,{'aweme_id':aid,'url':'https://www.douyin.com/video/'+aid,'selection_reason':'测试','identity_evidence':'页面匹配'})
  txt=self.root/'speech.txt';txt.write_text('测试');txt.with_suffix('.json').write_text(json.dumps({'media_sha256':'old','segments':[{'end':12}]}));before=(self.root/'batch.json').read_bytes()
  with patch.object(r,'check_media',return_value=(None,'new')),patch.object(r,'probe_duration',return_value=173):
   with self.assertRaises(ValueError):r.adopt_materials(self.root,aid,self.root/'v.mp4',txt)
  self.assertEqual((self.root/'batch.json').read_bytes(),before)

class ExportTests(unittest.TestCase):
 def test_export_receipt_rejects_changed_analysis(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/'batch';r.initialize(root,['AI认知'],'测试')
   analysis=root/'analysis.json';analysis.write_text('{}');workbook=root/'book.xlsx';workbook.write_bytes(b'fixture')
   proof=root/'receipt.json';r.save(proof,{'batch_sha256':r.digest(root/'batch.json'),'analysis_sha256':r.digest(analysis),'workbook_sha256':r.digest(workbook),'reopened':True,'ids':[]})
   before=(root/'batch.json').read_bytes();analysis.write_text('{"changed":true}')
   with self.assertRaises(ValueError):r.commit_export(root,analysis,workbook,proof)
   self.assertEqual((root/'batch.json').read_bytes(),before)
 def test_matching_receipt_does_not_bypass_failed_materials(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/'batch';r.initialize(root,['AI认知'],'测试')
   analysis=root/'analysis.json';analysis.write_text('{}');workbook=root/'book.xlsx';workbook.write_bytes(b'fixture')
   proof=root/'receipt.json';r.save(proof,{'batch_sha256':r.digest(root/'batch.json'),'analysis_sha256':r.digest(analysis),'workbook_sha256':r.digest(workbook),'reopened':True,'ids':[]})
   before=(root/'batch.json').read_bytes()
   with self.assertRaises(ValueError):r.commit_export(root,analysis,workbook,proof)
   self.assertEqual((root/'batch.json').read_bytes(),before)

if __name__=='__main__':unittest.main()
