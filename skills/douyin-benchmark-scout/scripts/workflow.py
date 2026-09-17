"""Actionable state and one bounded pass through available mechanical stages."""
import subprocess
import sys
import time
from pathlib import Path
import collection as c
from research_batch import read,save,now
from workflow_state import pending_keywords, search_state


def next_actions(root, status=None):
    status=status or c.verify(root)
    db=read(root/'竞品库.json');batch=read(root/'batch.json');actions=[]
    for state in status['search_states']:
        if not state['scope_complete']:
            actions.append({'stage':'search','keyword':state['keyword'],
                'action':'restore_access' if state['access_restricted'] else 'inspect_search' if state['retry_exhausted'] else 'continue_search',
                'reason':state['stop_reason'] or state['status']})
    missing=[i['aweme_id'] for i in db['items'].values() if c.needs_metrics(i,batch)]
    if missing:
        ledger=root/'指标任务.json';jobs=read(ledger)['jobs'] if ledger.is_file() else {}
        actions.append({'stage':'metrics','ids':missing,'action':'verify_public_metrics',
                        'failures':{aid:jobs[aid]['error'] for aid in missing if jobs.get(aid,{}).get('error')}})
    if len(db['selected_ids'])<db['target']:
        actions.append({'stage':'selection','action':'review_relevance_and_select',
                        'remaining':db['target']-len(db['selected_ids'])})
    for aid in db['selected_ids']:
        item=db['items'][aid];flags=status['material_status'][aid]
        if not flags['text_valid']:
            actions.append({'stage':'materials','id':aid,'action':(item.get('materials',{}).get('error') or {}).get('next_action','prepare_materials'),
                            'video_valid':flags['video_valid']})
        elif status['item_problems'][aid]:
            actions.append({'stage':'analysis','id':aid,'action':'read_full_text_and_visuals',
                            'problems':status['item_problems'][aid]})
    if status['ready']:
        receipt=root/'完成回执.json';done=read(receipt) if receipt.is_file() else {}
        file=Path(done.get('workbook',''))
        if not (done.get('input_sha256')==status['input_sha256'] and file.is_file() and c.digest(file)==done.get('workbook_sha256')):
            actions.append({'stage':'export','action':'export_reopen_review_and_commit'})
    return {'complete':not actions,'actions':actions,'counts':{k:status[k] for k in
            ('discovered','eligible','selected','metrics_verified','downloaded','materials_ready','analyses_verified')},'checked_at':now()}


def _resume(root,session=None,retry_failed=False,access_restored=False):
    batch=read(root/'batch.json');pending=pending_keywords(batch)
    if session and pending:
        cmd=[sys.executable,str(Path(__file__).with_name('collect_visible_search.py')),
             '--root',str(root),'--session',session]
        if access_restored:cmd.append('--access-restored')
        subprocess.run(cmd+pending,check=False)
    # No account refresh while the configured research session is restricted.
    batch=read(root/'batch.json')
    restricted=any(search_state(batch,k)['access_restricted'] for k in batch['keywords'])
    for pass_number in range(3):
        if pass_number:time.sleep(2**pass_number)
        if not restricted:c.enrich(root,retry_failed=retry_failed,access_restored=access_restored)
        db=c.refresh(root)
        if db['selected_ids']:c.prepare(root,retry_failed,access_restored,online_restricted=restricted)
        # Only temporary errors advance automatically. Content and access issues
        # remain explicit; failure budgets persist across invocations.
        retryable=[]
        for path in (root/'指标任务.json',root/'材料准备/材料队列.json'):
            if not path.is_file():continue
            jobs=read(path)['jobs'];jobs=jobs.values() if isinstance(jobs,dict) else jobs
            retryable.extend(j for j in jobs if j['status']=='failed' and
                (j.get('error') or {}).get('retryable') and sum(
                a.get('outcome') not in ('access_restricted','interrupted') for a in j['attempts'])<3)
        if not retryable:break
        access_restored=False
        retry_failed=False
    result=next_actions(root)
    save(root/'接续任务.json',result)
    return result


def resume(root,session=None,retry_failed=False,access_restored=False):
    from material_queue import locked
    with locked(root/'流程执行'):
        return _resume(root,session,retry_failed,access_restored)
