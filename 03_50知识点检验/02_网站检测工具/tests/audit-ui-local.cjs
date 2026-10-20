// 独立临时报告目录，只访问本地界面，测试数据不会写入用户的审核记录。
const {spawn}=require('node:child_process');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const net=require('node:net');
const assert=require('node:assert/strict');
const {Browser,CDP}=require('../browser.cjs');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
const root=path.resolve(__dirname,'..');
(async()=>{
  const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'checker-review-ui-'));
  const original=path.join(root,'reports/latest.json');if(fs.existsSync(original))fs.copyFileSync(original,path.join(temporary,'latest.json'));
  const probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));const base='http://127.0.0.1:'+port;
  let child;let cdp;const browser=new Browser();
  async function launch(){child=spawn(process.execPath,[path.join(root,'server.cjs')],{env:{...process.env,CHECKER_PORT:String(port),CHECKER_REPORTS_DIR:temporary},stdio:'ignore'});for(let i=0;i<50;i++){try{if((await fetch(base+'/api/health',{signal:AbortSignal.timeout(300)})).ok)return;}catch{}await delay(100);}throw Error('本地测试服务未启动');}
  async function stop(){const exiting=new Promise(r=>child.once('exit',r));await fetch(base+'/api/shutdown',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});await exiting;}
  async function wait(expression){for(let i=0;i<50;i++){if(await cdp.evaluate(expression))return;await delay(100);}throw Error('等待界面状态失败：'+expression);}
  try{
    await launch();console.log('本地服务已启动');await browser.start();console.log('本地浏览器已启动');const target=(await browser.control.call('Target.createTarget',{url:'about:blank'})).targetId;
    const pages=await(await fetch('http://127.0.0.1:'+browser.port+'/json/list')).json();cdp=await CDP.connect(pages.find(p=>p.id===target).webSocketDebuggerUrl);
    await cdp.call('Page.enable');await cdp.call('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});await cdp.call('Page.navigate',{url:base});
    await wait("document.querySelectorAll('[data-audit]').length===196");
    console.log('界面已加载196项');
    assert.equal(await cdp.evaluate("document.querySelector('#rows tr td').classList.contains('audit-cell')"),true);
    await cdp.evaluate("document.querySelector('[data-audit=\"1\"]').click()");
    await wait("document.querySelector('[data-audit=\"1\"]').checked && !document.querySelector('[data-audit=\"1\"]').disabled");
    assert.equal(JSON.parse(fs.readFileSync(path.join(temporary,'manual-audits.json'),'utf8')).items['1'].checked,true);
    await cdp.evaluate("document.querySelector('#audit-filter').value='checked';document.querySelector('#audit-filter').dispatchEvent(new Event('change'))");
    assert.equal(await cdp.evaluate("document.querySelectorAll('[data-audit]').length"),1);
    await cdp.call('Page.reload');await wait("document.querySelectorAll('[data-audit]').length===196");assert.equal(await cdp.evaluate("document.querySelector('[data-audit=\"1\"]').checked"),true);
    const before=await(await fetch(base+'/api/state')).json();assert.equal(before.stats.audited,1);assert.equal(before.job.status,'idle');
    const csv=await(await fetch(base+'/export/results.csv')).text();assert.ok(csv.includes('人工审核时间'));assert.ok(csv.includes('已审核'));
    const json=await(await fetch(base+'/export/results.json')).json();assert.equal(json.rows.find(r=>r.id===1).audit.checked,true);
    const report=await(await fetch(base+'/export/report.html')).text();assert.ok(report.includes('已人工审核 1 / 196'));
    console.log('勾选、刷新、筛选和导出已验证');
    await stop();await launch();const reopened=await(await fetch(base+'/api/state')).json();assert.equal(reopened.rows.find(r=>r.id===1).audit.checked,true);
    await cdp.call('Page.reload');await wait("document.querySelectorAll('[data-audit]').length===196");await cdp.evaluate("document.querySelector('[data-audit=\"1\"]').click()");await wait("!document.querySelector('[data-audit=\"1\"]').checked && !document.querySelector('[data-audit=\"1\"]').disabled");
    await cdp.evaluate("document.querySelector('#audit-filter').value='pending';document.querySelector('#audit-filter').dispatchEvent(new Event('change'))");assert.equal(await cdp.evaluate("document.querySelectorAll('[data-audit]').length"),196);
    await cdp.evaluate("document.querySelector('.list-heading').scrollIntoView();document.querySelector('.table-wrap').scrollLeft=0");
    const screenshot=await cdp.call('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(root,'docs/人工审核窗格预览.png'),Buffer.from(screenshot.data,'base64'));
    await stop();console.log('通过：左侧勾选框、审核时间、刷新与服务重启持久化、筛选、取消勾选、CSV/JSON/报告导出；未执行外网检测。');
  }finally{cdp?.close();await browser.close();child?.kill();assert.ok(fs.realpathSync(temporary).startsWith(fs.realpathSync(os.tmpdir())+path.sep));fs.rmSync(temporary,{recursive:true,force:true});}
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
