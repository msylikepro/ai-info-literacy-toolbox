(() => {
  const $=id=>document.getElementById(id);
  const search=$('search'), container=$('resources'), dialog=$('resource-dialog');
  const escape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const originalCategories=Array.from(document.querySelectorAll('.category'),button=>button.dataset.category);
  let cards=Array.from(document.querySelectorAll('.resource')), rows=[], selected='全部', editable=false, reading=false;
  function status(message,error=false){$('management-status').textContent=message;$('management-status').classList.toggle('error',error);}
  function filter(){
    const query=search.value.trim().normalize('NFKC').toLowerCase();let count=0;
    for(const card of cards){
      const category=selected==='全部'||JSON.parse(card.dataset.categories).includes(selected);
      card.hidden=!(category&&card.dataset.search.normalize('NFKC').toLowerCase().includes(query));
      if(!card.hidden)count++;
    }
    $('category-title').textContent=selected==='全部'?'全部资源':selected;
    $('result-count').textContent=`共 ${count} 个网址`;$('empty').hidden=count!==0;$('download').disabled=count===0;
    for(const button of document.querySelectorAll('.category')){
      const active=button.dataset.category===selected;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));
    }
  }
  function render(data){
    if(!Array.isArray(data))throw Error('资料列表格式无效，请重新打开工具箱');
    rows=data;
    container.innerHTML=rows.map(row=>{
      const categories=row.categories||[],modules=row.modules||[];
      const searchable=[row.title,row.siteName,...(row.siteAliases||[]),row.host,row.url,...(row.moduleTitles||[]),...modules.map(n=>'模块'+String(n).padStart(2,'0'))].join(' ');
      const links=(row.moduleLinks||[]).map(link=>`<li><a href="${escape(link.url)}" target="_blank" rel="noopener noreferrer">${String(link.number).padStart(2,'0')} ${escape(link.title)}</a></li>`).join('');
      const details=modules.length?`<details><summary>来源知识点 · ${modules.map(n=>String(n).padStart(2,'0')).join(' / ')}</summary><ul>${links|| (row.moduleTitles||[]).map(title=>`<li>${escape(title)}</li>`).join('')}</ul></details>`:`<p class="resource-note">${row.id>=100001?'手动添加的资料':'补充资料'}</p>`;
      return `<article class="resource" data-id="${row.id}" data-categories="${escape(JSON.stringify(categories))}" data-search="${escape(searchable.toLowerCase())}" data-url="${escape(row.url)}"><div class="resource-meta"><span class="site-name" title="${escape(row.host)}">${escape(row.siteName||row.title)}</span><span class="resource-id">${String(row.id).padStart(3,'0')}</span></div><h2><a href="${escape(row.url)}" target="_blank" rel="noopener noreferrer">${escape(row.title)} ↗</a></h2><a class="url" href="${escape(row.url)}" target="_blank" rel="noopener noreferrer">${escape(row.url)}</a><div class="tags">${categories.map(c=>`<span class="tag">${escape(c)}</span>`).join('')}</div>${details}<div class="resource-edit-row"><button type="button" data-edit="${row.id}" ${editable?'':'disabled'}>编辑名称和网址</button></div></article>`;
    }).join('');
    cards=Array.from(container.querySelectorAll('.resource'));
    const names=[...new Set([...originalCategories,...rows.flatMap(row=>row.categories||[])])];
    document.querySelector('.categories').innerHTML=names.map(name=>`<button class="category" type="button" data-category="${escape(name)}">${escape(name)}<span>${name==='全部'?rows.length:rows.filter(row=>(row.categories||[]).includes(name)).length}</span></button>`).join('');
    if(!names.includes(selected))selected='全部';
    $('total-resources').textContent=String(rows.length);filter();
  }
  async function api(route,body){
    let response;
    try{response=await fetch(route,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}
    catch(error){throw Error('无法连接本机资料服务，请确认工具箱仍在运行后重试');}
    const data=await response.json().catch(()=>({error:'资料服务未正常返回，请重新打开工具箱'}));
    if(!response.ok)throw Error(data.error||'操作失败，请重试');return data;
  }
  async function refresh(){
    if(reading)return;reading=true;$('add-resource').disabled=true;$('refresh-resources').disabled=true;status('正在读取本机保存的资料…');
    try{
      const data=await api('/api/resources');editable=!data.error;render(data.rows);
      status(data.error||'资料已读取，添加和修改会自动保存在本机工具箱中。',!!data.error);
    }catch(error){editable=false;status(error.message,true);container.querySelectorAll('button[data-edit]').forEach(button=>button.disabled=true);}
    finally{reading=false;$('add-resource').disabled=!editable;$('refresh-resources').disabled=false;}
  }
  function openEditor(row){
    if(!editable)return;
    $('resource-dialog-title').textContent=row?'编辑网址':'添加网址';$('resource-edit-id').value=row?row.id:'';
    $('resource-name').value=row?.title||'';$('resource-url').value=row?.url||'';$('resource-form-error').hidden=true;
    dialog.showModal();$('resource-name').focus();
  }
  search.addEventListener('input',filter);
  document.querySelector('.categories').addEventListener('click',event=>{const button=event.target.closest('button[data-category]');if(button){selected=button.dataset.category;filter();}});
  $('reset').addEventListener('click',()=>{selected='全部';search.value='';filter();search.focus();});
  $('download').addEventListener('click',()=>{
    const urls=cards.filter(card=>!card.hidden).map(card=>card.dataset.url);
    const url=URL.createObjectURL(new Blob([urls.join('\r\n')+'\r\n'],{type:'text/plain;charset=utf-8'}));
    const anchor=document.createElement('a');anchor.href=url;anchor.download=`信息素养_${selected}_${urls.length}个网址.txt`;document.body.appendChild(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  $('add-resource').addEventListener('click',()=>openEditor(null));$('refresh-resources').addEventListener('click',refresh);
  container.addEventListener('click',event=>{const button=event.target.closest('button[data-edit]');if(button)openEditor(rows.find(row=>row.id===Number(button.dataset.edit)));});
  $('resource-cancel').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('cancel',event=>{if($('resource-save').disabled)event.preventDefault();});
  $('resource-form').addEventListener('submit',async event=>{
    event.preventDefault();if($('resource-save').disabled)return;
    const id=$('resource-edit-id').value,body={title:$('resource-name').value.trim(),url:$('resource-url').value.trim()};
    if(id)body.id=Number(id);
    $('resource-save').disabled=true;$('resource-cancel').disabled=true;$('resource-form-error').hidden=true;
    try{
      const data=await api(id?'/api/resources/update':'/api/resources/add',body);
      selected='全部';search.value=data.resource.title;render(data.rows);dialog.close();status(id?'名称和网址已保存。':'网址已添加并保存。');
    }catch(error){$('resource-form-error').textContent=error.message;$('resource-form-error').hidden=false;}
    finally{$('resource-save').disabled=false;$('resource-cancel').disabled=false;}
  });
  if(['http:','https:'].includes(location.protocol))refresh();
  else{status('当前为离线预览；请从工具箱的“知识点资料”打开，即可添加和修改网址。');filter();}
})();
