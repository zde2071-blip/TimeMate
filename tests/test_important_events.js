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
const durationStart = html.indexOf('function addDurationToDateTime(');
const durationEnd = html.indexOf('\nfunction isVagueTimetableWeek(', durationStart);
vm.runInContext(html.slice(durationStart, durationEnd), context);
const deadlineHelpersStart = html.indexOf('function deadlineRemainingMs(');
const deadlineHelpersEnd = html.indexOf('\nfunction renderMonthCalendar(', deadlineHelpersStart);
vm.runInContext(html.slice(deadlineHelpersStart, deadlineHelpersEnd), context);
const { mergeScheduleDuplicates, deadlineReminder, sortDeadlineItems, addDurationToDateTime } = vm.runInContext('({ mergeScheduleDuplicates, deadlineReminder, sortDeadlineItems, addDurationToDateTime })', context);
const vagueWeekStart = html.indexOf('function isVagueTimetableWeek(');
const vagueWeekEnd = html.indexOf('\nfunction openCalendar(', vagueWeekStart);
vm.runInContext(html.slice(vagueWeekStart, vagueWeekEnd), context);
const { isVagueTimetableWeek } = vm.runInContext('({ isVagueTimetableWeek })', context);

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

const now = new Date('2026-10-06T12:00:00');
const deadline = (start, allDay = false) => ({ kind: 'deadline', start, event: { start, allDay } });
assert.equal(deadlineReminder(deadline('2026-10-06T23:00:00'), now).label, '1天内截止');
assert.equal(deadlineReminder(deadline('2026-10-08T12:00:00'), now).label, '3天内截止');
assert.equal(deadlineReminder(deadline('2026-10-12T12:00:00'), now).label, '7天内截止');
assert.equal(deadlineReminder(deadline('2026-10-14T12:00:00'), now), null);
assert.equal(deadlineReminder(deadline('2026-10-06T11:59:00'), now).label, '已截止');
assert.equal(deadlineReminder(deadline('2026-10-07T00:00:00', true), new Date('2026-10-07T12:00:00')).label, '1天内截止');
assert.equal(isVagueTimetableWeek({ title: 'CSI101 Week 4 实验课', start: '2026-10-05T00:00:00', end: '2026-10-10T00:00:00', allDay: true, evidence: 'Your lab begins this week. Check your timetable. Section: Week 4 October 5th-9th' }), true);
assert.equal(isVagueTimetableWeek({ title: '实验课', start: '2026-10-07T14:00:00', end: '2026-10-07T16:00:00', allDay: false, evidence: 'Check your timetable' }), false);
assert.equal(addDurationToDateTime('2026-10-07T14:00', 60), '2026-10-07T15:00');
assert.equal(addDurationToDateTime('2026-10-07T23:30', 60), '2026-10-08T00:30');
const editorStart = html.indexOf('function openEventEditor(');
const editorEnd = html.indexOf('\nfunction addSchedule(', editorStart);
const editorSource = html.slice(editorStart, editorEnd);
assert.match(editorSource, /\['\+30分钟',30\],\['\+1小时',60\],\['\+2小时',120\]/, 'event editing offers the same end-time duration shortcuts');
assert.match(editorSource, /start\.oninput=\(\)=>\{updateShortcuts\(\);if\(selectedDuration!==null\)end\.value=addDurationToDateTime\(start\.value,selectedDuration\)\}/, 'a chosen duration follows later start-time edits');

const sorted = sortDeadlineItems([
  deadline('2026-10-04T23:59:00'),
  deadline('2026-10-15T00:00:00'),
  deadline('2026-10-03T12:00:00'),
  deadline('2026-10-08T12:00:00'),
], now);
assert.deepEqual([...sorted].map(item => item.start), [
  '2026-10-08T12:00:00',
  '2026-10-15T00:00:00',
  '2026-10-03T12:00:00',
  '2026-10-04T23:59:00',
], 'upcoming deadlines are nearest-first and overdue deadlines are last');
