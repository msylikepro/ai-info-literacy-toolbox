const http = require('node:http');
const {Browser} = require(process.argv[2]);
(async()=>{
  const server = http.createServer((req,res)=>{
    res.setHeader('Content-Type','text/html; charset=utf-8');
    res.end('<title>学习平台</title><body>正在加载<script>setTimeout(()=>{document.title="账号登录";document.body.innerHTML="<form>请先登录后查看内容<input type=password></form>"},200)</script>');
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser = new Browser();
  try {
    await browser.start();
    const result = await browser.inspect('http://127.0.0.1:'+server.address().port+'/login',{timeoutMs:5000});
    console.log(JSON.stringify(result));
    if (!result.browserAvailable) process.exitCode = 1;
  } finally {
    await browser.close(); server.closeAllConnections();
    await new Promise(resolve=>server.close(resolve));
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
