// Real authenticated routes, source navigation and persisted partial-coverage notice.
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const assert=require('node:assert/strict');
const path=require('node:path');
(async()=>{
  const server=spawn(path.resolve('.venv/bin/python'),['tests/chat_browser_server.py']);
  let browser,log='';server.stderr.on('data',d=>log+=d);
  try {
    const origin=await new Promise((resolve,reject)=>{
      server.stdout.once('data',d=>resolve(String(d).trim()));
      server.once('exit',()=>reject(Error(log)));
    });
    browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
    for(const width of [1440,390]) {
      const page=await browser.newPage({viewport:{width,height:1000}}),errors=[];
      page.on('pageerror',e=>errors.push(e.message));
      await page.goto(origin+'/fixture-login');
      if(await page.locator('#connection-welcome').isVisible())await page.getByRole('button',{name:'稍后',exact:true}).click();
      await page.locator('#nav-chat').click();
      await page.locator('#chat-input').fill('检索回归：查询全部邮件中的截止');
      await page.locator('#chat-send').click();
      await page.locator('.chat-message-sources').waitFor();
      assert.equal(await page.locator('.chat-source-link').count(),1);
      assert.match(await page.locator('#chat-status').textContent(),/部分检索/);
      assert.match(await page.locator('.is-assistant .chat-message-content').textContent(),/部分检索/);
      await page.reload();await page.locator('#nav-chat').click();
      await page.locator('.chat-source-link').waitFor();
      assert.match(await page.locator('.is-assistant .chat-message-content').textContent(),/部分检索/);
      await page.locator('.chat-source-link').click();
      await page.locator('#mail-detail-pane').waitFor({state:'visible'});
      assert.match(await page.locator('#mail-detail-pane').textContent(),/检索样例/);
      assert.deepEqual(errors,[]);
      console.log(width+': retrieval, validated source link, persisted coverage notice and mail navigation passed');
      await page.close();
    }
  } finally { if(browser)await browser.close();server.kill('SIGTERM'); }
})().catch(e=>{console.error(e);process.exitCode=1});
