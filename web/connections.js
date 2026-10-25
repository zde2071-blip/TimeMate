// Multiple source mailboxes reuse the approved forwarding setup below.
let mailboxListOpen = true, mailEditingId = null;
let selectedMailboxId = 'all';
function mailboxName(entry) {
  return entry.name?.trim() || entry.school_sender || entry.account || '邮箱';
}
async function saveMailboxName() {
  const id=mailEditingId, name=$('mail-name').value.trim(), button=$('mail-name-save');
  if(!id)return;
  button.disabled=true;$('mail-name-feedback').textContent='';
  try {
    const response=await fetch('/api/mail/accounts/name',{method:'POST',headers:{'Content-Type':'application/json','X-Token':token},body:JSON.stringify({id,name})});
    const result=await response.json();if(!response.ok)throw Error(result.error || '名称保存失败');
    if(!(await refresh()))throw Error('名称已保存，请刷新页面查看。');
    if(mailEditingId===id && $('mail-name').value.trim()===name)$('mail-name-feedback').textContent='已保存';
  } catch(error) {if(mailEditingId===id)$('mail-name-feedback').textContent=error.message;}
  finally{button.disabled=false;}
}
function connectedReceiver(d, address) {
  return (d?.mailAccounts || []).find(x => x.connected && x.mode!=='oauth' && x.account.toLowerCase() === address.trim().toLowerCase());
}
function showMailboxList() {
  mailboxListOpen = true; mailboxManualOpen = false; mailboxDirectOpen = false;
  mailEditingId = null; renderMailboxConnection(state);
}
function openMailboxAccount(id = '') {
  if (receiverBusy || connectionStates.mail === '连接中') return;
  const entry = (state?.mailAccounts || []).find(x => x.id === id);
  $('mail-name').value=entry?.name || '';$('mail-name').placeholder=entry?.school_sender || entry?.account || '';$('mail-name-feedback').textContent='';
  if(entry?.mode==='oauth'){mailboxListOpen=false;mailEditingId=entry.id;mailboxMethodsOpen=false;mailboxManualOpen=false;mailboxDirectOpen=false;renderMailboxConnection(state);return;}
  mailEditingId = id; mailboxListOpen = false; mailboxManualOpen = !!entry;
  mailboxDirectOpen = false; mailboxMethodsOpen = !entry;
  receiverRevision++; receiverVerifiedRevision = -1;
  connectionStates.mail = ''; $('mail-feedback').textContent = '';
  const receiver = entry;
  $('school_sender').value = entry?.school_sender || '';
  $('account').value = receiver?.account || '';
  $('mail_provider').value = receiver?.mail_provider || '';
  $('password').value = ''; delete $('password').dataset.editing;
  savedSecret('password', !!receiver?.connected);
  if (entry) localStorage.setItem(forwardingKey(), 'yes');
  renderMailProvider(); renderMailboxConnection(state);
}
function renderMailboxAccounts(d) {
  const list = $('mail-account-list'); list.replaceChildren();
  for (const entry of d.mailAccounts || []) {
    const row = element('button', '', 'mail-account-entry'); row.type = 'button';
    row.setAttribute('aria-label', '设置 ' + mailboxName(entry));
    const icon = element('span', '', 'mail-account-mark');icon.setAttribute('aria-hidden','true');icon.append($('settings-nav-mail').querySelector('svg').cloneNode(true));
    const copy = element('span', '', 'mail-account-copy');
    copy.append(element('strong',mailboxName(entry)),element('small',entry.name?.trim()?entry.school_sender:entry.mode==='oauth'?'直接连接':'转发接入'));
    const tail = element('span','','settings-entry-tail');
    const health = d.status?.mailboxHealth?.[entry.account.toLowerCase()];
    const failed = ['paused','error','retrying'].includes(health?.sync_state);
    tail.append(element('span',entry.connected && !failed ? '✓ 已连接' : failed ? '连接异常' : '未连接',entry.connected && !failed ? 'settings-entry-connected' : 'meta'),element('span','›','settings-entry-chevron'));
    row.append(icon,copy,tail); row.onclick=()=>openMailboxAccount(entry.id); list.append(row);
  }
  if(d.mailConnection?.mode==='oauth' && !(d.mailAccounts||[]).some(x=>x.mode==='oauth')){
    const row=element('button','','mail-account-entry');row.type='button';const copy=element('span','','mail-account-copy');copy.append(element('strong',d.mailConnection.account),element('small','直接连接'));const tail=element('span',d.mailConnection.reauthorize?'需重新授权':'✓ 已连接','settings-entry-connected');row.append(copy,tail,element('span','›','settings-entry-chevron'));row.onclick=()=>{mailboxListOpen=false;mailboxMethodsOpen=false;mailboxManualOpen=false;renderMailboxConnection(state)};list.append(row);
  }
  if (!(d.mailAccounts || []).length && d.mailConnection?.mode!=='oauth') list.append(element('p','尚未添加邮箱','mail-account-empty'));
  $('mail-name-settings').hidden=mailboxListOpen || !mailEditingId;
  $('mail-account-new').hidden=!mailboxListOpen;
  $('mail-account-back').hidden=mailboxListOpen;
  $('mail-accounts').hidden=!mailboxListOpen;
  const heading=$('settings-nav-mail').getAttribute('aria-current')==='page';
  if(heading)$('settings-detail-title').textContent=mailboxListOpen?'邮箱':mailEditingId?'编辑邮箱':'添加邮箱';
  document.querySelector('[data-setting-summary="mail"]').hidden=true;
  $('mail-forward-back').hidden=!!mailEditingId;
}
function matchesMailbox(m) {
  return selectedMailboxId==='all'||m.mailbox_id===selectedMailboxId;
}
function mailboxAddress(m) {
  return (state?.mailAccounts || []).find(x=>x.id===m.mailbox_id)?.school_sender || '';
}
function renderMailboxPicker(d) {
  const picker=$('mail-account-filter'),entries=d.mailAccounts||[];
  if (!entries.some(x=>x.id===selectedMailboxId)) selectedMailboxId='all';
  picker.replaceChildren();const all=element('option','全部邮箱');all.value='all';picker.append(all);
  for(const entry of entries){const duplicate=entries.filter(x=>mailboxName(x)===mailboxName(entry)).length>1;const option=element('option',mailboxName(entry)+(duplicate?' · '+entry.school_sender:''));option.value=entry.id;picker.append(option);}
  picker.value=selectedMailboxId;picker.hidden=entries.length<2;
  if(!picker.hidden) fitMailCategorySelect(picker);
  picker.onchange=()=>{selectedMailboxId=picker.value;activeMailId=null;selectedMailIds.clear();render();};
}

