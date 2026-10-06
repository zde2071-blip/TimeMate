const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'..','index.html'),'utf8');
class Element{
 constructor(tag,text=''){this.tag=tag;this.textContent=text;this.children=[];}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=[...nodes];}
 setAttribute(k,v){this[k]=v;}
}
const flatten=node=>[node,...node.children.flatMap(flatten)];
function run(links){
 const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,new Element('div'));return nodes.get(id);};
 const event={title:'活动',start:'2026-10-15T13:30',end:'2026-10-15T16:15',kind:'活动',action:'报名'};
 const mails=Array.from({length:23},(_,i)=>({id:'mail-'+i,subject:'邮件 '+i,category:'活动与机会',date:'2026-10-06',is_read:true,result:JSON.stringify({events:[event]})}));
 const state={mails,calendarEvents:[{mail_id:mails[0].id,event_index:0,status:'subscribed',detail:JSON.stringify(event)},{mail_id:mails[2].id,event_index:0,status:'saved',detail:JSON.stringify({...event,start:'2026-10-20T10:00'})}],pins:[],eventLinks:links?[{mail_id:mails[1].id,event_index:0,target_mail_id:mails[0].id,target_index:0}]:[]};
 const context=vm.createContext({state,$,categories:['课程与教学','活动与机会'],mailSearchQuery:'',selected:'全部',selectedCourse:'全部课程',activeMailId:null,importantView:'all',calendarMonth:new Date('2026-10-01'),calendarSelected:'',selectedDeadlineKey:'',element:(tag,text)=>new Element(tag,text),document:{createElement:tag=>new Element(tag)},localDateKey:d=>d.toISOString().slice(0,10),calendarDayDifference:()=>1,eventContent:e=>new Element('div',e.title),eventOverrideData:()=>({}),applyEventOverride:(d,id,i,e)=>e,eventAction:e=>e.action,editEventMenu:()=>new Element('button','编辑'),renderCourses:()=>{},mailDateLabel:m=>m.date,jumpMail:()=>{},renderMailDetail:m=>$('mail-detail-pane').replaceChildren(new Element('h2',m?.subject||'暂无邮件'))});
 vm.runInContext(html.slice(html.indexOf('function renderMonthCalendar('),html.indexOf('\nfunction courseCodes(')),context);
 vm.runInContext(html.slice(html.indexOf('function mailListTitle('),html.indexOf('\nasync function refresh(')),context);
 context.render();
 assert.equal($('mails').children.length,23,'a saved event must not prevent rendering mails');
 assert.equal($('mail-detail-pane').children[0].textContent,'邮件 0');
 const calendar=flatten($('important-list-view'));
 assert.ok(flatten($('calendar-view')).some(n=>n.type==='month'),'calendar remains in the separate left pane');
 assert.equal(calendar.filter(n=>n.id?.startsWith('important-')).length,2,'default list includes all dates');
 context.calendarSelected='2026-10-15';context.renderImportant(state);
 let dayList=flatten($('important-list-view'));
 assert.equal(dayList.filter(n=>n.id?.startsWith('important-')).length,1,'selecting a date filters the actual cards');
 const reset=dayList.find(n=>n.textContent==='查看全部');assert.ok(reset);reset.onclick();
 assert.equal(context.calendarSelected,'');
 assert.equal(flatten($('important-list-view')).filter(n=>n.id?.startsWith('important-')).length,2,'view all restores other dates');
 context.calendarSelected='2026-10-01';context.renderImportant(state);
 assert.ok(flatten($('important-list-view')).some(n=>n.textContent==='当天暂无已加入的事项。'),'empty selected days explain their state');
 assert.ok(calendar.some(n=>n.textContent===(links?'原邮件（2）':'查看原邮件')));
}
run(false);run(true);
