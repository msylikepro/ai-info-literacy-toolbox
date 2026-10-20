const {spawn}=require('node:child_process');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const net=require('node:net');
const {performance}=require('node:perf_hooks');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
const pause=(ms,signal)=>new Promise((resolve,reject)=>{if(signal?.aborted)return reject(signal.reason);const end=()=>{clearTimeout(timer);signal?.removeEventListener('abort',abort);};const abort=()=>{end();reject(signal.reason);};const timer=setTimeout(()=>{end();resolve();},ms);signal?.addEventListener('abort',abort,{once:true});});
class CDP{
  constructor(ws){this.ws=ws;this.id=0;this.pending=new Map();this.handlers=[];
    ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.id&&this.pending.has(m.id)){const p=this.pending.get(m.id);clearTimeout(p.timer);this.pending.delete(m.id);m.error?p.reject(Error(m.error.message)):p.resolve(m.result);}else for(const handler of this.handlers)handler(m);});
    ws.addEventListener('close',()=>{for(const p of this.pending.values()){clearTimeout(p.timer);p.reject(Error('浏览器连接已关闭'));}this.pending.clear();});
  }
  static async connect(url,{signal,timeout=5000}={}){if(signal?.aborted)throw signal.reason;const ws=new WebSocket(url);await new Promise((resolve,reject)=>{const cleanup=()=>{clearTimeout(timer);signal?.removeEventListener('abort',abort);};const abort=()=>{cleanup();ws.close();reject(signal.reason);};const timer=setTimeout(()=>{cleanup();ws.close();reject(Error('浏览器连接超时'));},timeout);signal?.addEventListener('abort',abort,{once:true});ws.addEventListener('open',()=>{cleanup();resolve();},{once:true});ws.addEventListener('error',()=>{cleanup();reject(Error('浏览器连接失败'));},{once:true});});return new CDP(ws);}
  call(method,params={},timeout=15000,signal){return new Promise((resolve,reject)=>{if(signal?.aborted)return reject(signal.reason);const id=++this.id;const abort=()=>{clearTimeout(timer);this.pending.delete(id);reject(signal.reason);};const cleanup=()=>signal?.removeEventListener('abort',abort);const timer=setTimeout(()=>{cleanup();this.pending.delete(id);reject(Error(method+'超时'));},timeout);signal?.addEventListener('abort',abort,{once:true});this.pending.set(id,{resolve:v=>{cleanup();resolve(v);},reject:e=>{cleanup();reject(e);},timer});try{this.ws.send(JSON.stringify({id,method,params}));}catch(e){clearTimeout(timer);cleanup();this.pending.delete(id);reject(e);}});}
  async evaluate(expression,timeout=3000,signal){const r=await this.call('Runtime.evaluate',{expression,returnByValue:true},timeout,signal);if(r.exceptionDetails)throw Error('页面读取失败');return r.result.value;}
  close(){this.ws.close();}
}
class Browser{
  async start({signal}={}){
    const candidates=[process.env.CHECKER_BROWSER,path.join(process.env['PROGRAMFILES(X86)']||'C:\\Program Files (x86)','Microsoft/Edge/Application/msedge.exe'),path.join(process.env.PROGRAMFILES||'C:\\Program Files','Microsoft/Edge/Application/msedge.exe'),path.join(process.env.PROGRAMFILES||'C:\\Program Files','Google/Chrome/Application/chrome.exe')].filter(Boolean);
    const executable=candidates.find(p=>fs.existsSync(p));if(!executable)throw Error('未找到Edge或Chrome，请安装浏览器后重试');
    const probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));this.port=probe.address().port;await new Promise(r=>probe.close(r));
    this.profile=fs.mkdtempSync(path.join(os.tmpdir(),'info-literacy-checker-'));
    this.child=spawn(executable,['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-extensions','--remote-debugging-address=127.0.0.1','--remote-debugging-port='+this.port,'--user-data-dir='+this.profile,'about:blank'],{windowsHide:true,stdio:'ignore'});
    this.child.on('error',()=>{});
    for(let i=0;i<50;i++){if(signal?.aborted)break;try{const localSignal=signal?AbortSignal.any([signal,AbortSignal.timeout(1000)]):AbortSignal.timeout(1000);const version=await(await fetch(`http://127.0.0.1:${this.port}/json/version`,{signal:localSignal})).json();this.control=await CDP.connect(version.webSocketDebuggerUrl,{signal});return this;}catch{}await delay(200);}
    await this.close();throw Error(signal?.aborted?'检测已取消':'浏览器启动失败');
  }
  async inspect(url,{timeoutMs=16000,signal}={}){
    const started=performance.now();let target;let cdp;
    const combined=signal?AbortSignal.any([signal,AbortSignal.timeout(timeoutMs)]):AbortSignal.timeout(timeoutMs);
    const remaining=()=>{if(combined.aborted)throw combined.reason;return Math.max(1,Math.ceil(timeoutMs-(performance.now()-started)));};
    const abortPage=()=>{cdp?.close();if(target)this.control?.call('Target.closeTarget',{targetId:target},500).catch(()=>{});};combined.addEventListener('abort',abortPage,{once:true});
    try{
      if(signal?.aborted)throw Error('检测已取消');
      target=(await this.control.call('Target.createTarget',{url:'about:blank'},remaining(),combined)).targetId;
      const list=await(await fetch(`http://127.0.0.1:${this.port}/json/list`,{signal:combined})).json();const page=list.find(p=>p.id===target);
      if(!page)throw Error('无法创建检测页面');cdp=await CDP.connect(page.webSocketDebuggerUrl,{signal:combined,timeout:remaining()});
      let mainFrame;const documents=[];let loadFired=false;
      cdp.handlers.push(e=>{if(e.method==='Network.responseReceived'&&e.params.type==='Document')documents.push(e.params);if(e.method==='Page.loadEventFired')loadFired=true;});
      await cdp.call('Page.enable',{},remaining(),combined);await cdp.call('Network.enable',{},remaining(),combined);
      await cdp.call('Emulation.setDeviceMetricsOverride',{width:1280,height:900,deviceScaleFactor:1,mobile:false},remaining(),combined);
      const result=await cdp.call('Page.navigate',{url},remaining(),combined);mainFrame=result.frameId;if(result.errorText)throw Error(result.errorText);
      let ready=false;
      while(performance.now()-started<timeoutMs){remaining();try{ready=await cdp.evaluate("location.href !== 'about:blank' && document.readyState !== 'loading'",Math.min(1200,remaining()),combined);if(ready)break;}catch{}await pause(Math.min(150,remaining()),combined);}
      if(!ready)throw Error('浏览器页面就绪超时');
      await pause(Math.min(1000,Math.max(0,remaining()-100)),combined);
      const observed=await cdp.evaluate(`(() => {
        const p=performance.getEntriesByType('navigation')[0];
        const visible=e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&getComputedStyle(e).visibility!=='hidden';};
        return {finalUrl:location.href,title:document.title,text:(document.body?.innerText||'').slice(0,60000),password:[...document.querySelectorAll('input[type=password]')].some(visible),browserTtfbMs:p?.responseStart>0?Math.round(p.responseStart):null,domMs:p?.domContentLoadedEventEnd>0?Math.round(p.domContentLoadedEventEnd):null,loadMs:p?.loadEventEnd>0?Math.round(p.loadEventEnd):null};
      })()`,remaining(),combined);
      if(/^(chrome|edge)-error:/.test(observed.finalUrl))throw Error('浏览器显示网络错误页');
      const doc=documents.filter(d=>d.frameId===mainFrame).at(-1);
      return {...observed,status:doc?.response.status||null,browserAvailable:true,browserError:null,inspectionMs:Math.round(performance.now()-started),loadComplete:loadFired};
    }catch(e){return {browserAvailable:false,browserError:signal?.aborted?'检测已取消':combined.aborted?'浏览器页面就绪超时':e.message,inspectionMs:Math.round(performance.now()-started)};}
    finally{combined.removeEventListener('abort',abortPage);cdp?.close();if(target&&this.control)try{await this.control.call('Target.closeTarget',{targetId:target},300);}catch{}}
  }
  async close(){
    if(this.control){try{await this.control.call('Browser.close',{},2000);}catch{}this.control.close();this.control=null;}
    this.child?.kill();await delay(200);
    if(this.profile){const tempRoot=fs.realpathSync(os.tmpdir())+path.sep;let resolved;try{resolved=fs.realpathSync(this.profile);}catch{return;}
      if(resolved.startsWith(tempRoot)&&path.basename(resolved).startsWith('info-literacy-checker-'))try{fs.rmSync(resolved,{recursive:true,force:true,maxRetries:3,retryDelay:150});}catch{}
    }
  }
}
module.exports={Browser,CDP};