// Connection methods and the persistent, account-scoped setup guide.
let mailboxManualOpen = false, mailboxDirectOpen = false, mailboxMethodsOpen = false, mailboxPageInitialized = false;
let connectionWelcomeChecked = false, mailboxConnecting = false;
let receiverRevision = 0, receiverVerifiedRevision = -1, receiverBusy = false;
// Show the direct-connection choice; keep authorization behind the launch placeholder until approved.
const MAIL_OAUTH_UI_ENABLED = false;
const mailboxResults = {
  admin:'需要邮箱管理员批准 TimeMate 访问此邮箱。',
  blocked:'此邮箱的安全策略阻止了 TimeMate 访问。',
  cancel:'连接已取消，可以重新尝试。',
  network:'连接暂时失败，请重试。',
  permission:'尚未取得读取邮箱的权限，请重新授权。',
  expired:'邮箱授权已失效，请重新连接。',
  invalid:'授权已失效，请重新连接。',
  unavailable:'此连接方式暂未启用，请使用其他连接方式。',
  busy:'请等待当前操作完成后重新连接。'
};
let mailboxResult = new URLSearchParams(location.search).get('mail_connection') || '';
if (mailboxResult) {
  const clean = new URL(location.href); clean.searchParams.delete('mail_connection');
  history.replaceState(null, '', clean.pathname + clean.search + clean.hash);
}
function connectionStorage(action, key, value) {
  try { return localStorage[action]('timemate-connection:' + loginEmail + ':' + key, value); } catch (_) { return null; }
}
function showMailboxMethods(change = false) {
  mailboxListOpen = false; mailboxManualOpen = false; mailboxDirectOpen = false; mailboxMethodsOpen = change;
  renderMailboxConnection(state);
}
function showDirectMailbox() {
  mailboxListOpen = false;
  mailboxManualOpen = false; mailboxDirectOpen = true;
  renderMailboxConnection(state);
}
function showManualMailbox() {
  mailboxListOpen = false;
  mailboxManualOpen = true; mailboxDirectOpen = false;
  if (mailEditingId?.startsWith('oauth:')) { openMailboxAccount();mailboxManualOpen=true; }
  renderMailboxConnection(state);
}
function renderMailboxConnection(d) {
  if (!d?.config) return;
  const connection = d.mailConnection || {};
  if (!mailboxPageInitialized) {
    mailboxManualOpen = false;
    mailboxPageInitialized = true;
  }
  const direct = connection.mode === 'oauth' && !!mailEditingId?.startsWith('oauth:');
  const reauthorize = connection.reauthorize || direct && d.status?.sync_error_code === 'mail_authentication_failed';
  const methodsVisible = !direct || mailboxMethodsOpen || reauthorize;
  $('mail-manual-settings').hidden = !mailboxManualOpen;
  $('mail-connection-methods').hidden = mailboxManualOpen;
  $('mail-save').hidden = !mailboxManualOpen;
  $('mail-direct-account').hidden = !direct || mailboxMethodsOpen || mailboxDirectOpen;
  $('mail-method-choices').hidden = !methodsVisible || mailboxDirectOpen;
  $('mail-direct-setup').hidden = !mailboxDirectOpen;
  $('mail-direct-coming').hidden = MAIL_OAUTH_UI_ENABLED;
  $('mail-method-buttons').hidden = !MAIL_OAUTH_UI_ENABLED;
  $('mail-direct-address').textContent = direct ? connection.account : '';
  $('mail-direct-status').textContent = reauthorize ? '需重新授权' : '已连接';
  const result = $('mail-oauth-result');
  const message = reauthorize ? mailboxResults.expired : mailboxResults[mailboxResult] || '';
  result.hidden = !message; result.textContent = message;
  $('mail-oauth-help').hidden = !message || mailboxResult === 'cancel';
  if (direct) {
    $('mail-nav-provider').textContent = connection.provider === 'google' ? 'Google' : 'Microsoft';
    $('mail-nav-status').textContent = reauthorize ? '需重新授权' : '已连接';
  }
  document.querySelectorAll('[data-mail-oauth]').forEach(b => { b.hidden = !MAIL_OAUTH_UI_ENABLED; b.disabled = mailboxConnecting; });
  renderForwardingForm(d);
  renderMailboxAccounts(d);
  if(mailboxListOpen){$('mail-manual-settings').hidden=true;$('mail-connection-methods').hidden=true;$('mail-save').hidden=true;}
}
async function startMailboxOAuth(provider) {
  if (mailboxConnecting) return;
  mailboxConnecting = true; mailboxResult = ''; renderMailboxConnection(state);
  try {
    const response = await fetch('/api/mail/oauth/start', {method:'POST',headers:{'Content-Type':'application/json','X-Token':token},body:JSON.stringify({provider})});
    const result = await response.json();
    if (!response.ok) { mailboxResult = result.kind || 'network'; return; }
    const target = new URL(result.url);
    const allowed = provider === 'google' ? 'accounts.google.com' : 'login.microsoftonline.com';
    if (target.protocol !== 'https:' || target.hostname !== allowed) throw Error('Invalid authorization host');
    location.assign(target.href);
  } catch (_) { mailboxResult = 'network'; }
  finally { mailboxConnecting = false; renderMailboxConnection(state); }
}
function openGoogleMailConsent() {
  const dialog = $('google-mail-consent');
  if (!dialog?.showModal) {
    if (confirm('TimeMate 会以只读权限同步 Gmail 收件箱并保存邮件。使用 AI 分析时，邮件内容会发送给你选择的 AI 服务商。')) startMailboxOAuth('google');
    return;
  }
  dialog.showModal();
}
$('google-mail-consent-cancel').onclick = () => $('google-mail-consent').close();
$('google-mail-consent-continue').onclick = () => { $('google-mail-consent').close(); startMailboxOAuth('google'); };
document.querySelectorAll('[data-mail-oauth]').forEach(button => button.onclick = () => {
  const provider = button.dataset.mailOauth;
  if (provider === 'google') openGoogleMailConsent(); else startMailboxOAuth(provider);
});
function openConnectionStep(group) {
  showPage('settings'); selectConnectionSettings(group);
  if (group === 'mail') { if (!(state?.mailAccounts||[]).length && state?.mailConnection?.mode!=='oauth') openMailboxAccount(); else showMailboxList(); }
}
function closeConnectionWelcome() {
  $('connection-welcome').close();
  connectionStorage('setItem', 'seen', 'yes');
}
function renderConnectionOnboarding(d) {
  if (!d?.ready) return;
  const mail = !!d.ready.mail && !(d.mailConnection?.mode === 'oauth' && d.status?.sync_error_code === 'mail_authentication_failed');
  const ai = !!d.ready.ai, box = $('connection-onboarding');
  box.hidden = mail && ai;
  if (mail && ai) {
    if ($('connection-welcome').open) closeConnectionWelcome();
    connectionStorage('setItem', 'seen', 'yes'); return;
  }
  box.replaceChildren();
  if (connectionStorage('getItem','collapsed') === 'yes') {
    box.className = 'connection-onboarding is-collapsed';
    const expand = element('button', `完成设置 · ${Number(mail)+Number(ai)}/2`, 'connection-expand');
    expand.type='button';expand.onclick=()=>{connectionStorage('removeItem','collapsed');renderConnectionOnboarding(state)};
    box.append(expand);
  } else {
    box.className = 'connection-onboarding';
    const header = element('div','','connection-guide-header');
    header.append(element('strong','完成连接'));
    const collapse = element('button','⌄','connection-collapse');collapse.type='button';collapse.setAttribute('aria-label','收起引导');
    collapse.onclick=()=>{connectionStorage('setItem','collapsed','yes');renderConnectionOnboarding(state)};header.append(collapse);box.append(header);
    for (const [name,ready] of [['连接邮箱',mail],['配置 AI',ai]]) {
      const row = element('div','','connection-guide-step'+(ready?' is-done':''));
      const mark=element('span',ready?'✓':'○','connection-guide-check');mark.setAttribute('aria-hidden','true');
      row.append(mark,element('span',name),element('small',ready?'已完成':'待完成'));box.append(row);
    }
    const next = element('button', mail ? '配置 AI' : d.mailConnection?.reauthorize ? (MAIL_OAUTH_UI_ENABLED ? '重新授权' : '邮箱设置') : '连接邮箱', 'connection-next');next.type='button';next.onclick=()=>openConnectionStep(mail?'ai':'mail');box.append(next);
  }
  if (!connectionWelcomeChecked) {
    connectionWelcomeChecked = true;
    if (!mailboxResult && connectionStorage('getItem','seen') !== 'yes') {
      // Record before opening, so cancellation/Escape does not reopen it on polling.
      connectionStorage('setItem','seen','yes');
      const dialog = $('connection-welcome');
      dialog.querySelector('.connection-welcome-steps').replaceChildren(...[['连接邮箱',mail],['配置 AI',ai]].map(([label,ready])=>element('span',(ready?'✓ ':'○ ')+label)));
      const primary=dialog.querySelector('footer button:last-child');primary.textContent=mail?'配置 AI':'连接邮箱';primary.onclick=()=>{closeConnectionWelcome();openConnectionStep(mail?'ai':'mail')};
      dialog.showModal();
    }
  }
}

