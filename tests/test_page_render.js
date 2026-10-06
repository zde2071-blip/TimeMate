const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const html=require('./ui_source').readUI();
class Element{
 constructor(tag,text=''){this.tag=tag;this.textContent=text;this.children=[];}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=[...nodes];}
 setAttribute(k,v){this[k]=v;}
 showModal(){this.open=true;}
 close(){this.open=false;}
}
const flatten=node=>[node,...node.children.flatMap(flatten)];
function run(links){
 const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,new Element('div'));return nodes.get(id);};
 const event={title:'活动',start:'2026-10-15T13:30',end:'2026-10-15T16:15',kind:'活动',action:'报名'};
 const mails=Array.from({length:23},(_,i)=>({id:'mail-'+i,subject:'邮件 '+i,category:'活动与机会',date:'2026-10-06',is_read:true,result:JSON.stringify({events:[event]})}));
 const state={mails,calendarEvents:[{mail_id:mails[0].id,event_index:0,status:'subscribed',detail:JSON.stringify(event)},{mail_id:mails[2].id,event_index:0,status:'subscribed',detail:JSON.stringify({...event,start:'2026-10-20T10:00'})},{mail_id:mails[3].id,event_index:0,status:'removed',detail:JSON.stringify({...event,title:'已取消的活动',start:'2026-10-21T10:00'})}],pins:[],eventLinks:links?[{mail_id:mails[1].id,event_index:0,target_mail_id:mails[0].id,target_index:0}]:[]};
 const context=vm.createContext({state,$,categories:['课程与教学','活动与机会'],mailSearchQuery:'',selected:'全部',selectedCourse:'全部课程',activeMailId:null,importantView:'all',calendarMonth:new Date('2026-10-01'),calendarSelected:'',selectedDeadlineKey:'',element:(tag,text,cls)=>{let node=new Element(tag,text);node.className=cls;return node},document:{createElement:tag=>new Element(tag)},localDateKey:d=>d.toISOString().slice(0,10),calendarDayDifference:()=>1,eventContent:(e,a,l,b,title)=>{let copy=new Element('div',e.title);if(title)copy.append(title);return copy},eventOverrideData:()=>({}),applyEventOverride:(d,id,i,e)=>e,eventAction:e=>e.action,editEventMenu:()=>new Element('button','编辑'),renderCourses:()=>{},mailDateLabel:m=>m.date,jumpMail:()=>{},renderMailDetail:m=>$('mail-detail-pane').replaceChildren(new Element('h2',m?.subject||'暂无邮件'))});
 vm.runInContext(html.slice(html.indexOf('function renderImportantCard('),html.indexOf('\nfunction courseCodes(')),context);
 vm.runInContext(html.slice(html.indexOf('function countLabel('),html.indexOf('\nasync function refresh(')),context);
 context.render();
 assert.equal($('mails').children.length,23,'a saved event must not prevent rendering mails');
 assert.equal($('mail-detail-pane').children[0].textContent,'邮件 0');
 const calendar=flatten($('important-list-view'));
 assert.ok(flatten($('calendar-view')).some(n=>n.className==='calendar-month-picker'),'calendar remains in the separate left pane');
 assert.equal(calendar.filter(n=>n.id?.startsWith('important-')).length,2,'default list includes all dates');
 context.calendarMonth=new Date('2026-12-01');context.moveCalendarMonth(1);
 assert.equal(context.calendarMonth.getFullYear(),2027);assert.equal(context.calendarMonth.getMonth(),0,'next month crosses the year boundary');
 context.moveCalendarMonth(-1);assert.equal(context.calendarMonth.getFullYear(),2026);assert.equal(context.calendarMonth.getMonth(),11);
 context.openCalendarMonthPicker();assert.equal($('calendar-month-dialog').open,true);
 $('calendar-year-input').value='2028';$('calendar-month-input').value='2';
 $('calendar-month-form').onsubmit({preventDefault(){}});
 assert.equal(context.calendarMonth.getFullYear(),2028);assert.equal(context.calendarMonth.getMonth(),1);
 assert.equal($('calendar-month-dialog').open,false,'choosing year and month closes the picker');
 context.goCalendarToday();assert.equal(context.calendarSelected,new Date().toISOString().slice(0,10),'today selects the current day');
 context.goCalendarToday();assert.equal(context.calendarSelected,'','second click on today restores all dates');
 context.calendarMonth=new Date('2026-10-01');
 context.calendarSelected='2026-10-15';context.renderImportant(state);
 let dayList=flatten($('important-list-view'));
 assert.equal(dayList.filter(n=>n.id?.startsWith('important-')).length,1,'selecting a date filters the actual cards');
 const reset=dayList.find(n=>n.textContent==='查看全部');assert.ok(reset);reset.onclick();
 assert.equal(context.calendarSelected,'');
 assert.equal(flatten($('important-list-view')).filter(n=>n.id?.startsWith('important-')).length,2,'view all restores other dates');
 context.calendarSelected='2026-10-01';context.renderImportant(state);
 assert.ok(flatten($('important-list-view')).some(n=>n.textContent==='当天暂无已加入的事项。'),'empty selected days explain their state');
 let openedMail=null;context.jumpMail=id=>{openedMail=id};
 const sourceControl=calendar.find(n=>n.title==='查看来源邮件'||n.title==='选择来源邮件（2封）');
 if(links){assert.equal(sourceControl.tag,'summary');const sourceOptions=calendar.find(n=>n.className==='important-source-options');assert.equal(sourceOptions.children.length,2);sourceOptions.children[1].onclick();assert.equal(openedMail,'mail-1')}else{sourceControl.onclick();assert.equal(openedMail,'mail-0')}
 context.calendarSelected='';context.deadlineReminder=()=>null;context.compareDeadlineItems=()=>0;
 context.renderMonthCalendar(Array.from({length:6},(_,i)=>({date:'2026-10-10',kind:i<3?'schedule':'deadline',event:{title:'事项'+i},mail_id:'stack'+i,index:0})),[],state);
 const day=flatten($('calendar-view')).find(n=>n['aria-label']==='2026-10-10，6项事项');
 const markers=day.children.find(n=>n.className==='calendar-day-markers');
 assert.equal(markers.children.length,2,'many events show at most one marker per type');
 assert.equal(markers.children[0].className,'calendar-day-marker schedule');assert.equal(markers.children[1].textContent,'→');
 assert.ok(calendar.some(n=>links?n.title==='选择来源邮件（2封）':n.title==='查看来源邮件'));
}
run(false);run(true);
