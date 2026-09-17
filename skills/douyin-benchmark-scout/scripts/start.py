#!/usr/bin/env python3
"""Unified collection entrypoint. Material-only imports remain available separately."""
import argparse,json,subprocess,sys
from pathlib import Path
from datetime import datetime
import collection as c
HERE=Path(__file__).resolve().parent

def main():
 p=argparse.ArgumentParser(description='批量收集爆款竞品、补齐粉丝、分级和初步分析')
 p.add_argument('command',nargs='?',default='status',choices=['init','search','enrich','select','prepare','sync','review','reuse','verify','export','commit','status','check','next','resume'])
 p.add_argument('--root',type=Path);p.add_argument('--config',type=Path,default=Path.home()/'.douyin-benchmark-scout/config.json')
 p.add_argument('--target',type=int);p.add_argument('--keywords');p.add_argument('--session');p.add_argument('--file',type=Path);p.add_argument('--prior',type=Path)
 p.add_argument('--retry-failed',action='store_true');p.add_argument('--access-restored',action='store_true');p.add_argument('--output',type=Path);p.add_argument('--node');p.add_argument('--python');p.add_argument('--modules');p.add_argument('--require-complete',action='store_true')
 a=p.parse_args()
 if a.command=='check':
  from doctor import inspect
  print(json.dumps(inspect(),ensure_ascii=False,indent=2));return 0
 last=Path.home()/'.douyin-benchmark-scout/last_collection.txt'
 root=a.root or (Path(last.read_text().strip()) if last.is_file() and a.command!='init' else None)
 if not root:
  if a.command!='init':
   print('这里用于批量收集和初步分析。请在 Codex 中说“收集一批AI爆款竞品”，由代理创建批次并接续搜索。');return 0
  root=Path.cwd()/'outputs'/('竞品收集_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
 root=root.resolve()
 if a.command=='init':
  if not a.config.is_file() and a.config==Path.home()/'.douyin-benchmark-scout/config.json':
   a.config=HERE.parent/'assets/example-config.json'
  c.initialize_collection(root,a.config,a.target,a.keywords.split(',') if a.keywords else None)
  print('批次已建立：'+str(root));print('下一步由 Codex 在独立研究页搜索，随后自动补齐粉丝与材料。');return 0
 if a.command in ('next','resume'):
  from workflow import next_actions,resume
  result=resume(root,a.session,a.retry_failed,a.access_restored) if a.command=='resume' else next_actions(root)
  print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['complete'] else 2
 if a.command=='search':
  if not a.session:p.error('Kimi 搜索需指定已观察的独立研究页 session；Computer Use 可直接记录搜索观察')
  b=c.read(root/'batch.json');keywords=a.keywords.split(',') if a.keywords else c.pending_keywords(b)
  if not keywords:print('本批关键词均有已核实搜索记录');return 0
  cmd=[sys.executable,str(HERE/'collect_visible_search.py'),'--root',str(root),'--session',a.session]
  if a.access_restored:cmd.append('--access-restored')
  return subprocess.call(cmd+keywords)
 if a.command=='export':
  if not all([a.output,a.node,a.modules]):p.error('export 需要 --output --node --modules，使用已加载的工作簿运行环境')
  cmd=[a.node,str(HERE/'export_collection.mjs'),'--root',str(root),'--output',str(a.output),'--python',a.python or sys.executable,'--modules',a.modules]
  if a.require_complete:cmd.extend(['--require-complete','true'])
  return subprocess.call(cmd)
 if a.command=='status':
  d=c.verify(root)
  print(f"目标 {d['target']} 条，已入选 {d['selected']}；指标核实 {d['metrics_verified']}，视频已下载 {d['downloaded']}，文本已准备 {d['materials_ready']}，初步分析通过 {d['analyses_verified']}。")
  if d['search_pending']:print('搜索待补：'+'、'.join(d['search_pending']))
  if d['issues']:print('缺项已保存在收集验收记录，可从当前目录继续。')
  else:
   receipt=root/'完成回执.json';done=c.read(receipt) if receipt.is_file() else {}
   book=Path(done.get('workbook',''))
   if done.get('input_sha256')==d['input_sha256'] and book.is_file() and c.digest(book)==done.get('workbook_sha256'):
    print('本轮收集、初步分析与工作簿验收已完成：'+str(book))
   else:print('收集与初步分析已通过，工作簿仍需保存、重开与视觉复核。')
  return 0
 cmd=[sys.executable,str(HERE/'collection.py'),'--root',str(root),a.command]
 for k in ('file','prior'):
  if getattr(a,k):cmd.extend(['--'+k,str(getattr(a,k))])
 if a.retry_failed:cmd.append('--retry-failed')
 if a.access_restored:cmd.append('--access-restored')
 return subprocess.call(cmd)
if __name__=='__main__':sys.exit(main())