// Keep the setup card above the chat composer, including when the textarea grows.
function positionConnectionCard() {
  const box=$('connection-onboarding'), composer=$('chat-form');
  if (!box || !composer) return;
  box.style.bottom = document.body.classList.contains('chat-layout-page') && composer.getClientRects().length
    ? Math.max(24,window.innerHeight-composer.getBoundingClientRect().top+16)+'px' : '';
}
new ResizeObserver(positionConnectionCard).observe($('chat-form'));
window.addEventListener('resize',positionConnectionCard);

// Focusing selects the saved mask; typing replaces it without exposing the stored secret.
$('password').addEventListener('focus',()=>{
  if($('password').dataset.saved==='yes') $('password').select();
});
$('password').addEventListener('beforeinput',()=>{
  const field=$('password');
  if(field.dataset.saved==='yes') {
    field.value='';field.dataset.saved='';field.dataset.editing='1';
  }
});
$('password').addEventListener('blur',()=>{
  const field=$('password');
  const entry=(state?.mailAccounts||[]).find(item=>item.id===mailEditingId);
  if(!field.value && entry?.connected && entry.account.toLowerCase()===$('account').value.trim().toLowerCase() && entry.mail_provider===$('mail_provider').value) {
    delete field.dataset.editing;savedSecret('password',true);renderForwardingForm(state);
  }
});
function forwardingFormSaved(d) {
  const entry=(d?.mailAccounts||[]).find(item=>item.id===mailEditingId);
  return !!entry && entry.account.toLowerCase()===$('account').value.trim().toLowerCase() &&
    entry.mail_provider===$('mail_provider').value && entry.school_sender.toLowerCase()===$('school_sender').value.trim().toLowerCase() &&
    $('password').dataset.saved==='yes' && localStorage.getItem(forwardingKey())==='yes';
}
function forwardingReceiverVerified(d) {
  return receiverVerifiedRevision === receiverRevision || !!(connectedReceiver(d,$('account').value) && $('password').dataset.saved==='yes');
}

