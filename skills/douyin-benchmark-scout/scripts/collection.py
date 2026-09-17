#!/usr/bin/env python3
"""Batch discovery, creator metrics and initial-analysis ledger. No false completion."""
import argparse,datetime,hashlib,json,subprocess,sys,time
from pathlib import Path
from research_batch import read,save,now
from verify_evidence import digest, transcript_problem
from workflow_state import transaction, pending_keywords, SEARCH_DEFAULTS, search_state
HERE=Path(__file__).resolve().parent
FIELDS=('track','type','topic_summary','hook','structure','emotion','summary','viral','migration')

@transaction
def initialize_collection(root,config_path,target=None,keywords=None):
 from research_batch import initialize
 config=read(config_path)
 if (root/'batch.json').exists():return refresh(root)
 b=initialize(root,keywords or config['keywords'],'批量收集相关爆款竞品并完成初步分析')
 b.update(collection_target=target or config.get('collection_policy',{}).get('target',50),filter=config['filter'],breakout_rules=config['breakout_rules'])
 b['workflow_version']=3
 b['search_policy']={**SEARCH_DEFAULTS,**config.get('search_policy',{})}
 b['transcription_policy']=config.get('transcription',{})
 previous=Path.home()/'.douyin-benchmark-scout/last_collection.txt';seen=set()
 if previous.is_file():
  old=Path(previous.read_text().strip())/'竞品库.json'
  if old.is_file():
   seen.update(read(old).get('selected_ids',[]))
   prior_batch=old.parent/'batch.json'
   if prior_batch.is_file():seen.update(read(prior_batch).get('excluded_aweme_ids',[]))
 b['excluded_aweme_ids']=sorted(seen);save(root/'batch.json',b)
 previous.parent.mkdir(parents=True,exist_ok=True);previous.write_text(str(root.resolve()))
 return refresh(root)

def grade(i,r):
 f=i.get('follower_count');n=i.get('liked_count')
 if not isinstance(f,(int,float)) or f<=0 or not isinstance(n,(int,float)):return '待补指标','缺少可计算的粉丝或点赞数'
 v=n/f
 if f<=r['s_max_fans'] and n>=r['s_min_likes'] and v>=r['s_min_like_fan_ratio']:return 'S｜低粉高爆',f"粉丝≤{r['s_max_fans']:,}、点赞≥{r['s_min_likes']:,}、赞粉比≥{r['s_min_like_fan_ratio']:.0%}"
 if f<=r['a_max_fans'] and n>=r['a_min_likes'] and v>=r['a_min_like_fan_ratio']:return 'A｜重点观察',f"粉丝≤{r['a_max_fans']:,}、点赞≥{r['a_min_likes']:,}、赞粉比≥{r['a_min_like_fan_ratio']:.0%}"
 if f>=r['big_account_fans'] and v<r['big_account_ratio_ceiling']:return 'C｜大号常规流量',f"粉丝≥{r['big_account_fans']:,}且赞粉比<{r['big_account_ratio_ceiling']:.0%}"
 return 'B｜常规样本','有真实指标，但未达到S/A或C门槛'

def eligible(i,b):
 cutoff=datetime.datetime.fromisoformat(b['created_at']).timestamp()-b['filter']['days']*86400
 if i.get('relevance') == 'excluded':return False,i.get('relevance_reason','人工确认不相关')
 if i['aweme_id'] in b.get('excluded_aweme_ids',[]):return False,'历史已收录'
 if not i.get('create_time') or i['create_time']<cutoff:return False,'时间范围之外或缺少发布时间'
 if not i.get('source_duration_seconds'):return False,'图文或缺少视频时长'
 f=b['filter'];matches=any(isinstance(i.get(k),(int,float)) and i[k]>=f[t] for k,t in [('liked_count','min_likes'),('collected_count','min_favorites'),('comment_count','min_comments')])
 return (True,'达到互动初筛门槛') if matches else (False,'未达到互动初筛门槛')

def score(i):return (i.get('liked_count') or 0)+(i.get('collected_count') or 0)+2*(i.get('comment_count') or 0)+(i.get('share_count') or 0)

def valid_profile(d,aid,item=None):
 if not isinstance(d,dict) or d.get('aweme_id')!=aid:return False
 if type(d.get('follower_count')) is not int or d['follower_count']<0:return False
 if not isinstance(d.get('metrics'),dict) or not d.get('observed_at'):return False
 if any(d['metrics'].get(k) is not None and (type(d['metrics'][k]) is not int or d['metrics'][k]<0)
        for k in ('digg_count','collect_count','comment_count','share_count')):return False
 if d['metrics'].get('aweme_id') not in (None,aid):return False
 if item and item.get('creator_id') and d.get('creator_id') and item['creator_id']!=d['creator_id']:return False
 try:datetime.datetime.fromisoformat(d['observed_at'])
 except (ValueError,TypeError):return False
 return True

