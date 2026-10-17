// Connection methods and the persistent, account-scoped setup guide.
let mailboxManualOpen = false, mailboxMethodsOpen = false, mailboxPageInitialized = false;
let connectionWelcomeChecked = false, mailboxConnecting = false;
// Keep direct OAuth wired for the Google review flow, but don't expose it to users yet.
const MAIL_OAUTH_UI_ENABLED = false;
const mailboxResults = {
  admin:'需要学校管理员批准 TimeMate 读取邮箱。',
  blocked:'学校限制了此应用的邮箱访问。',
  cancel:'连接已取消，可以重新尝试。',
  network:'连接暂时失败，请重试。',
  permission:'尚未取得读取邮箱的权限，请重新授权或联系学校 IT。',
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
  mailboxManualOpen = false; mailboxMethodsOpen = change;
  renderMailboxConnection(state);
}
function showManualMailbox() {
  mailboxManualOpen = true;
  if (state?.mailConnection?.mode === 'oauth') {
    // Do not reuse the direct account as a forwarding recipient or its secret.
    $('account').value = ''; $('password').value = ''; $('password').dataset.saved = '';
    $('mail_provider').value = ''; renderMailProvider();
  }
  renderMailboxConnection(state);
}
function showMailboxHelp() {
  $('mail-connection-help').hidden = !$('mail-connection-help').hidden;
  $('mail-connection-explanation').textContent = mailboxResult === 'admin'
    ? '请向学校 IT 申请批准 TimeMate，并附上授权页面的错误信息。'
    : '登录窗口关闭或未返回结果时可重试。若学校限制直连，请联系学校 IT；转发也需学校允许。';
}
function renderMailboxConnection(d) {
  if (!d?.config) return;
  const connection = d.mailConnection || {};
  if (!mailboxPageInitialized) {
    mailboxManualOpen = connection.mode !== 'oauth' && !!d.config.account;
    mailboxPageInitialized = true;
  }
  const direct = connection.mode === 'oauth';
  const reauthorize = connection.reauthorize || direct && d.status?.sync_error_code === 'mail_authentication_failed';
  $('mail-manual-settings').hidden = !mailboxManualOpen;
  $('mail-connection-methods').hidden = mailboxManualOpen;
  $('mail-save').hidden = !mailboxManualOpen;
  $('mail-direct-account').hidden = !direct || mailboxMethodsOpen;
  $('mail-method-buttons').hidden = direct && !!connection.connected && !reauthorize && !mailboxMethodsOpen;
  $('mail-direct-address').textContent = direct ? connection.account : '';
  $('mail-direct-status').textContent = reauthorize ? '需重新授权' : '已连接';
  $('mail-oauth-pending').hidden = MAIL_OAUTH_UI_ENABLED || (direct && !reauthorize);
  $('mail-oauth-help').hidden = !MAIL_OAUTH_UI_ENABLED && !reauthorize;
  const result = $('mail-oauth-result');
  const message = reauthorize ? mailboxResults.expired : mailboxResults[mailboxResult] || '';
  result.hidden = !message; result.textContent = message;
  if (direct) {
    $('mail-nav-provider').textContent = connection.provider === 'google' ? 'Google' : 'Microsoft';
    $('mail-nav-status').textContent = reauthorize ? '需重新授权' : '已连接';
  }
  document.querySelectorAll('[data-mail-oauth]').forEach(b => { b.hidden = !MAIL_OAUTH_UI_ENABLED; b.disabled = mailboxConnecting; });
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
  if (group === 'mail') renderMailboxConnection(state);
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