function renderForwardingForm(d) {
  if (!d?.config) return;
  const address = $('account').value.trim();
  const verified = forwardingReceiverVerified(d);
  const forwarded = localStorage.getItem(forwardingKey()) === 'yes';
  $('mail-forward-target').value = address;
  $('mail-forward-copy').disabled = !address;
  $('mail-receiver-status').hidden = !verified;
  $('mail-receiver-connect').textContent = receiverBusy ? '连接中…' : verified ? '重新连接' : '连接邮箱';
  $('mail-receiver-connect').disabled = receiverBusy || !['qq','netease'].includes($('mail_provider').value) || !address || !($('password').value || $('password').dataset.saved === 'yes');
  $('confirm-forwarding').checked = forwarded;
  $('confirm-forwarding').disabled = !verified || !$('school_sender').value.trim();
  const saved=forwardingFormSaved(d);
  $('mail-save').textContent=connectionStates.mail==='连接中'?'保存中…':saved?'已保存':mailEditingId?'保存':'添加邮箱';
  $('mail-save').disabled = saved || receiverBusy || !verified || !forwarded || !$('school_sender').value.trim() || connectionStates.mail === '连接中';
}
async function connectForwardingReceiver() {
  if (receiverBusy) return;
  const revision = receiverRevision;
  const data = draft('mail');
  const box = $('mail-receiver-feedback');
  receiverBusy = true; box.textContent = ''; renderForwardingForm(state);
  try {
    const response = await fetch('/api/settings/mail/test', {method:'POST',headers:{'Content-Type':'application/json','X-Token':token},body:JSON.stringify(data)});
    const result = await response.json();
    if (!response.ok) throw Error(result.error || '邮箱连接失败，请检查 IMAP 授权码。');
    if (revision !== receiverRevision) throw Error('邮箱信息已更改，请重新连接。');
    receiverVerifiedRevision = revision;
  } catch (error) { box.textContent = error.message; }
  finally { receiverBusy = false; renderForwardingForm(state); }
}
async function saveForwardingMailbox() {
  if (!forwardingReceiverVerified(state) || !$('confirm-forwarding').checked) return;
  if (!$('school_sender').value.trim() || !$('school_sender').reportValidity()) return;
  if(forwardingFormSaved(state)) return;
  const adding=!mailEditingId;
  if (await connectionAction('mail','save')) {
    if(adding) showMailboxList(); else renderMailboxConnection(state);
  }
}
async function copyForwardingAddress() {
  const address = $('mail-forward-target');
  if (!address.value) return;
  try {
    try { await navigator.clipboard.writeText(address.value); }
    catch (_) { address.select(); if (!document.execCommand('copy')) throw Error('copy'); }
    $('mail-forward-copy').querySelector('span').textContent = '已复制';
  } catch (_) { notify('复制失败，请手动复制地址'); }
}
for (const id of ['account','password','mail_provider']) $(id).addEventListener(id === 'mail_provider' ? 'change' : 'input', () => {
  receiverRevision++; receiverVerifiedRevision = -1;
  $('mail-receiver-feedback').textContent = '';
  $('mail-forward-copy').querySelector('span').textContent = '复制';
  renderForwardingForm(state);
});

$('mail-name').addEventListener('input',()=>{ $('mail-name-feedback').textContent=''; });
