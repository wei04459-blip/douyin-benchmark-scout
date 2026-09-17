import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import collection as c
import research_batch as r
import material_queue as q
from workflow_state import search_state, pending_keywords, CaptureBudget, failure
from search_runner import run_keyword, known_items, source_path
from search_checkpoint import checkpoint
from transcribe_local import Transcriber
from verify_evidence import transcript_problem
import workflow

CONFIG=Path(__file__).resolve().parents[1]/'assets/example-config.json'

def obs(ids=('1111111111111',), keyword='AI', **extra):
    cards=[{'aweme_id':i,'title':'AI教程'+i} for i in ids]
    return {'keyword':keyword,'query':keyword,'observed_at':r.now(),'channel':'test fixture',
            'page_url':'https://www.douyin.com/search/AI','page_loaded':True,'query_confirmed':True,
            'cards':cards,'evidence_text':'\n'.join(c['aweme_id']+' '+c['title'] for c in cards) or '页面观察',**extra}

def incoming(observation):
    return [dict(card,keyword=observation['keyword']) for card in observation['cards']]

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.root=self.base/'batch'
        with patch('pathlib.Path.home',return_value=self.base):
            c.initialize_collection(self.root,CONFIG,1,['AI','教程'])

    def test_digest_includes_unselected_candidates_and_ignores_check_time(self):
        db=r.read(self.root/'竞品库.json');db['items']['x']={'title':'未入选'}
        r.save(self.root/'竞品库.json',db);old=c.input_digest(self.root)
        db['updated_at']='later';self.assertEqual(old,c.input_digest(self.root,db))
        db['items']['x']['title']='已变化';self.assertNotEqual(old,c.input_digest(self.root,db))

    def test_first_init_without_personal_config_uses_packaged_defaults(self):
        import start
        root=self.base/'first-run';home=self.base/'new-user'
        with patch('pathlib.Path.home',return_value=home),patch('sys.argv',['start.py','init','--root',str(root)]),patch.object(start.subprocess,'call') as network:
            self.assertEqual(start.main(),0)
            network.assert_not_called()
        batch=r.read(root/'batch.json')
        self.assertEqual(batch['collection_target'],50)
        self.assertTrue(batch['search_policy']['require_scope_completion'])
        self.assertFalse((home/'.douyin-benchmark-scout/config.json').exists())

    def test_latest_attempt_controls_scope_everywhere(self):
        r.record_search(self.root,obs(progress={'stop_reason':'target_reached'}))
        self.assertNotIn('AI',pending_keywords(r.read(self.root/'batch.json')))
        r.record_search(self.root,obs(error='timeout'))
        b=r.read(self.root/'batch.json')
        self.assertIn('AI',pending_keywords(b));self.assertFalse(r.search_summary(b)[0]['scope_complete'])
        self.assertIn('AI',c.verify(self.root)['search_pending'])

    def test_synonym_does_not_complete_exact_keyword(self):
        r.record_search(self.root,obs(query='人工智能',progress={'stop_reason':'target_reached'}))
        self.assertEqual(search_state(r.read(self.root/'batch.json'),'AI')['status'],'exact_query_pending')

    def test_seen_results_without_scope_are_pending(self):
        r.record_search(self.root,obs())
        self.assertFalse(search_state(r.read(self.root/'batch.json'),'AI')['scope_complete'])

    def test_incremental_capture_merges_duplicates_and_stops_at_target(self):
        pages=[obs(),obs(('1111111111111','2222222222222'))];calls=[]
        def reader(n):calls.append(n);return pages[n],incoming(pages[n])
        state=run_keyword(self.root,'AI',reader,{'target_per_keyword':2},wait=lambda _:None)
        self.assertEqual(calls,[0,1]);self.assertEqual(len(known_items(self.root,'AI')),2)
        self.assertTrue(state['scope_complete']);self.assertEqual(state['attempts'],1)

    def test_timeout_keeps_first_page_and_does_not_complete(self):
        def reader(n):
            if n:raise TimeoutError('test timeout')
            o=obs();return o,incoming(o)
        state=run_keyword(self.root,'AI',reader,wait=lambda _:None)
        self.assertEqual(len(known_items(self.root,'AI')),1)
        self.assertFalse(state['scope_complete']);self.assertEqual(state['status'],'retrieval_failed')
        another=obs(keyword='教程',progress={'stop_reason':'target_reached'})
        r.record_search(self.root,another)
        self.assertTrue(search_state(r.read(self.root/'batch.json'),'教程')['scope_complete'])

    def test_stall_and_unscoped_end_are_not_completion(self):
        def reader(n):
            o=obs(explicit_end=True);return o,incoming(o)
        s=run_keyword(self.root,'AI',reader,{'stall_rounds':2},wait=lambda _:None)
        self.assertEqual(s['stop_reason'],'stalled');self.assertFalse(s['scope_complete'])

    def test_scoped_end_marker_can_complete_short_search(self):
        o=obs(explicit_end=True,end_scope='search_results',end_evidence='没有更多了')
        o['evidence_text']+=' 没有更多了'
        s=run_keyword(self.root,'AI',lambda n:(o,incoming(o)),wait=lambda _:None)
        self.assertTrue(s['scope_complete']);self.assertEqual(s['stop_reason'],'content_exhausted')

    def test_empty_is_not_inferred_and_previous_items_survive_empty(self):
        s=run_keyword(self.root,'AI',lambda n:(obs(()),[]),wait=lambda _:None)
        self.assertFalse(s['scope_complete'])
        pages=[obs(),obs((),empty_marker='暂无搜索结果',evidence_text='暂无搜索结果')]
        s=run_keyword(self.root,'AI',lambda n:(pages[n],incoming(pages[n])),wait=lambda _:None)
        self.assertFalse(s['scope_complete']);self.assertEqual(s['stop_reason'],'empty_after_progress')
        self.assertEqual(len(known_items(self.root,'AI')),1)

    def test_exact_empty_without_prior_items_can_complete(self):
        o=obs((),empty_marker='暂无搜索结果',evidence_text='暂无搜索结果')
        s=run_keyword(self.root,'AI',lambda n:(o,[]))
        self.assertTrue(s['scope_complete']);self.assertEqual(s['observed_cards'],0)

    def test_attempt_budget_survives_restart(self):
        for _ in range(3):run_keyword(self.root,'AI',lambda n:(_ for _ in ()).throw(TimeoutError()))
        reader=unittest.mock.Mock()
        self.assertEqual(run_keyword(self.root,'AI',reader)['stop_reason'],'attempt_budget')
        reader.assert_not_called()

    def test_access_restored_can_resume_same_keyword(self):
        o=obs(restriction='滑块验证')
        for _ in range(3):r.record_search(self.root,o)
        with self.assertRaises(ValueError):checkpoint(self.root,obs(),incoming(obs()))
        state=checkpoint(self.root,obs(),incoming(obs()),access_restored=True)
        self.assertEqual(state['status'],'results_observed');self.assertEqual(state['observed_cards'],1)

    def test_cua_checkpoint_derives_progress(self):
        first=checkpoint(self.root,obs(),incoming(obs()))
        self.assertFalse(first['scope_complete'])
        o=obs(('1111111111111','2222222222222'))
        second=checkpoint(self.root,o,incoming(o))
        self.assertEqual(second['attempts'],1);self.assertEqual(second['observed_cards'],2)
        self.assertFalse(second['scope_complete'])

    def test_concurrent_observations_not_lost(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _:r.record_search(self.root,obs()),range(12)))
        rows=r.read(self.root/'batch.json')['searches']
        self.assertEqual([x['observation_id'] for x in rows],list(range(1,13)))

    def test_keyword_filename_safe_and_unique(self):
        a=source_path(self.root,'AI/写作');b=source_path(self.root,'AI 写作')
        self.assertEqual(a.parent,self.root/'搜索来源');self.assertNotEqual(a,b)

    def test_budget_time_and_scroll_limits(self):
        clock=[0];b=CaptureBudget({'max_seconds':5},lambda:clock[0]);clock[0]=6
        self.assertEqual(b.observe(1)['stop_reason'],'time_budget')
        b=CaptureBudget({'max_scrolls':1},lambda:0)
        self.assertEqual(b.observe(1)['stop_reason'],'');self.assertEqual(b.observe(2)['stop_reason'],'scroll_budget')

    def test_invalid_profile_never_verified(self):
        aid='1111111111111'
        d={'aweme_id':aid,'keyword':'AI','title':'AI教程','create_time':__import__('time').time(),
           'source_duration_seconds':10,'liked_count':20000,'follower_count':1000}
        r.save(self.root/'搜索来源/test.json',{'items':[d]})
        r.save(self.root/'账号核实'/f'{aid}.json',dict(d,aweme_id='9999999999999'))
        db=c.refresh(self.root);self.assertEqual(db['items'][aid]['metrics_status'],'pending')
        with self.assertRaises(ValueError):c.select(self.root,[aid])

    def test_platform_metrics_can_contain_video_identity(self):
        d={'aweme_id':'1111111111111','follower_count':1000,'observed_at':r.now(),
           'metrics':{'aweme_id':'1111111111111','digg_count':3000,'other_platform_flag':'unused'}}
        self.assertTrue(c.valid_profile(d,'1111111111111'))
        d['metrics']['aweme_id']='2222222222222';self.assertFalse(c.valid_profile(d,'1111111111111'))

    def test_missing_card_metadata_is_resolved_before_exclusion(self):
        item={'aweme_id':'1111111111111','metrics_status':'pending','eligible':False,'liked_count':20000}
        batch=r.read(self.root/'batch.json')
        self.assertTrue(c.needs_metrics(item,batch))
        item['relevance']='excluded';self.assertFalse(c.needs_metrics(item,batch))

    def test_ineligible_item_never_passes_analysis_gate(self):
        item={'eligible':False,'metrics_status':'verified','grade':'S','filter_reason':'不相关'}
        self.assertTrue(any('入选范围' in p for p in c.item_problems(item)))

    def test_next_actions_never_auto_selects_or_reviews(self):
        state=workflow.next_actions(self.root)
        self.assertFalse(state['complete']);self.assertEqual(state['counts']['selected'],0)
        self.assertTrue(any(a['stage']=='selection' for a in state['actions']))

    def test_resume_retries_only_transient_failures_with_bound(self):
        calls=[]
        def enrich(root,**kw):
            calls.append(1)
            r.save(root/'指标任务.json',{'jobs':{'x':{'status':'failed','error':{'retryable':True},
                     'attempts':[{'outcome':'failed'} for _ in calls]}}})
        with patch.object(c,'enrich',side_effect=enrich),patch.object(workflow.time,'sleep'):
            self.assertFalse(workflow.resume(self.root)['complete'])
        self.assertEqual(len(calls),3)

    def test_restricted_resume_never_calls_online_metrics(self):
        r.record_search(self.root,obs(restriction='验证'))
        with patch.object(c,'enrich') as enrich:
            workflow.resume(self.root);enrich.assert_not_called()

