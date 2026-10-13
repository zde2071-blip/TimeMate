const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/main.js','utf8'),html=fs.readFileSync('web/index.html','utf8');
const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,{value:'',children:[],setAttribute(k,v){this[k]=v},replaceChildren(...items){this.children=items},append(item){this.children.push(item)},showModal(){this.open=true},close(){this.open=false}});return nodes.get(id)};
let cfg={calendar_provider:'apple',calendar_method:'subscribe',calendar_subscription_confirmed:'no'};const requests=[];
const ctx=vm.createContext({calendarEditing:false,calendarConfig:{},calendarUrl:null,$,setupGuideRevision:0,element:(tag,text,cls)=>({tag,text,cls}),call:async(path,data)=>{requests.push(data);cfg={...cfg,...data};ctx.renderCalendarSettings(cfg,'https://example.com/calendar.ics');return true}});
vm.runInContext(require('./ui_source').functions("calendarHelp", "renderCalendarSettings", "changeCalendar", "showCalendarGuide", "calendarAction", "saveCalendar", "confirmCalendar"),ctx);
(async()=>{
 ctx.renderCalendarSettings(cfg,'https://example.com/calendar.ics');assert.equal($('calendar-connect').hidden,false);assert.equal($('calendar-connect').textContent,'确认订阅');
 await ctx.calendarAction();assert.equal(requests[0].calendar_subscription_confirmed,'yes');assert.equal($('calendar-connect').textContent,'✓ 已订阅');assert.equal($('calendar-connect').disabled,false);
 await ctx.calendarAction();assert.equal(requests[1].calendar_subscription_confirmed,'no');assert.equal($('calendar-connect').textContent,'确认订阅');
 ctx.showCalendarGuide();assert.equal($('setup-guide-dialog').open,true);assert.match($('setup-guide-title').textContent,/Apple/);assert.match($('setup-guide-content').children[0].text,/Mac/);
 $('calendar_provider').value='outlook';ctx.calendarHelp();ctx.showCalendarGuide();assert.match($('setup-guide-title').textContent,/Outlook/);assert.match($('setup-guide-content').children[0].text,/从 Web 订阅/);
 assert(!html.includes('id="calendar-guide-panel"'));assert(html.includes('id="calendar-confirm" class="field-status" role="status"'));assert(!html.includes('onclick="confirmCalendar()"'));
 console.log('Calendar confirmation toggle and shared tutorial dialog passed');
})().catch(error=>{console.error(error);process.exitCode=1});
