const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));

(async()=>{
  const base=process.argv[2],directory=process.argv[3];
  fs.mkdirSync(directory,{recursive:true});
  const answers=JSON.parse(fs.readFileSync(path.join(directory,'controlled-answers.json'),'utf8'));
  const executable=[path.join(process.env['PROGRAMFILES(X86)']||'C:/Program Files (x86)','Microsoft/Edge/Application/msedge.exe'),path.join(process.env.PROGRAMFILES||'C:/Program Files','Microsoft/Edge/Application/msedge.exe')].find(fs.existsSync);
  assert(executable,'Edge is required for local UI verification');
  const browser=await chromium.launch({executablePath:executable,headless:true});
  const context=await browser.newContext({viewport:{width:1440,height:1050}});
  const page=await context.newPage();
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const state=async(mode='all')=>(await (await context.request.get(base+'/api/drill/current?mode='+mode)).json()).round;
  async function awaitState(predicate){await page.waitForFunction(predicate,{},{timeout:10000});}
  try{
    await page.goto(base+'/register');
    await page.locator('input[name=username]').fill('刷题界面验证'+Date.now().toString().slice(-8));
    await page.locator('input[name=password]').fill('browser-test-password');
    await page.locator('form button').click();await page.waitForURL(base+'/');
    await page.screenshot({path:path.join(directory,'刷题入口.png'),fullPage:true});
    await page.getByRole('link',{name:'全题库刷题 / 继续上次'}).click();
    await page.locator('#drill-start:enabled').waitFor();
    await page.locator('#drill-start').click();
    await page.locator('#drill-question input').first().waitFor();
    let round=await state();const firstId=round.question.id;
    assert(!('correct' in round.question),'Answers must remain hidden before submission');
    const choices=round.question.options.map(o=>o.key),correct=answers[String(firstId)];
    const wrong=choices.find(key=>!correct.includes(key))||correct[0];
    await page.locator(`#drill-question input[value="${wrong}"]`).check();
    await awaitState(()=>document.getElementById('save-status').textContent.includes('已选选项和进度已保存'));
    await page.reload();
    await page.locator('#drill-question input:checked').waitFor();
    assert.deepEqual((await state()).question.selected,[wrong]);
    await page.locator('#drill-submit').click();
    await page.locator('#drill-feedback .review').waitFor();
    assert((await page.locator('#drill-feedback').innerText()).includes('正确答案'));
    assert.equal((await state()).question.is_correct,false);
    assert(await page.locator('#drill-next').isEnabled(),'Next question must be enabled after viewing feedback');
    await page.screenshot({path:path.join(directory,'刷题即时反馈.png'),fullPage:true});
    await page.reload();await page.locator('#drill-feedback .review').waitFor();
    assert.equal((await state()).question.id,firstId);
    await page.goto(base+'/wrong-book');
    await page.locator('.wrong-item').first().waitFor();await page.locator('.wrong-item summary').first().click();
    assert((await page.locator('#wrong-list').innerText()).includes('累计答错 1 次'));
    await page.screenshot({path:path.join(directory,'错题本.png'),fullPage:true});
    await page.getByRole('link',{name:'重练待复习错题'}).click();
    await page.locator('#drill-start:enabled').waitFor();await page.locator('#drill-start').click();
    await page.locator('#drill-question input').first().waitFor();
    const review=await state('wrong');assert.equal(review.question.id,firstId);
    for(const key of correct)await page.locator(`#drill-question input[value="${key}"]`).check();
    await page.locator('#drill-submit').click();await page.locator('#round-complete').waitFor();
    assert((await page.locator('#drill-feedback').innerText()).includes('回答正确'));
    await page.goto(base+'/wrong-book');await page.selectOption('#wrong-filter','mastered');
    await page.locator('.wrong-item').first().waitFor();
    assert((await page.locator('.wrong-item').innerText()).includes('已掌握'));
    await page.goto(base+'/drill');await page.locator('#drill-next').waitFor();
    assert.equal((await state()).id,round.id);
    await page.locator('#drill-next').click();
    await page.waitForFunction(()=>document.querySelector('#round-position').textContent.includes('第 2 题'));
    assert.notEqual((await state()).question.id,firstId);
    await page.setViewportSize({width:390,height:844});
    // Question banks can contain long URLs and English tokens without spaces.
    await page.locator('#drill-question .option span').first().evaluate(el=>el.textContent+=' https://example.test/'+ 'question'.repeat(35));
    await page.screenshot({path:path.join(directory,'刷题手机界面.png'),fullPage:true});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile layout must not overflow horizontally');
    // A failed autosave and failed submit must never claim the draft is saved.
    await page.route(/\/api\/drill\/\d+\/(draft|answer)$/,route=>route.abort());
    await page.locator('#drill-question input').first().check();
    await page.waitForFunction(()=>document.getElementById('save-status').textContent.includes('尚未保存'));
    await page.locator('#drill-submit').click();
    await page.waitForFunction(()=>!document.getElementById('drill-error').classList.contains('hidden'));
    assert((await page.locator('#save-status').innerText()).includes('尚未保存'),'Failed save must not be reported as saved');
    await page.unrouteAll({behavior:'wait'});
    assert.deepEqual(errors,[],'Browser must have no unhandled page errors');
    const report={passed:true,draftSurvivesReload:true,immediateFeedback:true,nextQuestionEnabled:true,
      reviewSurvivesReload:true,wrongBookSaved:true,masteryPreservesHistory:true,wrongReviewDoesNotResetFullRound:true,
      mobileHasNoHorizontalOverflow:true,failedSaveNeverReportedAsSaved:true,pageErrors:errors};
    fs.writeFileSync(path.join(directory,'刷题浏览器验证结果.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
  }finally{await context.close();await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
