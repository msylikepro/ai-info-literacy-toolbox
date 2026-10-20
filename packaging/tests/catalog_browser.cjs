const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const net=require('node:net');
const {chromium}=require(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));

(async()=>{
  const checker=path.resolve(process.argv[2]),directory=path.resolve(process.argv[3]);
  fs.mkdirSync(directory,{recursive:true});const reports=path.join(directory,'reports');assert(!fs.existsSync(reports));fs.mkdirSync(reports);
  const priorUrl='https://www.nmpa.gov.cn/datasearch/home-index.html';
  fs.writeFileSync(path.join(reports,'latest.json'),JSON.stringify({results:{1:{availability:'open',login:'public_page',detectorVersion:2},79:{availability:'open',login:'public_page',detectorVersion:2,finalUrl:priorUrl}},reviews:{79:'direct'}}));
  const entry={checked:true,reviewedAt:'2026-10-15T00:00:00Z',updatedAt:'2026-10-15T00:00:00Z'};
  fs.writeFileSync(path.join(reports,'manual-audits.json'),JSON.stringify({version:1,items:{1:entry,79:entry}}));
  const probe=net.createServer();await new Promise(resolve=>probe.listen(0,'127.0.0.1',resolve));const port=probe.address().port;await new Promise(resolve=>probe.close(resolve));
  const {createApp}=require(path.join(checker,'server.cjs'));
  let app=createApp({root:checker,reports,port});
  const listen=()=>new Promise(resolve=>app.server.listen(port,'127.0.0.1',resolve));await listen();
  const base='http://127.0.0.1:'+port;
  const executable=[path.join(process.env['PROGRAMFILES(X86)']||'C:/Program Files (x86)','Microsoft/Edge/Application/msedge.exe'),path.join(process.env.PROGRAMFILES||'C:/Program Files','Microsoft/Edge/Application/msedge.exe')].find(fs.existsSync);
  const browser=await chromium.launch({executablePath:executable,headless:true});
  const context=await browser.newContext({viewport:{width:1440,height:1100}}),page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const get=async route=>(await context.request.get(base+route)).json();
  const search=async value=>{await page.locator('#search').fill(value);};
  const edit=async(id,title,url)=>{
    await page.locator(`button[data-edit="${id}"]`).click();await page.locator('#resource-name').fill(title);
    if(url!==undefined)await page.locator('#resource-url').fill(url);
    await page.locator('#resource-save').click();await page.locator('#resource-dialog').waitFor({state:'hidden'});
  };
  try{
    await page.goto(base+'/knowledge/');await page.locator('#add-resource:enabled').waitFor();
    assert.equal(await page.locator('.resource').count(),197);
    await search('AI知数');assert.equal(await page.locator('.resource:visible').count(),1);
    assert.equal(await page.locator('.resource:visible h2 a').getAttribute('href'),'https://data.cnki.net/aidata/chat');
    await search('国家药品监督');assert.equal(await page.locator('.resource:visible h2 a').getAttribute('href'),'https://datasearch.nmpa.gov.cn/datasearch/home-index.html');
    let state=await get('/api/state');assert(!state.rows.find(r=>r.id===79).audit.checked);assert.equal(state.rows.find(r=>r.id===79).result,null);
    assert(state.rows.find(r=>r.id===1).audit.checked);assert(state.rows.find(r=>r.id===1).result);
    assert(fs.readFileSync(path.join(reports,'resource-url-history.json'),'utf8').includes(priorUrl));
    await page.locator('#add-resource').click();await page.locator('#resource-name').fill('手动学习资料');await page.locator('#resource-url').fill('https://example.test/learning');
    await page.locator('#resource-save').click();await page.locator('#resource-dialog').waitFor({state:'hidden'});
    let custom=(await get('/api/resources')).rows.find(r=>r.title==='手动学习资料');assert(custom.id>=100001);
    assert.equal(await page.locator('.resource:visible').count(),1);
    await edit(custom.id,'我的检索资料','https://example.test/updated');
    assert.equal(await page.locator('.resource:visible h2 a').getAttribute('href'),'https://example.test/updated');
    await page.reload();await page.locator('#add-resource:enabled').waitFor();await search('我的检索资料');assert.equal(await page.locator('.resource:visible').count(),1);
    await page.locator('#add-resource').click();await page.locator('#resource-name').fill('重复资料');await page.locator('#resource-url').fill('https://example.test/updated');await page.locator('#resource-save').click();
    await page.locator('#resource-form-error').waitFor();assert((await page.locator('#resource-form-error').innerText()).includes('重复'));await page.locator('#resource-cancel').click();
    await search('生成式人工智能服务管理暂行办法');await edit(1,'政策资料自定义名称');
    state=await get('/api/state');assert(state.rows.find(r=>r.id===1).audit.checked);assert(state.rows.find(r=>r.id===1).result);
    await edit(1,'政策资料自定义名称','https://example.test/new-policy');
    state=await get('/api/state');assert(!state.rows.find(r=>r.id===1).audit.checked);assert.equal(state.rows.find(r=>r.id===1).result,null);
    await page.locator(`button[data-edit="1"]`).click();await page.locator('#resource-url').fill('javascript:alert(1)');
    // Test the server rejection as well as the ordinary browser form path.
    const bad=await context.request.post(base+'/api/resources/update',{data:{id:1,title:'政策资料自定义名称',url:'javascript:alert(1)'}});assert.equal(bad.status(),400);
    await page.locator('#resource-cancel').click();
    await search('我的检索资料');const downloadEvent=page.waitForEvent('download');await page.locator('#download').click();const download=await downloadEvent;
    await download.saveAs(path.join(directory,'检索下载清单.txt'));assert(fs.readFileSync(path.join(directory,'检索下载清单.txt'),'utf8').includes('https://example.test/updated'));
    await page.screenshot({path:path.join(directory,'手动网址保存与检索.png'),fullPage:true});
    await page.locator('#add-resource').click();await page.setViewportSize({width:390,height:844});
    await page.locator('#resource-name').fill('新学习网址');await page.locator('#resource-url').fill('https://example.test/new');
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.screenshot({path:path.join(directory,'网址编辑手机界面.png')});await page.locator('#resource-cancel').click();
    await page.goto('about:blank');await app.close();app=createApp({root:checker,reports,port});await listen();
    await page.goto(base+'/knowledge/');await page.locator('#add-resource:enabled').waitFor();await search('我的检索资料');
    assert.equal(await page.locator('.resource:visible h2 a').getAttribute('href'),'https://example.test/updated');
    state=await get('/api/state');assert.equal(state.rows.length,198);assert.equal(state.rows.find(r=>r.id===1).url,'https://example.test/new-policy');
    assert.equal(state.rows.find(r=>r.id===custom.id).title,'我的检索资料');
    assert.deepEqual(errors,[]);
    const report={passed:true,defaultCount:197,aiDataPresent:true,nmpaMigrated:true,oldUrlHistoryPreserved:true,
      addEditAndSearch:true,customIdsStable:true,duplicateRejected:true,unsafeUrlRejected:true,titleOnlyKeepsAudit:true,
      urlChangeInvalidatesAuditAndResult:true,downloadUsesEditedUrl:true,restartPersistsEdits:true,mobileDialogNoOverflow:true,pageErrors:errors};
    fs.writeFileSync(path.join(directory,'网址管理浏览器验证.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
  }finally{await context.close();await browser.close();await app.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
