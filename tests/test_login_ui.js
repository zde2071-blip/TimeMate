const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('web/login.html','utf8'),script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
async function run(invited){
 const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,{value:'',checked:false,setAttribute(k,v){this[k]=v}});return nodes.get(id)};
 const calls=[],location={hash:invited?'#email=test%40example.com&invite=token':'',pathname:'/login',search:''};
 const ctx=vm.createContext({document:{getElementById:$},location,history:{replaceState(){}},URLSearchParams,fetch:async(url,opts)=>{calls.push({url,body:JSON.parse(opts.body)});return {ok:true,json:async()=>({})}}});
 vm.runInContext(script,ctx);
 ctx.mode('register');assert.equal($('submit').disabled,true);
 await $('form').onsubmit({preventDefault(){}});assert.equal(calls.length,0,'registration requires consent and invitation');
 $('consent').checked=true;$('consent').onchange();assert.equal($('submit').disabled,!invited);
 if(invited){$('password').value='password123';await $('form').onsubmit({preventDefault(){}});assert.equal(calls[0].url,'/api/auth/register');assert.equal(calls[0].body.invite,'token');assert.equal(calls[0].body.email,'test@example.com')}
 ctx.mode('login');assert.equal($('consent-group').hidden,true);assert.equal($('consent').required,false);assert.equal($('submit').disabled,false);
 $('email').value='login@example.com';$('password').value='password123';await $('form').onsubmit({preventDefault(){}});assert.equal(calls.at(-1).url,'/api/auth/login');assert.equal(location.href,'/');
 ctx.mode('reset');assert.equal($('reset-row').hidden,false);assert.equal($('back').hidden,false);
}
(async()=>{await run(false);await run(true);assert.ok(!html.includes('连接前请阅读'));console.log('Login, invitation registration consent and reset modes passed')})();
