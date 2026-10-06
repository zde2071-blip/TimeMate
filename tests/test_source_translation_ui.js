const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const html=require('./ui_source').readUI();
class Element{
 constructor(tag,text=''){this.tag=tag;this.textContent=text;this.children=[];this.dataset={};this.attrs={};}
 append(...nodes){for(const n of nodes){n.parent=this;this.children.push(n);}}
 replaceChildren(...nodes){this.children=[];this.append(...nodes);}
 contains(n){return this.children.includes(n)||this.children.some(c=>c.contains(n));}
 remove(){this.parent.children=this.parent.children.filter(n=>n!==this);}
 setAttribute(k,v){this.attrs[k]=v;}
 showModal(){this.open=true;}
}
async function run(){
 const box=new Element('div'),dialog=new Element('dialog'),calls=[];
 const source={html:'<p><a href="https://example.test/%E6%9C%88">Register</a><img data-external="0"></p>',external:['https://example.test/poster.png']};
 const translated={html:source.html.replace('Register','报名'),external:source.external,subject:'通知',cached:false,elapsedMs:20};
 const context=vm.createContext({token:'test',$:id=>id==='source-content'?box:dialog,element:(tag,text)=>new Element(tag,text),document:{createElement:tag=>new Element(tag)},performance:{now:()=>0},setInterval:()=>1,clearInterval:()=>{},fetch:async url=>{calls.push(url);return {ok:true,json:async()=>url==='/api/source'?source:translated};}});
 vm.runInContext(html.slice(html.indexOf('async function openSource('),html.indexOf('\nfunction formatEventTime(')),context);
 await context.openSource({id:'1',subject:'Notice'});
 assert.deepEqual(calls,['/api/source']);
 const toolbar=box.children.find(n=>n.tag==='div'),[original,chinese]=toolbar.children,frame=box.children.find(n=>n.tag==='iframe');
 assert.ok(frame.srcdoc.includes('Register'));
 await chinese.onclick();
 assert.ok(frame.srcdoc.includes('>报名</a>'));
 assert.equal(frame.hidden,false);
 assert.equal(frame.attrs.sandbox,'allow-popups allow-popups-to-escape-sandbox');
 const load=box.children.find(n=>n.textContent==='加载外部图片');load.onclick();
 assert.ok(frame.srcdoc.includes('src="https://example.test/poster.png"'));
 original.onclick();assert.ok(frame.srcdoc.includes('Register'));
 await chinese.onclick();assert.ok(frame.srcdoc.includes('>报名</a>'));
 assert.deepEqual(calls,['/api/source','/api/source/translate']);
}
run().catch(e=>{console.error(e);process.exitCode=1;});
