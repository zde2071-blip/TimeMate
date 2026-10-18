const assert = require('node:assert/strict'), vm = require('node:vm');
const nodes = new Map(), $ = id => {
  if (!nodes.has(id)) nodes.set(id, {textContent:'', close(){this.closed=true}});
  return nodes.get(id);
};
let saves = 0, calls = [];
const ctx = vm.createContext({$, calendarBusy:false, calendarProfileId:'apple',calendarUrl:'https://example.com/feed',
  calendarConfig:{calendar_subscriptions:JSON.stringify([{provider:'apple',confirmed:'no'},{provider:'outlook',confirmed:'yes'}])},
  renderCalendarSettings(){}, saveCalendar:async()=>saves++, call:async(path,data)=>{
    calls.push(data);
    const rows=JSON.parse(ctx.calendarConfig.calendar_subscriptions);
    rows.find(row=>row.provider===data.calendarProfileId).confirmed=data.calendar_subscription_confirmed;
    ctx.calendarConfig.calendar_subscriptions=JSON.stringify(rows);
    return true;
  }});
vm.runInContext(require('./ui_source').functions('calendarProfiles','calendarAction','confirmCalendar'),ctx);
(async()=>{
  const old=ctx.calendarProfiles({calendar_method:'subscribe',calendar_provider:'apple',calendar_subscription_confirmed:'yes'});
  assert.equal(old.length,1);assert.equal(old[0].confirmed,'yes');
  assert.equal(ctx.calendarProfiles({calendar_subscriptions:'invalid'}).length,0);
  await ctx.calendarAction();
  assert.equal(calls[0].calendarProfileId,'apple');
  assert.equal(calls[0].calendar_subscription_confirmed,'yes');
  assert.equal($('calendar-profile-dialog').closed,true);
  assert.equal(ctx.calendarProfiles(ctx.calendarConfig)[1].confirmed,'yes');
  await ctx.calendarAction();
  assert.equal(calls[1].calendar_subscription_confirmed,'no');
  assert.equal(ctx.calendarProfiles(ctx.calendarConfig)[1].confirmed,'yes');
  ctx.calendarBusy=true;await ctx.calendarAction();assert.equal(calls.length,2);
  ctx.calendarBusy=false;ctx.calendarProfileId='';await ctx.calendarAction();assert.equal(saves,1);
  console.log('PASS legacy calendar migration, independent confirmations, new-calendar routing, and busy protection');
})().catch(e=>{console.error(e);process.exitCode=1});
