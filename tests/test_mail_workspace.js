const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'..','index.html'),'utf8');
let top=240,height='',hidden=false;const workspace={getBoundingClientRect:()=>({top}),style:{setProperty:(key,value)=>height=value}},nav={getBoundingClientRect:()=>({height:65})};
const ctx=vm.createContext({window:{innerHeight:900,innerWidth:1200},$:()=>({hidden}),document:{querySelector:selector=>selector==='.tabs'?nav:workspace}});
vm.runInContext(html.slice(html.indexOf('function updateMailWorkspaceHeight('),html.indexOf('let mailStatusMessage=')),ctx);
ctx.updateMailWorkspaceHeight();assert.equal(height,'583px');top=20;ctx.updateMailWorkspaceHeight();assert.equal(height,'803px','scrolling header away makes the reading pane taller');
ctx.window.innerHeight=1000;ctx.updateMailWorkspaceHeight();assert.equal(height,'903px','resize fills available space');ctx.window.innerWidth=600;height='mobile';ctx.updateMailWorkspaceHeight();assert.equal(height,'mobile','mobile keeps the stacked layout');
assert.ok(!html.includes('100vh - 345px'));assert.match(html,/\.mail-list-title\{[^}]*webkit-line-clamp:2/);
