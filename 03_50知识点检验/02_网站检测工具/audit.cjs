const fs=require('node:fs');
class AuditStore{
  constructor(file,ids){this.file=file;this.ids=new Set(ids);this.items={};this.loadError=null;this.reload();}
  reload(){
    try{
      if(!fs.existsSync(this.file)){this.items={};this.loadError=null;return;}
      const data=JSON.parse(fs.readFileSync(this.file,'utf8'));
      if(data.version!==1||!data.items||typeof data.items!=='object'||Array.isArray(data.items))throw Error('记录格式不正确');
      const items={};for(const [id,entry]of Object.entries(data.items)){
        if(!this.ids.has(Number(id)))continue;
        if(!entry||typeof entry.checked!=='boolean')throw Error('审核状态格式不正确');
        items[id]={checked:entry.checked,reviewedAt:entry.reviewedAt||null,updatedAt:entry.updatedAt||null};
      }
      this.items=items;this.loadError=null;
    }catch(e){this.loadError='人工审核记录无法读取，原文件已保留：'+e.message;}
  }
  get(id){return {...(this.items[id]||{checked:false,reviewedAt:null,updatedAt:null})};}
  count(){return Object.values(this.items).filter(entry=>entry.checked).length;}
  syncIds(ids){this.ids=new Set(ids);this.reload();if(this.loadError)throw Error(this.loadError);}
  clear(ids){
    this.reload();if(this.loadError)throw Error(this.loadError);
    if(!ids.some(id=>Object.hasOwn(this.items,id)))return;
    const items={...this.items};for(const id of ids)delete items[id];
    const {atomicJson}=require('./resource-store.cjs');atomicJson(this.file,{version:1,items});this.items=items;
  }
  set(id,checked){
    if(!Number.isInteger(id)||!this.ids.has(id))throw Error('审核对象不存在');
    if(typeof checked!=='boolean')throw Error('勾选状态无效');
    this.reload();if(this.loadError)throw Error(this.loadError);
    const previous=this.get(id);const now=new Date().toISOString();
    const entry={checked,reviewedAt:checked?(previous.checked&&previous.reviewedAt?previous.reviewedAt:now):null,updatedAt:now};
    const items={...this.items,[id]:entry};const temporary=this.file+'.tmp';
    fs.writeFileSync(temporary,JSON.stringify({version:1,items},null,2));fs.renameSync(temporary,this.file);this.items=items;return {...entry};
  }
}
module.exports={AuditStore};
