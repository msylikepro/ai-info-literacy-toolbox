const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const net=require('node:net');
const {createApp}=require('../server.cjs');

async function fixture(t){
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'checker-catalog-server-'));
  t.after(()=>{assert.ok(fs.realpathSync(root).startsWith(fs.realpathSync(os.tmpdir())+path.sep));fs.rmSync(root,{recursive:true,force:true});});
  for(const name of ['data','reports','public','knowledge'])fs.mkdirSync(path.join(root,name));
  fs.writeFileSync(path.join(root,'data/resources.json'),JSON.stringify([{id:1,title:'测试网址',siteName:'测试站点',url:'https://example.com/',categories:['课程'],modules:[1]},{id:79,title:'药品查询',url:'https://new.example/drug',categories:['查询'],modules:[2]}]));
  fs.writeFileSync(path.join(root,'data/resource-migrations.json'),JSON.stringify({version:1,changes:[{id:79,from:'https://old.example/drug',to:'https://new.example/drug'}]}));
  for(const filename of ['index.html','app.js','style.css']){fs.writeFileSync(path.join(root,'public',filename),'checker '+filename);fs.writeFileSync(path.join(root,'knowledge',filename),'knowledge '+filename);}
  const reports=path.join(root,'reports');
  async function start(){
    const probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));
    const app=createApp({root,reports,port,knowledgeRoot:path.join(root,'knowledge')});await new Promise(r=>app.server.listen(port,'127.0.0.1',r));
    const base='http://127.0.0.1:'+port;
    const get=async route=>{const response=await fetch(base+route);return {response,data:await response.json()};};
    const post=async(route,body,headers={})=>{const response=await fetch(base+route,{method:'POST',headers:{'Content-Type':'application/json',...headers},body:JSON.stringify(body)});return {response,data:await response.json()};};
    return {...app,base,get,post,stop:()=>new Promise(r=>app.server.close(r))};
  }
  return {root,reports,start};
}

test('添加和编辑通过本机接口持久化，新增可人工审核，导出和导航使用有效清单',async t=>{
  const f=await fixture(t);let app=await f.start();
  try{
    assert.equal((await app.get('/api/resources')).data.rows.length,2);
    const add=await app.post('/api/resources/add',{title:'用户资源',url:'https://personal.example/'});assert.equal(add.response.status,200);assert.equal(add.data.saved,true);assert.equal(add.data.resource.id,100001);
    assert.equal((await app.post('/api/audit',{id:100001,checked:true})).data.audit.checked,true);
    await app.post('/api/resources/update',{id:1,title:'修改后的名称',url:'https://example.com/'});
    assert.equal((await app.get('/api/state')).data.rows[0].title,'修改后的名称');
    assert.equal((await fetch(app.base+'/knowledge/')).status,200);assert.equal(await(await fetch(app.base+'/knowledge/app.js')).text(),'knowledge app.js');
    assert.equal((await fetch(app.base+'/knowledge/../server.cjs')).status,404);
    assert.equal((await app.post('/api/resources/add',{title:'非法来源',url:'https://foreign.example/'},{Origin:'https://foreign.example'})).response.status,403);
    assert.equal((await app.post('/api/resources/add',{title:'重复',url:'https://example.com/'})).response.status,400);
    assert.ok((await(await fetch(app.base+'/export/results.csv')).text()).includes('用户资源'));
    assert.match(await(await fetch(app.base+'/export/report.html')).text(),/<title>3个网址检测报告<\/title>/);
  }finally{await app.stop();}
  app=await f.start();try{const rows=(await app.get('/api/state')).data.rows;assert.equal(rows.length,3);assert.equal(rows[0].title,'修改后的名称');assert.equal(rows[2].audit.checked,true);}finally{await app.stop();}
});