def needs_metrics(item,batch):
 if item['metrics_status']=='verified' or item.get('relevance')=='excluded' or item['aweme_id'] in batch.get('excluded_aweme_ids',[]):return False
 cutoff=datetime.datetime.fromisoformat(batch['created_at']).timestamp()-batch['filter']['days']*86400
 if item.get('create_time') and item['create_time']<cutoff:return False
 # Visible cards may omit dates, duration, or interactions. Resolve missing
 # facts before exclusion; a missing number is never interpreted as zero.
 fields=(('liked_count','min_likes'),('collected_count','min_favorites'),('comment_count','min_comments'))
 return item['eligible'] or any(item.get(k) is None or item[k]>=batch['filter'][t] for k,t in fields)

@transaction
def refresh(root):
 b=read(root/'batch.json');p=root/'竞品库.json';db=read(p) if p.exists() else {'schema_version':1,'created_at':now(),'target':b.get('collection_target',50),'items':{},'selected_ids':[]}
 for f in sorted((root/'搜索来源').glob('*.json')):
  for incoming in read(f)['items']:
   aid=incoming['aweme_id'];old=db['items'].get(aid,{})
   keys=set(old.get('source_keywords',[]));keys.add(incoming['keyword'])
   if not old:old=dict(incoming)
   elif incoming.get('metrics_observed_at','')>old.get('metrics_observed_at',''):
    # Refresh observed source fields, retaining relevance decisions and analysis.
    for k in ('title','nickname','source_duration_seconds','source_duration_evidence','create_time','liked_count','collected_count','comment_count','share_count','metrics_observed_at','video_download_url'):
     if k in incoming:old[k]=incoming[k]
   old['source_keywords']=sorted(keys);db['items'][aid]=old
 for aid,i in db['items'].items():
  profile=root/'账号核实'/f'{aid}.json'
  try:d=read(profile) if profile.exists() else None
  except (ValueError,OSError):d=None
  if valid_profile(d,aid,i):
   i.update({k:v for k,v in d.items() if k not in ('metrics','observed_at','eligible','relevance','relevance_reason','analysis','materials','source_keywords')});m=d.get('metrics') or {}
   for k,src in [('liked_count','digg_count'),('collected_count','collect_count'),('comment_count','comment_count'),('share_count','share_count')]:i[k]=m.get(src)
   i['metrics_observed_at']=d['observed_at'];i['metrics_status']='verified';i['profile_path']=str(profile.resolve())
  else:i['metrics_status']='pending'
  i['eligible'],i['filter_reason']=eligible(i,b);i['grade'],i['grade_reason']=grade(i,b['breakout_rules']);i['preliminary_score']=score(i)
 db['updated_at']=now();save(p,db);return db

