const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const html = require('./ui_source').readUI();
class Element {
  constructor(tag, text = '') { this.tag = tag; this.text = text; this.children = []; this.style = {}; }
  setAttribute(k,v) { this[k]=v; }
  append(...children) { this.children.push(...children); }
  replaceChildren() { this.children = []; }
  showModal() { this.open = true; }
  close() { this.open = false; }
}
function setup(check, succeeds = true) {
  const calls = [], notices = [], targets = [];
  const dialog = new Element('dialog'), content = new Element('div');
  const context = vm.createContext({
    token: 'test', element: (tag, text, cls) => Object.assign(new Element(tag, text), { className: cls }),
    document: { createElement: tag => new Element(tag), createTextNode: text => text },
    $: id => id === 'event-join-dialog' ? dialog : content,
    fetch: async () => ({ ok: true, json: async () => check }),
    call: async (url, data) => { calls.push({ url, data }); return succeeds; },
    notify: message => notices.push(message), focusImportantEvent: (id,index) => targets.push({id,index}),
  });
  vm.runInContext(require('./ui_source').functions("joinEvent"), context);
  return { join: vm.runInContext('joinEvent', context), calls, notices, targets, dialog, content };
}
const flatten = node => [node, ...node.children.flatMap(child => child instanceof Element ? flatten(child) : [])];
async function run() {
  let test = setup({ candidates: [] }), submitted = [];
  await test.join({ id: 'new', index: 0 }, async data => { submitted.push(data); return true; });
  assert.equal(submitted.length, 1);
  const candidate = { id: 'saved', index: 0, exact: true, event: { title: '通知' }, changes: [], confidence: 'same' };
  test = setup({ candidates: [candidate] });
  await test.join({ id: 'repeat', index: 0 }, async () => { throw Error('must not add duplicate'); });
  assert.equal(test.calls[0].url, '/api/event/link');
  assert.equal(test.calls[0].data.mode, 'link');
  assert.deepEqual(test.targets[0], {id:'saved',index:0});

  candidate.exact = false;
  candidate.changes = [
    { field: 'start', label: '截止时间', before: '10-15', after: '10-18', edited: false },
    { field: 'action', label: '待办', before: '人工内容', after: '新的内容', edited: true },
  ];
  test = setup({ candidates: [candidate] });
  let pending = test.join({ id: 'update', index: 0 }, async () => { throw Error('must not add'); });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(test.calls.length, 0, 'checking does not update automatically');
  const nodes = flatten(test.content), boxes = nodes.filter(node => node.type === 'checkbox');
  assert.deepEqual(boxes.map(box => box.checked), [true, false], 'manual edits remain unchecked');
  assert.equal(nodes.filter(node => node.className === 'event-join-values').length, 2);
  assert.equal(nodes.filter(node => node.text === '当前内容').length, 2);
  assert.equal(nodes.filter(node => node.text === '新邮件内容').length, 2);
  nodes.find(node => node.text === '更新并合并').onclick();
  assert.equal(await pending, true);
  assert.deepEqual(Array.from(test.calls[0].data.selectedFields), ['start']);
  assert.deepEqual(test.targets[0], {id:'saved',index:0});

  test = setup({ candidates: [candidate] });
  pending = test.join({ id: 'preserve', index: 0 }, async () => { throw Error('must not add'); });
  await new Promise(resolve => setImmediate(resolve));
  flatten(test.content).find(node => node.text === '保留原始').onclick();
  assert.equal(await pending, true);
  assert.equal(test.calls[0].data.mode, 'link');
  assert.equal(test.calls[0].data.selectedFields.length, 0);

  test = setup({ candidates: [candidate] }, false);
  pending = test.join({ id: 'failure', index: 0 }, async () => false);
  await new Promise(resolve => setImmediate(resolve));
  await flatten(test.content).find(node => node.text === '更新并合并').onclick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(test.dialog.open, true);
  assert.equal(flatten(test.content).find(node => node.className === 'event-join-error').hidden, false);
  flatten(test.content).find(node => node.text === '取消').onclick();
  assert.equal(await pending, false);

  test = setup({ candidates: [candidate] });
  submitted = [];
  pending = test.join({ id: 'separate', index: 0 }, async data => { submitted.push(data); return true; });
  await new Promise(resolve => setImmediate(resolve));
  flatten(test.content).find(node => node.text === '另建事项').onclick();
  await pending;
  assert.equal(submitted[0].joinDecision, 'new');
  assert.equal(test.calls.length, 0);

  test = setup({ candidates: [candidate] });
  pending = test.join({ id: 'cancel', index: 0 }, async () => { throw Error('must not add'); });
  await new Promise(resolve => setImmediate(resolve));
  flatten(test.content).find(node => node.text === '取消').onclick();
  assert.equal(await pending, false);
  assert.equal(test.calls.length, 0);
}
run().catch(error => { console.error(error); process.exitCode = 1; });
