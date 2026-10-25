// Connection overview only. All changes reuse the existing settings screens.
function intakeIcon(group) {
  const icon=$('settings-nav-'+group).querySelector('svg').cloneNode(true);
  icon.setAttribute('aria-hidden','true');return icon;
}
function openIntakeSettings(group='mail', id='') {
  showPage('settings');
  selectConnectionSettings(group);
  if(group==='mail') { if(id)openMailboxAccount(id);else showMailboxList(); }
  if(group==='agents' && id)openAgentConnection(id);
}
function intakeSource(group, entry, duplicate=false) {
  const button=element('button','','intake-source');button.type='button';
  const name=group==='mail'?mailboxName(entry):entry.name;
  button.dataset.sourceId=entry.id;button.dataset.sourceGroup=group;
  button.setAttribute('aria-label','设置 '+name);
  button.append(intakeIcon(group));
  const copy=element('span','','intake-source-copy');copy.append(element('span',name));
  if(duplicate)copy.append(element('small',entry.school_sender));
  button.append(copy);
  button.onclick=()=>openIntakeSettings(group,entry.id);
  return button;
}
function renderInformationIntake() {
  if($('intake-page').hidden)return;
  const map=$('intake-map');map.replaceChildren();
  const flow=element('div','','intake-flow');
  const ns='http://www.w3.org/2000/svg',wires=document.createElementNS(ns,'svg');wires.classList.add('intake-wires');wires.setAttribute('aria-hidden','true');
  const defs=document.createElementNS(ns,'defs'),marker=document.createElementNS(ns,'marker'),arrow=document.createElementNS(ns,'path');
  for(const [k,v] of Object.entries({id:'intake-arrow',viewBox:'0 0 8 8',refX:'7',refY:'4',markerWidth:'6',markerHeight:'6',orient:'auto'}))marker.setAttribute(k,v);
  arrow.setAttribute('d','M1 1 7 4 1 7');arrow.setAttribute('fill','none');arrow.setAttribute('stroke','currentColor');arrow.setAttribute('stroke-width','1.2');marker.append(arrow);defs.append(marker);wires.append(defs,document.createElementNS(ns,'g'));flow.append(wires);
  const sources=element('div','','intake-sources'),mailboxes=state?.mailAccounts || [];
  sources.append(element('h3','邮箱','intake-source-label'));
  for(const entry of mailboxes)sources.append(intakeSource('mail',entry,mailboxes.filter(x=>mailboxName(x)===mailboxName(entry)).length>1));
  if(!mailboxes.length) {const add=element('button','连接邮箱','intake-source intake-empty');add.type='button';add.onclick=()=>openIntakeSettings('mail');sources.append(add);}
  sources.append(element('h3','个人 Agent','intake-source-label intake-agent-label'));
  if(agentConnectionsError) {const retry=element('button','连接状态获取失败，重试','intake-source intake-empty');retry.type='button';retry.onclick=()=>loadAgentConnections();sources.append(retry);}
  else if(!agentConnectionsLoaded)sources.append(element('p','正在获取连接…','intake-empty'));
  else if(agentConnections.length)for(const entry of agentConnections)sources.append(intakeSource('agents',entry));
  else {const add=element('button','连接个人 Agent','intake-source intake-empty');add.type='button';add.onclick=()=>openIntakeSettings('agents');sources.append(add);}
  const workbench=element('div','','intake-workbench');workbench.append(element('h3','TimeMate'));
  const mail=element('button','','intake-destination');mail.type='button';mail.dataset.destination='mail';mail.append(intakeIcon('mail'),element('span','邮件处理'));mail.onclick=()=>showPage('mail');
  const other=element('div','','intake-destination intake-future');other.dataset.destination='other';other.append(intakeIcon('agents'),element('span','其他信息'),element('small','规划中'));other.setAttribute('aria-label','其他信息，规划中，暂未开放接收');
  workbench.append(mail,other);
  const output=element('div','','intake-output');output.append(element('p','确认后的日程','intake-source-label'));
  const calendar=element('button','','intake-calendar');calendar.type='button';const profiles=calendarProfiles(state?.config || {}),confirmed=profiles.filter(p=>p.confirmed==='yes');
  calendar.append(intakeIcon('calendar'),element('span','日历'),element('small',profiles.length?confirmed.length+' 个已订阅':'尚未连接'));calendar.onclick=()=>openIntakeSettings('calendar');output.append(calendar);
  flow.append(sources,workbench,output);map.append(flow);
  requestAnimationFrame(drawIntakeConnections);
}
function drawIntakeConnections() {
  if($('intake-page').hidden)return;
  const flow=$('intake-map').querySelector('.intake-flow');if(!flow)return;
  const g=flow.querySelector('.intake-wires g');g.replaceChildren();if(getComputedStyle(flow).display!=='grid')return;
  const frame=flow.getBoundingClientRect(),bench=flow.querySelector('.intake-workbench').getBoundingClientRect();
  function link(x1,y1,x2,y2,key) {
    const path=document.createElementNS('http://www.w3.org/2000/svg','path'),mid=(x1+x2)/2;
    path.setAttribute('d',`M${x1} ${y1} C${mid} ${y1},${mid} ${y2},${x2} ${y2}`);path.setAttribute('marker-end','url(#intake-arrow)');path.dataset.route=key;g.append(path);
  }
  for(const button of flow.querySelectorAll('[data-source-id]')) {
    const box=button.getBoundingClientRect(),types=button.dataset.sourceGroup==='mail'?['mail']:['mail','other'];
    for(const type of types) {
      const target=flow.querySelector('[data-destination="'+type+'"]').getBoundingClientRect();
      link(box.right-frame.left+2,box.top+box.height/2-frame.top,bench.left-frame.left-4,target.top+target.height/2-frame.top,button.dataset.sourceId+'-'+type);
    }
  }
  const cal=flow.querySelector('.intake-calendar').getBoundingClientRect();
  link(bench.right-frame.left+2,bench.top+bench.height/2-frame.top,cal.left-frame.left-4,cal.top+cal.height/2-frame.top,'calendar');
}
if(typeof ResizeObserver==='function')new ResizeObserver(drawIntakeConnections).observe($('intake-map'));
