import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
const args={};for(let j=2;j<process.argv.length;j+=2)args[process.argv[j].slice(2)]=process.argv[j+1];
for(const k of ['root','output','python','modules'])if(!args[k])throw Error(`Missing --${k}`);
const root=path.resolve(args.root),output=path.resolve(args.output),here=path.dirname(fileURLToPath(import.meta.url));
try{await fs.access(output);throw Error('目标已存在，请保存新版本');}catch(e){if(e.code!=='ENOENT')throw e;}
const v=spawnSync(args.python,[path.join(here,'collection.py'),'--root',root,'verify'],{encoding:'utf8',timeout:300000});
if(![0,2].includes(v.status))throw Error(v.stderr||v.stdout);
const read=async p=>JSON.parse(await fs.readFile(p,'utf8'));
const status=await read(path.join(root,'收集验收.json'));if(args['require-complete']&&!status.ready)throw Error('尚有缺项，不能输出完整验收版');
const db=await read(path.join(root,'竞品库.json')),batch=await read(path.join(root,'batch.json'));
const items=db.selected_ids.map(a=>db.items[a]);
const require=createRequire(path.join(path.resolve(args.modules),'../package.json'));
const {Workbook,SpreadsheetFile,FileBlob}=await import(require.resolve('@oai/artifact-tool'));
const wb=Workbook.create();let tn=0;const previews=[];
function col(n){let s='';for(n++;n>0;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;}
function safe(v){return typeof v==='string'&&/^[=+@]/.test(v)?"'"+v:v;}
function add(name,headers,rows,widths,title,subtitle,previewRange){
 const s=wb.worksheets.add(name);s.showGridLines=false;const total=Math.max(rows.length+4,6);
 s.getRangeByIndexes(0,0,total,headers.length).format={font:{name:'Arial',size:11},verticalAlignment:'top',wrapText:true};
 widths.forEach((w,c)=>s.getRangeByIndexes(0,c,total,1).format.columnWidthPx=w);
 const titleCol=widths.findIndex(w=>w>=280);const tc=titleCol<0?0:titleCol;
 s.getCell(0,tc).values=[[title]];s.getCell(0,tc).format.font={size:17,bold:true,color:'#183B4B'};
 s.getRangeByIndexes(0,0,1,headers.length).format.rowHeightPx=60;
 s.getCell(1,tc).values=[[subtitle]];s.getRangeByIndexes(1,0,1,headers.length).format.rowHeightPx=84;
 s.getRangeByIndexes(3,0,1,headers.length).values=[headers];s.getRangeByIndexes(3,0,1,headers.length).format={fill:'#203D4A',font:{bold:true,color:'#FFFFFF'},rowHeightPx:48,wrapText:true};
 if(rows.length){s.getRangeByIndexes(4,0,rows.length,headers.length).values=rows.map(row=>row.map(safe));s.tables.add(`A4:${col(headers.length-1)}${rows.length+4}`,true,'CollectionTable'+(++tn));}
 rows.forEach((row,r)=>{
  let lines=Math.max(...row.map((v,c)=>v instanceof Date?1:String(v??'').split('\n').reduce((n,line)=>n+Math.max(1,Math.ceil([...line].reduce((x,ch)=>x+(ch.charCodeAt(0)>255?13:7),0)/Math.max(20,widths[c]-14))),0)));
  s.getRangeByIndexes(r+4,0,1,headers.length).format.rowHeightPx=Math.max(50,lines*21+16);
 });
 s.freezePanes.freezeRows(4);previews.push([name,previewRange||`A1:${col(headers.length-1)}${Math.min(rows.length+4,7)}`]);return s;
}
const rules=batch.breakout_rules;
const ruleRows=[['S粉丝上限',rules.s_max_fans,'S需同时满足粉丝、点赞、赞粉比'],['S点赞下限',rules.s_min_likes,'包含边界'],['S赞粉比下限',rules.s_min_like_fan_ratio,'点赞÷当前观察粉丝'],['A粉丝上限',rules.a_max_fans,'先判断S，再判断A'],['A点赞下限',rules.a_min_likes,'包含边界'],['A赞粉比下限',rules.a_min_like_fan_ratio,'点赞÷当前观察粉丝'],['C粉丝下限',rules.big_account_fans,'大号且赞粉比较低'],['C赞粉比上限',rules.big_account_ratio_ceiling,'小于此值，不含边界'],['时间窗口天数',batch.filter.days,'以批次开始时点回溯'],['初筛点赞下限',batch.filter.min_likes,'点赞、收藏、评论三个门槛满足一个即可'],['初筛收藏下限',batch.filter.min_favorites,'或条件'],['初筛评论下限',batch.filter.min_comments,'或条件'],['默认收集目标',db.target,'合格视频数，独立于每次下载数量'],['比率解释','互动/粉丝=(赞+评+藏+转)/粉丝','是互动次数比，不是独立用户参与率'],['分级用途','S/A优先研究；B保留方法；C观察大号表达','不能由赞粉比证明自然推荐、收入或传播因果'],['阅读深度','全文初读与关键画面核对','语音稿可能仍有非关键同音错词；画面文字另标来源'],['更新时间','指标是本次公开观察快照','粉丝是当前值，不是作品发布当日粉丝；未取得播放量'],['后续更新','修改数据或阈值后重新运行导出','主表比率与等级为公式；重点账号成员是本次导出快照']];
// Main contract is deliberately first, followed by the original priority-account view.
const headers=['序号','内容方向/赛道','视频链接','账号名','账号粉丝数','账号总获赞','视频发布时间','视频时长（秒）','视频点赞','视频评论','视频收藏','视频转发','收藏/点赞比','视频标题','内容关键词','选题类型','选题概括','开头钩子/模式','内容结构','情绪设计','内容摘要与事实边界','爆款归因','账号可迁移思路','命中搜索关键词','完整口播稿路径','本地视频状态','赞粉比','互动/粉丝比','爆款等级','判断依据'];
const accepted=i=>!(status.item_problems[i.aweme_id]||[]).length;
const rows=items.map((i,n)=>{const a=accepted(i)?i.analysis:{},m=i.materials||{};return[n+1,a.track??'',i.url,i.nickname,i.follower_count??null,i.total_favorited??null,new Date(i.create_time*1000),i.source_duration_seconds,i.liked_count??null,i.comment_count??null,i.collected_count??null,i.share_count??null,null,i.title,a.topics??'',a.type??'',a.topic_summary??'',a.hook??'',a.structure??'',a.emotion??'',a.summary??'',a.viral??'',a.migration??'',i.source_keywords.join('、'),m.transcript_path??'',status.material_status[i.aweme_id]?.text_valid?'下载完整；文本已准备':'待准备或失败',null,null,'',i.grade_reason];});
const widths=[60,170,330,180,110,125,135,95,100,95,95,95,100,360,230,180,310,360,440,280,450,400,400,230,390,195,105,115,180,270];
const main=add('竞品选题分析',headers,rows,widths,'AI竞品收集',`${db.target}条为本轮目标；按S/A优先排序。每行对应一个真实作品。`,'A3:M7');
main.freezePanes.freezeColumns(4);
previews.push(['竞品选题分析','N3:W6']);previews.push(['竞品选题分析','X3:AD7']);

if(items.length){main.getRangeByIndexes(4,4,items.length,2).setNumberFormat('#,##0');main.getRangeByIndexes(4,8,items.length,4).setNumberFormat('#,##0');main.getRangeByIndexes(4,6,items.length,1).setNumberFormat('yyyy-mm-dd');main.getRangeByIndexes(4,7,items.length,1).setNumberFormat('0.0');for(const c of [12,26,27])main.getRangeByIndexes(4,c,items.length,1).setNumberFormat('0.0%');}
const creators=new Map();for(const i of items.filter(i=>/^[SA]/.test(i.grade))){const key=i.creator_id||i.sec_uid;if(!key)throw Error('Priority creator missing identity');const old=creators.get(key);if(!old||i.liked_count/i.follower_count>old.liked_count/old.follower_count)creators.set(key,i);}
const priority=[...creators.values()].sort((a,b)=>a.grade[0].localeCompare(b.grade[0])*-1||b.liked_count/b.follower_count-a.liked_count/a.follower_count);
const pr=add('重点关注账号',['账号','方向','粉丝','总获赞','代表视频','点赞','赞粉比','等级','值得观察什么','主页','视频链接'],priority.map(i=>[i.nickname,i.analysis?.track||'',i.follower_count,i.total_favorited,i.title,i.liked_count,i.liked_count/i.follower_count,i.grade,accepted(i)?i.analysis.migration:'待初步分析',i.creator_url,i.url]),[190,180,110,120,350,100,110,170,400,330,330],`重点账号 ${priority.length} 个`,'只含S/A；同一账号取赞粉比最高的代表作。','A1:I7');
if(priority.length){pr.getRangeByIndexes(4,2,priority.length,2).setNumberFormat('#,##0');pr.getRangeByIndexes(4,5,priority.length,1).setNumberFormat('#,##0');pr.getRangeByIndexes(4,6,priority.length,1).setNumberFormat('0.0%');}
const stages=add('材料与分析状态',['账号','标题','指标观察时间（UTC）','视频','文本来源','初读状态','缺项或说明','文本文件','本地视频','作品ID'],items.map(i=>{let m=i.materials||{},a=i.analysis||{},p=status.item_problems[i.aweme_id]||[];return[i.nickname,i.title,new Date(i.metrics_observed_at),status.material_status[i.aweme_id]?.video_valid?'已验收保存':'未完成或已变化',m.source_type==='visual'?'画面文字，非口播':m.source_type==='mixed'?'画面与语音记录，非完整口播':m.transcript_path?'语音转录，非逐字听校':'未完成',p.length?'待处理':'初步分析已核对',p.length?p.join('；'):a.evidence_review?.quality_notes||'',m.transcript_path||'',m.video_path||'',"'"+i.aweme_id];}),[190,340,170,145,220,165,480,390,390,195],'材料处理记录',`入选${status.selected}；指标${status.metrics_verified}；视频${status.downloaded}；文本${status.materials_ready}；初读通过${status.analyses_verified}。`,'A1:G7');
if(items.length)stages.getRangeByIndexes(4,2,items.length,1).setNumberFormat('yyyy-mm-dd hh:mm');
const refs=[];for(const i of items){if(!accepted(i))continue;for(const r of i.analysis.evidence_review.references||[])refs.push([i.nickname,({hook:'开头',structure:'结构',summary:'摘要'}[r.field]||r.field),r.start,r.end,r.quote,i.url,i.analysis.evidence_review.visual_evidence||'已在原批次核对关键画面']);}
const refsheet=add('引用与画面依据',['账号','对应判断','开始秒','结束秒','依据原文','原视频','关键画面'],refs,[190,120,85,85,610,340,420],'分析依据','时间对应本地文本分段；画面文字和语音稿在材料表注明。','A1:F9');if(refs.length)refsheet.getRangeByIndexes(4,2,refs.length,2).setNumberFormat('0.0');
const reasons={target_reached:'达到本词目标',content_exhausted:'结果区明确结束',stalled:'连续加载无新增',time_budget:'达到时间上限',scroll_budget:'达到滚动上限',empty_after_progress:'前后结果矛盾，待核实',access_restricted:'访问受限',retrieval_failed:'本次读取失败',retrieval_unverified:'本次未能核实'};
const obs=batch.keywords.map(k=>{const o=batch.searches.filter(o=>o.keyword===k).at(-1),s=status.search_states.find(s=>s.keyword===k);const hit=Object.values(db.items).filter(i=>i.source_keywords?.includes(k));return[k,o?.query||'',({'results_observed':'已见结果','confirmed_empty':'明确零结果','access_restricted':'访问受限','retrieval_failed':'检索失败','retrieval_unverified':'未能核实','exact_query_pending':'原词待核实'}[s.status]||'待搜索'),hit.length,hit.filter(i=>db.selected_ids.includes(i.aweme_id)).length,s.attempts,o?.observed_at?new Date(o.observed_at):null,s.scope_complete?'已完成本词范围':'范围未完成',reasons[s.stop_reason]||s.stop_reason||(s.scope_complete?'沿用旧批次口径':'尚未结束'),o?.page_url||''];});
const os=add('搜索覆盖',['关键词','实际查询','页面状态','去重命中','入选命中','尝试次数','最后观察（UTC）','搜索范围','停止原因','页面'],obs,[280,180,150,110,110,110,190,175,260,460],`${batch.keywords.length}词搜索覆盖`,'看到结果不等于搜完。同一作品可命中多个词，命中数不能相加当总数。','A1:I10');if(obs.length)os.getRangeByIndexes(4,6,obs.length,1).setNumberFormat('yyyy-mm-dd hh:mm');
add('全部候选',['账号','标题摘录','作品链接','命中词','相关性或筛选理由','本轮入选','粉丝','点赞','收藏','评论'],Object.values(db.items).sort((a,b)=>b.preliminary_score-a.preliminary_score).map(i=>[i.nickname,i.title.length>220?i.title.slice(0,220)+'…':i.title,i.url,i.source_keywords.join('、'),i.filter_reason,db.selected_ids.includes(i.aweme_id)?'是':'否',i.follower_count??null,i.liked_count??null,i.collected_count??null,i.comment_count??null]),[190,430,340,230,370,100,100,100,100,100],`${Object.keys(db.items).length}条去重候选`,'未达到门槛或不相关的来源也保留，便于追查漏项与筛选原因。','A1:F8');
const rs=add('筛选规则',['规则','数值或口径','解释'],ruleRows,[240,360,630],'筛选与阅读口径','阈值延续历史Excel；比率及主表等级由公式计算。','A1:C12');for(const r of [6,9,11])rs.getCell(r,1).setNumberFormat('0.0%');
for(let n=0;n<items.length;n++){
 let r=n+5;main.getCell(n+4,12).formulas=[[`=IF(OR(I${r}="",I${r}=0,K${r}=""),"",K${r}/I${r})`]];
 main.getCell(n+4,26).formulas=[[`=IF(OR(E${r}="",E${r}=0,I${r}=""),"",I${r}/E${r})`]];
 main.getCell(n+4,27).formulas=[[`=IF(OR(E${r}="",E${r}=0,I${r}="",J${r}="",K${r}="",L${r}=""),"",SUM(I${r}:L${r})/E${r})`]];
 main.getCell(n+4,28).formulas=[[`=IF(AA${r}="","待补指标",IF(AND(E${r}<='筛选规则'!$B$5,I${r}>='筛选规则'!$B$6,AA${r}>='筛选规则'!$B$7),"S｜低粉高爆",IF(AND(E${r}<='筛选规则'!$B$8,I${r}>='筛选规则'!$B$9,AA${r}>='筛选规则'!$B$10),"A｜重点观察",IF(AND(E${r}>='筛选规则'!$B$11,AA${r}<'筛选规则'!$B$12),"C｜大号常规流量","B｜常规样本"))))`]];
}
const pd=path.join(root,'预览');await fs.mkdir(pd,{recursive:true});let pi=0;for(const [name,range]of previews){pi++;if(args['preview-sheets']&&!args['preview-sheets'].split(',').includes(name))continue;const blob=await wb.render({sheetName:name,range,scale:1,format:'png'});await fs.writeFile(path.join(pd,`${pi}_${name}.png`),new Uint8Array(await blob.arrayBuffer()));}
const scan=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:30},summary:'公式错误检查'});await fs.writeFile(path.join(root,'公式检查.txt'),scan.ndjson);
if(args['preview-only']){console.log(JSON.stringify({preview_only:true,sheets:previews.length}));process.exit(0);}
await fs.mkdir(path.dirname(output),{recursive:true});await (await SpreadsheetFile.exportXlsx(wb)).save(output);
const reopened=await SpreadsheetFile.importXlsx(await FileBlob.load(output));const rm=reopened.worksheets.getItem('竞品选题分析');
const assert=(ok,message)=>{if(!ok)throw Error(message);};
assert(JSON.stringify(rm.getRange('A4:AD4').values[0])===JSON.stringify(headers),'30列表头不一致');
const values=items.length?rm.getRangeByIndexes(4,0,items.length,30).values:[];
for(let n=0;n<items.length;n++){let i=items[n],r=values[n];assert(r[2]===i.url,'视频链接不一致');assert(r[4]===i.follower_count&&r[8]===i.liked_count,'数字不一致');assert(Math.abs(Number(r[26])-i.liked_count/i.follower_count)<1e-9,'赞粉比不一致');assert(r[28]===i.grade,'分级不一致');for(let c=16;c<=22;c++)assert(r[c]===rows[n][c],'初步分析不一致');}
assert(new Set(values.map(r=>r[2])).size===items.length,'视频重复');
const pnames=priority.length?reopened.worksheets.getItem('重点关注账号').getRangeByIndexes(4,0,priority.length,1).values.map(r=>r[0]):[];assert(JSON.stringify(pnames)===JSON.stringify(priority.map(i=>i.nickname)),'重点账号不一致');
const searchValues=reopened.worksheets.getItem('搜索覆盖').getRangeByIndexes(4,0,obs.length,10).values;
for(let n=0;n<obs.length;n++)for(const c of [0,2,3,4,5,7,8])assert(searchValues[n][c]===obs[n][c],'搜索范围或停止原因导出不一致');
const hash=b=>createHash('sha256').update(b).digest('hex');
await fs.writeFile(path.join(root,'导出回执.json'),JSON.stringify({input_sha256:status.input_sha256,workbook_sha256:hash(await fs.readFile(output)),ids:items.map(i=>i.aweme_id),priority_accounts:priority.length,reopened:true,visual_reviewed:false,complete:status.ready,created_at:new Date().toISOString()},null,2));
console.log(JSON.stringify({output,rows:items.length,priority_accounts:priority.length,complete:status.ready,visual_review_pending:true}));
