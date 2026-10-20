const http=require('node:http');
const https=require('node:https');
const zlib=require('node:zlib');
const {performance}=require('node:perf_hooks');

function errorKind(error){
  if(error.name==='AbortError'||error.code==='ABORT_ERR')return 'cancelled';
  if(error.code==='CHECK_TIMEOUT')return 'timeout';
  if(/CERT|SSL|TLS|SELF_SIGNED|UNABLE_TO_VERIFY/.test(error.code||''))return 'tls';
  if(['ENOTFOUND','EAI_AGAIN'].includes(error.code))return 'dns';
  return 'connection';
}
function decode(buffer,headers){
  try{const encoding=headers['content-encoding'];if(encoding==='gzip')buffer=zlib.gunzipSync(buffer,{maxOutputLength:1024*1024});else if(encoding==='br')buffer=zlib.brotliDecompressSync(buffer,{maxOutputLength:1024*1024});else if(encoding==='deflate')buffer=zlib.inflateSync(buffer,{maxOutputLength:1024*1024});}catch{}
  const charset=(headers['content-type']||'').match(/charset\s*=\s*["']?([\w-]+)/i)?.[1]||buffer.toString('latin1').match(/charset\s*=\s*["']?([\w-]+)/i)?.[1]||'utf-8';
  let html;try{html=new TextDecoder(charset).decode(buffer);}catch{html=buffer.toString('utf8');}
  const text=html.replace(/<script\b[\s\S]*?<\/script>/gi,' ').replace(/<style\b[\s\S]*?<\/style>/gi,' ').replace(/<[^>]*>/g,' ').replace(/&nbsp;|&#160;/g,' ').replace(/\s+/g,' ').trim();
  return {text:text.slice(0,60000),title:html.match(/<title\b[^>]*>([\s\S]*?)<\/title>/i)?.[1]?.replace(/\s+/g,' ').trim()||'',isPublicFile:buffer.subarray(0,5).toString()==='%PDF-'||(/xml|json|text\/plain/.test(headers['content-type']||'')&&!/<html|<!doctype html/i.test(html.slice(0,500))&&buffer.length>30)};
}
async function checkHttp(url,{timeoutMs=12000,signal,maxBytes=192*1024}={}){
  const start=performance.now();let current=url;const redirects=[];const seen=new Set();let last={};
  try{
    for(let count=0;count<9;count++){
      if(seen.has(current))return {...last,finalUrl:current,redirects,errorKind:'redirect_loop',error:'重定向循环',elapsedMs:Math.round(performance.now()-start)};
      seen.add(current);const remain=timeoutMs-(performance.now()-start);
      if(remain<=0)throw Object.assign(new Error('请求超时'),{code:'CHECK_TIMEOUT'});
      const target=new URL(current);if(!['http:','https:'].includes(target.protocol))throw new Error('仅支持HTTP/HTTPS');
      last=await new Promise((resolve,reject)=>{
        let settled=false;let timer;
        const finish=(err,value)=>{if(settled)return;settled=true;clearTimeout(timer);err?reject(err):resolve(value);};
        const request=(target.protocol==='https:'?https:http).request(target,{method:'GET',agent:false,signal,headers:{'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36','Accept':'text/html,application/pdf,application/xml;q=0.9,*/*;q=0.8','Accept-Encoding':'identity'}},res=>{
          const status=res.statusCode;const headers=res.headers;const ttfbMs=Math.round(performance.now()-start);
          if(status>=300&&status<400&&headers.location){finish(null,{status,headers,ttfbMs,bytes:0});res.destroy();return;}
          const chunks=[];let bytes=0;const done=()=>finish(null,{status,headers,ttfbMs,bytes,...decode(Buffer.concat(chunks),headers)});
          res.on('data',data=>{const chunk=data.subarray(0,Math.max(0,maxBytes-bytes));bytes+=chunk.length;chunks.push(chunk);if(bytes>=maxBytes){done();res.destroy();}});
          res.on('end',done);res.on('error',err=>finish(err));res.on('aborted',()=>{if(!settled)finish(new Error('响应中断'));});
        });
        timer=setTimeout(()=>request.destroy(Object.assign(new Error('请求超时'),{code:'CHECK_TIMEOUT'})),remain);
        request.on('error',err=>finish(err));request.end();
      });
      if(last.status>=300&&last.status<400&&last.headers.location){redirects.push({url:current,status:last.status});current=new URL(last.headers.location,current).href;continue;}
      return {...last,contentType:last.headers['content-type']||'',finalUrl:current,redirects,elapsedMs:Math.round(performance.now()-start),errorKind:null};
    }
    return {...last,finalUrl:current,redirects,errorKind:'redirect_loop',error:'重定向次数过多',elapsedMs:Math.round(performance.now()-start)};
  }catch(e){return {finalUrl:current,redirects,status:last.status||null,ttfbMs:last.ttfbMs??null,errorKind:errorKind(e),error:e.code?`${e.code}: ${e.message}`:e.message,elapsedMs:Math.round(performance.now()-start)};}
}
function classify(observation){
  const o=observation;const text=(o.text||'').replace(/\s+/g,' ').trim();const title=o.title||'';const evidence=[];
  const challenge=/(checking your browser|verify you are human|just a moment|access denied|正在进行安全验证|请完成(?:人机|安全)?验证|请先完成(?:人机|安全)?验证|访问过于频繁|访问被拒绝|检测到异常访问)/i;
  if(challenge.test(title)||(text.length<1800&&challenge.test(text))){evidence.push('页面出现明确验证挑战或访问限制提示');return {availability:'verification',login:'unknown',evidence};}
  if(o.status===401){evidence.push('服务器返回HTTP 401');return {availability:'login_gate',login:'required',evidence};}
  if(o.status===403||o.status===429){evidence.push(`HTTP ${o.status}；可能是访问控制或频率限制，不能直接认定需要账号`);return {availability:'verification',login:'unknown',evidence};}
  if(o.status>=400){evidence.push(`最终页面HTTP ${o.status}，即使能显示正文也不是正常内容`);return {availability:'http_error',login:'unknown',evidence};}
  if(o.isPublicFile&&o.status>=200&&o.status<300){evidence.push('匿名请求成功返回可读取的文档或数据文件');return {availability:'open',login:'public_file',evidence};}
  if(!o.browserAvailable){evidence.push(o.browserError||o.error||'浏览器未能完成页面检查');return {availability:o.status>=200&&o.status<300?'http_only':'network_error',login:'unknown',evidence};}
  const gate=/(请先登录|登录后(?:才可访问|才可阅读|才能继续)|登录才能(?:查看|访问|继续)|需要登录(?:后才能|才可)|必须登录|sign in to continue|log in to (?:continue|access)|login required|please (?:sign|log) in)/i;
  const loginUrl=/\/(?:login|signin|sign-in|passport|sso|oauth)(?:[\/?#.]|$)/i.test(o.finalUrl||'');
  const loginTitle=/(登录|登陆|sign in|log in)/i.test(title);
  const loginWords=/(登录|登陆|sign in|log in)/i.test(text);
  if((gate.test(text)&&text.length<250)||(o.password&&(loginUrl||loginTitle)&&text.length<1500)||(loginUrl&&loginWords&&text.length<1800)){
    evidence.push(gate.test(text)?'可见正文明确提示登录后才能继续':'页面进入账号登录入口，并显示登录表单或登录标题');
    return {availability:'login_gate',login:'required',evidence};
  }
  if(text.length<100||/^(正在加载|loading|请启用javascript|很抱歉，如果没有 JavaScript)/i.test(text)){
    evidence.push('已收到页面，但可见内容不足或仍在加载');return {availability:'http_only',login:'unknown',evidence};
  }
  if(/(登录|登陆|注册|sign in|log in|sign up)/i.test(text)){
    evidence.push('可见正文可浏览，同时有登录或注册入口；部分功能可能需要账号');return {availability:'open',login:'partial',evidence};
  }
  evidence.push('匿名浏览器显示可见正文，未发现明确登录墙；尚未操作核心功能');
  return {availability:'open',login:'public_page',evidence};
}
module.exports={checkHttp,classify};
