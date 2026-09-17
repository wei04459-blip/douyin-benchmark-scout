import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
const argv=process.argv.slice(2);const args={};for(let i=0;i<argv.length;i+=2)args[argv[i].replace(/^--/,'')]=argv[i+1];
for(const k of ['root','analysis','output','python','modules'])if(!args[k])throw new Error(`Missing --${k}`);
const root=path.resolve(args.root), analysis=path.resolve(args.analysis), output=path.resolve(args.output);
try {await fs.access(output);throw new Error('Output exists; use a new version');}catch(e){if(e.code!=='ENOENT')throw e;}
const script=path.join(args.scripts || path.dirname(fileURLToPath(import.meta.url)),'research_batch.py');
function execute(cmd){const r=spawnSync(args.python,[script,...cmd],{encoding:'utf8',timeout:1800000,env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});if(r.status!==0)throw new Error(r.stderr||r.stdout||String(r.error));}
execute(['verify','--root',root,'--analysis',analysis]);
const req=createRequire(path.join(path.resolve(args.modules),'../package.json'));
const {Workbook,SpreadsheetFile,FileBlob}=await import(req.resolve('@oai/artifact-tool'));
const batch=JSON.parse(await fs.readFile(path.join(root,'batch.json'),'utf8'));const data=JSON.parse(await fs.readFile(analysis,'utf8'));
const hash=b=>createHash('sha256').update(b).digest('hex');
const before={batch_sha256:hash(await fs.readFile(path.join(root,'batch.json'))),analysis_sha256:hash(await fs.readFile(analysis))};
const wb=Workbook.create();let tableIndex=0;const renders=[];
const textValue=v=>typeof v==='string'&&/^[=+@]/.test(v)?"'"+v:v;
function sheet(name,title,subtitle,headers,rows,widths,heights=65){
 const s=wb.worksheets.add(name);s.showGridLines=false;
 const range=s.getRangeByIndexes(0,0,Math.max(rows.length+4,5),headers.length);range.format.font={name:'Arial',size:11};range.format.verticalAlignment='top';range.format.wrapText=true;
 widths.forEach((w,i)=>s.getRangeByIndexes(0,i,rows.length+4,1).format.columnWidthPx=w);
 s.getCell(0,0).values=[[title]];s.getCell(0,0).format.font={size:16,bold:true};s.getRangeByIndexes(0,0,1,headers.length).format.rowHeightPx=54;
 s.getCell(1,widths[0]<160?1:0).values=[[subtitle]];s.getRangeByIndexes(1,0,1,headers.length).format.rowHeightPx=64;
 // Keep headings and context unmerged; place short context within first wide column.
 s.getRangeByIndexes(3,0,1,headers.length).values=[headers];s.getRangeByIndexes(3,0,1,headers.length).format={fill:'#25374A',font:{color:'#FFFFFF',bold:true},rowHeightPx:38,wrapText:true};
 if(rows.length)s.getRangeByIndexes(4,0,rows.length,headers.length).values=rows.map(r=>r.map(textValue));
 s.getRangeByIndexes(4,0,Math.max(1,rows.length),headers.length).format.rowHeightPx=heights;
 rows.forEach((r,j)=>{const lines=r.map((v,c)=>String(v??'').split('\n').reduce((sum,line)=>sum+Math.max(1,Math.ceil([...line].reduce((w,ch)=>w+(ch.charCodeAt(0)>255?15:8),0)/Math.max(20,widths[c]-10))),0));s.getRangeByIndexes(j+4,0,1,headers.length).format.rowHeightPx=Math.max(heights,Math.max(...lines)*24+18);});
 if(rows.length){s.tables.add(`A4:${String.fromCharCode(64+headers.length)}${rows.length+4}`,true,'ResearchTable'+(++tableIndex));}
 if(rows.length>8)s.freezePanes.freezeRows(4);
 renders.push([name,Math.min(rows.length+4,name==='一周选题'?11:10),headers.length]);return s;
}
if(data.week_topics?.length){
 const topics=data.week_topics;
 sheet('一周选题','一周选题','先完成实践，再拍真实结果；尚未执行的内容为建议',['顺序','拟定标题','切入点','拍摄提纲','拍摄前准备','如何复盘','参考作品'],topics.map(t=>[t.day,t.title,t.angle,t.outline,t.prepare,t.measure,'https://www.douyin.com/video/'+t.source]),[110,340,310,550,480,430,330],160);
}
const scope=[['研究问题',batch.question],['入选范围',`${batch.items.length} 条作品，${batch.selection_scope || batch.question}。搜索观察与精读样本分别统计。`],['审核方法','全文语音转录、字幕交叉核对、关键画面查看、可定位引用。不是逐字听校。'],['事实边界','收入、效果、脑科学等作者主张不因内容审核而成为事实。传播解释为待验证假设。'],['数据口径',batch.selection_scope || '互动为观察时点公开快照。粉丝缺失留空，不推断低粉，也不能据此推断自然流量。'],['历史材料','历史Excel不覆盖，未纳入本批的旧条目不自动通过新版审核。']];
sheet('研究范围','竞品内容研究','本批材料与观察范围',['项目','说明'],scope,[220,800],65);
const metrics=batch.items.map(i=>["'"+i.aweme_id,i.title.split("\n")[0],i.nickname,i.source_duration_seconds,i.media_duration_seconds,i.liked_count??null,i.follower_count??null,null,i.metrics_observed_at?new Date(i.metrics_observed_at):null,i.metrics_note??'',i.url,i.collected_count??null,i.comment_count??null,i.share_count??null,new Date(i.create_time*1000)]);
const ms=sheet('作品数据','作品与公开指标','互动为采集快照；缺失粉丝留空',['作品ID','标题首段','账号','来源时长','媒体时长','点赞','粉丝约数','赞粉比','观察日期','指标说明','原页面','收藏','评论','分享','发布时间（UTC）'],metrics,[180,350,180,95,95,90,100,90,180,220,330,90,90,90,180],110);
for(let j=0;j<metrics.length;j++){let row=j+5;ms.getCell(j+4,7).formulas=[[`=IF(OR(F${row}="",G${row}="",G${row}=0),"",F${row}/G${row})`]];}
ms.getRangeByIndexes(4,0,metrics.length,1).setNumberFormat('@');ms.getRangeByIndexes(4,8,metrics.length,1).setNumberFormat('yyyy-mm-dd hh:mm');
ms.getRangeByIndexes(4,3,metrics.length,2).setNumberFormat('0.00');ms.getRangeByIndexes(4,5,metrics.length,2).setNumberFormat('#,##0');ms.getRangeByIndexes(4,7,metrics.length,1).setNumberFormat('0.0%');
ms.getRangeByIndexes(4,11,metrics.length,3).setNumberFormat('#,##0');ms.getRangeByIndexes(4,14,metrics.length,1).setNumberFormat('yyyy-mm-dd hh:mm');
const names={topic_summary:'选题概括',hook:'开头',structure:'结构',emotion:'情绪',summary:'内容与事实边界',viral:'传播假设',migration:'可测试的借鉴'};const content=[],quotes=[],transcripts=[];
for(const i of batch.items){const a=data.items[i.aweme_id];for(const [k,label]of Object.entries(names)){const refs=a.evidence_review.references.filter(r=>r.field===k);content.push([i.nickname,label,a[k],refs.map(r=>`${r.start.toFixed(1)}–${r.end.toFixed(1)}秒`).join('\n'),i.url]);}
 for(const r of a.evidence_review.references)quotes.push([i.nickname,names[r.field],r.start,r.end,r.quote,i.url]);
 const t=JSON.parse(await fs.readFile(i.transcript_path.replace(/\.txt$/,'.json'),'utf8'));for(const s of t.segments)transcripts.push([i.nickname,s.start,s.end,s.text]);
}
sheet('内容拆解','内容拆解','观点和借鉴均以原材料为依据',['账号','分析项','分析内容','证据位置','原页面'],content,[180,125,670,180,330],150);
const qs=sheet('引用证据','分析引用','引用对应校对稿的分段；单位为秒',['账号','分析项','开始','结束','校对原文','原页面'],quotes,[180,125,80,80,600,330],85);qs.getRangeByIndexes(4,2,quotes.length,2).setNumberFormat('0.00');
const ts=sheet('校对文本','全文校对稿','非逐字听校；不清楚的片段保留标注',['账号','开始秒','结束秒','文本'],transcripts,[210,90,90,820],60);ts.getRangeByIndexes(4,1,transcripts.length,2).setNumberFormat('0.00');
const searches=[];for(const o of batch.searches){if(!o.cards?.length)searches.push([o.keyword,o.query,o.status,'','','',o.observed_at,o.page_url]);for(const c of o.cards??[])searches.push([o.keyword,o.query,({'results_observed':'已见结果','confirmed_empty':'明确零结果','retrieval_failed':'检索失败','retrieval_unverified':'尚未核实','access_restricted':'访问受限'}[o.status]??o.status),c.title,c.author??c.nickname??'',c.form??'',new Date(o.observed_at),o.page_url]);}
const ss=sheet('搜索观察','搜索观察记录','可见卡片不是已审核的精读作品',['关键词','实际查询','检索状态','可见结果标题','作者','形式','记录时间（UTC）','来源'],searches,[180,140,165,540,180,90,210,300],110);ss.getRangeByIndexes(4,6,searches.length,1).setNumberFormat('yyyy-mm-dd hh:mm');
for(const [name,rows,cols]of renders){const preview=await wb.render({sheetName:name,range:`A1:${String.fromCharCode(64+cols)}${rows}`,scale:1,format:'png'});await fs.mkdir(path.join(root,'预览'),{recursive:true});await fs.writeFile(path.join(root,'预览',name+'.png'),new Uint8Array(await preview.arrayBuffer()));}
const check=await wb.inspect({kind:'table',range:'作品数据!A4:H6',include:'values,formulas',tableMaxRows:3,tableMaxCols:8});await fs.writeFile(path.join(root,'关键数据检查.txt'),check.ndjson);
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:30},summary:'Formula scan'});await fs.writeFile(path.join(root,'公式检查.txt'),errors.ndjson);
await fs.mkdir(path.dirname(output),{recursive:true});const file=await SpreadsheetFile.exportXlsx(wb);await file.save(output);
const reopened=await SpreadsheetFile.importXlsx(await FileBlob.load(output));
const actual=reopened.worksheets.getItem('作品数据').getRangeByIndexes(4,0,batch.items.length,1).values.map(x=>String(x[0]).replace(/^'/,''));
if(JSON.stringify(actual)!==JSON.stringify(batch.items.map(i=>i.aweme_id)))throw new Error('Reopened IDs mismatch');
const reopenedText=reopened.worksheets.getItem('内容拆解').getRangeByIndexes(4,2,content.length,1).values.map(x=>x[0]);if(JSON.stringify(reopenedText)!==JSON.stringify(content.map(x=>x[2])))throw new Error('Reopened analysis mismatch');
if(data.week_topics?.length){const titles=reopened.worksheets.getItem('一周选题').getRangeByIndexes(4,1,data.week_topics.length,1).values.map(x=>x[0]);if(JSON.stringify(titles)!==JSON.stringify(data.week_topics.map(t=>t.title)))throw new Error('Reopened topics mismatch');}
const savedMetrics=reopened.worksheets.getItem('作品数据').getRangeByIndexes(4,11,batch.items.length,3).values;for(let j=0;j<batch.items.length;j++){const i=batch.items[j];if(JSON.stringify(savedMetrics[j])!==JSON.stringify([i.collected_count??null,i.comment_count??null,i.share_count??null]))throw new Error('Reopened metrics mismatch');}
const ratios=reopened.worksheets.getItem('作品数据').getRangeByIndexes(4,7,batch.items.length,1).values;for(let j=0;j<batch.items.length;j++){const i=batch.items[j];if(i.follower_count&&i.liked_count!=null&&Math.abs(Number(ratios[j][0])-i.liked_count/i.follower_count)>1e-9)throw new Error('Reopened ratio mismatch');}
const receipt={...before,reopened:true,ids:actual,workbook_sha256:hash(await fs.readFile(output)),created_at:new Date().toISOString()};const rp=path.join(root,'导出回执.json');await fs.writeFile(rp,JSON.stringify(receipt,null,2));
// Final completion is committed after the agent visually checks previews.
console.log(JSON.stringify({output,receipt:rp,rows:actual.length,commit_pending_visual_review:true}));
