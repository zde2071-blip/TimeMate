const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const html=require('./ui_source').readUI();
class Element{constructor(tag,text=''){this.tag=tag;this.textContent=text;this.children=[];this.value='';}append(...nodes){this.children.push(...nodes)}replaceChildren(...nodes){this.children=[...nodes]}setAttribute(k,v){this[k]=v}focus(){this.focused=true}scrollIntoView(){}classList={add(){}}}
const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,new Element('div'));return nodes.get(id)};
const state={mails:[
{id:'1',category:'课程与教学',subject:'ISA104 Project',sender:'Haoran Wen',body:'abc',source_body:'完整正文尾部关键词',result:JSON.stringify({summary:'课程摘要',events:[{action:'小组提交主题'}]}),is_read:true},
{id:'2',category:'活动与机会',subject:'Workshop',sender:'Office',body:'return shuttle',result:JSON.stringify({summary:'校车预约'}),is_read:true},
{id:'3',category:'课程与教学',subject:'Other',sender:'Office',body:'different',result:null,is_read:true}],calendarEvents:[]};
let calls=0;
const context=vm.createContext({mailSearchRequest:0,mailSearchIds:null,mailSearchResolvedQuery:'',mailSearchPending:false,mailSearchError:'',mailSearchTimer:null,mailRenderFilter:'',mailRenderLimit:50,lastSelectedMailIndex:null,clearTimeout(){},setTimeout(){},resolveMailSearch(){},state,$,mailSearchQuery:'',categories:['课程与教学','活动与机会'],selected:'全部',selectedCourse:'全部课程',activeMailId:null,renderImportant(){},renderCourses(){},matchesCourse:()=>true,element:(tag,text)=>new Element(tag,text),displaySubject:x=>x,mailDateLabel:()=>'',call:()=>{calls++},showPage(){},document:{getElementById:id=>$('mails').children.find(x=>x.id===id)},renderMailDetail:m=>$('mail-detail-pane').replaceChildren(new Element('h2',m?.id||'empty'))});
vm.runInContext(require('./ui_source').functions("initMailSearch", "countLabel", "mailListTitle", "matchesMailSearch", "setMailSearch", "render", "updateMailWorkspaceHeight", "compactMailStatus", "renderMailControls"),context);
vm.runInContext(require('./ui_source').functions("allEventMails", "jumpMail"),context);
context.initMailSearch();
for(const q of ['isa104','ＩＳＡ１０４','haoran','尾部关键词','课程摘要','小组提交主题','isa104 提交']){context.setMailSearch(q);context.mailSearchPending=false;context.render();assert.equal($('mails').children.length,1,q);assert.equal($('mail-detail-pane').children[0].textContent,'1',q)}
context.setMailSearch('shuttle');assert.equal($('mail-detail-pane').children[0].textContent,'2');
context.setMailSearch('Office');assert.equal($('mails').children.length,2);$('mail-detail-pane').scrollTop=500;$('mails').children[1].onclick();assert.equal($('mail-detail-pane').children[0].textContent,'3');assert.equal($('mail-detail-pane').scrollTop,0,'opening a search result starts at the mail heading');context.render();assert.equal($('mail-detail-pane').children[0].textContent,'3','refresh retains selection');
context.setMailSearch('xyz');context.mailSearchPending=false;context.render();assert.match($('mails').children[0].textContent,/没有匹配/);assert.equal($('mail-detail-pane').children[0].textContent,'empty');
context.setMailSearch('Office');$('filters').children[1].onclick();assert.equal($('mails').children.length,1);assert.equal($('mail-detail-pane').children[0].textContent,'3','category and search combine');
$('mail-search-clear').onclick();assert.equal($('mails').children.length,3);assert.ok($('mail-search-input').focused);
context.setMailSearch('Office');$('mail-search-input').onkeydown({key:'Enter',preventDefault(){}});assert.equal($('mail-detail-pane').children[0].textContent,'2');assert.ok($('mails').children[0].focused);
context.setMailSearch('不存在');context.jumpMail('1');assert.equal($('mails').children.length,2);assert.equal($('mail-detail-pane').children[0].textContent,'1');assert.equal($('mail-search-input').value,'');
assert.equal(calls,0,'search and selection of read mail do not request AI/API');
console.log('邮件搜索测试通过');

assert.equal(context.mailListTitle({subject:'原始完整标题',display_title:'项目主题提交'}),'项目主题提交');
assert.equal(context.mailListTitle({subject:'Original'}),'Original');
context.state.mails[0].display_title='独有侧栏关键词';context.setMailSearch('独有侧栏关键词');assert.equal($('mails').children.length,1,'stored sidebar titles are searchable');
assert.doesNotMatch(html,/function (?:compactMailTitle|mailTopicTitle|englishMailTopic|limitMailTitle)/,'the UI must not infer or rewrite mail titles');
assert.doesNotMatch(html,/webkit-line-clamp/,'topic titles remain readable');
