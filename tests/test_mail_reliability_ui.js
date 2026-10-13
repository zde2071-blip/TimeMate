const assert = require('node:assert/strict');
const vm = require('node:vm');
const {functions} = require('./ui_source');
async function run() {
  const calls = [], source = {id:'saved',date:'2026-10-10',result:'{"events":[{"title":"保留的事项"}]}',is_read:true};
  const context = vm.createContext({token:'test',state:{mails:[source],eventSourceMails:[]},
    fetch:async(path,options)=>{calls.push(JSON.parse(options.body));return {ok:true,json:async()=>({ok:true})}},
    refresh:async()=>false,render(){},notify:message=>{throw Error(message)}});
  vm.runInContext(functions('mutateMailDeletion'),context);
  assert.equal(await context.mutateMailDeletion(['saved'],'delete'),true,'saved deletion must succeed even if refreshing fails');
  assert.equal(context.state.mails.length,0);
  assert.equal(context.state.eventSourceMails[0].result,source.result,'saved event source remains available offline');
  assert.equal(await context.mutateMailDeletion(['saved'],'restore'),true);
  assert.equal(context.state.mails[0].id,'saved');
  assert.equal(context.state.mails[0].is_deleted,false);
  context.state.mails = []; context.state.eventSourceMails = [];
  await context.mutateMailDeletion(['saved'], 'restore', [source]);
  assert.equal(context.state.mails[0].id, 'saved', 'undo can render its saved snapshot after a successful delete refresh and failed restore refresh');
  assert.deepEqual(calls.slice(0,2),[{ids:['saved'],action:'delete'},{ids:['saved'],action:'restore'}]);

  let requests=0;
  const detail = vm.createContext({token:'test',mailDetailCache:new Map(),fetch:async()=>{requests++;return {ok:true,json:async()=>({mail:{body:'full original',source_body:'full source',is_read:false,category:'旧分类'}})}}});
  vm.runInContext(functions('getMailDetail'),detail);
  await detail.getMailDetail({id:'a',is_read:false});
  const updated=await detail.getMailDetail({id:'a',is_read:true,category:'课程与教学',result:'new analysis'});
  assert.equal(requests,1,'opening the same source body reuses its cached content');
  assert.equal(updated.is_read,true);assert.equal(updated.category,'课程与教学');assert.equal(updated.result,'new analysis');
  assert.equal(updated.body,'full original');

  const pending=[], search = vm.createContext({token:'test',mailSearchQuery:'first',mailSearchRequest:0,render(){},
    fetch:()=>new Promise(resolve=>pending.push(resolve))});
  vm.runInContext(functions('resolveMailSearch'),search);
  const first=search.resolveMailSearch();search.mailSearchQuery='second';const second=search.resolveMailSearch();
  pending[1]({ok:true,json:async()=>({ids:['body-only-result']})});await second;
  pending[0]({ok:true,json:async()=>({ids:['stale-result']})});await first;
  assert.deepEqual([...search.mailSearchIds],['body-only-result'],'a slower search cannot replace newer results');
  assert.equal(search.mailSearchResolvedQuery,'second');

  const requestsMade=[], nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,{});return nodes.get(id)};
  let refreshes=0;
  const poll = vm.createContext({document:{hidden:false,querySelectorAll:()=>[]},token:'test',statePollInFlight:false,lastCalendarMinute:Math.floor(Date.now()/60000),state:{revision:'r1'},$,renderMailControls(){},renderImportant(){},scheduleStatePoll(){},
    refresh:async()=>{refreshes++;poll.state.revision='r2';return true},fetch:async path=>{requestsMade.push(path);return {ok:true,json:async()=>({revision:refreshes?'r2':'r1',status:{auto:true},pendingCount:0,failedCount:0})}}});
  vm.runInContext(functions('pollState'),poll);
  await poll.pollState();assert.equal(refreshes,0,'unchanged polling never fetches full mailbox state');
  poll.state.revision='older';await poll.pollState();assert.equal(refreshes,1);
  assert.deepEqual(requestsMade,['/api/updates','/api/updates']);
  console.log('Delete/restore with refresh failure, body cache, search races and lightweight polling passed');
}
run().catch(error=>{console.error(error);process.exitCode=1});
