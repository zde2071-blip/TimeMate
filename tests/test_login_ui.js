const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('web/login.html','utf8'),script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,{value:'',checked:false,hidden:false,disabled:false,setAttribute(k,v){this[k]=v}});return nodes.get(id)};
const calls=[],location={href:''};
const ctx=vm.createContext({document:{getElementById:$},location,fetch:async(url,opts)=>{calls.push({url,body:JSON.parse(opts.body)});return {ok:true,text:async()=>'{"ok":true}'}}});
vm.runInContext(script,ctx);
(async()=>{
 ctx.mode('register');assert.equal($('submit').disabled,true);assert.equal($('send-code').hidden,false);
 $('email').value='test@example.com';$('consent').checked=true;$('consent').onchange();
 await $('send-code').onclick();assert.equal(calls[0].url,'/api/auth/send-code');
 $('code').value='123456';$('code').oninput();$('password').value='password123';
 await $('form').onsubmit({preventDefault(){}});assert.equal(calls[1].url,'/api/auth/register');assert.equal(calls[1].body.code,'123456');assert.equal(calls[1].body.email,'test@example.com');assert.ok(!('invite' in calls[1].body));assert.equal(location.href,'/');
 ctx.mode('login');assert.equal($('consent-group').hidden,true);assert.equal($('submit').disabled,false);
 ctx.mode('reset');assert.equal($('reset-row').hidden,false);assert.equal($('back').hidden,false);$('reset-code').value='654321';$('reset-code').oninput();
 await $('send-reset-code').onclick();assert.equal(calls[2].url,'/api/auth/send-reset-code');$('password').value='new-password-123';
 await $('form').onsubmit({preventDefault(){}});assert.equal(calls[3].url,'/api/auth/reset');assert.equal(calls[3].body.code,'654321');assert.equal($('submit').textContent,'登录');
 assert.ok(!html.includes('invite-note'));console.log('Public registration, email-code recovery, and login UI flows are wired');
})().catch(error=>{console.error(error);process.exitCode=1});
