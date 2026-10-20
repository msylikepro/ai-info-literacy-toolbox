// 仅检查本地批处理启动和页面接口，绝不调用/api/start或访问外部网址。
const {spawn}=require('node:child_process');
const assert=require('node:assert/strict');
const path=require('node:path');
const net=require('node:net');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
  const probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));
  const root=path.resolve(__dirname,'..');const child=spawn('cmd.exe',['/d','/c','启动检测工具.bat'],{cwd:root,env:{...process.env,CHECKER_PORT:String(port)},stdio:['ignore','pipe','pipe']});
  let output='';child.stdout.on('data',chunk=>output+=chunk.toString('utf8'));child.stderr.on('data',chunk=>output+=chunk.toString('utf8'));child.on('error',()=>{});
  let started=false;
  try{
    const base='http://127.0.0.1:'+port;
    for(let i=0;i<40;i++){try{const r=await fetch(base+'/api/health',{signal:AbortSignal.timeout(300)});if(r.ok){const h=await r.json();assert.equal(h.app,'info-literacy-checker');started=true;break;}}catch{}await delay(100);}
    assert.ok(started,'批处理应正常启动本地服务：'+output);
    const state=await(await fetch(base+'/api/state')).json();assert.equal(state.rows.length,196);assert.equal(state.job.status,'idle');assert.equal(state.job.active.length,0);
    assert.equal((await fetch(base+'/')).status,200);
    const csv=await(await fetch(base+'/export/results.csv')).text();assert.ok(csv.includes('账号要求（自动）'));
    const foreign=await fetch(base+'/api/review',{method:'POST',headers:{Origin:'https://unrelated.example','Content-Type':'application/json'},body:'{}'});assert.equal(foreign.status,403);
    const invalid=await fetch(base+'/api/start',{method:'POST',headers:{'Content-Type':'application/json'},body:'{"ids":[99999]}'});assert.equal(invalid.status,400);
    const unchanged=await(await fetch(base+'/api/state')).json();assert.equal(unchanged.job.status,'idle');
    console.log('本地检查通过：批处理前台启动，196项清单可读，页面与导出正常，未启动联网扫描。');
  }finally{
    if(started)try{await fetch('http://127.0.0.1:'+port+'/api/shutdown',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});}catch{}
    await Promise.race([new Promise(r=>child.once('exit',r)),delay(1000)]);child.kill();
  }
})().catch(e=>{console.error(e.message);process.exitCode=1;});
