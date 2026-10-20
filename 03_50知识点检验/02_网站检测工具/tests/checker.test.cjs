const {test}=require('node:test');
const assert=require('node:assert/strict');
const http=require('node:http');
const {checkHttp,classify}=require('../checker.cjs');

test('公开首页的普通登录入口不等于必须登录',()=>{
  const r=classify({status:200,contentType:'text/html',text:'公开资料页面 '.repeat(150)+'登录 注册',title:'学习资源',finalUrl:'https://example.com/',browserAvailable:true});
  assert.equal(r.login,'partial');
  assert.equal(r.availability,'open');
});
test('明确登录墙说明当前入口需要账号',()=>{
  assert.equal(classify({status:200,text:'请先登录后查看内容',title:'账号登录',finalUrl:'https://example.com/login',password:true,browserAvailable:true}).login,'required');
});
test('验证挑战和403不能当成必须注册账号',()=>{
  const r=classify({status:403,text:'Checking your browser. Verify you are human',title:'Access denied',finalUrl:'https://example.com/',browserAvailable:true});
  assert.equal(r.login,'unknown');assert.equal(r.availability,'verification');
});
test('没有真实正文的SPA不能判定可直接使用',()=>{
  assert.equal(classify({status:200,text:'正在加载',title:'AI工具',finalUrl:'https://example.com/',browserAvailable:true}).login,'unknown');
});
test('浏览器渲染出的404正文仍是错误页',()=>{
  assert.equal(classify({status:404,browserAvailable:true,text:'没有找到该页面。'.repeat(100),title:'Not Found',finalUrl:'https://example.com/missing'}).availability,'http_error');
});
test('公开资料仅下载收藏功能要求登录时不能判为整个入口登录墙',()=>{
  const r=classify({status:200,browserAvailable:true,text:'公开课程介绍：这里可以直接阅读人工智能入门的内容。'.repeat(20)+'登录后可下载收藏资料',title:'公开课程',finalUrl:'https://example.com/course'});
  assert.equal(r.availability,'open');assert.equal(r.login,'partial');
});
test('验证码教程不等于实际人机验证；短信验证码登录页仍是登录页',()=>{
  assert.equal(classify({status:200,browserAvailable:true,text:'验证码开发教程，介绍安全验证的开发方法。'.repeat(100),title:'验证码教程',finalUrl:'https://example.com/article'}).availability,'open');
  assert.equal(classify({status:200,browserAvailable:true,text:'验证码登录 密码登录 获取短信验证码 登录/注册 未注册手机验证后自动登录',title:'知乎',finalUrl:'https://example.com/signin?next=/'}).login,'required');
});
test('实际PDF文件公开返回才标记可直接读取',()=>{
  assert.equal(classify({status:200,contentType:'application/pdf',isPublicFile:true,finalUrl:'https://example.com/report.pdf'}).login,'public_file');
  assert.notEqual(classify({status:403,contentType:'application/pdf',finalUrl:'https://example.com/report.pdf'}).login,'public_file');
});
test('真实HTTP重定向保留最终地址和单次计时；慢响应有总超时',async()=>{
  const srv=http.createServer((req,res)=>{
    if(req.url==='/redirect'){res.writeHead(302,{Location:'/public'});return res.end();}
    if(req.url==='/loop'){res.writeHead(302,{Location:'/loop'});return res.end();}
    if(req.url==='/slow'){const timer=setTimeout(()=>res.end('late'),800);res.on('close',()=>clearTimeout(timer));return;}
    res.setHeader('Content-Type','text/html; charset=utf-8');res.end('<h1>公开资料</h1>');
  });
  await new Promise(r=>srv.listen(0,'127.0.0.1',r));const base='http://127.0.0.1:'+srv.address().port;
  try{
    const good=await checkHttp(base+'/redirect',{timeoutMs:2000});assert.equal(good.status,200);assert.equal(good.finalUrl,base+'/public');assert.equal(good.redirects.length,1);assert.ok(good.ttfbMs>=0);assert.ok(good.text.includes('公开资料'));
    const slow=await checkHttp(base+'/slow',{timeoutMs:120});assert.equal(slow.errorKind,'timeout');assert.ok(slow.elapsedMs<700);
    const loop=await checkHttp(base+'/loop',{timeoutMs:1000});assert.equal(loop.errorKind,'redirect_loop');
  }finally{srv.closeAllConnections();await new Promise(r=>srv.close(r));}
});