def enrich(root,limit=0,retry_failed=False,access_restored=False):
 from material_queue import locked,MaterialError
 from workflow_state import failure
 db=refresh(root);batch=read(root/'batch.json');folder=root/'账号核实';folder.mkdir(exist_ok=True)
 project=Path.home()/'Douyin_TikTok_Download_API';runtime=project/'.venv311/bin/python';n=0
 with locked(root/'指标执行'):
  ledger=root/'指标任务.json';tasks=read(ledger) if ledger.is_file() else {'jobs':{}}
  if any(j.get('status')=='access_restricted' for j in tasks['jobs'].values()) and not access_restored:return db
  for i in sorted(db['items'].values(),key=score,reverse=True):
   if i['metrics_status']=='verified':
    job=tasks['jobs'].get(i['aweme_id'])
    if job and job['status']!='verified':
     for old in job['attempts']:
      if not old.get('finished_at'):old.update(outcome='verified_after_recovery',finished_at=now())
     job['status']='verified';job.pop('error',None);save(ledger,tasks)
    continue
   if not needs_metrics(i,batch):continue
   aid=i['aweme_id'];job=tasks['jobs'].setdefault(aid,{'status':'queued','attempts':[]})
   if job['status']=='access_restricted' and access_restored:
    job.setdefault('access_recoveries',[]).append(now());job['status']='queued'
   if job['status']=='running':
    for old in job['attempts']:
     if not old.get('finished_at'):old.update(outcome='interrupted',finished_at=now())
    job['status']='queued'
   if job['status']=='failed' and not retry_failed and not job.get('error',{}).get('retryable'):continue
   if sum(a.get('outcome') not in ('access_restricted','interrupted') for a in job['attempts'])>=3:continue
   attempt={'started_at':now()};job['attempts'].append(attempt);job['status']='running';save(ledger,tasks)
   target=folder/(aid+'.json');n+=1
   try:
    if target.exists():target.rename(folder/(aid+'.invalid.'+str(len(job['attempts']))+'.json'))
    result=subprocess.run([str(runtime),str(HERE/'installed_downloader.py'),'--project',str(project),'--id',aid,'--with-profile','--output',str(target)],capture_output=True,text=True,timeout=70)
    if result.returncode:
     try:code=json.loads(result.stdout.strip().splitlines()[-1]).get('code','resolver_failed')
     except (ValueError,IndexError):code='resolver_failed'
     raise MaterialError(code,'指标接口未返回可验证结果')
    d=read(target)
    if not valid_profile(d,aid,i):raise MaterialError('identity_mismatch','指标记录身份或字段不符')
    job['status']='verified';job.pop('error',None)
   except Exception as exc:
    job['error']=failure(exc,'metrics');job['status']='access_restricted' if job['error']['category']=='access' else 'failed'
    save(folder/(aid+'.failure.json'),{'aweme_id':aid,'failed_at':now(),**job['error']})
   attempt.update(outcome=job['status'],finished_at=now());save(ledger,tasks)
   print(json.dumps({'id':aid,'stage':'metrics','status':job['status']},ensure_ascii=False),flush=True)
   if job['status']=='access_restricted' or (limit and n>=limit):break
   time.sleep(2)
 return refresh(root)

@transaction
def select(root,ids):
 if len(ids)!=len(set(ids)):raise ValueError('入选作品ID重复')
 db=refresh(root)
 if db['selected_ids'] and not set(db['selected_ids']).issubset(ids):raise ValueError('入选已固定；不能删除失败条目换取完成。新增批次或明确增加样本。')
 for aid in ids:
  i=db['items'].get(aid)
  if not i or not i['eligible'] or i['metrics_status']!='verified':raise ValueError('入选需符合门槛且指标已核实：'+aid)
 db['selected_ids']=ids;save(root/'竞品库.json',db)
 return db

@transaction
def reuse(root,prior):
 db=refresh(root);b=read(prior/'batch.json');analysis=read(prior/'审核分析.json')
 for old in b['items']:
  aid=old['aweme_id']
  if aid not in db['selected_ids']:continue
  video=Path(old['video_path']);txt=Path(old['transcript_path']);t=read(txt.with_suffix('.json'));a=analysis['items'][aid]
  if digest(video)!=t['media_sha256'] or digest(txt)!=a['evidence_review']['transcript_sha256']:raise ValueError('历史材料指纹不匹配')
  db['items'][aid]['materials']={'video_path':str(video),'transcript_path':str(txt),'media_sha256':digest(video),'transcript_sha256':digest(txt),'transcript_metadata_sha256':digest(txt.with_suffix('.json')),'media_duration_seconds':t.get('media_duration_seconds'),'status':'prepared','reused_from':str(prior)}
  db['items'][aid]['analysis']=a
 save(root/'竞品库.json',db);return db

def prepare(root,retry_failed=False,access_restored=False,online_restricted=False):
 from material_queue import enqueue,prepare as run
 db=refresh(root);qroot=root/'材料准备'
 for aid in db['selected_ids']:
  i=db['items'][aid]
  if i.get('materials',{}).get('status')=='prepared' and material_flags(i)['text_valid']:continue
  enqueue(qroot,{'aweme_id':aid,'url':i['url'],'source_duration_seconds':i['source_duration_seconds']})
 if (qroot/'材料队列.json').exists():
  from doctor import inspect
  settings=read(root/'batch.json').get('transcription_policy',{})
  capabilities=inspect();python=settings.get('python') or capabilities.get('transcription_python')
  model=Path(settings['model_path']).expanduser() if settings.get('model_path') else Path.home()/'.cache/whisper'/(settings.get('model','medium')+'.pt')
  if not python:raise ValueError('本地转录运行环境不可用；已有材料和队列已保存')
  run(qroot,python,model,retry_failed,access_restored,online_restricted=online_restricted)
 return sync(root)

