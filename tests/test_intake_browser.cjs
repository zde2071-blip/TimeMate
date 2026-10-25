const {chromium}=require('playwright'),{spawn}=require('node:child_process'),assert=require('node:assert/strict'),path=require('node:path'),os=require('node:os');
(async()=>{
 const server=spawn(path.resolve('.venv/bin/python'),['tests/connections_browser_server.py']);let browser,log='';server.stderr.on('data',d=>log+=d);
 try {
  const origin=await new Promise((res,rej)=>{server.stdout.once('data',d=>res(String(d).trim()));server.once('exit',()=>rej(Error(log)))});
  browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
  for(const width of [1440,1024,390,320]) {
   const page=await browser.newPage({viewport:{width,height:1050}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(10000);
   const connections=[{id:'fixture-dot',name:'Dot',provider:'dot',scope:'mail:read mail:write items:read items:write changes:read',expires:9999999999,last_used:1,feedback:[]}];
   await page.route('**/api/agents',r=>r.fulfill({json:{connections,mcp_url:origin+'/mcp'}}));
   await page.goto(origin+'/fixture-login');await page.getByRole('button',{name:'稍后',exact:true}).click();
   await page.locator('#nav-intake').click();await page.locator('[data-source-id="fixture-dot"]').waitFor();
   assert.equal(await page.locator('.intake-source.intake-empty').count(),1,'empty mailboxes link to existing settings');
   await page.locator('.intake-source.intake-empty').click();assert.equal(await page.locator('#settings-page').isVisible(),true);assert.equal(await page.locator('#mail-accounts').isVisible(),true);
   const ids=await page.evaluate(async()=>{
    const headers={'Content-Type':'application/json','X-Token':document.querySelector('meta[name="csrf-token"]').content};
    for(const school_sender of ['school@example.edu','personal@example.com']){
     const r=await fetch('/api/settings/mail',{method:'POST',headers,body:JSON.stringify({mailAccountId:'',school_sender,account:'receiver@qq.com',mail_provider:'qq',password:'fixture-secret'})});if(!r.ok)throw Error(await r.text());
    }
    await refresh();return state.mailAccounts.map(x=>x.id);
   });
   await page.locator('#nav-intake').click();await page.locator('[data-source-id="'+ids[0]+'"]').waitFor();await page.mouse.move(width-5,5);
   assert.equal(await page.locator('[data-source-id]').count(),3);
   if(width>=1024){await page.waitForFunction(()=>document.querySelectorAll('.intake-wires g path').length===5);assert.equal(await page.locator('.intake-wires g path').count(),5);assert.ok(await page.locator('.intake-wires g path').evaluateAll(paths=>paths.every(p=>getComputedStyle(p).strokeDasharray==='none')));}
   await page.locator('[data-source-id="'+ids[0]+'"]').click();
   assert.equal(await page.locator('#settings-nav-mail').getAttribute('aria-current'),'page');assert.equal(await page.locator('#school_sender').inputValue(),'school@example.edu');
   assert.deepEqual(await page.locator('.forward-step-heading h4').allTextContents(),['连接接收邮箱','设置自动转发']);
   await page.locator('#mail-name').fill('学校邮箱');await page.locator('#mail-name-save').click();await page.locator('#mail-name-feedback').getByText('已保存',{exact:true}).waitFor();
   await page.locator('#nav-intake').click();assert.equal(await page.locator('[data-source-id="'+ids[0]+'"] .intake-source-copy').textContent(),'学校邮箱');
   await page.locator('[data-source-id="'+ids[1]+'"]').click();assert.equal(await page.locator('#school_sender').inputValue(),'personal@example.com');
   await page.locator('#mail-name').fill('个人邮箱');await page.locator('#mail-name-save').click();await page.locator('#mail-name-feedback').getByText('已保存',{exact:true}).waitFor();
   await page.locator('#nav-intake').click();await page.mouse.move(width-5,5);await page.waitForTimeout(200);
   await page.screenshot({path:path.join(os.tmpdir(),`timemate-intake-live-${width}.png`),fullPage:true});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'no page overflow');
   await page.locator('[data-source-id="fixture-dot"]').click();assert.equal(await page.locator('#settings-page').isVisible(),true);assert.equal(await page.locator('#settings-nav-agents').getAttribute('aria-current'),'page');assert.equal(await page.locator('#agent-dialog').isVisible(),true);assert.equal(await page.locator('#agent-dialog-title').textContent(),'Dot');
   await page.locator('#agent-cancel').click();await page.locator('#nav-intake').click();await page.locator('.intake-calendar').click();assert.equal(await page.locator('#settings-nav-calendar').getAttribute('aria-current'),'page');
   await page.locator('#nav-intake').click();await page.locator('.intake-heading button').click();assert.equal(await page.locator('#settings-nav-mail').getAttribute('aria-current'),'page');assert.equal(await page.locator('#mail-accounts').isVisible(),true);
   await page.reload();await page.locator('#nav-intake').click();await page.locator('[data-source-id="'+ids[0]+'"] .intake-source-copy').getByText('学校邮箱',{exact:true}).waitFor();
   await page.locator('[data-source-id="'+ids[1]+'"]').click();await page.locator('#mail-name').fill('学校邮箱');await page.locator('#mail-name-save').click();await page.locator('#mail-name-feedback').getByText('已保存',{exact:true}).waitFor();
   await page.locator('#nav-intake').click();assert.deepEqual(await page.locator('.intake-source-copy small').allTextContents(),['school@example.edu','personal@example.com'],'duplicate labels remain distinguishable');
   await page.locator('[data-destination="mail"]').click();assert.equal(await page.locator('#mail-page').isVisible(),true);assert.equal(await page.locator('#intake-page').isVisible(),false);
   assert.deepEqual(await page.locator('#mail-account-filter option').allTextContents(),['全部邮箱','学校邮箱 · school@example.edu','学校邮箱 · personal@example.com']);
   assert.deepEqual(errors,[]);await page.close();console.log('PASS intake, settings destinations, labels persisted, duplicate names and solid lines '+width);
  }
 } finally {await browser?.close();server.kill();}
})().catch(e=>{console.error(e);process.exit(1)});
