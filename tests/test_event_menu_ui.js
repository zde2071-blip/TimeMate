const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'..','index.html'),'utf8');
class Element{
 constructor(tag,text='',className=''){this.tag=tag;this.textContent=text;this.className=className;this.children=[];this.listeners={};this.open=false;}
 append(...nodes){for(const n of nodes){this.children.push(n);n.parent=this}}
 setAttribute(k,v){this[k]=v}
 addEventListener(type,handler){this.listeners[type]=handler}
 contains(target){return this===target||this.children.some(n=>n.contains(target))}
}
const flatten=n=>[n,...n.children.flatMap(flatten)];
async function run(){
 const body=new Element('body'),listeners={},timers=[];let ok=true,requests=[],editOpened=false;
 const document={body,getElementById:id=>flatten(body).find(n=>n.id===id),querySelectorAll:()=>flatten(body).filter(n=>n.className==='event-manage'&&n.open),addEventListener:(name,fn)=>listeners[name]=fn};
 const context=vm.createContext({document,element:(tag,text,cls)=>new Element(tag,text,cls),call:async(path,data)=>{requests.push(data);return ok},openEventEditor:()=>editOpened=true,setTimeout:fn=>{timers.push(fn);return timers.length},clearTimeout:()=>{}});
 vm.runInContext(html.slice(html.indexOf('function editEventMenu('),html.indexOf('\nfunction openEventEditor(')),context);
 const item={kind:'deadline',mail_id:'mail',index:2,state:'active'},menu=context.editEventMenu(item);body.append(menu);menu.open=true;
 // Clicking an option or the summary stays inside the menu; blank space closes it.
 listeners.click({target:menu.children[0]});assert.equal(menu.open,true);
 listeners.click({target:body});assert.equal(menu.open,false);
 menu.open=true;listeners.keydown({key:'Escape'});assert.equal(menu.open,false);
 const other=context.editEventMenu(item);body.append(other);menu.open=true;other.open=true;other.listeners.toggle();assert.equal(menu.open,false);assert.equal(other.open,true);
 await menu.children[1].children[1].onclick();assert.equal(requests[0].action,'complete');assert.equal(document.getElementById('event-action-feedback').textContent,'已标记完成');
 await menu.children[1].children[2].onclick();assert.equal(document.getElementById('event-action-feedback').textContent,'已移除');
 const completed=context.editEventMenu({...item,state:'completed'});body.append(completed);
 await completed.children[1].children[1].onclick();assert.equal(requests.at(-1).action,'restore');assert.equal(document.getElementById('event-action-feedback').textContent,'已恢复');
 timers.at(-1)();assert.equal(document.getElementById('event-action-feedback').hidden,true);
 ok=false;await completed.children[1].children[2].onclick();assert.equal(document.getElementById('event-action-feedback').hidden,true,'failed operation must not show success');
 completed.open=true;completed.children[1].children[0].onclick();assert.equal(completed.open,false);assert.equal(editOpened,true);
 // Execute the actual completed-card rendering and verify the same action wrapper.
 const calendar=new Element('div');Object.assign(context,{$:()=>calendar,calendarMonth:new Date('2026-10-01'),calendarSelected:'',localDateKey:d=>d.toISOString().slice(0,10),importantView:'all',eventContent:()=>new Element('div')});document.createElement=tag=>new Element(tag);
 vm.runInContext(html.slice(html.indexOf('function renderImportantCard('),html.indexOf('\nfunction setImportantView(')),context);
 context.renderMonthCalendar([], [{...item,event:{title:'已完成'},state:'completed'}], {mails:[]});
 const completedCard=flatten(calendar).find(n=>n.id==='important-mail-2');assert.ok(completedCard);assert.equal(completedCard.children[1].className,'important-actions');assert.equal(completedCard.children[1].children[0].className,'event-manage');
}
run().catch(err=>{console.error(err);process.exitCode=1});
