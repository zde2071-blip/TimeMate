const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const js=fs.readFileSync('web/main.js','utf8');let calls=0,fail=false;
const ctx=vm.createContext({setupGuideCache:new Map(),fetch:async()=>{calls++;return {ok:!fail,text:async()=>'<main>教程</main>'}}});
vm.runInContext(require('./ui_source').functions("loadSetupGuide"),ctx);
(async()=>{const values=await Promise.all([ctx.loadSetupGuide('/guide'),ctx.loadSetupGuide('/guide')]);assert.equal(calls,1);assert.equal(values[0],values[1]);await ctx.loadSetupGuide('/guide');assert.equal(calls,1);fail=true;await assert.rejects(ctx.loadSetupGuide('/retry'));fail=false;await ctx.loadSetupGuide('/retry');assert.equal(calls,3);console.log('Tutorial requests reused; failed requests can retry')})();
