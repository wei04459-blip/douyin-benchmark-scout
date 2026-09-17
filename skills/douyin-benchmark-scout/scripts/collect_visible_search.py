import json,time,sys,urllib.request,argparse
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parent))
from research_batch import read
from search_runner import run_keyword
from workflow_state import search_state

ROOT=None
SESSION=None
DEADLINE=None
def call(action,args):
 remaining=DEADLINE-time.monotonic() if DEADLINE else 30
 if remaining<=0:raise TimeoutError('本词采集时间预算已用完')
 req=urllib.request.Request('http://127.0.0.1:10086/command',data=json.dumps({'action':action,'args':args,'session':SESSION}).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=min(30,remaining)) as r:result=json.load(r)
 if not result.get('ok'):raise RuntimeError('bridge command failed: '+action)
 return result.get('data',{})
def nodes(tree):
 for n in tree:
  yield n
  yield from nodes(n.get('children',[]))
def extract(body):
 objects=[]
 try:objects=[json.loads(body)]
 except ValueError:
  for line in body.splitlines():
   if line.startswith('data:'):line=line[5:].strip()
   try:objects.append(json.loads(line))
   except ValueError:pass
 found={}
 def walk(v):
  if isinstance(v,dict):
   if v.get('aweme_id') and isinstance(v.get('desc'),str) and isinstance(v.get('video'),dict):found[str(v['aweme_id'])]=v
   else:
    for x in v.values():walk(x)
  elif isinstance(v,list):
   for x in v:walk(x)
 for x in objects:walk(x)
 return found
def read_page(keyword,navigate=True,scrolls=0):
 s=call('snapshot',{});allnodes=list(nodes(s.get('tree',[])))
 field=next(n for n in allnodes if n.get('role')=='textbox' and n.get('name')=='搜索你感兴趣的内容')
 if navigate:
  call('fill',{'selector':field['ref'],'value':keyword})
  button=next(n for n in allnodes if n.get('role')=='button' and n.get('name')=='搜索')
  call('click',{'selector':button['ref']})
  time.sleep(3)
 for _ in range(scrolls):
  call('evaluate',{'code':'window.scrollBy(0,900)'})
  time.sleep(3)
 s=call('snapshot',{});allnodes=list(nodes(s.get('tree',[])))
 text='\n'.join(n.get('name','') for n in allnodes if n.get('role')=='StaticText')
 field=next((n for n in allnodes if n.get('role')=='textbox' and n.get('name')=='搜索你感兴趣的内容'),{})
 if any(word in text for word in ['请完成下方验证','拖动滑块完成拼图','安全验证']):
  raise RuntimeError('access_restricted: verification shown')
 if field.get('value')!=keyword or keyword not in __import__('urllib.parse',fromlist=['unquote']).unquote(s.get('url','')):
  raise RuntimeError('search query not confirmed')
 requests=call('network',{'cmd':'list','filter':'general/search'}).get('requests',[])
 matched=[]
 for r in requests:
  qs=parse_qs(urlsplit(r.get('url','')).query)
  if qs.get('keyword')==[keyword] and r.get('status')==200:matched.append(r)
 found={}
 for r in matched[-8:]:
  d=call('cdp',{'method':'Network.getResponseBody','params':{'requestId':r['requestId']}})
  body=d.get('body','')
  if d.get('base64Encoded'):
   body=__import__('base64').b64decode(body).decode('utf-8',errors='replace')
  found.update(extract(body))
 when=datetime.now(timezone.utc).isoformat();cards=[];materials=[]
 for aid,item in found.items():
  title=item['desc'];visible=bool(title.strip()) and (title in text or title[:min(20,len(title))] in text)
  if not visible:continue
  stats=item.get('statistics',{});author=item.get('author',{});video=item['video']
  cards.append({'aweme_id':aid,'title':title,'author':author.get('nickname'),'duration_seconds':video.get('duration',0)/1000,'create_time':item.get('create_time'),'metrics':{k:stats.get(k) for k in ['digg_count','collect_count','comment_count','share_count']}})
  materials.append({'aweme_id':aid,'url':'https://www.douyin.com/video/'+aid,'title':title,'nickname':author.get('nickname'),
    'source_duration_seconds':video.get('duration',0)/1000,'source_duration_evidence':'本次页面搜索响应 video.duration 毫秒',
    'identity_evidence':'本次页面可见标题与搜索响应作品 ID 对应','create_time':item.get('create_time'),
    'liked_count':stats.get('digg_count'),'collected_count':stats.get('collect_count'),'comment_count':stats.get('comment_count'),'share_count':stats.get('share_count'),
    'metrics_observed_at':when,'keyword':keyword,'follower_count':None,'creator_id':str(author.get('uid') or ''),'sec_uid':author.get('sec_uid'),
    'video_download_url':((video.get('play_addr') or {}).get('url_list') or [None])[0]})
 evidence=text+'\n对应的本次公开搜索响应摘录：\n'+'\n'.join(c['aweme_id']+'\n'+c['title'] for c in cards)+'\n'+json.dumps(cards,ensure_ascii=False)
 observation={'keyword':keyword,'query':keyword,'observed_at':when,'channel':'Kimi WebBridge 页面及本页公开搜索响应','page_url':s.get('url'),
   'page_loaded':True,'query_confirmed':True,'cards':cards,'evidence_text':evidence}
 if not cards:observation['notes']='页面已核实，但未能把响应作品与可见标题匹配；不是零结果'
 empty_marker=next((marker for marker in ('暂无搜索结果','没有找到相关内容') if marker in text),None)
 if not cards and empty_marker:observation['empty_marker']=empty_marker
 # Whole-page text cannot prove that an end marker belongs to search results.
 observation['explicit_end']=False
 return observation,materials

if __name__=='__main__':
 p=argparse.ArgumentParser(description='记录已打开的独立Kimi研究页；只读页面公开结果，不提取登录信息')
 p.add_argument('--root',required=True,type=Path);p.add_argument('--session',required=True);p.add_argument('--current-first',action='store_true');p.add_argument('--scrolls',type=int);p.add_argument('--access-restored',action='store_true');p.add_argument('keywords',nargs='+')
 args=p.parse_args();ROOT=args.root.resolve();SESSION=args.session
 if not (ROOT/'batch.json').exists():p.error('先初始化研究批次')
 b=read(ROOT/'batch.json')
 if any(search_state(b,k)['access_restricted'] for k in b['keywords']) and not args.access_restored:
  p.error('该研究通道仍有访问限制；核实恢复后使用 --access-restored 继续原批次')
 incomplete=False
 from material_queue import locked
 queue_lock=locked(ROOT/'搜索执行')
 queue_lock.__enter__()
 try:
  call('network',{'cmd':'start'})
  for i,kw in enumerate(args.keywords):
   if i:time.sleep(18)
   policy={'max_scrolls':args.scrolls} if args.scrolls is not None else None
   DEADLINE=time.monotonic()+b.get('search_policy',{}).get('max_seconds',180)
   state=run_keyword(ROOT,kw,lambda round:read_page(kw,navigate=round==0 and not(i==0 and args.current_first),scrolls=1 if round else 0),policy)
   incomplete=incomplete or not state['scope_complete']
   if state['access_restricted']:break
 finally:
  DEADLINE=None
  try:call('network',{'cmd':'stop'})
  finally:queue_lock.__exit__(None,None,None)
 sys.exit(2 if incomplete else 0)
