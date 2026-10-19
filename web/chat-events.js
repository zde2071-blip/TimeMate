// One compact, editable list per batch of source material.
const chatEventSelections = new Map();
const chatExpandedGroups = new Set();
let chatEventBusy = false, chatEditingProposal = null;

function redrawChatEvents() {
  const top=$('chat-transcript').scrollTop;
  renderChatTranscript();
  $('chat-transcript').scrollTop=top;
}

function mergeChatEvents(events) {
  const updates=new Map(events.map(event=>[event.id,event]));
  for(const message of chatMessages)message.events=(message.events||[]).map(event=>updates.get(event.id)||event);
}

function chatProposalDate(proposal) {
  const event=proposal.event;
  if(proposal.status==='needs_info'&&(!event.start||(event.missing_fields||[]).some(name=>['year','date'].includes(name))))return '日期待确认';
  if(!event.start)return '日期待确认';
  const date=event.start.slice(0,10);
  if(event.timePrecision==='date')return date+(event.kind==='活动'?' · 时间待定':'');
  if(event.allDay)return date+(event.kind==='活动'?' · 全天':'');
  return event.start.slice(0,16).replace('T',' ')+(event.end?' – '+(event.end.slice(0,10)===date?event.end.slice(11,16):event.end.slice(0,16).replace('T',' ')):'');
}