class TranscriptionRecoveryTests(unittest.TestCase):
    def test_partial_chunks_cache_and_model_reuse(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);model=root/'model';model.write_bytes(b'fake model');calls=[];loads=[]
            class Audio:
                def __getitem__(self,index):return index.start//16000
            class Model:
                def transcribe(self,audio,**kw):
                    calls.append(audio)
                    if audio==10 and calls.count(10)==1:raise RuntimeError('interrupted chunk')
                    return {'text':'实际口播','segments':[{'start':0,'end':10,'text':'实际口播'}]}
            def loader(path):loads.append(path);return Model()
            engine=Transcriber(model,loader)
            _,first=engine.chunks(Audio(),30,'videoA',root/'cache',10)
            self.assertEqual([c['status'] for c in first],['ok','failed','ok'])
            _,second=engine.chunks(Audio(),30,'videoA',root/'cache',10)
            self.assertEqual([c['status'] for c in second],['ok']*3)
            self.assertEqual(calls,[0,10,20,10]);self.assertEqual(len(loads),1)
            engine.chunks(Audio(),10,'videoB',root/'cache',10)
            self.assertEqual(len(loads),1);self.assertEqual(len(calls),5)
            model.write_bytes(b'different model')
            Transcriber(model,loader).chunks(Audio(),10,'videoA',root/'cache',10)
            self.assertEqual(len(calls),6)

    def test_empty_malformed_and_partial_transcripts_rejected(self):
        good={'segments':[{'start':0,'end':1,'text':'正文'}]}
        self.assertIsNone(transcript_problem('正文',good,1))
        for bad in ([],dict(good,chunks=[None]),dict(good,chunks='ok'),
                    dict(good,incomplete_chunks=[0]),dict(good,status='machine_partial_unreviewed'),
                    {'segments':[{'start':False,'end':1,'text':'正文'}]}):
            self.assertIsNotNone(transcript_problem('正文',bad,1))
        self.assertIsNotNone(transcript_problem('',good,1))
        self.assertIsNotNone(transcript_problem('捏造正文',good,1))

    def test_failure_classification(self):
        import urllib.error
        for exc,category in [(TimeoutError(),'transient'),(urllib.error.HTTPError('url',403,'',{},None),'access'),
                             (q.MaterialError('transcript_incomplete',''),'material'),
                             (q.MaterialError('model_missing',''),'environment')]:
            self.assertEqual(failure(exc,'test')['category'],category)

class QueueRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.video=self.root/'original.mp4';self.video.write_bytes(b'fixture')
        self.addCleanup(patch.stopall)
        patch.object(q,'check_media',side_effect=lambda p,f:(None,q.digest(p))).start()
        patch.object(q,'probe_duration',return_value=12).start()

    def worker(self,partial=False,fail=False):
        outer=self
        class Worker:
            def __init__(self,*args):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def transcribe(self,media,out,cache):
                if fail:raise TimeoutError('worker stopped')
                out.mkdir();(out/'transcript.txt').write_text('测试口播')
                r.save(out/'transcript.json',{'media_sha256':q.digest(media),
                  'segments':[{'start':0,'end':12,'text':'测试口播'}],
                  'incomplete_chunks':[1] if partial else []})
                return {'transcript':str(out/'transcript.txt'),'incomplete_chunks':[1] if partial else []}
        return Worker

    def test_partial_text_does_not_become_prepared(self):
        q.enqueue(self.root,{'local_video':str(self.video)})
        jobs=q.prepare(self.root,'unused',Path('/model'),worker_factory=self.worker(partial=True))['jobs']
        self.assertEqual(jobs[0]['status'],'failed')
        self.assertEqual(jobs[0]['error']['code'],'transcript_incomplete')
        self.assertTrue(Path(jobs[0]['partial_transcript_path']).is_file())
        self.assertFalse(q.verify_prepared(jobs[0]))

    def test_interrupted_job_reuses_download_before_transcription(self):
        q.enqueue(self.root,{'local_video':str(self.video)})
        job=q.prepare(self.root,'unused',Path('/model'),worker_factory=self.worker(fail=True))['jobs'][0]
        original=job['artifacts']['video_path']
        job['status']='preparing';job['attempts'][-1].pop('finished_at');job['attempts'][-1].pop('outcome')
        r.save(self.root/'材料队列.json',{'jobs':[job]})
        with patch.object(q.shutil,'copy2',side_effect=AssertionError('must reuse saved video')):
            job=q.prepare(self.root,'unused',Path('/model'),worker_factory=self.worker())['jobs'][0]
        self.assertEqual(job['artifacts']['video_path'],original);self.assertEqual(job['status'],'pending_review')
        self.assertEqual(job['attempts'][0]['outcome'],'interrupted')

    def test_restricted_channel_blocks_remote_but_allows_local_jobs(self):
        q.enqueue(self.root,{'video_download_url':'https://example.com/v','source_duration_seconds':12})
        q.enqueue(self.root,{'local_video':str(self.video)})
        with patch.object(q,'acquire',side_effect=AssertionError('network must not run')):
            jobs=q.prepare(self.root,'unused',Path('/model'),worker_factory=self.worker(),online_restricted=True)['jobs']
        self.assertEqual([j['status'] for j in jobs],['queued','pending_review'])

    def test_restricted_job_stops_following_remote_work(self):
        q.enqueue(self.root,{'video_download_url':'https://example.com/one','source_duration_seconds':12})
        q.enqueue(self.root,{'video_download_url':'https://example.com/two','source_duration_seconds':12})
        with patch.object(q,'acquire',side_effect=q.MaterialError('access_restricted','验证')) as acquire:
            jobs=q.prepare(self.root,'unused',Path('/model'),worker_factory=self.worker())['jobs']
            self.assertEqual(acquire.call_count,1)
        self.assertEqual([j['status'] for j in jobs],['access_restricted','queued'])

    def test_retry_budget_persists_across_invocations(self):
        q.enqueue(self.root,{'local_video':str(self.video)})
        for _ in range(5):job=q.prepare(self.root,'unused',Path('/model'),worker_factory=self.worker(fail=True))['jobs'][0]
        self.assertEqual(len(job['attempts']),3);self.assertEqual(job['status'],'failed')

    def test_changed_original_invalidates_prepared_copy(self):
        q.enqueue(self.root,{'local_video':str(self.video)})
        job=q.prepare(self.root,'unused',Path('/model'),worker_factory=self.worker())['jobs'][0]
        self.assertTrue(q.verify_prepared(job));self.video.write_bytes(b'changed source')
        self.assertFalse(q.verify_prepared(job))

if __name__=='__main__':unittest.main()