@transaction
def sync(root):
 db=refresh(root);qp=root/'材料准备/材料队列.json'
 if qp.exists():
  for job in read(qp)['jobs']:
   aid=job['source']['aweme_id']
   if aid in db['items']:
    db['items'][aid]['materials']={**job.get('artifacts',{}),'status':'prepared' if job['status']=='pending_review' else job['status'],'error':job.get('error')}
 save(root/'竞品库.json',db);return db

@transaction
def review(root,file):
 db=sync(root);a=read(file)
 for aid,value in a['items'].items():
  if aid not in db['selected_ids']:raise ValueError('分析必须属于入选集')
  db['items'][aid]['analysis']=value
 save(root/'竞品库.json',db);return db

def input_digest(root,db=None):
 db=db or read(root/'竞品库.json');b=read(root/'batch.json')
 payload={'digest_version':2,'selected_ids':db['selected_ids'],
          'items':{a:db['items'][a] for a in sorted(db['items'])},
          'searches':b['searches'],'keywords':b['keywords'],'filter':b['filter'],
          'rules':b['breakout_rules'],'target':db['target'],
          'scope_created_at':b['created_at'],'excluded_aweme_ids':b.get('excluded_aweme_ids',[]),
          'search_policy':b.get('search_policy',{}),'workflow_version':b.get('workflow_version',2)}
 return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def material_flags(i):
 """Count actual bound artifacts, never merely files or status labels."""
 m=i.get('materials',{});flags={'video_valid':False,'text_valid':False}
 try:
  v=Path(m.get('video_path',''));t=Path(m.get('transcript_path',''));meta=t.with_suffix('.json')
  flags['video_valid']=v.is_file() and bool(m.get('media_sha256')) and digest(v)==m['media_sha256']
  if not flags['video_valid'] or m.get('status')!='prepared' or not t.is_file() or not meta.is_file():return flags
  d=read(meta);duration=m.get('media_duration_seconds') or d.get('media_duration_seconds')
  flags['text_valid']=bool(duration and duration>0 and transcript_problem(t.read_text(),d,duration) is None and digest(t)==m.get('transcript_sha256') and digest(meta)==m.get('transcript_metadata_sha256') and d.get('media_sha256')==m.get('media_sha256'))
 except (OSError,ValueError,TypeError):pass
 return flags

def item_problems(i):
 problems=[];m=i.get('materials',{});a=i.get('analysis',{});rev=a.get('evidence_review',{});path=Path(m.get('transcript_path',''))
 if i.get('eligible') is not True or i.get('relevance')=='excluded':problems.append('当前不符合入选范围或互动门槛：'+i.get('filter_reason',i.get('relevance_reason','资格未核实')))
 if i['metrics_status']!='verified' or i['grade']=='待补指标':problems.append('指标未核实或无法分级')
 if m.get('status')!='prepared' or not path.is_file():problems.append('视频与文本尚未准备')
 else:
  try:
   if digest(path)!=m.get('transcript_sha256'):problems.append('文本指纹不符')
   video=Path(m['video_path']);meta=path.with_suffix('.json')
   if not video.is_file() or digest(video)!=m['media_sha256']:problems.append('视频缺失或已更改')
   if not meta.is_file() or digest(meta)!=m.get('transcript_metadata_sha256'):problems.append('文本来源记录缺失或已更改')
   t=read(meta)
   if t.get('media_sha256')!=m['media_sha256'] or not t.get('segments'):problems.append('视频与文本不对应或没有分段')
   if rev.get('media_sha256')!=m['media_sha256'] or rev.get('transcript_sha256')!=m['transcript_sha256']:problems.append('分析未绑定当前材料')
   text=path.read_text();duration=m.get('media_duration_seconds') or t.get('media_duration_seconds') or i['source_duration_seconds']
   text_problem=transcript_problem(text,t,duration)
   if text_problem:problems.append(text_problem)
   if not text.strip():problems.append('文本为空')
   for field in ('hook','structure','summary'):
    refs=[r for r in rev.get('references',[]) if r.get('field')==field]
    valid=False
    for r in refs:
     start,end=r.get('start'),r.get('end');quote=r.get('quote','')
     if not isinstance(start,(int,float)) or not isinstance(end,(int,float)) or not 0<=start<end<=duration+1 or not quote.strip():continue
     segment_text=''.join(s['text'] for s in t['segments'] if s['end']>start and s['start']<end)
     # Paragraph breaks and ASR segment boundaries may differ in the saved TXT.
     compact=lambda s:''.join(s.split())
     if compact(quote) in compact(segment_text) and compact(quote) in compact(text):valid=True
    if not valid:problems.append(field+'缺少对应时间范围的原文依据')
  except (KeyError,ValueError,OSError,TypeError) as e:problems.append('材料记录不完整：'+type(e).__name__)
 if rev.get('visual_evidence'):
  visual=Path(rev['visual_evidence'])
  if not visual.is_file() or digest(visual)!=rev.get('visual_sha256'):problems.append('画面依据缺失或已变化')
 else:problems.append('缺少关键画面依据')
 if any(not isinstance(a.get(k),str) or not a[k].strip() for k in FIELDS):problems.append('初步分析字段不全')
 if not rev.get('full_content_checked') or not rev.get('quality_notes'):problems.append('全文初读未审核')
 return problems

