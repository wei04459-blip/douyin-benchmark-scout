#!/usr/bin/env python3
"""Accept one real Computer Use observation, deriving progress without a browser dependency."""
import argparse
import json
import time
import uuid
from pathlib import Path
from datetime import datetime
from research_batch import read, classify_observation
from search_runner import persist, known_items
from workflow_state import CaptureBudget, search_state, latest_search, transaction


@transaction
def checkpoint(root,observation,items,new_attempt=False,access_restored=False):
    batch=read(root/'batch.json');keyword=observation['keyword']
    if keyword not in batch['keywords']:raise ValueError('关键词不属于本轮范围')
    state=search_state(batch,keyword);last=latest_search(batch,keyword) or {}
    if any(search_state(batch,k)['access_restricted'] for k in batch['keywords']) and not access_restored:
        raise ValueError('研究通道访问尚未恢复')
    prior=last.get('progress',{})
    begin=new_attempt or not last.get('attempt_id') or bool(prior.get('stop_reason'))
    if begin and state['retry_exhausted']:raise ValueError('已达到尝试上限，需检查来源或范围，不能盲目重试')
    budget=CaptureBudget(batch.get('search_policy',{}),time.monotonic)
    aid=uuid.uuid4().hex if begin else last['attempt_id']
    if not begin:
        budget.last_count=prior.get('observed_count',0)
        budget.stalls=prior.get('no_growth_rounds',0)
        budget.rounds=prior.get('scrolls',0)+1
        started=next(o['recorded_at'] for o in batch['searches'] if o.get('attempt_id')==aid)
        elapsed=max(0,time.time()-datetime.fromisoformat(started).timestamp())
        budget.started-=elapsed
    observation=dict(observation,attempt_id=aid)
    status=classify_observation(observation)
    existing=known_items(root,keyword)
    count=len(set(existing)|{i['aweme_id'] for i in items})
    if status in ('results_observed','confirmed_empty'):
        proven_end=(observation.get('explicit_end') is True and observation.get('end_scope')=='search_results'
                    and bool(observation.get('end_evidence')) and observation['end_evidence'] in observation['evidence_text'])
        progress=budget.observe(count,proven_end or status=='confirmed_empty')
        if status=='confirmed_empty' and count:
            observation['error']='inconsistent_empty_page';observation.pop('empty_marker',None)
            progress['stop_reason']='empty_after_progress'
    else:
        if items:raise ValueError('未核实的页面不能新增作品')
        progress={'stop_reason':status,'observed_count':len(existing)}
    observation['progress']=progress
    persist(root,observation,items)
    return search_state(read(root/'batch.json'),keyword)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--file',type=Path,required=True)
    p.add_argument('--new-attempt',action='store_true');p.add_argument('--access-restored',action='store_true')
    a=p.parse_args();payload=read(a.file)
    result=checkpoint(a.root.resolve(),payload['observation'],payload.get('items',[]),a.new_attempt,a.access_restored)
    print(json.dumps(result,ensure_ascii=False));raise SystemExit(0 if result['scope_complete'] else 2)