async function addChatSelection(message, ids) {
  if(chatEventBusy||chatBusy||!ids.length)return;
  chatEventBusy=true;redrawChatEvents();
  try{
    const data=await chatRequest('/api/chat/events/batch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids,dateOnly:true})});
    mergeChatEvents(data.events||[]);
    for(const proposal of data.events||[])if(['added','duplicate'].includes(proposal.status))chatEventSelections.delete(proposal.id);
    const done=(data.events||[]).filter(event=>ids.includes(event.id)&&['added','duplicate'].includes(event.status)).length;
    message.executionNotice=(done?'已处理 '+done+' 项。':'')+((data.errors||[]).length?'部分事项需确认，请查看对应事项。':'');
    await refresh();
  }catch(error){message.executionNotice=error.message}
  finally{chatEventBusy=false;redrawChatEvents()}
}

function renderChatEvents(message) {
  const events=message.events||[],list=element('section','','chat-compact-events');
  list.setAttribute('aria-label','整理出的事项');
  const group=events[0]?.id||String(message.id),expanded=chatExpandedGroups.has(group);
  const available=events.filter(p=>p.status==='pending');
  for(const proposal of available)if(!chatEventSelections.has(proposal.id))chatEventSelections.set(proposal.id,true);
  const selected=available.filter(p=>chatEventSelections.get(p.id));
  const added=events.filter(p=>['added','duplicate','completed'].includes(p.status));
  const missing=events.filter(p=>p.status==='needs_info');
  const header=element('header','','chat-compact-heading'),heading=element('div');
  heading.append(element('strong','整理出的事项'),element('span',`${events.length} 项`+(missing.length?` · ${missing.length} 项待确认`:'')+(added.length?` · 已添加 ${added.length} 项`:''),'chat-compact-count'));
  const add=element('button',selected.length?`添加所选 (${selected.length})`:available.length?'选择事项':added.length===events.length?'已添加':'待确认','chat-event-add chat-batch-add');add.type='button';add.disabled=!selected.length||chatEventBusy||chatBusy;add.onclick=()=>addChatSelection(message,selected.map(p=>p.id));header.append(heading,add);list.append(header);
  const tools=element('div','','chat-compact-selection'),label=element('label'),all=document.createElement('input');all.type='checkbox';all.setAttribute('aria-label','全选可添加事项');all.checked=!!available.length&&selected.length===available.length;all.indeterminate=selected.length>0&&selected.length<available.length;all.disabled=!available.length||chatEventBusy;all.onchange=()=>{for(const p of available)chatEventSelections.set(p.id,all.checked);redrawChatEvents()};label.append(all,element('span',selected.length?`已选 ${selected.length} 项`:'全选'));tools.append(label);if(events.some(p=>p.event.timePrecision==='date'&&p.event.kind==='活动'&&p.status==='pending'))tools.append(element('span','未注明钟点的日程按日期添加'));list.append(tools);
  for(const proposal of expanded?events:events.slice(0,5)){
    const event=proposal.event,row=element('div','','chat-compact-row');row.dataset.proposalId=proposal.id;
    const saved=['added','duplicate','completed','removed'].includes(proposal.status);
    if(saved)row.append(element('span',proposal.status==='removed'?'−':'✓','chat-compact-check'));else{
      const check=document.createElement('input');check.type='checkbox';check.checked=proposal.status==='pending'&&chatEventSelections.get(proposal.id)===true;check.disabled=proposal.status!=='pending'||chatEventBusy;check.setAttribute('aria-label','选择 '+event.title);check.onchange=()=>{chatEventSelections.set(proposal.id,check.checked);redrawChatEvents()};row.append(check);
    }
    const copy=element('div','','chat-compact-copy');copy.append(element('strong',event.title),element('small',event.kind==='截止'?'截止事项':'日程安排'));row.append(copy);
    const date=element('div','','chat-compact-date');date.append(element('span',saved?({removed:'已移除',completed:'已完成',duplicate:'已有相同事项',added:'已添加'}[proposal.status]):chatProposalDate(proposal),saved?'chat-compact-saved':''));if(saved)date.append(element('small',chatProposalDate(proposal)));else if(proposal.status==='conflict')date.append(element('small','发现相似事项'));row.append(date);
    const edit=element('button',saved?'↗':'','chat-compact-edit');edit.type='button';edit.disabled=chatEventBusy||chatBusy;edit.setAttribute('aria-label',(saved?'查看 ':'编辑 ')+event.title);
    if(!saved){edit.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 4 5 5M4 20l4-1 12-12-4-4L4 15v5Z"/></svg>';edit.onclick=()=>openChatEventEditor(proposal)}else{edit.onclick=async()=>{await refresh();showPage('important');if(proposal.savedId)focusImportantEvent(proposal.savedId,proposal.savedIndex)}}row.append(edit);list.append(row);
    if(proposal.status==='conflict'){
      const conflict=element('div','','chat-compact-conflict'),view=element('button','查看相似事项','secondary'),separate=element('button','另行添加','secondary');view.type=separate.type='button';view.onclick=()=>showPage('important');separate.onclick=async()=>{if(chatEventBusy||!window.confirm('已有相似事项，仍要另行添加吗？'))return;chatEventBusy=true;redrawChatEvents();try{const data=await chatRequest('/api/chat/events/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:proposal.id,separate:true,dateOnly:true})});mergeChatEvents(data.events);await refresh()}catch(e){message.executionNotice=e.message}finally{chatEventBusy=false;redrawChatEvents()}};conflict.append(view,separate);list.append(conflict);
    }
  }
  if(events.length>5){const more=element('button',expanded?'收起':`展开其余 ${events.length-5} 项`,'chat-compact-more');more.type='button';more.onclick=()=>{if(expanded)chatExpandedGroups.delete(group);else chatExpandedGroups.add(group);redrawChatEvents()};list.append(more)}
  if(message.executionNotice){const notice=element('p',message.executionNotice,'chat-compact-notice');notice.setAttribute('role','status');list.append(notice)}
  return list;
}

function openChatEventEditor(proposal) {
  if(chatBusy||chatEventBusy)return;
  chatEditingProposal=proposal;
  const event=proposal.event;
  $('chat-edit-title').value=event.title;
  $('chat-edit-precision').value=event.timePrecision==='date'||event.allDay||(!event.end&&event.kind==='活动')?'date':'datetime';
  $('chat-edit-start').value='';$('chat-edit-end').value='';
  updateChatEditPrecision();
  const uncertainDate=proposal.status==='needs_info'&&((event.missing_fields||[]).some(k=>['year','date'].includes(k))||/年份|具体日期/.test(proposal.note||''));
  $('chat-edit-start').value=uncertainDate?'':(event.start||'').slice(0,$('chat-edit-precision').value==='date'?10:16);
  $('chat-edit-end').value=(event.end||'').slice(0,16);
  $('chat-edit-location').value=event.location||'';
  $('chat-edit-feedback').textContent=proposal.status==='needs_info'?proposal.note||'请确认具体日期。':event.annotation||'';
  $('chat-event-editor').showModal();
}

function updateChatEditPrecision() {
  const dateOnly=$('chat-edit-precision').value==='date',start=$('chat-edit-start'),old=start.value;
  start.type=dateOnly?'date':'datetime-local';start.value=dateOnly?old.slice(0,10):old.length===10?'':old;
  $('chat-edit-end-label').hidden=dateOnly||chatEditingProposal?.event.kind==='截止';
  $('chat-edit-end').required=!dateOnly&&chatEditingProposal?.event.kind==='活动';
}
$('chat-edit-precision').onchange=updateChatEditPrecision;
$('chat-event-edit-close').onclick=$('chat-event-edit-cancel').onclick=()=>{if(!chatEventBusy)$('chat-event-editor').close()};
$('chat-event-editor').addEventListener('cancel',event=>{if(chatEventBusy)event.preventDefault()});
$('chat-event-edit-form').onsubmit=async event=>{
  event.preventDefault();if(chatEventBusy||!chatEditingProposal)return;
  const precision=$('chat-edit-precision').value;
  const fields={title:$('chat-edit-title').value.trim(),start:$('chat-edit-start').value,end:precision==='date'?'':$('chat-edit-end').value,location:$('chat-edit-location').value,action:chatEditingProposal.event.action||'',timePrecision:precision,allDay:precision==='date',timeZone:Intl.DateTimeFormat().resolvedOptions().timeZone};
  chatEventBusy=true;$('chat-event-edit-save').disabled=true;
  try{const data=await chatRequest('/api/chat/events/edit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:chatEditingProposal.id,fields})});mergeChatEvents(data.events);chatEventSelections.set(chatEditingProposal.id,true);$('chat-event-editor').close();redrawChatEvents()}catch(error){$('chat-edit-feedback').textContent=error.message}finally{chatEventBusy=false;$('chat-event-edit-save').disabled=false;redrawChatEvents()}
};
