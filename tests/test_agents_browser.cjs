const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const assert=require('node:assert/strict'),path=require('node:path'),os=require('node:os');
(async()=>{
 const server=spawn(path.resolve('.venv/bin/python'),['tests/connections_browser_server.py']);
 let browser,log='';server.stderr.on('data',d=>log+=d);
 try {
  const origin=await new Promise((res,rej)=>{server.stdout.once('data',d=>res(String(d).trim()));server.once('exit',()=>rej(Error(log)))});
  browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
  for(const width of [1440,390]){
   const page=await browser.newPage({viewport:{width,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(10000);
   await page.goto(origin+'/fixture-login');await page.getByRole('button',{name:'稍后',exact:true}).click();
   const presentation=selector=>page.locator(selector).evaluate(el=>{const c=getComputedStyle(el);return [c.fontSize,c.padding,c.borderRadius,c.backgroundColor,c.height]});
   await page.locator('#settings-nav-ai').click();
   const standardButton=await presentation('#ai-profile-new');
   await page.locator('#ai-profile-new').click();
   const standardDialog=await page.locator('#ai-profile-dialog').evaluate(el=>({width:el.getBoundingClientRect().width,font:getComputedStyle(el.querySelector('h2')).fontSize}));
   await page.evaluate(()=>document.getElementById('ai-profile-dialog').close());
   await page.locator('#settings-nav-agents').click();await page.getByText('尚未添加 Agent').waitFor();
   await page.getByRole('button',{name:'＋ 添加 Agent',exact:true}).click();
   await page.mouse.move(0,0);
   assert.deepEqual(await presentation('#agent-profile-new'),standardButton,'same add-button presentation as AI settings');
   const agentDialog=await page.locator('#agent-dialog').evaluate(el=>({width:el.getBoundingClientRect().width,font:getComputedStyle(el.querySelector('h2')).fontSize}));
   assert.deepEqual(agentDialog,standardDialog,'same dialog width and title scale as AI settings');
   assert.equal(await page.locator('#agent-provider').inputValue(),'dot');
   assert.equal(await page.locator('#agent-dot-setup').isVisible(),true);
   assert.equal(await page.locator('#agent-dot-setup p').count(),0,'Dot uses illustrated guide without duplicate prose');
   assert.equal(await page.locator('#agent-setup-help').isVisible(),false);
   await page.screenshot({path:path.join(os.tmpdir(),`timemate-agent-dot-${width}.png`)});
   await page.getByRole('link',{name:'查看图文教程 ↗',exact:true}).click();
   await page.locator('#setup-guide-content figure').nth(0).waitFor();
   assert.equal(await page.locator('#setup-guide-content img').count(),3);
   assert.equal(await page.locator('#setup-guide-content figure:visible').count(),1);
   assert.equal(await page.locator('#setup-guide-progress').textContent(),'1 / 3');
   assert.equal(await page.locator('#setup-guide-prev').isDisabled(),true);
   await page.locator('#setup-guide-next').click();
   assert.equal(await page.locator('#setup-guide-progress').textContent(),'2 / 3');
   await page.locator('#setup-guide-next').press('ArrowRight');
   assert.equal(await page.locator('#setup-guide-progress').textContent(),'3 / 3');
   assert.equal(await page.locator('#setup-guide-next').isDisabled(),true);
   assert.equal(await page.locator('#setup-guide-content figure:visible p').count(),2,'final page retains connection and consent instructions');
   assert.ok(await page.locator('#setup-guide-content').evaluate(el=>el.scrollHeight<=el.clientHeight+2),'whole step including consent text fits without scrolling');
   await page.locator('#setup-guide-prev').click();
   assert.equal(await page.locator('#setup-guide-content figure:visible').count(),1);

   await page.locator('#setup-guide-content img').evaluateAll(async imgs=>{await Promise.all(imgs.map(img=>{img.loading='eager';return img.decode()}))});
   assert.equal(await page.locator('#setup-guide-title').textContent(),'连接 TimeMate');
   assert.equal(await page.locator('#setup-guide-dialog').evaluate(el=>el.scrollWidth<=el.clientWidth),true,'tutorial fits dialog');
   await page.screenshot({path:path.join(os.tmpdir(),`timemate-agent-guide-${width}.png`)});
   await page.evaluate(()=>closeSetupGuide());
   assert.equal(await page.locator('#agent-dialog').isVisible(),true,'closing tutorial returns to setup');
   await page.evaluate(()=>openSetupGuide('qq'));
   await page.locator('#setup-guide-progress').getByText('1 / 3',{exact:true}).waitFor();
   await page.locator('#setup-guide-content').dispatchEvent('touchstart',{touches:[{identifier:1,clientX:250,clientY:100}]});
   await page.locator('#setup-guide-content').dispatchEvent('touchend',{changedTouches:[{identifier:1,clientX:100,clientY:108}]});
   assert.equal(await page.locator('#setup-guide-progress').textContent(),'2 / 3');
   await page.evaluate(()=>closeSetupGuide());
   await page.locator('#agent-provider').selectOption('grok');
   const connectPrompt=await page.evaluate(()=>agentConnectionInstructions('grok'));
   assert.ok(connectPrompt.includes('connection_status'));
   assert.ok(!connectPrompt.includes('Routine'),'connection does not also start a feedback task');
   assert.ok(!(await page.evaluate(()=>agentConnectionInstructions('muse'))).includes('Grok'));
   assert.ok((await page.evaluate(()=>agentConnectionInstructions('grok','feedback'))).includes('acknowledge_feedback'));
   await page.locator('#agent-create').click();await page.locator('#agent-issued').waitFor();
   const key=await page.locator('#agent-issued-key').inputValue();assert.ok(key.startsWith('tm_'));
   assert.equal(await page.locator('#agent-direction-status-connection').textContent(),'待连接');
   assert.equal(await page.locator('#agent-tab-connection').evaluate(el=>el.classList.contains('is-connected')),false);
   assert.equal(await page.locator('#agent-tab-feedback').evaluate(el=>el.classList.contains('is-connected')),false);
   const rpc=await page.request.post(origin+'/mcp',{headers:{Authorization:'Bearer '+key},data:{jsonrpc:'2.0',id:1,method:'tools/call',params:{name:'connection_status',arguments:{}}}});
   assert.equal(rpc.status(),200);assert.equal((await rpc.json()).result.isError,false);
   await page.evaluate(()=>loadAgentConnections());
   assert.equal(await page.locator('#agent-direction-status-connection').textContent(),'已连接');
   assert.equal(await page.locator('#agent-direction-status-feedback').textContent(),'待配置');
   assert.equal(await page.locator('#agent-tab-connection').evaluate(el=>el.classList.contains('is-connected')),true);
   assert.equal(await page.locator('#agent-tab-feedback').evaluate(el=>el.classList.contains('is-connected')),false);
   const verifiedStates=await page.evaluate(()=>{
     const c=agentConnections.find(c=>c.id===agentEditing),original=c.feedback;
     const checked=[];
     for(const sub of [
       {enabled:true,expires:Date.now()/1000+3600,last_ack:null,last_delivery:Date.now()/1000,last_error:''},
       {enabled:true,expires:Date.now()/1000+3600,last_ack:Date.now()/1000,last_error:''},
       {enabled:true,expires:Date.now()/1000+3600,last_ack:Date.now()/1000,last_error:'Delivery failed'},
       {enabled:true,expires:Date.now()/1000-1,last_ack:Date.now()/1000,last_error:''}
     ]) {
       c.feedback=[sub];renderAgentConnection();
       checked.push([document.getElementById('agent-tab-connection').classList.contains('is-connected'),document.getElementById('agent-tab-feedback').classList.contains('is-connected')]);
     }
     c.feedback=original;renderAgentConnection();return checked;
   });
   assert.deepEqual(verifiedStates,[[true,false],[true,true],[true,false],[true,false]],'only acknowledged, current, healthy feedback turns the return direction green');
   assert.ok(await page.locator('#agent-tab-feedback').getAttribute('aria-label').then(s=>s.startsWith('TimeMate → Grok Bot')));
   assert.ok(await page.locator('#agent-tab-connection').getAttribute('aria-label').then(s=>s.startsWith('Grok Bot → TimeMate')));
   await page.screenshot({path:path.join(os.tmpdir(),`timemate-agent-connection-${width}.png`)});
   await page.locator('#agent-tab-feedback').click();
   assert.equal(await page.locator('#agent-grok-feedback').isVisible(),true);
   assert.equal(await page.locator('#agent-panel-connection').isVisible(),false);
   await page.screenshot({path:path.join(os.tmpdir(),`timemate-agent-feedback-${width}.png`)});
   await page.locator('#agent-grok-feedback').getByRole('link',{name:'查看图文教程 ↗'}).click();
   await page.getByText('1 / 2',{exact:true}).waitFor();
   assert.equal(await page.locator('#setup-guide-content figure:visible').count(),1);
   await page.locator('#setup-guide-content img').evaluateAll(async imgs=>{await Promise.all(imgs.map(img=>img.decode()))});
   await page.screenshot({path:path.join(os.tmpdir(),`timemate-grok-guide-${width}.png`)});
   await page.locator('#setup-guide-next').click();
   assert.equal(await page.locator('#setup-guide-progress').textContent(),'2 / 2');
   assert.ok(await page.locator('#setup-guide-content').evaluate(el=>el.scrollHeight<=el.clientHeight+2),'Grok guide caption and explanation fit without scrolling');
   if(width===390)assert.ok(await page.locator('#setup-guide-dialog').evaluate(el=>el.getBoundingClientRect().height<700),'mobile guide does not leave a full-screen blank area');
   await page.evaluate(()=>closeSetupGuide());

   await page.locator('#agent-tab-feedback').press('ArrowLeft');
   assert.equal(await page.locator('#agent-panel-connection').isVisible(),true);
   await page.locator('#agent-dialog').getByRole('button',{name:'关闭',exact:true}).click();
   await page.screenshot({path:path.join(os.tmpdir(),`timemate-agent-list-${width}.png`)});
   await page.waitForFunction(()=>document.getElementById('agent-issued-key').value==='');
   await page.getByRole('button',{name:'设置 Grok Bot',exact:true}).click();
   assert.equal(await page.locator('#agent-issued').isVisible(),false);
   page.once('dialog',dialog=>dialog.accept());await page.getByRole('button',{name:'断开连接',exact:true}).click();
   await page.locator('#agent-dialog').waitFor({state:'hidden'});
   const revoked=await page.request.post(origin+'/mcp',{headers:{Authorization:'Bearer '+key},data:{jsonrpc:'2.0',id:2,method:'ping'}});assert.equal(revoked.status(),401);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'no horizontal overflow');
   await page.getByRole('button',{name:'＋ 添加 Agent',exact:true}).click();await page.locator('#agent-provider').selectOption('muse');
   assert.equal(await page.locator('#agent-muse-note').isVisible(),true);
   assert.deepEqual(errors,[]);await page.close();
  }
  console.log('Agent setup, isolated credential lifecycle, real MCP call, revocation and responsive layout passed');
 }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1});
