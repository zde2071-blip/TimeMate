const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
const start = html.indexOf('function genericHelpSuggestion(');
const end = html.indexOf('\nfunction render()', start);
assert.notEqual(start, -1, 'event helpers exist in index.html');
assert.notEqual(end, -1, 'event helpers end before render()');
const context = vm.createContext({});
vm.runInContext(html.slice(start, end), context);
const { mergeScheduleDuplicates } = vm.runInContext('({ mergeScheduleDuplicates })', context);

const title = '第二届西交利物浦大学芯片学院学术沙龙暨校外导师半导体行业专委会思享汇';
const location = '西浦创业家学院 G-1006（太仓）';
const action = '扫描二维码报名参加；如从园区出发，返程需自行预约校车';
const oldEvent = { title, kind: '日程', start: '2026-10-15T13:30:00', end: '2026-10-15T16:15:00', location, action: '' };
const correctedEvent = { ...oldEvent, kind: '活动', end: '2026-10-15T13:53:00', action };
const oldMail = { id: 'old', date: 'Mon, 05 Oct 2026 02:50:28 +0000', result: JSON.stringify({ events: [oldEvent] }) };
const correctedMail = { id: 'corrected', date: 'Mon, 05 Oct 2026 03:15:09 +0000', result: JSON.stringify({ events: [correctedEvent] }) };
const items = [
  { key: 'old:0', kind: 'schedule', m: oldMail, event: oldEvent, result: JSON.parse(oldMail.result) },
  { key: 'corrected:0', kind: 'schedule', m: correctedMail, event: correctedEvent, result: JSON.parse(correctedMail.result) },
];

const merged = mergeScheduleDuplicates(items, [oldMail, correctedMail]);
assert.equal(merged.length, 1, 'the same activity is shown once');
assert.equal(merged[0].m.id, 'corrected', 'the correction email is the source');
assert.equal(merged[0].action, action, 'the available todo is carried onto the merged card');
assert.equal(merged[0].event.end, '', 'conflicting end times are left for confirmation');
