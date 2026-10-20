const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {ResourceStore}=require('../resource-store.cjs');

function fixture(t){
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'checker-catalog-'));
  t.after(()=>{assert.ok(fs.realpathSync(root).startsWith(fs.realpathSync(os.tmpdir())+path.sep));fs.rmSync(root,{recursive:true,force:true});});
  fs.mkdirSync(path.join(root,'data'));const reports=path.join(root,'userdata');fs.mkdirSync(reports);
  const base=[{id:1,title:'原始名称',url:'https://example.com/',siteName:'原站点',host:'example.com',categories:['课程'],modules:[1],moduleTitles:['第一讲'],siteAliases:['别名']},{id:79,title:'药品查询',url:'https://new.example/drug',categories:['查询'],modules:[2]}];
  const baseline=path.join(root,'data/resources.json');fs.writeFileSync(baseline,JSON.stringify(base));
  const migrations=path.join(root,'data/resource-migrations.json');fs.writeFileSync(migrations,JSON.stringify({version:1,changes:[{id:79,from:'https://old.example/drug',to:'https://new.example/drug'}]}));
  return {root,reports,base,baseline,open:()=>new ResourceStore({baseline,reports,migrations})};
}

test('添加、编辑和重启保留自定义，更新默认资料仍保留独立名称覆盖',t=>{
  const f=fixture(t);let store=f.open();store.reconcile(()=>{});
  const added=store.add({title:'我的资源',url:'https://personal.example/'});assert.equal(added.id,100001);assert.deepEqual(added.categories,['用户添加']);assert.deepEqual(added.modules,[]);
  store.update({id:1,title:'我的名称',url:'https://example.com/'});
  assert.equal(fs.readFileSync(f.baseline,'utf8'),JSON.stringify(f.base));
  f.base[0].url='https://updated.example/';fs.writeFileSync(f.baseline,JSON.stringify(f.base));
  store=f.open();assert.equal(store.rows.find(r=>r.id===1).title,'我的名称');assert.equal(store.rows.find(r=>r.id===1).url,'https://updated.example/');assert.ok(store.rows[0].siteAliases.includes('原始名称'));assert.equal(store.rows.find(r=>r.id===100001).host,'personal.example');
  store.update({id:100001,title:'新名称',url:'https://personal.example/new'});
  assert.equal(f.open().rows.find(r=>r.id===100001).url,'https://personal.example/new');
});

test('拒绝非完整网址、凭据、控制字符、超长名称和重复网址，坏文件不覆盖',t=>{
  const f=fixture(t);const store=f.open();
  for(const url of ['example.com','ftp://example.com/','https://u:p@example.com/','https://example.com/\n','https:example.com','https://example.com/'+ 'x'.repeat(4096)])assert.throws(()=>store.add({title:'测试',url}));
  for(const title of ['', 'x'.repeat(201),'名称\u0000'])assert.throws(()=>store.add({title,url:'https://another.example/'}));
  assert.throws(()=>store.add({title:'重复',url:'https://EXAMPLE.com:443'}));
  assert.throws(()=>store.update({id:999,title:'未知',url:'https://unknown.example/'}));
  fs.writeFileSync(path.join(f.reports,'resource-customizations.json'),'broken user data');
  assert.throws(()=>f.open());assert.equal(fs.readFileSync(path.join(f.reports,'resource-customizations.json'),'utf8'),'broken user data');
});

test('首次发布网址迁移和后续自定义变更均向调用方交付旧网址再提交新状态',t=>{
  const f=fixture(t);let store=f.open();const changes=[];store.reconcile(items=>changes.push(...items));
  assert.deepEqual(changes.map(c=>[c.id,c.from,c.to]),[[79,'https://old.example/drug','https://new.example/drug']]);
  store=f.open();store.reconcile(()=>assert.fail('重启不可重复迁移'));
  let observed;store.update({id:1,title:'名称',url:'https://new.example/'},items=>{observed=items;assert.equal(f.open().rows[0].url,'https://example.com/');});
  assert.equal(observed[0].from,'https://example.com/');assert.equal(f.open().rows[0].url,'https://new.example/');
});

test('不完整的事务恢复文件禁止启动并原样保留',t=>{
  const f=fixture(t);const file=path.join(f.reports,'resource-catalog-transaction.json');
  const broken=JSON.stringify({version:1,phase:'pending',files:[]});fs.writeFileSync(file,broken);
  assert.throws(()=>f.open(),/保留/);assert.equal(fs.readFileSync(file,'utf8'),broken);
});

module.exports={fixture};
