import tempfile,unittest
from pathlib import Path
from collection import grade,eligible,select,read,save,refresh,item_problems,initialize_collection
from material_queue import enqueue
from installed_downloader import normalize
RULES=read(Path(__file__).resolve().parents[1]/'assets/example-config.json')['breakout_rules']
class CollectionTests(unittest.TestCase):
 def test_grade_boundaries_and_missing(self):
  for fans,likes,expected in [(10000,10000,'S'),(100000,100000,'S'),(100001,100001,'A'),(300000,90000,'A'),(300001,90000,'B'),(1000000,99999,'C'),(1000000,100000,'B'),(None,90000,'待'),(0,90000,'待')]:
   self.assertTrue(grade({'follower_count':fans,'liked_count':likes},RULES)[0].startswith(expected))
 def test_select_keeps_failed_and_rejects_duplicates(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/'run';config=Path(__file__).resolve().parents[1]/'assets/example-config.json'
   # Never mutate the user's last-run pointer in a unit test.
   from unittest.mock import patch
   with patch('pathlib.Path.home',return_value=Path(d)):
    initialize_collection(root,config,2,['AI'])
   b=read(root/'batch.json');b['created_at']='2026-09-10T00:00:00+00:00';save(root/'batch.json',b)
   for aid in ('1111111111111','2222222222222'):
    profile={'aweme_id':aid,'keyword':'AI','title':'AI教程','create_time':1788998400,'source_duration_seconds':30,'follower_count':1000,'observed_at':'2026-09-10T00:00:00+00:00','metrics':{'digg_count':10000,'collect_count':0,'comment_count':0,'share_count':0}}
    save(root/'账号核实'/f'{aid}.json',profile)
    save(root/'搜索来源'/f'{aid}.json',{'items':[profile]})
   with self.assertRaises(ValueError):select(root,['1111111111111','1111111111111'])
   select(root,['1111111111111','2222222222222'])
   with self.assertRaises(ValueError):select(root,['1111111111111'])
 def test_job_idempotency_is_video_identity(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);enqueue(r,{'aweme_id':'1111111111111','url':'https://www.douyin.com/video/1111111111111'})
   enqueue(r,{'aweme_id':'1111111111111','video_download_url':'https://example.com/changed','followers':20})
   self.assertEqual(len(read(r/'材料队列.json')['jobs']),1)
 def test_small_dash_video_cannot_replace_muxed_audio(self):
  source={'aweme_detail':{'aweme_id':'1111111111111','video':{'duration':50000,'play_addr':{'url_list':['https://example.com/original'],'width':1080,'height':1920,'data_size':300},'bit_rate':[{'format':'dash','play_addr':{'url_list':['https://example.com/silent'],'width':720,'height':1280,'data_size':10}},{'format':'mp4','play_addr':{'url_list':['https://example.com/muxed'],'width':720,'height':1280,'data_size':80}}]}}}
  self.assertEqual(normalize(source,'1111111111111')['video_download_url'],'https://example.com/muxed')
 def test_filled_analysis_does_not_complete_missing_materials(self):
  i={'metrics_status':'verified','grade':'S','materials':{'status':'prepared','transcript_path':'/missing'},'analysis':{'hook':'依据标题写满'}}
  self.assertIn('视频与文本尚未准备',item_problems(i));self.assertIn('全文初读未审核',item_problems(i))
 def test_fingerprint_and_reference_time_binding(self):
  from verify_evidence import digest
  from collection import FIELDS
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);video=r/'video.mp4';video.write_bytes(b'fixture');txt=r/'transcript.txt';txt.write_text('开头是问题。后面给出方法。')
   meta=txt.with_suffix('.json');save(meta,{'media_sha256':digest(video),'segments':[{'start':0,'end':2,'text':'开头是问题。'},{'start':5,'end':8,'text':'后面给出方法。'}]})
   m={'status':'prepared','video_path':str(video),'transcript_path':str(txt),'media_sha256':digest(video),'transcript_sha256':digest(txt),'transcript_metadata_sha256':digest(meta),'media_duration_seconds':10}
   visual=r/'frame.jpg';visual.write_bytes(b'frame fixture')
   rev={'full_content_checked':True,'quality_notes':'测试完整阅读','media_sha256':digest(video),'transcript_sha256':digest(txt),'visual_evidence':str(visual),'visual_sha256':digest(visual),'references':[{'field':f,'start':0,'end':2,'quote':'开头是问题。'} for f in ('hook','structure','summary')]}
   i={'eligible':True,'metrics_status':'verified','grade':'S','materials':m,'analysis':{**{f:'测试分析' for f in FIELDS},'evidence_review':rev}}
   self.assertEqual(item_problems(i),[])
   rev['references'][0]['start']=5;rev['references'][0]['end']=8
   self.assertIn('hook缺少对应时间范围的原文依据',item_problems(i))
   txt.write_text('被替换了');self.assertIn('文本指纹不符',item_problems(i))
   from collection import material_flags
   self.assertEqual(material_flags(i),{'video_valid':True,'text_valid':False})
   video.write_bytes(b'corrupted');self.assertEqual(material_flags(i),{'video_valid':False,'text_valid':False})
if __name__=='__main__':unittest.main()