test('修改网址及官方79迁移使旧结果、登录标注、人工审核失效并无损归档',async t=>{
  const f=await fixture(t);fs.writeFileSync(path.join(f.reports,'latest.json'),JSON.stringify({results:{1:{title:'原结果',detectorVersion:2},79:{title:'旧药品检测',detectorVersion:2}},reviews:{1:'direct',79:'required'}}));
  fs.writeFileSync(path.join(f.reports,'manual-audits.json'),JSON.stringify({version:1,items:{1:{checked:true,reviewedAt:'2026-01-01'},79:{checked:true,reviewedAt:'2026-01-02'}}}));
  let app=await f.start();try{
    let rows=(await app.get('/api/state')).data.rows;assert.equal(rows[1].result,null);assert.equal(rows[1].review,'');assert.equal(rows[1].audit.checked,false);assert.equal(rows[0].audit.checked,true);
    await app.post('/api/resources/update',{id:1,title:'仅修改名称',url:'https://example.com/'});rows=(await app.get('/api/state')).data.rows;assert.equal(rows[0].result.title,'原结果');assert.equal(rows[0].audit.checked,true);
    const update=await app.post('/api/resources/update',{id:1,title:'新网址',url:'https://changed.example/'});assert.equal(update.response.status,200);rows=(await app.get('/api/state')).data.rows;assert.equal(rows[0].result,null);assert.equal(rows[0].review,'');assert.equal(rows[0].audit.checked,false);
    const history=JSON.parse(fs.readFileSync(path.join(f.reports,'resource-url-history.json'),'utf8'));assert.equal(history.entries.length,2);assert.equal(history.entries[0].result.title,'旧药品检测');assert.equal(history.entries[0].audit.reviewedAt,'2026-01-02');assert.equal(history.entries[1].review,'direct');assert.equal(history.entries[1].from,'https://example.com/');
    assert.equal((await fetch(app.base+'/resource-url-history.json')).status,404);
  }finally{await app.stop();}
  app=await f.start();try{assert.equal(JSON.parse(fs.readFileSync(path.join(f.reports,'resource-url-history.json'),'utf8')).entries.length,2);assert.equal((await app.get('/api/state')).data.rows[0].result,null);}finally{await app.stop();}
});

test('运行期间被破坏的用户文件拒绝写入，原文件内容保持',async t=>{
  const f=await fixture(t);const app=await f.start();try{
    const file=path.join(f.reports,'resource-customizations.json');fs.writeFileSync(file,'broken customization');
    const response=await app.post('/api/resources/add',{title:'不可保存',url:'https://add.example/'});assert.equal(response.response.status,400);assert.match(response.data.error,/保留/);assert.equal(fs.readFileSync(file,'utf8'),'broken customization');
  }finally{await app.stop();}
});

test('检测运行和取消期间拒绝编辑资料且不发外网请求',async t=>{
  const {Browser}=require('../browser.cjs');const original=Browser.prototype.start;
  let release;const gate=new Promise(resolve=>{release=resolve;});
  // Hold the browser dependency before HTTP workers start, then cancel the run.
  Browser.prototype.start=async function(){await gate;throw Error('本测试不启动浏览器');};
  const f=await fixture(t);const app=await f.start();try{
    assert.equal((await app.post('/api/start',{ids:[1]})).response.status,202);
    assert.equal((await app.post('/api/resources/add',{title:'运行中',url:'https://held.example/'})).response.status,409);
    await app.post('/api/cancel',{});
    assert.equal((await app.post('/api/resources/update',{id:1,title:'取消中',url:'https://held.example/'})).response.status,409);
    release();await app.close();
    assert.equal(fs.existsSync(path.join(f.reports,'resource-customizations.json')),false);
  }finally{release();Browser.prototype.start=original;await app.close();}
});

test('发布79迁移不触碰其他编号的历史结果和人工审核文件字节',async t=>{
  const f=await fixture(t);
  const latest='{ "results": {"1":{"title":"个人检测"}}, "reviews": {"1":"direct"} }\n';
  const manual='{ "version":1, "items":{"1":{"checked":true,"reviewedAt":"2026-01-01"}} }\n';
  fs.writeFileSync(path.join(f.reports,'latest.json'),latest);fs.writeFileSync(path.join(f.reports,'manual-audits.json'),manual);
  const app=await f.start();try{
    assert.equal(fs.readFileSync(path.join(f.reports,'latest.json'),'utf8'),latest);
    assert.equal(fs.readFileSync(path.join(f.reports,'manual-audits.json'),'utf8'),manual);
    assert.equal(fs.existsSync(path.join(f.reports,'resource-url-history.json')),false);
    assert.equal((await app.get('/api/state')).data.rows[0].audit.checked,true);
  }finally{await app.stop();}
});

test('坏状态、检测记录或审核文件启动失败且不覆盖任何原文件',async t=>{
  for(const filename of ['resource-catalog-state.json','latest.json','manual-audits.json']){
    const f=await fixture(t);const file=path.join(f.reports,filename);fs.writeFileSync(file,'broken '+filename);
    await assert.rejects(()=>f.start(),/保留/);assert.equal(fs.readFileSync(file,'utf8'),'broken '+filename);
  }
});

