const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'..','index.html'),'utf8');
class Element{constructor(tag,text=''){this.tag=tag;this.textContent=text;this.children=[];this.value='';}append(...nodes){this.children.push(...nodes)}replaceChildren(...nodes){this.children=[...nodes]}setAttribute(k,v){this[k]=v}focus(){this.focused=true}scrollIntoView(){}classList={add(){}}}
const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,new Element('div'));return nodes.get(id)};
const state={mails:[
{id:'1',category:'课程与教学',subject:'ISA104 Project',sender:'Haoran Wen',body:'abc',source_body:'完整正文尾部关键词',result:JSON.stringify({summary:'课程摘要',events:[{action:'小组提交主题'}]}),is_read:true},
{id:'2',category:'活动与机会',subject:'Workshop',sender:'Office',body:'return shuttle',result:JSON.stringify({summary:'校车预约'}),is_read:true},
{id:'3',category:'课程与教学',subject:'Other',sender:'Office',body:'different',result:null,is_read:true}],calendarEvents:[]};
let calls=0;
const context=vm.createContext({state,$,mailSearchQuery:'',categories:['课程与教学','活动与机会'],selected:'全部',selectedCourse:'全部课程',activeMailId:null,renderImportant(){},renderCourses(){},matchesCourse:()=>true,element:(tag,text)=>new Element(tag,text),displaySubject:x=>x,mailDateLabel:()=>'',call:()=>{calls++},showPage(){},document:{getElementById:id=>$('mails').children.find(x=>x.id===id)},renderMailDetail:m=>$('mail-detail-pane').replaceChildren(new Element('h2',m?.id||'empty'))});
vm.runInContext(html.slice(html.indexOf('function mailListTitle('),html.indexOf('\nasync function refresh(')),context);
vm.runInContext(html.slice(html.indexOf('function jumpMail('),html.indexOf('\nfunction ',html.indexOf('function jumpMail(')+1)),context);
for(const q of ['isa104','ＩＳＡ１０４','haoran','尾部关键词','课程摘要','小组提交主题','isa104 提交']){context.setMailSearch(q);assert.equal($('mails').children.length,1,q);assert.equal($('mail-detail-pane').children[0].textContent,'1',q)}
context.setMailSearch('shuttle');assert.equal($('mail-detail-pane').children[0].textContent,'2');
context.setMailSearch('Office');assert.equal($('mails').children.length,2);$('mail-detail-pane').scrollTop=500;$('mails').children[1].onclick();assert.equal($('mail-detail-pane').children[0].textContent,'3');assert.equal($('mail-detail-pane').scrollTop,0,'opening a search result starts at the mail heading');context.render();assert.equal($('mail-detail-pane').children[0].textContent,'3','refresh retains selection');
context.setMailSearch('xyz');assert.match($('mails').children[0].textContent,/没有匹配/);assert.equal($('mail-detail-pane').children[0].textContent,'empty');
context.setMailSearch('Office');$('filters').children[1].onclick();assert.equal($('mails').children.length,1);assert.equal($('mail-detail-pane').children[0].textContent,'3','category and search combine');
$('mail-search-clear').onclick();assert.equal($('mails').children.length,3);assert.ok($('mail-search-input').focused);
context.setMailSearch('Office');$('mail-search-input').onkeydown({key:'Enter',preventDefault(){}});assert.equal($('mail-detail-pane').children[0].textContent,'2');assert.ok($('mails').children[0].focused);
context.setMailSearch('不存在');context.jumpMail('1');assert.equal($('mails').children.length,2);assert.equal($('mail-detail-pane').children[0].textContent,'1');assert.equal($('mail-search-input').value,'');
assert.equal(calls,0,'search and selection of read mail do not request AI/API');
console.log('邮件搜索测试通过');

assert.equal(context.mailListTitle({subject:'Full English Subject',result:JSON.stringify({short_title:'ISA104 项目主题提交提醒'})}),'ISA104 项目主题提交提醒');
assert.equal(context.mailListTitle({subject:'Long title',result:JSON.stringify({events:[{title:'志愿者招募'},{title:'迎新杯长跑'},{title:'瑜伽体验'}]})}),'Long title');
assert.equal(context.mailListTitle({subject:'Original',result:null}),'Original');
context.setMailSearch('isa104');assert.equal($('mails').children[0].title,'ISA104 Project');
assert.match(html,/webkit-line-clamp:2/);
const sports='【Volunteer Recruitment & Student Activity】Special Care Education义工学院特殊教育志愿者招募& 5000 Competition “迎新杯”5000米长跑 &Yoga Experience Event “迎新杯” 瑜伽体验活动';
const sportsTitle=context.mailListTitle({subject:sports,result:JSON.stringify({summary:'集中发布志愿者招募和体育活动',events:[]})});
assert.ok(sportsTitle.length<=32,sportsTitle);for(const topic of ['志愿者招募','5000米长跑','瑜伽'])assert.ok(sportsTitle.includes(topic),sportsTitle);
assert.ok(!sportsTitle.includes('Volunteer'));assert.ok(!sportsTitle.includes('【'));
const psychology='Love, Subjectivity, Attachment, Collage... A New Batch of Psychology Groups Is Here! 预报从速！爱情、主体性、依恋、拼贴画......SCC第三批心理团体报名来袭......';
const legacy={subject:psychology,result:JSON.stringify({events:[{title:'爱的团体：收回关系里的投射（第1次）'},{title:'拼贴画自我叙事大学生心理成长团体（第1次）'}]})};
const before=JSON.stringify(legacy);assert.equal(context.mailListTitle(legacy),'心理团体报名');assert.equal(JSON.stringify(legacy),before,'display cleanup does not change analysis or events');
assert.equal(context.mailListTitle({subject:'Full subject',result:{short_title:'ISA104 小组项目主题提交提醒（第1次）'}}),'ISA104 小组项目主题提交提醒');
assert.ok(context.mailListTitle({subject:'Full subject',result:{short_title:'这是一个非常长的中文标题'.repeat(6)}}).length<=32);
assert.equal(context.mailListTitle({subject:'',result:null}),'');

assert.equal(context.mailListTitle({subject:'Original',result:{short_title:'AI 智能体设计与 RAG 知识库'}}),'AI 智能体设计与 RAG 知识库');
