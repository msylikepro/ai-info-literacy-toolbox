const fs=require('node:fs');
const path=require('node:path');
let sequence=0;
function atomicWrite(file,content){
  const temporary=file+'.'+process.pid+'.'+(++sequence)+'.tmp';
  try{fs.writeFileSync(temporary,content);fs.renameSync(temporary,file);}
  finally{if(fs.existsSync(temporary))fs.unlinkSync(temporary);}
}
function atomicJson(file,data){atomicWrite(file,JSON.stringify(data,null,2));}
function readJson(file){try{return JSON.parse(fs.readFileSync(file,'utf8'));}catch(e){throw Error(path.basename(file)+' 无法读取，原文件已保留：'+e.message);}}
function object(value){return value&&typeof value==='object'&&!Array.isArray(value);}
function validTitle(value){
  if(typeof value!=='string'||/[\u0000-\u001f\u007f-\u009f]/.test(value)||!value.trim()||value.trim().length>200)throw Error('网址名称须为1至200个字符，不能包含控制字符');
  return value.trim();
}
function validUrl(value){
  if(typeof value!=='string'||value.length>4096||/[\u0000-\u0020\u007f-\u009f]/.test(value)||!/^https?:\/\//i.test(value)||value.includes('\\'))throw Error('请输入完整的HTTP或HTTPS网址，不能包含空白、控制字符或登录凭据');
  let url;try{url=new URL(value);}catch{throw Error('网址格式无效');}
  if(!url.hostname||url.username||url.password||!['http:','https:'].includes(url.protocol))throw Error('网址格式无效或包含登录凭据');
  // An empty userinfo section is also a credential-bearing URL syntax.
  if(value.slice(value.indexOf('://')+3).split(/[/?#]/,1)[0].includes('@'))throw Error('网址不能包含登录凭据');
  return url.href;
}
class ResourceStore{
  constructor({baseline,reports,migrations}){
    this.reports=reports;this.journalFile=path.join(reports,'resource-catalog-transaction.json');this.loadError=null;
    this.transactionFiles=['resource-customizations.json','resource-catalog-state.json','latest.json','manual-audits.json','resource-url-history.json'];
    this.recover();
    this.file=path.join(reports,'resource-customizations.json');this.stateFile=path.join(reports,'resource-catalog-state.json');
    this.base=readJson(baseline);if(!Array.isArray(this.base)||this.base.some(r=>!object(r)||!Number.isInteger(r.id)||r.id<1||typeof r.url!=='string'))throw Error('默认网址资料格式不正确');
    this.migrations=migrations&&fs.existsSync(migrations)?readJson(migrations):{version:1,changes:[]};
    if(this.migrations.version!==1||!Array.isArray(this.migrations.changes))throw Error('网址迁移资料格式不正确');
    this.rows=[];this.refresh();this.readState();
  }
  assertReady(){if(this.loadError)throw Error(this.loadError);}
  readJournal(){
    const data=readJson(this.journalFile);
    if(data.version!==1||!['pending','committed'].includes(data.phase)||!Array.isArray(data.files)||data.files.length!==this.transactionFiles.length||new Set(data.files.map(f=>f?.name)).size!==data.files.length||data.files.some(f=>!object(f)||!this.transactionFiles.includes(f.name)||!(f.content===null||typeof f.content==='string'&&Buffer.from(f.content,'base64').toString('base64')===f.content)))throw Error('网址保存恢复记录格式不正确，原文件已保留');
    return data;
  }
  restore(files){
    for(const snapshot of files){
      const file=path.join(this.reports,snapshot.name);
      if(snapshot.content===null){if(fs.existsSync(file))fs.unlinkSync(file);continue;}
      const original=Buffer.from(snapshot.content,'base64');
      if(fs.existsSync(file)&&fs.readFileSync(file).equals(original))continue;
      atomicWrite(file,original);
    }
  }
  recover(){
    if(!fs.existsSync(this.journalFile))return;
    const journal=this.readJournal();if(journal.phase==='pending')this.restore(journal.files);
    fs.unlinkSync(this.journalFile);
  }
  transaction(action){
    this.assertReady();
    const files=this.transactionFiles.map(name=>{const file=path.join(this.reports,name);return {name,content:fs.existsSync(file)?fs.readFileSync(file).toString('base64'):null};});
    const journal={version:1,phase:'pending',files};atomicJson(this.journalFile,journal);
    try{
      action();atomicJson(this.journalFile,{...journal,phase:'committed'});
    }catch(error){
      try{this.restore(files);fs.unlinkSync(this.journalFile);}
      catch(recoveryError){this.loadError='网址保存失败，自动恢复尚未完成；原始记录已保存在恢复文件中。请关闭并重新启动工具：'+recoveryError.message;throw Error(this.loadError);}
      throw error;
    }
    // A committed journal is safe to leave behind if cleanup is temporarily
    // blocked. Startup removes it without undoing the successful update.
    try{fs.unlinkSync(this.journalFile);}catch{}
  }
  readUser(){
    if(!fs.existsSync(this.file))return {version:1,nextId:100001,overrides:{},custom:[]};
    const data=readJson(this.file);
    if(data.version!==1||!object(data.overrides)||!Array.isArray(data.custom)||!Number.isInteger(data.nextId)||data.nextId<100001)throw Error('自定义网址记录格式不正确，原文件已保留');
    const ids=new Set(this.base.map(r=>r.id));
    for(const [id,entry]of Object.entries(data.overrides)){
      if(!/^\d+$/.test(id)||!object(entry)||Object.keys(entry).some(k=>!['title','url'].includes(k)))throw Error('网址覆盖记录格式不正确');
      if(entry.title!==undefined)validTitle(entry.title);if(entry.url!==undefined)validUrl(entry.url);
    }
    for(const row of data.custom){
      if(!object(row)||!Number.isInteger(row.id)||row.id<100001||ids.has(row.id))throw Error('用户网址编号无效或重复');
      ids.add(row.id);validTitle(row.title);validUrl(row.url);
    }
    if(data.custom.some(r=>r.id>=data.nextId))throw Error('用户网址编号记录无效');
    return data;
  }
  merge(data){
    const rows=[...this.base.map(base=>{
      const override=data.overrides[base.id]||{};const title=override.title??base.title;const url=override.url??base.url;
      return {...base,title,url,host:new URL(url).hostname,siteName:override.title??base.siteName??title,siteAliases:[...new Set([...(base.siteAliases||[]),...(override.title?[base.title,base.siteName].filter(Boolean):[])])]};
    }),...data.custom.map(row=>({...row,siteName:row.title,host:new URL(row.url).hostname,categories:['用户添加'],modules:[],moduleTitles:[],siteAliases:row.siteAliases||[]}))];
    const urls=new Set();for(const row of rows){const key=new URL(row.url).href;if(urls.has(key))throw Error('网址与现有资料重复，请修改后再保存');urls.add(key);}
    return rows;
  }
  refresh(){this.assertReady();this.data=this.readUser();this.rows.splice(0,this.rows.length,...this.merge(this.data));}
  readState(){
    if(!fs.existsSync(this.stateFile))return null;
    const state=readJson(this.stateFile);
    if(state.version!==1||!object(state.urls)||Object.entries(state.urls).some(([id,url])=>!/^\d+$/.test(id)||typeof url!=='string'))throw Error('网址状态记录格式不正确，原文件已保留');
    return state;
  }
  changes(rows){
    const state=this.readState();const changes=[];
    for(const row of rows){
      const migration=this.migrations.changes.find(c=>c.id===row.id&&c.to===row.url);
      const from=state?state.urls[row.id]:(migration?.from??row.url);
      if(from&&from!==row.url)changes.push({id:row.id,from,to:row.url});
    }
    return changes;
  }
  saveState(rows){atomicJson(this.stateFile,{version:1,urls:Object.fromEntries(rows.map(r=>[r.id,r.url]))});}
  reconcile(beforeChange=()=>{}){const changes=this.changes(this.rows);this.transaction(()=>{if(changes.length)beforeChange(changes);this.saveState(this.rows);});}
  persist(data,beforeChange){
    const rows=this.merge(data);const changes=this.changes(rows);
    this.transaction(()=>{if(changes.length)beforeChange(changes);atomicJson(this.file,data);this.saveState(rows);});
    this.data=data;this.rows.splice(0,this.rows.length,...rows);
  }
  add(input,beforeChange=()=>{}){
    this.refresh();const title=validTitle(input?.title);const url=validUrl(input?.url);const data=structuredClone(this.data);
    const resource={id:data.nextId++,title,url,siteName:title,host:new URL(url).hostname,categories:['用户添加'],modules:[],moduleTitles:[]};
    data.custom.push(resource);this.persist(data,beforeChange);return this.rows.find(r=>r.id===resource.id);
  }
  update(input,beforeChange=()=>{}){
    this.refresh();if(!Number.isInteger(input?.id)||!this.rows.some(r=>r.id===input.id))throw Error('网址资料不存在');
    const title=validTitle(input.title);const url=validUrl(input.url);const data=structuredClone(this.data);const base=this.base.find(r=>r.id===input.id);
    if(base){const override={};if(title!==base.title)override.title=title;if(url!==new URL(base.url).href)override.url=url;data.overrides[input.id]=override;}
    else{const row=data.custom.find(r=>r.id===input.id);if(row.title!==title)row.siteAliases=[...new Set([...(row.siteAliases||[]),row.title])];Object.assign(row,{title,url});}
    this.persist(data,beforeChange);return this.rows.find(r=>r.id===input.id);
  }
}
module.exports={ResourceStore,atomicJson,readJson};
