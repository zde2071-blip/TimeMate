const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const html=require('./ui_source').readUI();
let top=240,height='',hidden=false;const workspace={getBoundingClientRect:()=>({top}),style:{setProperty:(key,value)=>height=value}},nav={getBoundingClientRect:()=>({height:65})};
const ctx=vm.createContext({window:{innerHeight:900,innerWidth:1200},$:()=>({hidden}),document:{querySelector:selector=>selector==='.tabs'?nav:workspace}});
vm.runInContext(require('./ui_source').functions("updateMailWorkspaceHeight"),ctx);
ctx.updateMailWorkspaceHeight();assert.equal(height,'648px');top=20;ctx.updateMailWorkspaceHeight();assert.equal(height,'868px','scrolling header away makes the reading pane taller');
ctx.window.innerHeight=1000;ctx.updateMailWorkspaceHeight();assert.equal(height,'968px','resize fills available space');ctx.window.innerWidth=600;height='mobile';ctx.updateMailWorkspaceHeight();assert.equal(height,'mobile','mobile keeps the stacked layout');
assert.ok(!html.includes('100vh - 345px'));assert.doesNotMatch(html,/\.mail-list-title\{[^}]*(?:line-clamp|overflow:hidden)/);
