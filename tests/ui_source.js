const fs = require('node:fs');
const path = require('node:path');
const root = path.join(__dirname, '..', 'web');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const scripts = [...html.matchAll(/<script src="\/([^"/]+\.js)"><\/script>/g)].map(match => match[1]);
const script = scripts.map(file => fs.readFileSync(path.join(root, file), 'utf8')).join('\n');
exports.readUI = () => html.replace('<link rel="stylesheet" href="/styles.css">', '<style>' + fs.readFileSync(path.join(root, 'styles.css'), 'utf8') + '</style>').replace(/<script src="\/[^"/]+\.js"><\/script>/g, '').replace('</html>', '<script>' + script + '</script></html>');
// Load named declarations only: unrelated DOM listeners must never leak into a
// unit-test VM when a neighbouring feature gains a listener or another helper.
exports.functions = (...names) => names.map(name => {
  const start = script.search(new RegExp('^(?:async )?function ' + name + '\\(', 'm'));
  if (start < 0) throw Error('Unknown UI function: ' + name);
  const end = script.indexOf('\n}', start);
  if (end < 0) throw Error('Unclosed UI function: ' + name);
  return script.slice(start, end + 2);
}).join('\n');
