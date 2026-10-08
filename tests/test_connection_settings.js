const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/main.js','utf8');
const nodes=new Map();const $=id=>{if(!nodes.has(id))nodes.set(id,{value:'',dataset:{},setAttribute(k,v){this[k]=v}});return nodes.get(id)};
const requests=[];let fails=false;
const ctx=vm.createContext({$,token:'test',aiRevision:0,state:{ready:{mail:true,ai:true}},connectionStates:{mail:'',ai:''},connectionBadge:()=>{},document:{querySelectorAll:()=>[]},refresh:async()=>true,fetch:async(path)=>{requests.push(path);return {ok:!(fails&&path.endsWith('/test')),json:async()=>({error:'连接失败'})}}});
vm.runInContext(source.slice(source.indexOf('function connectionBadge('),source.indexOf('function modelOptions(')),ctx);
vm.runInContext(source.slice(source.indexOf('function editSecret('),source.indexOf('\nlet calendarEditing=')),ctx);
async function run(){
 $('account').value='test@qq.com';$('school_sender').value='test@school.edu';
 ctx.savedSecret('password',true);assert.equal($('password').value,'');assert.equal($('password').readOnly,false);assert.equal(ctx.draft('mail').password,'','saved credential is retained without sending the masked display');
 $('password').value='new-secret';$('password').dataset.saved='';$('password').dataset.editing='1';ctx.savedSecret('password',true);assert.equal($('password').value,'new-secret','polling preserves unsaved replacement');
 $('mail-settings').open=true;fails=true;await ctx.connectionAction('mail','save');assert.deepEqual(requests,['/api/settings/mail/test'],'failed validation must not save');assert.equal($('password').value,'new-secret');assert.equal($('mail-settings').open,true);assert.equal($('mail-save').textContent,'连接并保存');
 requests.length=0;fails=false;await ctx.connectionAction('mail','save');assert.deepEqual(requests,['/api/settings/mail/test','/api/settings/mail']);assert.equal($('password').value,'');assert.equal($('mail-settings').open,false);assert.equal($('mail-save').textContent,'✓ 已连接');assert.equal($('mail-feedback').textContent,'');
 ctx.connectionEdited('mail');assert.equal($('mail-save').textContent,'连接并保存');
 $('provider').value='deepseek';ctx.connectionStates.ai='未保存';ctx.renderFieldStatuses(ctx.state);assert.equal($('provider-status').textContent,'✓','selected provider is checked before connecting');assert.equal($('key-status').textContent,'○');ctx.connectionStates.ai='✓ 成功';ctx.renderFieldStatuses(ctx.state);assert.equal($('key-status').textContent,'✓');
 const storage=new Map();ctx.localStorage={getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)};ctx.state.config={};
 vm.runInContext(source.slice(source.indexOf('function forwardingKey('),source.indexOf('\nfunction showPage(')),ctx);
 ctx.renderSetupGuide(ctx.state);assert.equal($('confirm-forwarding').textContent,'○ 未确认');
 ctx.confirmForwarding();assert.equal($('confirm-forwarding').textContent,'✓ 已确认');assert.equal($('confirm-forwarding').disabled,false);assert.equal($('confirm-forwarding').textContent,'✓ 已确认');
 ctx.confirmForwarding();assert.equal($('confirm-forwarding').textContent,'○ 未确认');assert.equal($('confirm-forwarding').textContent,'○ 未确认');
 ctx.connectionStates.mail='';ctx.renderFieldStatuses(ctx.state);assert.equal($('school_sender-status').textContent,'✓');
 ctx.connectionStates.mail='未保存';ctx.renderFieldStatuses(ctx.state);assert.equal($('school_sender-status').textContent,'○');
 console.log('Connection validation, retained credentials and field statuses passed');
}
run().catch(e=>{console.error(e);process.exitCode=1});
