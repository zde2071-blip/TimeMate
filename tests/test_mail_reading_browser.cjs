// Real UI/routes regression: reading switches, edit before adding, pin/cancel, and reload.
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const path = require('node:path'), os = require('node:os'), assert = require('node:assert/strict');
(async () => {
  const server = spawn(path.resolve('.venv/bin/python'), ['tests/mail_reading_browser_server.py']);
  let browser, log = '';
  server.stderr.on('data', d => { log += d; });
  try {
    const origin = await new Promise((resolve, reject) => {
      server.stdout.once('data', d => resolve(String(d).trim()));
      server.once('exit', () => reject(Error(log)));
    });
    browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
    for (const width of [1440, 1024, 736, 390]) {
      const page = await browser.newPage({viewport: {width, height: 1100}}), errors = [];
      page.on('pageerror', e => errors.push(e.message));
      page.setDefaultTimeout(10000);
      await page.goto(origin + '/fixture-login');
      if (await page.locator('#connection-welcome').isVisible()) await page.getByRole('button', {name: '稍后', exact: true}).click();
      await page.locator('#nav-mail').click();
      if (await page.locator('.connection-collapse').isVisible()) await page.locator('.connection-collapse').click();
      await page.locator('#mail-reading-summary-panel .event-row').first().waitFor();
      const rows = page.locator('#mail-reading-summary-panel .event-row');
      assert.equal(await rows.count(), 2);
      const first = rows.first();
      const [date, place] = await first.locator('.mail-event-meta').all();
      assert.equal(await date.textContent(), '2026-10-23 14:00–15:00');
      assert.equal(await rows.nth(1).locator('.mail-event-meta').first().textContent(), '2026-10-30 23:59（截止）');
      assert.equal(await date.locator('svg').innerHTML(), await rows.nth(1).locator('.mail-event-meta svg').first().innerHTML());
      const dateBox = await date.boundingBox(), placeBox = await place.boundingBox();
      assert.ok(placeBox.y >= dateBox.y + dateBox.height - 1, 'date and location are separate lines');
      const edit = first.getByRole('button', {name: '编辑事项：ADS102 课堂测试', exact: true});
      assert.equal(await edit.textContent(), '编辑');
      assert.equal(await edit.locator('svg').count(), 1);
      const editBox = await edit.boundingBox(), addBox = await first.locator('.mail-event-add').boundingBox();
      assert.ok(editBox.y + editBox.height <= addBox.y, 'edit belongs to heading, add belongs below');
      for (const row of await rows.all()) {
        const headingBox = await row.locator('.mail-event-heading').boundingBox();
        const detailsBox = await row.locator('.mail-event-details').boundingBox();
        const buttonBox = await row.locator('.mail-event-add').boundingBox();
        assert.ok(Math.abs(buttonBox.x - headingBox.x) < 1, 'add is aligned with the title');
        assert.ok(Math.abs(buttonBox.x - detailsBox.x) < 1, 'add is aligned with time and location');
        assert.ok(buttonBox.y >= detailsBox.y + detailsBox.height + 19, 'add appears below all metadata with spacing');
      }
      const bounds = await page.locator('#mail-detail-pane').boundingBox();
      assert.ok(editBox.x + editBox.width <= bounds.x + bounds.width, 'actions fit reader');
      assert.equal(await page.locator('.mail-reading-tabs').evaluate(e => getComputedStyle(e.querySelector('.active')).color), 'rgb(22, 115, 78)');
      await page.screenshot({path: path.join(os.tmpdir(), `timemate-mail-reading-${width}.png`), fullPage: true});
      await edit.click();
      await page.locator('#event-edit-form input').first().fill('ADS102 已核对测试');
      await page.getByRole('button', {name: '保存修改', exact: true}).click();
      await page.locator('#event-edit-dialog').waitFor({state: 'hidden'});
      await first.locator('.mail-event-heading strong').getByText('ADS102 已核对测试', {exact: true}).waitFor();
      await page.getByRole('tab', {name: '原邮件', exact: true}).click();
      await page.frameLocator('.inline-mail-source iframe').first().getByText('Please attend the examination on Friday.', {exact: true}).waitFor();
      await page.getByRole('tab', {name: '摘要与事项', exact: true}).click();
      await first.getByRole('button', {name: '加入日程安排', exact: true}).click();
      await page.locator('#calendar-dialog').waitFor({state: 'visible'});
      await page.locator('#calendar-dialog').getByRole('button', {name: '取消', exact: true}).click();
      await first.getByRole('button', {name: '加入日程安排', exact: true}).click();
      await page.locator('#calendar-dialog').getByRole('button', {name: '确认添加', exact: true}).click();
      await page.locator('#calendar-dialog').waitFor({state: 'hidden'});
      await first.locator('.mail-event-saved').getByText('已添加', {exact: true}).waitFor();
      await first.locator('button.mail-event-saved').click();
      await page.locator('#important-reading-0-0').waitFor({state:'visible'});
      assert.equal(await page.locator('#important-page').isVisible(),true,'saved schedule status navigates to important items');
      await page.waitForFunction(()=>document.activeElement?.id==='important-reading-0-0');
      assert.equal(await page.locator('#important-reading-0-0').evaluate(el=>el===document.activeElement),true,'saved schedule gets keyboard focus');
      assert.equal(await page.locator('#important-reading-0-0').evaluate(el=>Boolean(el.closest('.calendar-completed[open]'))),true,'ended schedule archive opens automatically');
      await page.locator('#important-reading-0-0 .important-source-title').click();
      const deadline = rows.nth(1);
      await deadline.getByRole('button', {name: '加入截止事项', exact: true}).click();
      await deadline.locator('.mail-event-saved').getByText('已添加', {exact: true}).waitFor();
      await deadline.locator('button.mail-event-saved').click();
      await page.locator('#important-reading-0-1').waitFor({state:'visible'});
      await page.waitForFunction(()=>document.activeElement?.id==='important-reading-0-1');
      assert.equal(await page.locator('#important-reading-0-1').evaluate(el=>el===document.activeElement),true,'saved deadline status focuses the matching item');
      // Approved important cards: identical clock icons, compact time text, working menus/source.
      await page.locator('#nav-important').click();
      await page.mouse.move(width - 5, 10);
      const scheduleCard = page.locator('.calendar-entry.schedule');
      const deadlineCard = page.locator('.calendar-entry.deadline');
      await page.getByRole('button', {name: '全部展开', exact: true}).click();
      if(!await scheduleCard.isVisible()) await page.locator('.calendar-completed > summary').filter({hasText: '已结束日程'}).click();
      await scheduleCard.waitFor();
      await deadlineCard.waitFor();
      assert.equal(await scheduleCard.locator('.important-card-time').textContent(), '10/23 14:00–15:00');
      assert.equal(await deadlineCard.locator('.important-card-time').textContent(), '23:59（截止）');
      assert.equal(await scheduleCard.locator('.important-card-time svg').innerHTML(), await deadlineCard.locator('.important-card-time svg').innerHTML(), 'schedule and deadline use one clock icon');
      for (const card of [scheduleCard, deadlineCard]) {
        const titleBox = await card.locator('.important-entry-summary>strong').boundingBox();
        const menuBox = await card.locator('.event-manage>summary').boundingBox();
        assert.ok(titleBox.x + titleBox.width <= menuBox.x + 1, 'title and edit never overlap');
        assert.equal(await card.locator('.event-manage>summary svg').count(), 1);
        assert.equal(await card.locator('.source-mail-icon svg').count(), 1);
        const timeBox = await card.locator('.important-card-time').boundingBox();
        const locationBox = await card.locator('.important-card-location').boundingBox();
        if(width>=736)assert.ok(Math.abs(locationBox.y-timeBox.y)<1, 'time and location share one metadata row');
      }
      await page.screenshot({path: path.join(os.tmpdir(), `timemate-important-cards-${width}.png`), fullPage: true, animations: 'disabled'});
      await scheduleCard.locator('.event-manage>summary').click();
      await scheduleCard.getByRole('button', {name: '修改信息', exact: true}).click();
      await page.locator('#event-edit-form input').first().fill('ADS102 已核对测试');
      await page.getByRole('button', {name: '保存修改', exact: true}).click();
      await page.locator('#event-edit-dialog').waitFor({state: 'hidden'});
      await deadlineCard.locator('button.important-complete').click();
      await page.locator('.calendar-completed>summary').last().waitFor();
      // The mail's completed status must also open its otherwise folded archive.
      await page.locator('#nav-mail').click();
      await deadline.locator('button.mail-event-saved').getByText('已完成',{exact:true}).waitFor();
      await deadline.locator('button.mail-event-saved').click();
      const completedCard = page.locator('.calendar-completed .calendar-entry.deadline');
      await completedCard.waitFor({state:'visible'});
      await page.waitForFunction(()=>document.activeElement?.id==='important-reading-0-1');
      assert.equal(await completedCard.evaluate(el=>el===document.activeElement),true,'completed status opens and focuses the archived item');
      await completedCard.evaluate(e => e.scrollIntoView({block: 'center'}));
      await completedCard.locator('.event-manage>summary').click();
      await completedCard.getByRole('button', {name: '恢复', exact: true}).click();
      await page.locator('.calendar-day-events .calendar-entry.deadline').waitFor();
      // Render an additional linked source using the existing saved-item state.
      // This fixture is client-only: no production data and no extra backend behavior.
      await page.evaluate(()=>{
        const source=allEventMails(state).find(m=>m.id==='reading-0'&&m.result),alias={...source,id:'linked-fixture'};
        const data={...state,eventLinks:[...(state.eventLinks||[]),{mail_id:alias.id,event_index:0,target_mail_id:'reading-0',target_index:0},{mail_id:alias.id,event_index:1,target_mail_id:'reading-0',target_index:1}]};
        showPage('mail');
        renderMailDetail(alias,data,new Map(state.calendarEvents.map(item=>[item.mail_id+':'+item.event_index,item])));
      });
      await rows.nth(1).locator('button.mail-event-saved').click();
      await page.locator('#important-reading-0-1').waitFor({state:'visible'});
      await page.waitForFunction(()=>document.activeElement?.id==='important-reading-0-1');
      assert.equal(await page.locator('#important-reading-0-1').evaluate(el=>el===document.activeElement),true,'linked mail opens the saved target rather than the unsaved source id');
      assert.equal(await page.locator('#important-linked-fixture-1').count(),0,'linked source does not create another item');
      await scheduleCard.locator('.important-source-title').click();
      await page.locator('#mail-detail-pane').waitFor({state: 'visible'});
      await page.reload();
      await page.locator('#nav-mail').click();
      await first.locator('.mail-event-heading strong').getByText('ADS102 已核对测试', {exact: true}).waitFor();
      await first.getByRole('button', {name: '取消同步日历', exact: true}).click();
      await first.getByRole('button', {name: '加入日程安排', exact: true}).waitFor();
      await deadline.getByRole('button', {name: '取消加入截止事项', exact: true}).click();
      await deadline.getByRole('button', {name: '加入截止事项', exact: true}).waitFor();
      await page.locator('#mail-reading-original-tab').click();
      await page.locator('#mail-reading-original-panel').waitFor({state: 'visible'});
      await page.locator('#mail-reading-summary-tab').click();
      assert.deepEqual(errors, []);
      console.log(width + ': aligned metadata/actions; saved/linked/completed jump; inline complete; edit/original/add/cancel passed');
      await page.close();
    }
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
