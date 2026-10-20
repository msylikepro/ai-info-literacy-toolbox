const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'../..');
const prior=JSON.parse(fs.readFileSync(path.join(root,'交付文件/AI信息素养工具箱_Windows免安装版_v1.6.0/03_50知识点检验/02_网站检测工具/data/resources.json'),'utf8'));
const next=JSON.parse(fs.readFileSync(path.join(root,'03_50知识点检验/04_网址导航网站/knowledge-links/dist/resources.json'),'utf8'));
assert.equal(next.length,197);
for(const row of prior){
  const current=next.find(value=>value.id===row.id);assert(current,'Original ID retained');
  assert.deepEqual(current.modules,row.modules);assert.deepEqual(current.categories,row.categories);
  assert.equal(current.url,row.id===79?'https://datasearch.nmpa.gov.cn/datasearch/home-index.html':row.url);
}
assert.equal(next.find(row=>row.id===197).url,'https://data.cnki.net/aidata/chat');
assert.equal(next.find(row=>row.id===197).title,'AI 知数');
assert.equal(fs.readFileSync(path.join(root,'03_50知识点检验/02_网站检测工具/data/resources.json'),'utf8'),JSON.stringify(next,null,2));
console.log(JSON.stringify({passed:true,resourceCount:197,originalIdsStable:true,onlyApprovedUrlChanged:true}));