test('网址目录或状态提交失败时，回滚原网址、检测、审核和历史文件，后续审核重启不丢失',async t=>{
  for(const target of ['resource-customizations.json','resource-catalog-state.json']){
    const f=await fixture(t);
    fs.writeFileSync(path.join(f.reports,'latest.json'),JSON.stringify({results:{1:{title:'旧检测',detectorVersion:2}},reviews:{1:'direct'}}));
    fs.writeFileSync(path.join(f.reports,'manual-audits.json'),JSON.stringify({version:1,items:{1:{checked:true,reviewedAt:'2026-01-01'}}}));
    let app=await f.start();const names=['resource-customizations.json','resource-catalog-state.json','latest.json','manual-audits.json','resource-url-history.json'];
    const before=Object.fromEntries(names.map(name=>[name,fs.existsSync(path.join(f.reports,name))?fs.readFileSync(path.join(f.reports,name),'utf8'):null]));
    const rename=fs.renameSync;
    try{
      fs.renameSync=function(source,destination){if(destination===path.join(f.reports,target))throw Error('模拟目标文件被占用');return rename.apply(this,arguments);};
      const failed=await app.post('/api/resources/update',{id:1,title:'修改失败',url:'https://failed.example/'});assert.equal(failed.response.status,400);
    }finally{fs.renameSync=rename;}
    try{
      for(const name of names)assert.equal(fs.existsSync(path.join(f.reports,name))?fs.readFileSync(path.join(f.reports,name),'utf8'):null,before[name],target+'失败应恢复'+name);
      const row=(await app.get('/api/state')).data.rows[0];assert.equal(row.url,'https://example.com/');assert.equal(row.result.title,'旧检测');assert.equal(row.review,'direct');assert.equal(row.audit.checked,true);
      await app.post('/api/audit',{id:1,checked:true});await app.post('/api/review',{id:1,value:'partial'});
    }finally{await app.stop();}
    app=await f.start();try{const row=(await app.get('/api/state')).data.rows[0];assert.equal(row.url,'https://example.com/');assert.equal(row.audit.checked,true);assert.equal(row.review,'partial');assert.equal(row.result.title,'旧检测');}finally{await app.stop();}
  }
});

test('回滚文件也被占用时停止后续写入，重启先恢复事务再读取结果',async t=>{
  const f=await fixture(t);const latest=path.join(f.reports,'latest.json');
  const original=JSON.stringify({results:{1:{title:'不能丢失的检测',detectorVersion:2}},reviews:{1:'direct'}});fs.writeFileSync(latest,original);
  let app=await f.start();const rename=fs.renameSync;let resultWrites=0;
  try{
    fs.renameSync=function(source,destination){
      if(destination===latest&&++resultWrites>1)throw Error('模拟检测记录恢复也被占用');
      if(destination===path.join(f.reports,'resource-customizations.json'))throw Error('模拟目录提交被占用');
      return rename.apply(this,arguments);
    };
    const failed=await app.post('/api/resources/update',{id:1,title:'未提交',url:'https://failed.example/'});assert.equal(failed.response.status,400);assert.match(failed.data.error,/恢复尚未完成/);
    assert.equal((await app.post('/api/audit',{id:1,checked:true})).response.status,400);
    assert.equal((await app.post('/api/review',{id:1,value:'partial'})).response.status,400);
    assert.equal((await app.post('/api/start',{ids:[1]})).response.status,400);
    assert.ok(fs.existsSync(path.join(f.reports,'resource-catalog-transaction.json')));
  }finally{fs.renameSync=rename;await app.stop();}
  app=await f.start();try{const row=(await app.get('/api/state')).data.rows[0];assert.equal(row.url,'https://example.com/');assert.equal(row.result.title,'不能丢失的检测');assert.equal(row.review,'direct');assert.equal(fs.readFileSync(latest,'utf8'),original);assert.equal(fs.existsSync(path.join(f.reports,'resource-catalog-transaction.json')),false);}finally{await app.stop();}
});

test('成功提交后即使恢复文件清理失败，重启也不回滚新网址及其新审核',async t=>{
  const f=await fixture(t);let app=await f.start();const unlink=fs.unlinkSync;
  try{
    fs.unlinkSync=function(file){if(file===path.join(f.reports,'resource-catalog-transaction.json'))throw Error('模拟恢复文件清理被占用');return unlink.apply(this,arguments);};
    const saved=await app.post('/api/resources/update',{id:1,title:'已成功提交',url:'https://new.example/'});assert.equal(saved.response.status,200);
  }finally{fs.unlinkSync=unlink;}
  try{await app.post('/api/audit',{id:1,checked:true});await app.post('/api/review',{id:1,value:'partial'});}finally{await app.stop();}
  app=await f.start();try{const row=(await app.get('/api/state')).data.rows[0];assert.equal(row.url,'https://new.example/');assert.equal(row.audit.checked,true);assert.equal(row.review,'partial');assert.equal(fs.existsSync(path.join(f.reports,'resource-url-history.json')),false);}finally{await app.stop();}
});
