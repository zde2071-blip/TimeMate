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
      const dateBox = await date.boundingBox(), placeBox = await place.boundingBox();
      assert.ok(placeBox.y >= dateBox.y + dateBox.height - 1, 'date and location are separate lines');
      const edit = first.getByRole('button', {name: '编辑事项：ADS102 课堂测试', exact: true});
      assert.equal(await edit.textContent(), '编辑');
      assert.equal(await edit.locator('svg').count(), 1);
      const editBox = await edit.boundingBox(), addBox = await first.locator('.mail-event-add').boundingBox();
      assert.ok(editBox.y + editBox.height <= addBox.y, 'edit belongs to heading, add belongs below');
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
      const deadline = rows.nth(1);
      await deadline.getByRole('button', {name: '加入截止事项', exact: true}).click();
      await deadline.locator('.mail-event-saved').getByText('已添加', {exact: true}).waitFor();
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
      console.log(width + ': aligned metadata/actions; edit persisted; original/summary; add and cancel passed');
      await page.close();
    }
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
