const fs = require('node:fs');
const path = require('node:path');
const result = JSON.parse(fs.readFileSync(path.resolve(__dirname, 'data/extraction_result.json'), 'utf8'));
const categories = JSON.parse(fs.readFileSync(path.resolve(__dirname, 'data/categories.json'), 'utf8').replace(/^\uFEFF/,'')).data;
const escape = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const siteNames = JSON.parse(fs.readFileSync(path.resolve(__dirname,'data/site_names.json'),'utf8'));
const addressLabel = (label,host) => !label || label===host || label===host.replace(/^www\./,'') || /^(?:https?:\/\/|www\.)/i.test(label) || /(?:[&?](?:mpshare|__biz|chksm|srcid)=|sharer_shareinfo|^[a-f0-9]{24,}[&=])/i.test(label);
const grouped = new Map();
for (const m of result.modules) for (const link of m.links) {
  const url = new URL(/^https?:\/\//.test(link.url) ? link.url : `https://${link.url}`);
  const key = url.host.toLowerCase() + url.pathname.replace(/\/$/, '') + url.search + url.hash;
  const cat = categories.find(c=>c.id===m.categoryid);
  if (!grouped.has(key)) grouped.set(key,{url: url.href,host: url.host,title:'',modules:[],categories:[],variants:[]});
  const row = grouped.get(key);
  if (url.protocol === 'https:' && row.url.startsWith('http:')) row.url=url.href;
  const label = link.name.trim();
  if (!row.title && label && !/^(https?:\/\/|www\.)/.test(label) && !/^[a-z0-9.-]+\.(com|cn|org|net)(\/.*)?$/i.test(label)) row.title=label;
  if (!row.modules.includes(m.sort)) row.modules.push(m.sort);
  if (!row.categories.includes(cat.name)) row.categories.push(cat.name);
  if (!row.variants.includes(link.url)) row.variants.push(link.url);
}
let rows = [...grouped.values()].map((r,i)=>{
  const site=siteNames.sites[r.host];
  if(!site?.name || addressLabel(site.name,r.host))throw new Error('Missing website name: '+r.host);
  const override=siteNames.titles?.[String(i+1)]?.title;
  const title=override || (addressLabel(r.title,r.host) || new URL(r.url).pathname==='/' ? site.name : r.title);
  const legacy=siteNames.legacyTitles?.[String(i+1)];
  const aliases=[...new Set([...(site.aliases||[]),...(!addressLabel(r.title,r.host)&&r.title!==title?[r.title]:[]),...(!addressLabel(legacy,r.host)&&legacy!==title?[legacy]:[])])];
  return {...r,id:i+1,title,siteName:site.name,siteAliases:aliases,moduleTitles:r.modules.map(n=>result.modules.find(m=>m.sort===n).title.replace(/^知识模块\d+：/,''))};
});
if(rows.length!==196)throw new Error(`Unexpected original unique count: ${rows.length}`);
const updates=JSON.parse(fs.readFileSync(path.join(__dirname,'data/catalog_updates.json'),'utf8'));
for(const update of updates.updates){
  const row=rows.find(r=>r.id===update.id);if(!row)throw Error('Unknown resource ID');
  const previous=row.title;
  Object.assign(row,update,{host:new URL(update.url).host,variants:[update.url]});
  row.siteAliases=[...new Set([...row.siteAliases,previous])];
}
for(const row of updates.additions){
  if(rows.some(r=>r.id===row.id||r.url===row.url))throw Error('Duplicate supplemental resource');
  rows.push(row);
}
for(const row of rows)row.moduleLinks=row.modules.map(n=>{
  const module=result.modules.find(m=>m.sort===n);
  return {number:n,title:module.title.replace(/^知识模块\d+：/,''),url:module.source};
});
if(rows.length!==197)throw Error('Unexpected final resource count');
const arrow='<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M7 17 17 7M7 7h10v10"/></svg>';
const cards=rows.map(r=>`<article class="resource" data-categories="${escape(JSON.stringify(r.categories))}" data-search="${escape([r.title,r.siteName,...r.siteAliases,r.host,r.url,...r.moduleTitles,...r.modules.map(n=>'模块'+String(n).padStart(2,'0'))].join(' ').toLowerCase())}" data-url="${escape(r.url)}"><div class="resource-meta"><span class="site-name" title="${escape(r.host)}">${escape(r.siteName)}</span><span class="resource-id">${String(r.id).padStart(3,'0')}</span></div><h2><a href="${escape(r.url)}" target="_blank" rel="noopener noreferrer">${escape(r.title)}${arrow}</a></h2><a class="url" href="${escape(r.url)}" target="_blank" rel="noopener noreferrer">${escape(r.url)}</a><div class="tags">${r.categories.map(c=>`<span class="tag">${escape(c)}</span>`).join('')}</div><details><summary>来源知识点 · ${r.modules.map(n=>String(n).padStart(2,'0')).join(' / ')}</summary><ul>${r.modules.map((n,i)=>`<li><a href="${result.modules.find(m=>m.sort===n).source}" target="_blank" rel="noopener noreferrer">${String(n).padStart(2,'0')} ${escape(r.moduleTitles[i])}</a></li>`).join('')}</ul>${r.variants.length>1?`<p class="variant-note">已合并原文中的 ${r.variants.length} 种网址写法。</p>`:''}</details></article>`).join('\n');
const chips=[...new Set(['全部',...categories.map(c=>c.name),...rows.flatMap(r=>r.categories)])].map((c,i)=>`<button class="category${i===0?' active':''}" type="button" data-category="${escape(c)}" aria-pressed="${i===0}">${escape(c)}<span>${i===0?rows.length:rows.filter(r=>r.categories.includes(c)).length}</span></button>`).join('');
const html=`<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="汇集50个AI与信息素养知识点及补充资料的${rows.length}个网址，按领域查找学习、科研和信息检索资源。"><meta name="theme-color" content="#f5f7fb"><title>AI＋信息素养 · 网址导航</title><link rel="stylesheet" href="style.css"></head><body>
<header class="topbar"><div class="topbar-inner"><a class="brand" href="#"><span class="brand-mark">↗</span>AI＋信息素养<span class="brand-sub">网址导航</span></a><a class="original" href="https://csc.xxsuyang.com/Knowledge" target="_blank" rel="noopener noreferrer">查看原始知识点 ${arrow}</a></div></header>
<main><section class="intro"><p class="eyebrow">2026 大学生 AI＋信息素养大赛</p><h1>把学习资源，<br class="mobile-break">放在一处。</h1><p class="description">汇集 50 个知识点资料与补充网址，支持添加和修改，随时查找。</p><div class="stats"><div><strong id="total-resources">${rows.length}</strong><span>个资料网址</span></div><div><strong>50</strong><span>个知识点</span></div><div><strong>9</strong><span>个知识领域</span></div></div></section>
<section class="navigation" aria-label="查找网址"><div class="search-row"><div class="search-wrap"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></svg><label class="sr-only" for="search">搜索网站、网址或知识点</label><input id="search" type="search" placeholder="搜索网站、网址或知识点…" autocomplete="off"><kbd>Ctrl F</kbd></div><button id="download" class="download" type="button">下载网址清单 ↓</button></div><div class="categories" role="group" aria-label="知识领域">${chips}</div></section>
<div class="resource-management"><button id="add-resource" type="button" disabled>＋ 添加网址</button><button id="refresh-resources" type="button" disabled>刷新资料</button><p id="management-status" role="status">正在读取本机资料…</p></div>
<div class="results-heading"><h2 id="category-title">全部资源</h2><p id="result-count" aria-live="polite">共 ${rows.length} 个网址</p></div><section id="resources" class="resources" aria-label="网址列表">${cards}</section><div id="empty" class="empty" hidden><h2>没有找到匹配的网址</h2><p>试试其他关键词，或切换到全部资源。</p><button id="reset" type="button">清除筛选</button></div>
<dialog id="resource-dialog" aria-labelledby="resource-dialog-title"><form id="resource-form"><h2 id="resource-dialog-title">添加网址</h2><input id="resource-edit-id" type="hidden"><label for="resource-name">网址名称</label><input id="resource-name" maxlength="200" required placeholder="例如：AI 知数"><label for="resource-url">网址</label><input id="resource-url" type="url" maxlength="4096" required placeholder="https://"><p>更换网址后，旧地址的检测与审核状态会重置；修改名称不影响检测状态。</p><p id="resource-form-error" role="alert" hidden></p><div class="resource-form-actions"><button id="resource-cancel" type="button">取消</button><button id="resource-save" type="submit">保存网址</button></div></form></dialog>
<footer><p>数据提取于 2026 年 10 月 14 日 · 来源于大赛的 50 个知识点正文</p><p>同一地址的 HTTP / HTTPS 与末尾斜杠差异已合并。样题及参考资源中的网址一并保留，参考课程入口不计入此清单。</p></footer></main><script src="app.js" defer></script></body></html>`;
fs.mkdirSync(path.join(__dirname,'dist'),{recursive:true});
fs.writeFileSync(path.join(__dirname,'dist/index.html'),html);
fs.writeFileSync(path.join(__dirname,'dist/网址清单.txt'),rows.map(r=>r.url).join('\r\n')+'\r\n');
fs.writeFileSync(path.join(__dirname,'dist/resources.json'),JSON.stringify(rows,null,2));
fs.writeFileSync(path.resolve(__dirname,'../../02_网站检测工具/data/resources.json'),JSON.stringify(rows,null,2));
console.log(`Generated ${rows.length} unique resource cards covering ${new Set(rows.flatMap(r=>r.modules)).size} modules with explicit URLs.`);
