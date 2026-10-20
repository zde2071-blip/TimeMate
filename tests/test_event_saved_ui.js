const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const html=require('./ui_source').readUI();
class Element{constructor(tag,text=''){this.tag=tag;this.textContent=text;this.children=[];this.dataset={};}querySelector(){return null;}setAttribute(k,v){this[k]=v;}getAttribute(k){return this[k];}get childNodes(){return this.children;}append(...n){this.children.push(...n)}replaceChildren(...n){this.children=[...n]}}
const flatten=node=>[node,...node.children.flatMap(flatten)];
async function run(){
 const pane=new Element('section'),content=[];
 const context=vm.createContext({mailSelectionMode:false,mailReadingMode:"summary",mailReadingId:null,mailSenderLabel:()=>"",mailActionIcon:()=>new Element("svg"),mailEventIcon:()=>new Element("svg"),fitMailCategorySelect(){},$:()=>pane,element:(tag,text)=>new Element(tag,text),displaySubject:s=>s,mailCategoryPicker:()=>new Element('select'),mailDateLabel:()=>'',value:s=>s,eventAction:e=>e.action,mailEventParts:e=>{content.push(e);return {heading:new Element('div',e.title),details:new Element('div')}},Object});
 vm.runInContext(require('./ui_source').functions("allEventMails", "eventTarget", "eventOverrideData", "applyEventOverride", "mailEventForDisplay"),context);
 vm.runInContext(require('./ui_source').functions("renderMailDetail", "visibleMails", "selectMailInList", "bulkMailAction", "markFilteredMailRead", "closeMailSettingsMenu", "countLabel", "mailListTitle", "matchesMailSearch", "setMailSearch"),context);
 const event={title:'项目截止',action:'提交主题',kind:'截止',start:'2026-10-11T00:00',end:'',allDay:true};
 const first={id:'first',is_read:true,result:JSON.stringify({summary:'摘要',events:[event]})},update={...first,id:'update'};
 const data={mails:[first,update],pins:[{mail_id:'first',event_index:0,state:'active'}],eventLinks:[{mail_id:'update',event_index:0,target_mail_id:'first',target_index:0}],eventOverrides:[{mail_id:'first',event_index:0,fields:JSON.stringify({start:'2026-10-11T23:59',action:'提交150词简介'}),state:'active'}],status:{busy:false}};
 context.renderMailDetail(update,data,new Map());
 assert.ok(flatten(pane).some(n=>n.textContent==='取消加入截止事项'));
 assert.ok(!flatten(pane).some(n=>n.textContent==='加入截止事项'));
 assert.equal(content[0].start,'2026-10-11T23:59');assert.equal(content[0].action,'提交150词简介');

 const elements=new Map(),pending=[],renders=[];
 const refreshContext=vm.createContext({token:'test',mailSearchQuery:"",refreshIssued:0,refreshApplied:0,initialized:true,settingsFoldsInitialized:true,last:'',state:null,$:id=>{if(!elements.has(id))elements.set(id,new Element('div'));return elements.get(id)},fetch:()=>new Promise(resolve=>pending.push(resolve)),aiProfiles:[],aiEditingId:null,mailEditingId:null,renderAIProfiles(){},renderChatModel(){},renderMailboxConnection(){},renderConnectionOnboarding(){},connectedReceiver(){},savedSecret:()=>{},connectionBadge:()=>{},renderCalendarSettings:()=>{},renderSetupGuide:()=>{},renderFieldStatuses:()=>{},renderMailControls:()=>{},document:{querySelectorAll:()=>[]},render:()=>renders.push(refreshContext.state.marker),console});
 vm.runInContext(require('./ui_source').functions("refresh"),refreshContext);
 const payload=marker=>({marker,config:{},ready:{mail:true,ai:true},status:{auto:true},mails:[marker]});
 const old=refreshContext.refresh(),latest=refreshContext.refresh();
 pending[1]({ok:true,json:async()=>payload('updated')});assert.equal(await latest,true);
 pending[0]({ok:true,json:async()=>payload('stale')});assert.equal(await old,true);
 assert.equal(refreshContext.state.marker,'updated');assert.deepEqual(renders,['updated']);

 let noticed='';const callContext=vm.createContext({token:'test',fetch:async()=>({ok:true,json:async()=>({ok:true})}),refresh:async()=>false,notify:message=>noticed=message});
 vm.runInContext(require('./ui_source').functions("call"),callContext);
 assert.equal(await callContext.call('/api/event/link',{}),false);assert.ok(noticed.includes('页面刷新失败'));
}
run().catch(e=>{console.error(e);process.exitCode=1});
