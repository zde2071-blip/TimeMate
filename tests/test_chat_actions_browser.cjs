// Real local routes/storage with deterministic AI responses; no production accounts or API calls.
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),assert=require('node:assert/strict');
(async()=>{
 const server=spawn(path.resolve('.venv/bin/python'),['tests/chat_browser_server.py'],{cwd:process.cwd(),stdio:['ignore','pipe','pipe']});
 let browser,errors=[],serverLog='';
 server.stderr.on('data',chunk=>serverLog+=chunk);
 try {
  const origin=await new Promise((resolve,reject)=>{
   const timeout=setTimeout(()=>reject(Error('Fixture startup timed out: '+serverLog)),12000);
   server.stdout.once('data',chunk=>{clearTimeout(timeout);resolve(String(chunk).trim())});
   server.once('exit',code=>{clearTimeout(timeout);reject(Error('Fixture exited '+code+': '+serverLog))});
  });
  browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  for (const width of [1440,390]) {
   const page=await browser.newPage({viewport:{width,height:1000}});
   page.on('pageerror',error=>errors.push(error.message));
   await page.goto(origin+'/fixture-login');
   await page.locator('#nav-chat').click();
   await page.locator('#chat-input').waitFor({state:'visible'});
   await page.locator('#chat-new').click();
   assert.equal(await page.locator('#chat-approval-name').textContent(),'逐项确认');
   // Build a readable exam image using the browser, then send it through the actual upload path.
   const imagePage=await browser.newPage({viewport:{width:800,height:500}});
   await imagePage.setContent('<html><meta charset="utf-8"><body style="padding:40px;font:24px sans-serif"><h1>考试与提交安排</h1><p>ISA104 项目：2026年10月25日23:59截止</p><p>SOE104 考试：2026年10月26日09:00—11:00</p><p>地点：FB308</p></body></html>');
   const image=await imagePage.screenshot();await imagePage.close();
   assert.equal(await page.locator('#chat-form #chat-approval-menu').count(),1);
   await page.locator('#chat-approval-menu summary').click();
   await page.getByText('整理出事项，由你逐条点击添加。',{exact:true}).waitFor({state:'visible'});
   await page.locator('[data-approval-mode=confirm]').click();
   assert.equal(await page.locator('#chat-model-name').textContent(),'fixture-vision');
   assert.equal(await page.locator('#chat-mode-hint, #chat-image-notice').count(),0);
   await page.locator('#chat-model-menu summary').click();
   await page.locator('#chat-model-settings').click();
   await page.locator('#settings-page').waitFor({state:'visible'});
   assert.equal(await page.locator('.settings-nav-item[aria-current="page"]').getAttribute('data-setting'),'ai');
   await page.locator('#nav-chat').click();
   await page.locator('#chat-new').click();
   // Exercise the browser paste event with the same files/items data used by Cmd/Ctrl+V.
   await page.locator('#chat-input').fill('图片');
   await page.locator('#chat-input').evaluate((input,encoded)=>{
    input.setSelectionRange(0,2);
    const bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));
    const clipboard=new DataTransfer();
    clipboard.items.add(new File([bytes],'粘贴图片.png',{type:'image/png'}));
    clipboard.setData('text/plain','请整理图片');
    input.dispatchEvent(new ClipboardEvent('paste',{clipboardData:clipboard,bubbles:true,cancelable:true}));
   },image.toString('base64'));
   await page.locator('.chat-attachment img').waitFor();
   assert.equal(await page.locator('#chat-input').inputValue(),'请整理图片');
   await page.locator('.chat-attachment button').click();
   assert.equal(await page.locator('.chat-attachment').count(),0);
   await page.locator('#chat-input').fill('');

   await page.locator('#chat-image-input').setInputFiles({name:'考试安排.png',mimeType:'image/png',buffer:image});
   await page.locator('.chat-attachment').waitFor();
   await page.locator('#chat-send').click();
   await page.locator('.chat-event-card').first().waitFor();
   assert.equal(await page.locator('.chat-event-list').evaluate(node=>getComputedStyle(node).borderTopWidth),'0px','event list must not inherit a nested panel border');
   assert.equal(await page.locator('.chat-event-add').count(),2);
   await page.screenshot({path:path.join(os.tmpdir(),`timemate-chat-actions-ready-${width}.png`)});
   assert.equal(await page.locator('.chat-attachment').count(),0);
   await page.locator('.chat-event-add').first().click();
   await page.locator('.chat-event-state').first().waitFor();
   assert.equal(await page.locator('.chat-event-add').count(),1);
   await page.reload();await page.locator('#nav-chat').click();
   await page.locator('.chat-event-state').first().waitFor();
   assert.equal(await page.locator('.chat-event-add').count(),1,'pending action survives reload');
   await page.locator('.chat-event-add').click();
   await page.waitForFunction(()=>document.querySelectorAll('.chat-event-state').length===2);
   await page.locator('#nav-important').click();
   await page.getByRole('button',{name:'日程安排',exact:true}).click();
   await page.locator('.important-source-title').filter({hasText:'SOE104'}).first().waitFor({state:'visible'});
   await page.locator('.important-source-title').filter({hasText:'SOE104'}).first().click();
   await page.locator('#chat-input').waitFor({state:'visible'});
   await page.locator('#chat-new').click();
   await page.locator('#chat-approval-menu summary').click();
   await page.locator('[data-approval-mode=auto]').click();
   await page.locator('#chat-input').fill('整理并加入这些事项');await page.locator('#chat-send').click();
   await page.locator('.chat-event-state').first().waitFor();
   assert.equal(await page.locator('.chat-event-add').count(),0,'automatic mode avoids confirmation for exact duplicates');
   const labels=await page.locator('.chat-event-state').allTextContents();
   assert.ok(labels.every(text=>text.includes('已有相同事项')));
   await page.locator('#chat-new').click();
   await page.locator('#chat-input').fill('整理这个不完整的考试时间');await page.locator('#chat-send').click();
   await page.getByRole('button',{name:'补充信息',exact:true}).waitFor();
   assert.equal(await page.locator('.chat-event-add').count(),0,'missing end time never writes in auto mode');
   await page.screenshot({path:path.join(os.tmpdir(),`timemate-chat-actions-${width}.png`)});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'no horizontal overflow');
   await page.locator('#chat-new').click();
   await page.locator('#chat-image-input').setInputFiles({name:'考试.png',mimeType:'image/png',buffer:image});
   await page.locator('.chat-attachment').waitFor();
   await page.locator('#chat-input').fill('不支持图片');await page.locator('#chat-send').click();
   await page.getByText('当前模型或接口不支持这次图片输入',{exact:false}).waitFor();
   assert.equal(await page.locator('.chat-attachment').count(),1,'failed request keeps attachment for retry');

   await page.locator('#chat-new').click();
   await page.locator('#chat-model-menu summary').click();
   await page.locator('#chat-model-settings').click();
   for (const [name,model,key] of [['文本问答','first-model','fixture-key-one'],['图片识别','second-model','fixture-key-two']]) {
    await page.locator('#ai-profile-new').click();
    await page.locator('#ai-profile-name').fill(name);
    await page.locator('#key').fill(key);
    await page.locator('#model-choice').selectOption('__manual__');
    await page.locator('#model').fill(model);
    await page.locator('#ai-save').click();
    await page.waitForFunction(name=>Array.from(document.querySelector('#ai-profile-choice').options).some(o=>o.textContent.startsWith(name)),name);
   }
   await page.locator('#nav-chat').click();
   await page.locator('#chat-new').click();
   await page.locator('#chat-model-menu summary').click();
   await page.locator('.chat-model-option').filter({hasText:'图片识别'}).click();
   assert.equal(await page.locator('#chat-model-name').textContent(),'图片识别');
   await page.locator('#chat-input').fill('查询当前连接');await page.locator('#chat-send').click();
   await page.getByText('当前模型：second-model',{exact:true}).waitFor();
   await page.reload();await page.locator('#nav-chat').click();
   await page.waitForFunction(()=>document.querySelector('#chat-model-name').textContent==='图片识别');
   await page.locator('#chat-approval-menu summary').click();
   await page.screenshot({path:path.join(os.tmpdir(),`timemate-chat-approval-${width}.png`)});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'approval menu fits viewport');
   for (const selector of ['#chat-form','.chat-approval-options']) {
    const rect=await page.locator(selector).boundingBox();
    assert.ok(rect.x>=0 && rect.x+rect.width<=width, selector+' is fully inside the viewport');
   }
   await page.locator('[data-approval-mode=confirm]').click();
   await page.locator('#chat-model-menu summary').click();
   await page.locator('#chat-model-settings').click();
   assert.equal(await page.locator('#key').inputValue(),'','saved API keys never return to browser');
   await page.screenshot({path:path.join(os.tmpdir(),`timemate-api-profiles-${width}.png`)});
   console.log(width+': paste preview/removal, compact toolbar/model settings, multiple API save/switch/reload, upload, per-item approval, reload, calendar navigation, auto dedupe, uncertainty, unsupported-model recovery passed');
   await page.close();
  }
  assert.deepEqual(errors,[]);
 } finally {
  if(browser)await browser.close();
  server.kill('SIGTERM');
 }
})().catch(error=>{console.error(error);process.exitCode=1});