@transaction
def verify(root):
 db=sync(root);b=read(root/'batch.json');issues=[];items=[db['items'][a] for a in db['selected_ids']]
 if len(items)<db['target']:issues.append(f'目标{db["target"]}条，实际入选{len(items)}条')
 pending=pending_keywords(b)
 if pending:issues.append({'search_pending':pending})
 checked={i['aweme_id']:item_problems(i) for i in items}
 materials={i['aweme_id']:material_flags(i) for i in items}
 for aid,p in checked.items():
  if p:issues.append({'id':aid,'problems':p})
 result={'ready':not issues,'target':db['target'],'selected':len(items),
  'discovered':len(db['items']),'eligible':sum(i['eligible'] for i in db['items'].values()),
  'metrics_verified':sum(i['metrics_status']=='verified' for i in items),
  'downloaded':sum(m['video_valid'] for m in materials.values()),
  'materials_ready':sum(m['text_valid'] for m in materials.values()),'material_status':materials,
  'analyses':sum(bool(i.get('analysis')) for i in items),'analyses_verified':sum(not p for p in checked.values()),
  'search_pending':pending,'search_states':[search_state(b,k) for k in b['keywords']],
  'item_problems':checked,'issues':issues,'input_sha256':input_digest(root,db),'checked_at':now()}
 save(root/'收集验收.json',result);return result

@transaction
def commit(root,file):
 result=verify(root);receipt=read(root/'导出回执.json')
 if not result['ready']:raise ValueError('收集验收存在缺项，不能标记全流程完成')
 if not receipt.get('reopened') or not receipt.get('visual_reviewed'):raise ValueError('需要保存重开和画面复核')
 if receipt['input_sha256']!=result['input_sha256'] or receipt['workbook_sha256']!=digest(file):raise ValueError('出表后输入或工作簿已变化')
 save(root/'完成回执.json',{'status':'collection_and_initial_analysis_complete','count':result['selected'],'workbook':str(file.resolve()),'workbook_sha256':digest(file),'input_sha256':result['input_sha256'],'completed_at':now()})
 return result

def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('command',choices=['refresh','enrich','select','reuse','prepare','sync','review','verify','commit','status']);p.add_argument('--file',type=Path);p.add_argument('--prior',type=Path);p.add_argument('--limit',type=int,default=0);p.add_argument('--retry-failed',action='store_true');p.add_argument('--access-restored',action='store_true');a=p.parse_args();root=a.root.resolve()
 if a.command=='enrich':d=enrich(root,a.limit,a.retry_failed,a.access_restored)
 elif a.command=='select':d=select(root,read(a.file)['ids'])
 elif a.command=='reuse':d=reuse(root,a.prior.resolve())
 elif a.command=='prepare':d=prepare(root,a.retry_failed,a.access_restored)
 elif a.command=='review':d=review(root,a.file)
 elif a.command=='verify':d=verify(root);print(json.dumps(d,ensure_ascii=False));return 0 if d['ready'] else 2
 elif a.command=='commit':
  print(json.dumps(commit(root,a.file),ensure_ascii=False));return 0
 elif a.command=='sync':d=sync(root)
 else:d=refresh(root)
 print(json.dumps({'discovered':len(d['items']),'eligible':sum(i['eligible'] for i in d['items'].values()),'metrics_verified':sum(i['eligible'] and i['metrics_status']=='verified' for i in d['items'].values()),'selected':len(d['selected_ids']),'target':d['target']},ensure_ascii=False))
 if a.command=='prepare':return 0 if d['selected_ids'] and all(material_flags(d['items'][aid])['text_valid'] for aid in d['selected_ids']) else 2
 if a.command=='enrich':return 2 if any(needs_metrics(i,read(root/'batch.json')) for i in d['items'].values()) else 0
 return 0
if __name__=='__main__':sys.exit(main())
