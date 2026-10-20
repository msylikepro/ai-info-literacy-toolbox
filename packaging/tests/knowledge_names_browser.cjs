const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));

(async()=>{
  const directory=path.resolve(process.argv[2]);const evidence=path.resolve(process.argv[3]);
  fs.mkdirSync(evidence,{recursive:true});
  const before=JSON.parse(fs.readFileSync(path.join(evidence,'改名前备份/dist/resources.json'),'utf8'));
  const rows=JSON.parse(fs.readFileSync(path.join(directory,'resources.json'),'utf8'));
  assert.equal(rows.length,196);
  assert.deepEqual(rows.map(r=>[r.id,r.url,r.host,r.modules,r.categories]),before.map(r=>[r.id,r.url,r.host,r.modules,r.categories]),'Resource IDs, URLs and associations must remain stable');
  const executable=[path.join(process.env['PROGRAMFILES(X86)']||'C:/Program Files (x86)','Microsoft/Edge/Application/msedge.exe'),path.join(process.env.PROGRAMFILES||'C:/Program Files','Microsoft/Edge/Application/msedge.exe')].find(fs.existsSync);
  const browser=await chromium.launch({executablePath:executable,headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:1100}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
  try {
    await page.goto(pathToFileURL(path.join(directory,'index.html')).href);
    assert.equal(await page.locator('.resource').count(),196);
    assert.equal(await page.locator('.site-name').count(),196,'Each card must display its website name');
    assert(rows.every(r=>r.siteName && r.siteName!==r.host && r.siteName!==r.host.replace(/^www\./,'')),'Every host must have a human name');
    assert(!rows.some(r=>r.title===r.host || r.title===r.host.replace(/^www\./,'')),'No domain-only resource titles');
    const visible=async()=>page.locator('.resource:visible .resource-id').allTextContents();
    for(const [query,expected] of [['国家法律法规数据库',['046']],['腾讯元宝',['019']],['国家药品监督管理局数据查询',['079']],['国家图书馆',['121','122','123','124','135']],['UNESCO',['008','009','010','011']],['www.gov.cn',['001','047','049']]]){
      await page.locator('#search').fill(query);
      assert.deepEqual(await visible(),expected,'Search by '+query);
    }
    await page.locator('#search').fill('国家法律法规数据库');
    await page.screenshot({path:path.join(evidence,'按中文网站名搜索.png'),fullPage:true});
    await page.locator('#search').fill('');
    assert((await page.locator('.resource').first().locator('h2').innerText()).includes('生成式人工智能服务管理暂行办法'),'Specific document titles should remain');
    await page.evaluate(()=>document.querySelector('.results-heading').scrollIntoView({block:'start'}));
    await page.screenshot({path:path.join(evidence,'网站名称桌面界面.png')});
    await page.setViewportSize({width:390,height:844});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile page must not overflow');
    await page.screenshot({path:path.join(evidence,'网站名称手机界面.png')});
    assert.deepEqual(errors,[]);
    const report={passed:true,resourceCount:196,stableIdsAndUrls:true,humanNamesOnEveryCard:true,chineseAndEnglishNameSearch:true,domainSearchPreserved:true,documentTitlesPreserved:true,mobileNoHorizontalOverflow:true,pageErrors:errors};
    fs.writeFileSync(path.join(evidence,'导航命名浏览器验证.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
