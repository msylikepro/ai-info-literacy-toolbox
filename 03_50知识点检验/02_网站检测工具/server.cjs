const http=require('node:http');
const fs=require('node:fs');
const path=require('node:path');
const {checkHttp,classify}=require('./checker.cjs');
const {Browser}=require('./browser.cjs');
const {AuditStore}=require('./audit.cjs');
const {ResourceStore,atomicJson,readJson}=require('./resource-store.cjs');
const DETECTOR_VERSION=2;
function csvCell(value){let s=String(value??'');if(/^[\s]*[=+@-]/.test(s)||/^[\t\r\n]/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"';}
function createApp(options={}){
const PORT=Number(options.port??process.env.CHECKER_PORT??8766);
if(!Number.isInteger(PORT)||PORT<1024||PORT>65535)throw new Error('端口必须为1024到65535之间的整数');
const ROOT=options.root||__dirname;const REPORTS=options.reports||(process.env.CHECKER_REPORTS_DIR?path.resolve(process.env.CHECKER_REPORTS_DIR):path.join(ROOT,'reports'));fs.mkdirSync(REPORTS,{recursive:true});
const KNOWLEDGE=options.knowledgeRoot||path.resolve(ROOT,'../04_网址导航网站/knowledge-links/dist');
const catalog=new ResourceStore({baseline:path.join(ROOT,'data/resources.json'),reports:REPORTS,migrations:path.join(ROOT,'data/resource-migrations.json')});const resources=catalog.rows;
const audits=new AuditStore(path.join(REPORTS,'manual-audits.json'),resources.map(r=>r.id));
if(audits.loadError)throw Error(audits.loadError);
const resultFile=path.join(REPORTS,'latest.json');let saved={results:{},reviews:{}};
if(fs.existsSync(resultFile))saved=readJson(resultFile);
if(!saved||typeof saved!=='object'||Array.isArray(saved)||!saved.results||typeof saved.results!=='object'||Array.isArray(saved.results)||!saved.reviews||typeof saved.reviews!=='object'||Array.isArray(saved.reviews))throw Error('历史检测结果格式不正确，原文件已保留');
const results=saved.results||{};const reviews=saved.reviews||{};
let job={status:'idle',total:0,done:0,active:[],startedAt:null,finishedAt:null,error:null};let controller;let engine;let scanPromise;const hostTimes=new Map();
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const availabilityNames={open:'可打开',login_gate:'打开到登录页',verification:'验证或访问受限',http_only:'仅确认网页响应',http_error:'HTTP错误',network_error:'网络或浏览器错误'};
const loginNames={required:'当前入口需要登录',partial:'页面可浏览，部分功能可能需登录',public_file:'公开文件，可直接读取',public_page:'页面可浏览，核心功能未确认',unknown:'尚无法判断'};
const reviewNames={required:'人工确认：需要登录',partial:'人工确认：部分功能需要登录',direct:'人工确认：可直接使用'};
function save(){const tmp=resultFile+'.tmp';fs.writeFileSync(tmp,JSON.stringify({updatedAt:new Date().toISOString(),job:{...job,active:[]},results,reviews},null,2));fs.renameSync(tmp,resultFile);}
function reloadAfterRollback(){
  catalog.assertReady();catalog.refresh();audits.syncIds(resources.map(r=>r.id));
  const restored=fs.existsSync(resultFile)?readJson(resultFile):{results:{},reviews:{}};
  for(const key of Object.keys(results))delete results[key];for(const key of Object.keys(reviews))delete reviews[key];
  Object.assign(results,restored.results||{});Object.assign(reviews,restored.reviews||{});
}
function invalidate(changes){
  // Keep the old URL and all decisions before any destructive reset. State is
  // committed last, so interrupted updates are safely reconciled on restart.
  audits.reload();if(audits.loadError)throw Error(audits.loadError);
  const affected=changes.filter(change=>Object.hasOwn(results,change.id)||Object.hasOwn(reviews,change.id)||Object.hasOwn(audits.items,change.id));
  if(!affected.length)return;
  const file=path.join(REPORTS,'resource-url-history.json');const history=fs.existsSync(file)?readJson(file):{version:1,entries:[]};
  if(history.version!==1||!Array.isArray(history.entries))throw Error('网址历史记录格式不正确，原文件已保留');
  const entries=affected.map(change=>({...change,archivedAt:new Date().toISOString(),result:results[change.id]||null,review:reviews[change.id]||'',audit:audits.get(change.id)}));
  atomicJson(file,{version:1,entries:[...history.entries,...entries]});
  audits.clear(affected.map(c=>c.id));const resultsChanged=affected.some(change=>Object.hasOwn(results,change.id)||Object.hasOwn(reviews,change.id));
  for(const change of affected){delete results[change.id];delete reviews[change.id];}if(resultsChanged)save();
}
catalog.reconcile(invalidate);
function rows(){return resources.map(resource=>{const stored=results[resource.id];let result=null;if(stored){const {observation,...summary}=stored;result={...summary,needsRecheck:stored.detectorVersion!==DETECTOR_VERSION};}return {...resource,result,review:reviews[resource.id]||'',audit:audits.get(resource.id)};});}
function stats(){const checked=Object.values(results);return {total:resources.length,checked:checked.length,audited:audits.count(),needsRecheck:checked.filter(r=>r.detectorVersion!==DETECTOR_VERSION).length,open:checked.filter(r=>['open','login_gate'].includes(r.availability)).length,restricted:checked.filter(r=>r.availability==='verification').length,failed:checked.filter(r=>['http_error','network_error'].includes(r.availability)).length,loginRequired:checked.filter(r=>r.login==='required').length};}
async function scan(ids,options){
  const run=job={status:'running',total:ids.length,done:0,active:[],startedAt:new Date().toISOString(),finishedAt:null,error:null};const abort=controller=new AbortController();let cursor=0;let terminal='completed';let localEngine;
  try{
    const instance=new Browser();try{localEngine=engine=await instance.start({signal:abort.signal});}catch(e){await instance.close();run.error='浏览器不可用，保留HTTP检测结果：'+e.message;}
    const worker=async()=>{
      while(cursor<ids.length&&!abort.signal.aborted){
        const id=ids[cursor++];const resource=resources.find(r=>r.id===id);run.active.push(id);
        const host=new URL(resource.url).hostname;const scheduled=Math.max(Date.now(),hostTimes.get(host)||0);hostTimes.set(host,scheduled+700);await sleep(Math.max(0,scheduled-Date.now()));
        if(abort.signal.aborted){run.active=run.active.filter(v=>v!==id);break;}
        const response=await checkHttp(resource.url,{timeoutMs:options.httpTimeout*1000,signal:abort.signal});
        let browser={browserAvailable:false,browserError:localEngine?'文件入口不需要网页渲染':'浏览器不可用'};
        if(localEngine&&!abort.signal.aborted&&!(response.status>=200&&response.status<300&&response.isPublicFile))browser=await localEngine.inspect(resource.url,{timeoutMs:options.browserTimeout*1000,signal:abort.signal});
        if(!abort.signal.aborted){
          const observation={...response,...(browser.browserAvailable?browser:{}),browserAvailable:browser.browserAvailable,browserError:browser.browserError,status:browser.status??response.status};
          const classification=classify(observation);
          const cancelled=abort.signal.aborted;
          if(!cancelled){results[id]={...classification,detectorVersion:DETECTOR_VERSION,checkedAt:new Date().toISOString(),httpStatus:response.status,browserStatus:browser.status??null,finalUrl:browser.finalUrl||response.finalUrl,title:browser.title||response.title||'',ttfbMs:response.ttfbMs??null,browserTtfbMs:browser.browserTtfbMs??null,domMs:browser.domMs??null,loadMs:browser.loadMs??null,elapsedMs:response.elapsedMs,inspectionMs:browser.inspectionMs??null,httpError:response.error||null,httpErrorKind:response.errorKind||null,browserError:browser.browserError||null,redirects:response.redirects||[],contentType:response.contentType||'',textPreview:observation.text?.slice(0,500)||'',observation:{status:observation.status,finalUrl:observation.finalUrl,title:observation.title,text:observation.text?.slice(0,60000),password:observation.password,isPublicFile:observation.isPublicFile,browserAvailable:observation.browserAvailable,browserError:observation.browserError,error:observation.error},browserChecked:!!browser.browserAvailable,loadComplete:!!browser.loadComplete};run.done++;}
        }
        run.active=run.active.filter(v=>v!==id);save();console.log(`${run.done}/${run.total} ${id} ${classificationLabel(results[id])}`);
      }
    };
    await Promise.all(Array.from({length:options.concurrency},()=>worker()));
    terminal=abort.signal.aborted?'cancelled':'completed';
  }catch(e){terminal=abort.signal.aborted?'cancelled':'failed';run.error=e.message;}
  finally{if(localEngine)await localEngine.close();if(engine===localEngine)engine=null;run.status=terminal;run.active=[];run.finishedAt=new Date().toISOString();save();fs.writeFileSync(path.join(REPORTS,'检测报告.html'),report());console.log('SCAN_FINISHED '+JSON.stringify({job:run,stats:stats()}));}
}
function classificationLabel(r){return r?availabilityNames[r.availability]+' / '+loginNames[r.login]:'已取消';}
const escape=s=>String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
function csv(){const out=[['人工审核','人工审核时间','编号','网站名称','网址','可访问性','账号要求（自动）','账号要求（人工）','HTTP状态','浏览器HTTP状态','HTTP首字节(ms)','浏览器首字节(ms)','DOM就绪(ms)','完整加载(ms)','最终地址','检测时间','依据','HTTP错误','浏览器提示']];for(const r of rows()){const d=r.result||{};out.push([r.audit.checked?'已审核':'未审核',r.audit.reviewedAt,r.id,r.title,r.url,availabilityNames[d.availability]||'未检测',loginNames[d.login]||'未检测',reviewNames[r.review]||'',d.httpStatus,d.browserStatus,d.ttfbMs,d.browserTtfbMs,d.domMs,d.loadMs,d.finalUrl,d.checkedAt,d.evidence?.join('；'),d.httpError,d.browserError]);}return '\uFEFF'+out.map(row=>row.map(csvCell).join(',')).join('\r\n');}
function report(){
  const summary=stats();
  return `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>${resources.length}个网址检测报告</title><style>body{font:14px/1.7 Microsoft YaHei,sans-serif;margin:30px;color:#21314c}table{border-collapse:collapse;width:100%}td,th{padding:10px;border:1px solid #dce3ed;text-align:left;vertical-align:top}a{color:#245cce;overflow-wrap:anywhere}.url{max-width:360px;word-break:break-all}small{display:block;color:#708198}</style><h1>网址检测报告</h1><p>导出时间：${new Date().toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})} · 已检测 ${summary.checked} / ${resources.length} · 已人工审核 ${summary.audited} / ${resources.length}</p><p>本机网络单次检测，页面可浏览不代表核心功能无需账号。HTTP首字节包含连接与跳转；DOM就绪是浏览器页面结构准备完成；空白耗时表示未测得。受验证码、网络限制或动态加载影响的结果应人工确认。人工审核勾选表示已人工查看。</p>${summary.needsRecheck?'<p style="background:#fff3df;padding:14px;color:#8c5d20">本报告包含初版检测结果，旧分类仅供初步参考，需要重测后更新。</p>':''}<table><thead><tr><th>人工审核</th><th>网站与网址</th><th>可访问性</th><th>HTTP首字节</th><th>DOM就绪</th><th>登录判断</th><th>判断依据</th></tr></thead><tbody>${rows().map(r=>{const d=r.result||{};return `<tr><td>${r.audit.checked?'已审核':'未审核'}<small>${escape(r.audit.reviewedAt?new Date(r.audit.reviewedAt).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'')}</small></td><td class="url">${escape(r.title)}<small><a href="${escape(r.url)}" target="_blank" rel="noopener">${escape(r.url)}</a></small></td><td>${escape(availabilityNames[d.availability]||'未检测')}<small>HTTP ${escape(d.httpStatus||'—')}</small></td><td>${d.ttfbMs==null?'—':(d.ttfbMs/1000).toFixed(2)+'秒'}</td><td>${d.domMs==null?'—':(d.domMs/1000).toFixed(2)+'秒'}</td><td>${escape(reviewNames[r.review]||loginNames[d.login]||'未检测')}</td><td>${escape(d.evidence?.join('；')||'')}<small>${escape(d.httpError||'')} ${escape(d.browserError||'')}</small></td></tr>`;}).join('')}</tbody></table></html>`;
}
const server=http.createServer(async(req,res)=>{
  const send=(code,data,type='application/json; charset=utf-8')=>{res.writeHead(code,{'Content-Type':type,'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});res.end(typeof data==='string'?data:JSON.stringify(data));};
  const url=new URL(req.url,'http://127.0.0.1:'+PORT);
  if(!['127.0.0.1:'+PORT,'localhost:'+PORT].includes(req.headers.host))return send(403,{error:'仅接受本机请求'});
  try{
    if(req.method==='GET'){
      if(url.pathname==='/api/health')return send(200,{app:'info-literacy-checker',port:PORT});
      if(url.pathname==='/api/resources')return send(200,{rows:rows()});
      if(url.pathname==='/api/state')return send(200,{job,stats:stats(),rows:rows(),auditError:audits.loadError});
      if(url.pathname==='/export/report.html')return send(200,report(),'text/html; charset=utf-8');
      if(url.pathname==='/export/results.csv'){res.setHeader('Content-Disposition','attachment; filename="website-check-results.csv"');return send(200,csv(),'text/csv; charset=utf-8');}
      if(url.pathname==='/export/results.json'){res.setHeader('Content-Disposition','attachment; filename="website-check-results.json"');return send(200,{exportedAt:new Date().toISOString(),job,rows:rows()});}
      const knowledgeFile={'/knowledge/':'index.html','/knowledge/style.css':'style.css','/knowledge/app.js':'app.js'}[url.pathname];
      if(knowledgeFile){if(!fs.existsSync(path.join(KNOWLEDGE,knowledgeFile)))return send(404,{error:'知识资料导航页面不存在，请重新解压完整工具包'});return send(200,fs.readFileSync(path.join(KNOWLEDGE,knowledgeFile),'utf8'),knowledgeFile.endsWith('.js')?'text/javascript; charset=utf-8':knowledgeFile.endsWith('.css')?'text/css; charset=utf-8':'text/html; charset=utf-8');}
      const file={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}[url.pathname];if(file)return send(200,fs.readFileSync(path.join(ROOT,'public',file),'utf8'),file.endsWith('.js')?'text/javascript; charset=utf-8':file.endsWith('.css')?'text/css; charset=utf-8':'text/html; charset=utf-8');
      return send(404,{error:'页面不存在'});
    }
    if(req.method!=='POST')return send(405,{error:'不支持此请求方式'});
    if(req.headers.origin&&!['http://127.0.0.1:'+PORT,'http://localhost:'+PORT].includes(req.headers.origin))return send(403,{error:'仅允许本机界面操作'});
    let body='';for await(const chunk of req){body+=chunk;if(body.length>32768)return send(413,{error:'请求过大'});}const input=JSON.parse(body||'{}');
    if(!['/api/cancel','/api/shutdown'].includes(url.pathname))catalog.assertReady();
    if(['/api/resources/add','/api/resources/update'].includes(url.pathname)){
      if(job.status==='running'||job.status==='cancelling')return send(409,{error:'检测正在运行，请结束检测后再编辑网址资料'});
      let resource;try{resource=url.pathname.endsWith('/add')?catalog.add(input,invalidate):catalog.update(input,invalidate);}
      catch(error){reloadAfterRollback();throw error;}
      audits.syncIds(resources.map(r=>r.id));return send(200,{saved:true,resource,rows:rows()});
    }
    if(url.pathname==='/api/start'){
      if(job.status==='running'||job.status==='cancelling')return send(409,{error:'已有检测正在运行'});
      const ids=input.ids??resources.map(r=>r.id);if(!Array.isArray(ids)||ids.length===0||ids.some(id=>!Number.isInteger(id)||!resources.some(r=>r.id===id)))return send(400,{error:'请选择有效网址'});
      const bounded=(value,fallback,min,max)=>{const n=Number(value??fallback);return Number.isInteger(n)&&n>=min&&n<=max?n:fallback;};
      scanPromise=scan([...new Set(ids)],{concurrency:bounded(input.concurrency,4,1,6),httpTimeout:bounded(input.httpTimeout,12,3,30),browserTimeout:bounded(input.browserTimeout,16,5,30)});return send(202,{started:true,total:new Set(ids).size});
    }
    if(url.pathname==='/api/cancel'){controller?.abort();if(job.status==='running')job.status='cancelling';return send(200,{cancelled:true});}
    if(url.pathname==='/api/audit'){const audit=audits.set(input.id,input.checked);return send(200,{saved:true,audit,audited:audits.count()});}
    if(url.pathname==='/api/review'){if(!resources.some(r=>r.id===input.id)||!['','required','partial','direct'].includes(input.value))return send(400,{error:'标注无效'});reviews[input.id]=input.value;save();return send(200,{saved:true});}
    if(url.pathname==='/api/shutdown'){controller?.abort();send(200,{closed:true});setTimeout(async()=>{if(engine)await engine.close();server.close();process.exit(0);},200);return;}
    send(404,{error:'接口不存在'});
  }catch(e){send(400,{error:e.message});}
});
async function close(){controller?.abort();if(job.status==='running')job.status='cancelling';if(scanPromise)await scanPromise;if(engine)await engine.close();if(server.listening)await new Promise(resolve=>server.close(resolve));}
return {server,report,stats,rows,close,port:PORT};
}
if(require.main===module){
  const {server,close,port:PORT}=createApp();
  server.on('error',error=>{console.error(error.code==='EADDRINUSE'?`端口 ${PORT} 已被占用。若工具已经启动，请使用已有窗口；否则换一个端口。`:error.message);process.exitCode=1;});
  server.listen(PORT,'127.0.0.1',()=>{
    console.log('网址检测工具已启动。');
    console.log(`请在浏览器打开：http://127.0.0.1:${PORT}`);
    console.log('保持此窗口打开。点击界面的“退出工具”或按 Ctrl+C 结束。');
    console.log('启动后不会自动联网扫描；点击“检测全部网址”才开始检测。');
  });
  const stop=async()=>{await close();process.exit(0);};process.on('SIGINT',stop);process.on('SIGTERM',stop);
}
module.exports={csvCell,createApp};
