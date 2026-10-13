const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const html=require('./ui_source').readUI();
class Element{constructor(tag,text){this.tag=tag;this.textContent=text;this.children=[]}append(...n){this.children.push(...n)}replaceChildren(){this.children=[]}setAttribute(k,v){this[k]=v}}
let calls=[],renderCount=0,box=new Element('nav');
const context=vm.createContext({categories:['课程与教学','活动与机会','其他'],selected:'课程与教学',selectedCourse:'全部课程',activeMailId:'old',$:()=>box,element:(t,x)=>new Element(t,x),matchesMailSearch:()=>true,render:()=>renderCount++,notify:()=>{},call:async(path,data)=>{calls.push({path,data});context.activeMailId='changed-by-refresh';return true}});
vm.runInContext(require('./ui_source').functions("countLabel"),context);
vm.runInContext(require('./ui_source').functions("courseCodes", "renderCourses", "saveMailCategory", "mailCategoryPicker", "matchesCourse"),context);
assert.deepEqual(Array.from(context.courseCodes({subject:'csi 101',body:'SOE104',source_body:'ISA 104',result:'{"summary":"FAK999"}'})),['CSI 101','SOE 104','ISA 104']);
assert.deepEqual(Array.from(context.courseCodes({course_codes:[],subject:'fake CSI101'})),[]);
context.renderCourses({mails:[{subject:'CSI101',category:'课程与教学'}],courseCodes:['ISA104','CSI101']});
assert.equal(box.children.filter(x=>x.textContent==='CSI 101'&&x.children[0].textContent==='(1)').length,1);
assert.ok(box.children.some(x=>x.textContent==='ISA 104'&&x.children[0].textContent==='(0)'));
assert.ok(box.children.some(x=>x.textContent==='＋ 手工添加'));
(async()=>{await context.saveMailCategory({id:'original',category:'课程与教学'},'活动与机会');assert.equal(context.activeMailId,'original');assert.equal(context.selected,'活动与机会');assert.equal(context.selectedCourse,'全部课程');assert.equal(renderCount,1);assert.equal(calls[0].path,'/api/mail/category');context.call=async()=>false;let picker=context.mailCategoryPicker({id:'m',category:'课程与教学'}),select=picker.children[0];select.value='活动与机会';await select.onchange();assert.equal(select.value,'课程与教学');assert.equal(select.disabled,false);console.log('课程分类测试通过')})().catch(e=>{console.error(e);process.exitCode=1});
