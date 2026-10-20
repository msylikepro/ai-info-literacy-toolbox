const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
(async()=>{
  const [base,directory]=process.argv.slice(2);
  const executable=[path.join(process.env['PROGRAMFILES(X86)']||'C:/Program Files (x86)','Microsoft/Edge/Application/msedge.exe'),path.join(process.env.PROGRAMFILES||'C:/Program Files','Microsoft/Edge/Application/msedge.exe')].find(fs.existsSync);
  const browser=await chromium.launch({executablePath:executable,headless:true});
  const context=await browser.newContext({viewport:{width:1440,height:1050}}),page=await context.newPage();
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const ready=()=>page.waitForFunction(()=>document.getElementById('bank-results').getAttribute('aria-busy')==='false');
  const search=async query=>{await page.locator('#bank-query').fill(query);await page.getByRole('button',{name:'检索题目',exact:true}).click();await ready();};
  const get=async route=>(await context.request.get(base+route)).json();
  const cards=()=>page.locator('.bank-item');
  try{
    await page.goto(base+'/register');await page.locator('input[name=username]').fill('题库浏览验证');await page.locator('input[name=password]').fill('fixture-password');await page.locator('form button').click();await page.waitForURL(base+'/');
    let before=(await (await context.request.post(base+'/api/drill/start',{data:{mode:'all'}})).json()).round;
    await context.request.post(base+'/api/favorites/'+before.question.id);
    before=(await get('/api/drill/current')).round;
    await page.getByRole('link',{name:'浏览题库',exact:true}).click();await ready();
    assert.equal(await cards().count(),20);assert((await page.locator('#bank-summary').innerText()).includes('25'));
    assert.equal(await page.locator('.bank-answer:visible').count(),0);
    assert.equal(await page.locator('.bank-item img').count(),0);
    const firstIds=await cards().evaluateAll(elements=>elements.map(el=>Number(el.dataset.questionId)));
    await cards().nth(0).locator('.bank-reveal').click();await cards().nth(0).locator('.review').waitFor();
    assert(await cards().nth(1).locator('.bank-answer').isHidden());
    await cards().nth(1).locator('.bank-reveal').click();await cards().nth(1).locator('.review').waitFor();
    await cards().nth(0).locator('.bank-reveal').click();
    assert(await cards().nth(0).locator('.bank-answer').isHidden());assert(await cards().nth(1).locator('.bank-answer').isVisible());
    await page.locator('#bank-next').click();await ready();assert.equal(await cards().count(),5);
    const nextIds=await cards().evaluateAll(elements=>elements.map(el=>Number(el.dataset.questionId)));
    assert.equal(new Set([...firstIds,...nextIds]).size,25);
    await page.locator('#bank-prev').click();await ready();assert.equal(await cards().count(),20);
    for(const [query,count] of [['人工智能',2],['自然语言处理',1],['人工智能 机器学习',1],['gpt',1],['%_\\',1],['没有匹配的词',0]]){
      await search(query);assert.equal(await cards().count(),count,query);assert.equal(await page.locator('.bank-answer:visible').count(),0);
    }
    let started;const firstRequest=new Promise(resolve=>started=resolve);
    await page.route(/\/api\/question-bank\?/,async route=>{
      if(new URL(route.request().url()).searchParams.get('q')==='慢检索'){
        started();await new Promise(resolve=>setTimeout(resolve,250));
        await route.fulfill({json:{items:[],total:999,page:1,pages:1,page_size:20,query:'慢检索'}}).catch(()=>{});
      }else await route.continue();
    });
    await page.locator('#bank-query').fill('慢检索');await page.getByRole('button',{name:'检索题目',exact:true}).click();await firstRequest;
    await search('分页');assert((await page.locator('#bank-summary').innerText()).includes('22'));
    await new Promise(resolve=>setTimeout(resolve,300));assert((await page.locator('#bank-summary').innerText()).includes('22'));
    await page.unrouteAll({behavior:'wait'});
    await page.locator('#bank-clear').click();await ready();
    await page.route(/\/api\/question-bank\?/,route=>route.abort());
    await search('检索请求失败');assert(await page.locator('#bank-error').isVisible());assert.equal(await cards().count(),20);
    await cards().nth(0).locator('.bank-reveal').click();
    await cards().nth(0).locator('.review').waitFor({timeout:4000});
    assert((await cards().nth(0).locator('.bank-answer').innerText()).includes('正确答案'));
    await page.unrouteAll({behavior:'wait'});
    const secondId=await cards().nth(1).getAttribute('data-question-id');
    await page.route(new RegExp('/api/question-bank/'+secondId+'/answer$'),route=>route.abort());
    await cards().nth(1).locator('.bank-reveal').click();await page.getByRole('button',{name:'重试显示答案'}).waitFor();
    assert(await cards().nth(0).locator('.review').isVisible());
    await page.unrouteAll({behavior:'wait'});await cards().nth(1).locator('.bank-reveal').click();await cards().nth(1).locator('.review').waitFor();
    await search('人工智能');await cards().nth(0).locator('.bank-reveal').click();await cards().nth(0).locator('.review').waitFor();
    assert.equal(await page.locator('.bank-answer:visible').count(),1);
    await page.screenshot({path:path.join(directory,'题库关键词检索与独立答案.png'),fullPage:true});
    await search('gpt');await page.setViewportSize({width:390,height:844});
    await cards().first().locator('.bank-options span').first().evaluate(el=>el.textContent+=' https://example.test/'+ 'longtext'.repeat(40));
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await search('gpt');await cards().first().locator('.bank-reveal').click();await cards().first().locator('.review').waitFor();
    await page.screenshot({path:path.join(directory,'题库浏览手机界面.png'),fullPage:true});
    assert.equal(await page.evaluate(()=>window.bankInjected),undefined);
    assert.deepEqual((await get('/api/drill/current')).round,before);
    assert.equal((await get('/api/drill/wrongs')).total,0);assert.equal((await get('/api/favorites')).total,1);
    assert.deepEqual(errors,[]);
    const report={passed:true,all25QuestionsAcrossPages:true,stemAndOptionKeywordSearch:true,literalAndMultiwordSearch:true,
      perQuestionAnswerVisibility:true,newSearchHidesAnswers:true,latestSearchWins:true,failedSearchKeepsUsableResults:true,
      individualAnswerFailureRecoverable:true,escapedQuestionContent:true,mobileNoOverflow:true,learningRecordsUnchanged:true,pageErrors:errors};
    fs.writeFileSync(path.join(directory,'题库浏览浏览器验证.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
  }finally{await context.close();await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
