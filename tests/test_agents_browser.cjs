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
   await page.locator('#settings-nav-agents').click();await page.getByText('连接你的个人 Agent，传入邮件并接收处理结果。').waitFor();
   await page.getByRole('button',{name:'＋ 连接 Agent',exact:true}).click();
   assert.equal(await page.locator('#agent-provider').inputValue(),'dot');
   assert.equal(await page.locator('#agent-dot-setup').isVisible(),true);
   await page.screenshot({path:path.join(os.tmpdir(),`timemate-agent-dot-${width}.png`)});
   await page.locator('#agent-provider').selectOption('grok');
   await page.locator('#agent-create').click();await page.locator('#agent-issued').waitFor();
   const key=await page.locator('#agent-issued-key').inputValue();assert.ok(key.startsWith('tm_'));
   assert.equal(await page.locator('#agent-connection-state').textContent(),'等待 Agent 连接');
   const rpc=await page.request.post(origin+'/mcp',{headers:{Authorization:'Bearer '+key},data:{jsonrpc:'2.0',id:1,method:'tools/call',params:{name:'connection_status',arguments:{}}}});
   assert.equal(rpc.status(),200);assert.equal((await rpc.json()).result.isError,false);
   await page.evaluate(()=>loadAgentConnections());
   assert.equal(await page.locator('#agent-connection-state').textContent(),'已连接 · 未启用反馈');
   await page.screenshot({path:path.join(os.tmpdir(),`timemate-agent-connection-${width}.png`)});
   await page.locator('#agent-dialog').getByRole('button',{name:'关闭',exact:true}).click();
   await page.waitForFunction(()=>document.getElementById('agent-issued-key').value==='');
   await page.getByRole('button',{name:'设置 Grok Bot',exact:true}).click();
   assert.equal(await page.locator('#agent-issued').isVisible(),false);
   page.once('dialog',dialog=>dialog.accept());await page.getByRole('button',{name:'断开连接',exact:true}).click();
   await page.locator('#agent-dialog').waitFor({state:'hidden'});
   const revoked=await page.request.post(origin+'/mcp',{headers:{Authorization:'Bearer '+key},data:{jsonrpc:'2.0',id:2,method:'ping'}});assert.equal(revoked.status(),401);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'no horizontal overflow');
   await page.getByRole('button',{name:'＋ 连接 Agent',exact:true}).click();await page.locator('#agent-provider').selectOption('muse');
   assert.equal(await page.locator('#agent-muse-note').isVisible(),true);
   assert.deepEqual(errors,[]);await page.close();
  }
  console.log('Agent setup, isolated credential lifecycle, real MCP call, revocation and responsive layout passed');
 }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1});
