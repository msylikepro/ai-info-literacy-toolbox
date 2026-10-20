const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));

(async () => {
  const [base, directory] = process.argv.slice(2);
  const fixtures = JSON.parse(fs.readFileSync(path.join(directory,'controlled-questions.json'),'utf8'));
  const executable = [path.join(process.env['PROGRAMFILES(X86)'] || 'C:/Program Files (x86)','Microsoft/Edge/Application/msedge.exe'),path.join(process.env.PROGRAMFILES || 'C:/Program Files','Microsoft/Edge/Application/msedge.exe')].find(fs.existsSync);
  const browser = await chromium.launch({executablePath:executable,headless:true});
  const context = await browser.newContext({viewport:{width:1440,height:1050}});
  const page = await context.newPage(); const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const get = async route => (await context.request.get(base+route)).json();
  const ready = async () => page.waitForFunction(() => !document.getElementById('favorite-status').textContent.includes('正在'));
  try {
    await page.goto(base+'/register');
    await page.locator('input[name=username]').fill('收藏浏览器验证');
    await page.locator('input[name=password]').fill('fixture-password');
    await page.locator('form button').click(); await page.waitForURL(base+'/');
    await page.getByRole('link',{name:'我的收藏集'}).click();
    await page.locator('#favorite-empty').waitFor(); await ready();
    await page.getByRole('link',{name:'去刷题并收藏'}).click();
    await page.locator('#drill-start:enabled').waitFor(); await page.locator('#drill-start').click();
    await page.locator('#drill-question input').first().waitFor();
    await page.locator('#drill-question input').first().check();
    await page.waitForFunction(() => document.getElementById('save-status').textContent.includes('已选选项和进度已保存'));
    await page.locator('#drill-favorite').click();
    await page.waitForFunction(() => document.getElementById('drill-favorite').getAttribute('aria-pressed')==='true');
    await page.reload(); await page.locator('#drill-question input:checked').waitFor();
    assert.equal(await page.locator('#drill-favorite').getAttribute('aria-pressed'),'true');
    await page.locator('#drill-favorite').click();
    await page.waitForFunction(() => document.getElementById('drill-favorite').getAttribute('aria-pressed')==='false');
    assert.equal((await get('/api/favorites')).total,0);
    for (const q of fixtures) assert((await context.request.post(base+'/api/favorites/'+q.id)).ok());
    const before = (await get('/api/drill/current')).round;
    await page.getByRole('link',{name:'我的收藏集'}).click();
    await page.locator('#favorite-question input').first().waitFor(); await ready();
    assert.equal((await page.locator('#favorite-feedback').innerText()),'');
    await page.locator('#favorite-reveal').click(); await page.locator('#favorite-feedback .review').waitFor(); await ready();
    assert((await page.locator('#favorite-feedback').innerText()).includes('正确答案'));
    assert.equal((await get('/api/drill/wrongs')).total,0);
    await page.locator('#favorite-reveal').click(); await ready();
    assert.equal(await page.locator('#favorite-feedback').innerText(),'');
    const listing = (await get('/api/favorites')).items;
    for (const q of fixtures) {
      const index = listing.findIndex(item => item.id===q.id);
      await page.locator(`#favorite-numbers button[data-position="${index}"]`).click(); await ready();
      if (await page.locator('#favorite-reset').isVisible()) { await page.locator('#favorite-reset').click(); await ready(); }
      const wrong = q.options.find(o=>!q.answer.includes(o.key));
      await page.locator(`#favorite-question input[value="${wrong.key}"]`).check();
      await page.locator('#favorite-submit').click(); await ready();
      assert((await page.locator('#favorite-feedback').innerText()).includes('回答错误，本次仅作复习'));
      assert.equal((await get('/api/drill/wrongs')).total,0);
      await page.locator('#favorite-reset').click(); await ready();
      for (const key of q.answer) await page.locator(`#favorite-question input[value="${key}"]`).check();
      await page.locator('#favorite-submit').click(); await ready();
      assert((await page.locator('#favorite-feedback').innerText()).includes('回答正确'));
    }
    await page.screenshot({path:path.join(directory,'收藏集作答与答案.png'),fullPage:true});
    const after = (await get('/api/drill/current')).round;
    for (const key of ['id','current_position','answered_count','correct_count','wrong_count']) assert.equal(after[key],before[key]);
    assert.deepEqual(after.question.selected,before.question.selected);
    await page.locator('#favorite-numbers button[data-position="0"]').click(); await ready();
    await page.locator('#favorite-next').click(); await ready();
    assert((await page.locator('#favorite-position').innerText()).includes('第 2 /'));
    await page.locator('#favorite-prev').click(); await ready();
    await page.route(/\/api\/favorites\/\d+$/, route => route.request().method()==='DELETE' ? route.abort() : route.continue());
    await page.locator('#favorite-remove').click(); await ready();
    assert.equal((await get('/api/favorites')).total,3);
    assert(await page.locator('#favorite-error').isVisible());
    await page.screenshot({path:path.join(directory,'收藏移出失败仍保留.png'),fullPage:true});
    await page.unrouteAll({behavior:'wait'});
    await page.locator('#favorite-reset').click(); await ready();
    await page.setViewportSize({width:390,height:844});
    await page.locator('#favorite-question .option span').first().evaluate(el=>el.textContent+=' https://example.test/'+ 'longtext'.repeat(40));
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.screenshot({path:path.join(directory,'收藏集手机长网址验证.png'),fullPage:true});
    await page.locator('#favorite-reveal').click(); await ready();
    await page.screenshot({path:path.join(directory,'收藏集手机界面.png'),fullPage:true});
    // Reload to clear visited-question cache, so the successor requires a GET.
    await page.reload(); await page.locator('#favorite-question input').first().waitFor(); await ready();
    const nextId = (await get('/api/favorites')).items[1].id;
    await page.route(new RegExp('/api/favorites/'+nextId+'$'), route => route.request().method()==='GET' ? route.abort() : route.continue());
    await page.locator('#favorite-remove').click(); await ready();
    assert.equal((await get('/api/favorites')).total,2);
    assert(await page.locator('#favorite-panel').isHidden(),'A removed question must not remain actionable when loading its successor fails');
    assert(await page.locator('#favorite-error').isVisible());
    await page.unrouteAll({behavior:'wait'});
    await page.locator('#favorite-refresh').click(); await ready();
    await page.locator('#favorite-question input').first().waitFor();
    for (let count=2;count>0;count--) {
      await page.locator('#favorite-remove').click(); await ready();
      assert.equal((await get('/api/favorites')).total,count-1);
    }
    await page.locator('#favorite-empty').waitFor();
    assert.equal((await get('/api/drill/wrongs')).total,0);
    assert.deepEqual(errors,[]);
    const report = {passed:true,bookmarkSurvivesReload:true,drillCancelBookmark:true,threeQuestionTypes:true,
      explicitShowAndHideAnswer:true,previousAndNext:true,reviewNeverChangesWrongBookOrDrill:true,
      failedRemovalKeepsFavorite:true,successorLoadFailureNeverShowsRemovedQuestion:true,refreshRecoversRemainingFavorites:true,
      removeLastShowsEmptyState:true,mobileNoOverflow:true,pageErrors:errors};
    fs.writeFileSync(path.join(directory,'收藏集浏览器验证.json'),JSON.stringify(report,null,2)); console.log(JSON.stringify(report));
  } finally { await context.close(); await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
