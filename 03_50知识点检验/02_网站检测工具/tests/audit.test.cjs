const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {AuditStore}=require('../audit.cjs');

test('人工审核勾选与时间在重新打开后保留，取消勾选同样持久化',()=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'checker-audit-test-'));const file=path.join(dir,'audits.json');
  try{
    const first=new AuditStore(file,[1,2]);assert.equal(first.get(1).checked,false);
    const mark=first.set(1,true);assert.equal(mark.checked,true);assert.ok(Number.isFinite(Date.parse(mark.reviewedAt)));
    const reopened=new AuditStore(file,[1,2]);assert.equal(reopened.get(1).reviewedAt,mark.reviewedAt);assert.equal(reopened.count(),1);assert.equal(reopened.get(2).checked,false);
    reopened.set(1,false);const cleared=new AuditStore(file,[1,2]);assert.equal(cleared.get(1).checked,false);assert.equal(cleared.get(1).reviewedAt,null);assert.equal(cleared.count(),0);
  }finally{assert.ok(fs.realpathSync(dir).startsWith(fs.realpathSync(os.tmpdir())+path.sep));fs.rmSync(dir,{recursive:true,force:true});}
});
test('非法ID和字符串勾选值不能写入审核记录；损坏文件不能被覆盖',()=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'checker-audit-test-'));const file=path.join(dir,'audits.json');
  try{
    const store=new AuditStore(file,[1]);assert.throws(()=>store.set(999,true));assert.throws(()=>store.set(1,'false'));assert.equal(fs.existsSync(file),false);
    fs.writeFileSync(file,'broken original record');const corrupt=new AuditStore(file,[1]);assert.throws(()=>corrupt.set(1,true));assert.equal(fs.readFileSync(file,'utf8'),'broken original record');
  }finally{assert.ok(fs.realpathSync(dir).startsWith(fs.realpathSync(os.tmpdir())+path.sep));fs.rmSync(dir,{recursive:true,force:true});}
});
