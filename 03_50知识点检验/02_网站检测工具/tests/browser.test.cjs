const {test}=require('node:test');
const assert=require('node:assert/strict');
const http=require('node:http');
const {performance}=require('node:perf_hooks');
const {Browser}=require('../browser.cjs');
const {classify}=require('../checker.cjs');

test('真实Edge读取动态登录墙，并在超时和取消后清理目标',async()=>{
  const server=http.createServer((req,res)=>{
    if(req.url==='/slow'){const timer=setTimeout(()=>res.end('late'),2000);res.on('close',()=>clearTimeout(timer));return;}
    res.setHeader('Content-Type','text/html; charset=utf-8');res.end('<title>学习平台</title><body>正在加载<script>setTimeout(()=>{document.title="账号登录";document.body.innerHTML="<form>请先登录后查看内容<input type=password></form>"},200)</script>');
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));const base='http://127.0.0.1:'+server.address().port;const browser=new Browser();
  try{
    await browser.start();const dynamic=await browser.inspect(base+'/login',{timeoutMs:5000});assert.equal(dynamic.browserAvailable,true);assert.equal(classify(dynamic).login,'required');assert.ok(dynamic.domMs>=0);
    const start=performance.now();const short=await browser.inspect(base+'/slow',{timeoutMs:200});assert.equal(short.browserAvailable,false);assert.match(short.browserError,/超时/);assert.ok(performance.now()-start<800);
    const abort=new AbortController();const timer=setTimeout(()=>abort.abort(),50);const at=performance.now();const cancelled=await browser.inspect(base+'/slow',{timeoutMs:5000,signal:abort.signal});clearTimeout(timer);assert.match(cancelled.browserError,/取消/);assert.ok(performance.now()-at<800);
    const response=await fetch('http://127.0.0.1:'+browser.port+'/json/list');const pages=await response.json();assert.ok(pages.filter(p=>p.type==='page').length<=1,'检测标签页应已关闭');
  }finally{await browser.close();server.closeAllConnections();await new Promise(r=>server.close(r));}
});
