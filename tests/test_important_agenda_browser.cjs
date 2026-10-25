// Real storage/routes, dense list and existing source/edit/complete interactions.
const {chromium}=require('playwright'),{spawn}=require('node:child_process'),assert=require('node:assert/strict'),path=require('node:path'),os=require('node:os');
(async()=>{
 const server=spawn(path.resolve('.venv/bin/python'),['tests/important_browser_server.py']);let browser,log='';server.stderr.on('data',d=>log+=d);
 try {
  const origin=await new Promise((res,rej)=>{server.stdout.once('data',d=>res(String(d).trim()));server.once('exit',()=>rej(Error(log)))});
  browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
  for(const width of [1440,1024,736,390,320]) {
   const page=await browser.newPage({viewport:{width,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(10000);
   await page.goto(origin+'/fixture-login');
   if(await page.locator('#connection-welcome').isVisible()) await page.getByRole('button',{name:'稍后',exact:true}).click();
   await page.locator('#important-ongoing-0').waitFor();
   if(await page.locator('.connection-collapse').isVisible()) await page.locator('.connection-collapse').click();await page.mouse.move(width-3,3);
   assert.equal(await page.locator('#important-page h1,#important-page h2').count(),0,'no repeated important-items page title');
   assert.equal(await page.locator('.important-date-group[open]').count(),1,'only today starts expanded');
   assert.equal(await page.locator('#important-history-0').isVisible(),false,'ended schedules start in folded history');
   assert.equal(await page.locator('#important-completed-0').isVisible(),false,'completed deadlines are folded');
   assert.equal(await page.locator('.important-overdue #important-overdue-0').isVisible(),true,'overdue unfinished deadlines remain visible');
   assert.equal(await page.locator('.important-date-group #important-ongoing-0').isVisible(),true,'ongoing cross-day schedule is under today');
   assert.equal(await page.locator('#important-unknown-0').isVisible(),true,'missing end does not prematurely hide today');
   assert.equal(await page.locator('#important-ongoing-0 .important-card-todo').textContent(),'按复习计划完成每日练习');
   assert.equal(await page.locator('.calendar-day-markers').evaluateAll(nodes=>nodes.every(n=>n.children.length<=2&&n.querySelectorAll('.schedule').length<=1&&n.querySelectorAll('.deadline').length<=1)),true,'one schedule dot and one deadline arrow per date');
   await page.screenshot({path:path.join(os.tmpdir(),`timemate-agenda-production-${width}.png`),fullPage:true});
   await page.getByRole('button',{name:'全部展开',exact:true}).click();
   assert.equal(await page.locator('.important-date-group:not([open])').count(),0);
   const rows=page.locator('.important-date-group .calendar-entry');assert.equal(await rows.count(),30);
   assert.equal(await page.locator('.important-date-context').count(),0,'date headings contain no relative day or weekday');
   const headingText=await page.locator('.important-date-group>.important-date-heading').allTextContents();
   assert.ok(headingText.every(text=>!/今天|明天|星期/.test(text)));
   const month=await page.locator('.calendar-month-picker').boundingBox(),legend=await page.locator('.calendar-legend').boundingBox();
   assert.ok(Math.abs(month.y+month.height/2-legend.y-legend.height/2)<1,'calendar legend shares the month row');
   assert.ok(legend.x>=month.x+month.width+4,'legend is at the right of the month');
   assert.ok(legend.x+legend.width<=(await page.locator('#calendar-view').boundingBox()).x+(await page.locator('#calendar-view').boundingBox()).width,'legend fits calendar pane');
   for(const row of await rows.all()){
    const date=await row.locator('.important-card-time').boundingBox(),place=await row.locator('.important-card-location').boundingBox(),title=await row.locator('.important-entry-summary>strong').boundingBox(),todo=await row.locator('.important-card-todo').boundingBox();
    const label=await row.locator('xpath=..').locator('.important-date-label').boundingBox();
    assert.ok(Math.abs(title.x-label.x)<1,'item title aligns with date text, not collapse chevron');
    assert.ok(Math.abs(date.x-title.x)<1,'metadata icons align with title');
    assert.ok(Math.abs(todo.x-title.x)<1,'reminder icon aligns with title');
    assert.equal(await row.locator('.important-card-todo svg').count(),1,'reminder retains its icon');
    assert.ok(todo.y>=title.y+title.height,'reminder is below title');
    assert.ok(date.y>=todo.y+todo.height,'time and deadline stay on a separate row from reminder');
    if(width>=736)assert.ok(Math.abs(place.y-date.y)<1,'time and location share one metadata row');
   }
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'no horizontal page overflow');
   const future=await page.evaluate(()=>{const d=new Date();d.setDate(d.getDate()+2);return localDateKey(d)});
   await page.locator('.calendar-day[aria-label^="'+future+'"]').click();
   assert.equal(await page.locator('.important-date-group #important-ongoing-0').isVisible(),true,'cross-day schedule appears when selecting its middle day');
   await page.locator('#view-deadline').click();assert.equal(await page.locator('.important-date-group .schedule').count(),0);
   await page.locator('#view-schedule').click();assert.equal(await page.locator('.important-date-group .deadline').count(),0);
   await page.locator('#view-all').click();await page.getByRole('button',{name:'查看全部',exact:true}).click();
   const item=page.locator('#important-item-1-0');
   await item.locator('.event-manage > summary').click();await item.getByRole('button',{name:'修改信息',exact:true}).click();
   await page.locator('#event-edit-form input').first().fill('已核对的实验任务');
   await page.locator('#event-edit-form textarea').fill('完成实验并上传报告');
   await page.getByRole('button',{name:'保存修改',exact:true}).click();await page.locator('#event-edit-dialog').waitFor({state:'hidden'});
   await item.locator('.important-card-todo').getByText('完成实验并上传报告',{exact:true}).waitFor();
   await item.locator('.event-manage > summary').click();await item.getByRole('button',{name:'标记完成',exact:true}).click();
   await page.waitForFunction(()=>document.querySelector('#important-item-1-0')?.closest('.calendar-completed'));
   await page.locator('.calendar-completed').last().locator('summary').first().click();
   await item.locator('.event-manage > summary').click();await item.getByRole('button',{name:'恢复',exact:true}).click();
   await page.waitForFunction(()=>document.querySelector('#important-item-1-0')?.closest('.important-date-group'));
   await item.locator('.important-source-title').click();assert.equal(await page.locator('#mail-page').isVisible(),true,'source title opens the real mail page');
   await page.locator('#nav-important').click();assert.equal(await item.isVisible(),true,'return preserves expanded date groups');
   assert.deepEqual(errors,[]);await page.close();console.log('PASS dense agenda, dates, filters, edit/complete/restore/source '+width);
  }
 }finally{await browser?.close();server.kill();}
})().catch(e=>{console.error(e);process.exit(1)});
