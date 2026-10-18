let aiProfiles = [];
let aiEditingId = null;
let aiModelDraft = [];
let aiProfileBusy = false;
let aiMailModelDraft = '';
let aiModelNamesDraft = {};
const aiNameLookups = new Set();

function aiModelName(profile, model) {
  return profile?.model_names?.[model] || model;
}

async function loadAIModelNames(profiles) {
  for (const profile of profiles) {
    const signature = JSON.stringify([profile.id, profile.provider, profile.base, profile.models]);
    if (aiNameLookups.has(signature) || aiProfileModels(profile).every(id => profile.model_names?.[id])) continue;
    aiNameLookups.add(signature);
    try {
      const response = await fetch('/api/settings/ai/models', {method:'POST',headers:{'Content-Type':'application/json','X-Token':token},body:JSON.stringify({profileId:profile.id})});
      const result = await response.json();
      if (!response.ok || !Object.keys(result.modelNames || {}).length) continue;
      const current = aiProfiles.find(p => p.id === profile.id);
      if (!current) continue;
      current.model_names = {...current.model_names,...result.modelNames};
      if (aiEditingId === profile.id && !aiProfileBusy) {
        aiModelNamesDraft = {...aiModelNamesDraft,...result.modelNames};
        renderAIModelOptions();
      }
      await refresh();
    } catch (_) { /* Keep the original ID when discovery is unavailable. */ }
  }
}

function selectAIProfileTab(tab) {
  const models = tab === 'models';
  $('ai-model-panel').hidden = !models;
  $('ai-connection-panel').hidden = models;
  $('ai-model-tab').setAttribute('aria-selected', String(models));
  $('ai-connection-tab').setAttribute('aria-selected', String(!models));
  $('ai-save').textContent = !aiEditingId && !models ? '下一步' : '保存';
}

function replaceAIKey() {
  const field = $('ai-key-field'), show = field.hidden;
  field.hidden = !show;
  $('ai-key-replace').setAttribute('aria-expanded', String(show));
  if (show) $('key').focus();
}

function aiProfileModels(profile) {
  return profile.models?.length ? profile.models : [profile.model];
}

function renderAIProfiles(data) {
  aiProfiles = data.aiProfiles || [];
  const list = $('ai-provider-list');
  list.replaceChildren();
  for (const profile of aiProfiles) {
    const title = providers[profile.provider]?.name || profile.provider;
    const models = aiProfileModels(profile);
    const row = element('button', '', 'ai-provider-row settings-clickable-entry'); row.type='button';
    row.setAttribute('aria-label','设置 '+title); row.onclick=()=>openAIProfile(profile.id);
    const mark=element('span',profile.provider==='deepseek'?'DS':profile.provider==='qwen'?'Q':title[0],'ai-provider-mark');mark.setAttribute('aria-hidden','true');
    const copy=element('span','','ai-provider-copy');copy.append(element('strong',title),element('small',models.length>2?`已启用 ${models.length} 个模型`:models.map(id=>aiModelName(profile,id)).join(' · ')));
    const tail=element('span','','settings-entry-tail');tail.append(element('span',profile.connected?'✓ 已连接':'未连接',profile.connected?'settings-entry-connected':'meta'),element('span','›','settings-entry-chevron'));
    row.append(mark,copy,tail);list.append(row);
  }
  $('ai-nav-provider').textContent = aiProfiles.length ? aiProfiles.map(p => providers[p.provider]?.name || p.provider).filter((v,i,a) => a.indexOf(v) === i).join(' · ') : '尚未设置';
  void loadAIModelNames(aiProfiles);
}

function fillAIProfile(id) {
  const profile = aiProfiles.find(item => item.id === id);
  aiEditingId = profile?.id || '';
  $('provider').value = profile?.provider || 'deepseek';
  $('base').value = profile?.base || providers[$('provider').value]?.base || '';
  $('key').value = '';
  delete $('key').dataset.editing;
  $('key').dataset.saved = profile ? 'yes' : '';
  $('key').placeholder = '输入 API Key';
  $('ai-key-field').hidden = !!profile;
  $('ai-key-replace').hidden = !profile;
  $('ai-key-replace').setAttribute('aria-expanded', String(!profile));
  aiModelDraft = [];
  aiModelNamesDraft = {...profile?.model_names};
  aiMailModelDraft = profile?.is_default ? profile.model : '';
  modelOptions(profile ? aiProfileModels(profile) : [], profile?.model || '');
  $('ai-advanced').open = false;
  $('ai-provider-field').hidden = !!profile;
  $('ai-dialog-title').textContent = profile ? providers[profile.provider]?.name || profile.provider : '添加服务';
  $('ai-dialog-mark').textContent = profile?.provider === 'deepseek' || !profile ? 'DS' : (providers[profile.provider]?.name || profile.provider)[0];
  $('ai-profile-delete').hidden = !profile;
  renderProviderHelp();
  $('ai-feedback').textContent = '';
  selectAIProfileTab(profile ? 'models' : 'connection');
}

function openAIProfile(id) {
  if (aiProfileBusy) return;
  fillAIProfile(id);
  $('ai-profile-dialog').showModal();
  $(id ? 'ai-model-tab' : 'provider').focus();
}

function closeAIProfile() {
  if (aiProfileBusy) return;
  $('key').value = '';
  delete $('key').dataset.editing;
  $('ai-profile-dialog').close();
}

function renderAIModelOptions() {
  const list = $('ai-model-list'); list.replaceChildren();
  $('ai-model-count').textContent = `已启用 ${aiModelDraft.filter(m => m.enabled).length} 个`;
  for (const model of aiModelDraft) {
    const selected = model.id === aiMailModelDraft;
    const row = element('div', '', 'ai-model-row' + (selected ? ' is-mail' : ''));
    const label = element('label', '', 'ai-model-option');
    const input = element('input'); input.type = 'checkbox'; input.checked = model.enabled; input.value = model.id;
    input.onchange = () => {
      if (!input.checked && model.id === aiMailModelDraft) {
        input.checked = true; $('ai-feedback').textContent = '先选择其他默认模型'; return;
      }
      model.enabled = input.checked; aiRevision++; renderAIModelOptions();
    };
    const choice = element('button', selected ? '✓ 默认' : '设为默认', 'ai-mail-choice');
    choice.type = 'button'; choice.disabled = !model.enabled;
    choice.dataset.model = model.id;
    const name = aiModelNamesDraft[model.id] || model.id;
    choice.setAttribute('aria-label', name + (selected ? '：邮件分析默认模型' : '：设为邮件分析默认模型'));
    choice.setAttribute('aria-pressed', String(selected));
    choice.onclick = () => {
      aiMailModelDraft = model.id; aiRevision++; $('ai-feedback').textContent = ''; renderAIModelOptions();
      [...list.querySelectorAll('.ai-mail-choice')].find(b => b.dataset.model === model.id)?.focus();
    };
    label.append(input, element('span', name)); row.append(label, choice); list.append(row);
  }
  $('model').value = aiMailModelDraft || aiModelDraft.find(m => m.enabled)?.id || '';
}

async function saveAIService() {
  if (aiProfileBusy) return;
  if (!aiEditingId && !$('ai-connection-panel').hidden) {
    if (!aiModelDraft.length && !await connectionAction('ai', 'models')) return;
    selectAIProfileTab('models'); return;
  }
  const data = draft('ai');
  if (!data.models.length) { $('ai-feedback').textContent = '至少启用一个模型'; return; }
  if (!$('base').checkValidity()) { selectAIProfileTab('connection'); $('ai-advanced').open = true; $('base').reportValidity(); return; }
  const controls = [...$('ai-profile-dialog').querySelectorAll('input,select,button')];
  aiProfileBusy = true; controls.forEach(e => e.disabled = true); $('ai-feedback').textContent = '正在连接…';
  try {
    const headers = {'Content-Type':'application/json','X-Token':token};
    let response = await fetch('/api/settings/ai/test', {method:'POST',headers,body:JSON.stringify(data)});
    let result = await response.json(); if (!response.ok) throw Error(result.error || '连接失败');
    response = await fetch('/api/settings/ai', {method:'POST',headers,body:JSON.stringify(data)});
    result = await response.json(); if (!response.ok) throw Error(result.error || '保存失败');
    $('key').value = ''; delete $('key').dataset.editing; $('ai-profile-dialog').close();
    connectionStates.ai = '已保存';
    await refresh(); $('ai-library-feedback').textContent = '';
  } catch(error) { $('ai-feedback').textContent = error.message; }
  finally { aiProfileBusy = false; controls.forEach(e => e.disabled = false); renderAIModelOptions(); }
}

$('ai-profile-dialog').addEventListener('cancel', event => { if (aiProfileBusy) event.preventDefault(); });
$('ai-profile-dialog').addEventListener('close', () => { $('key').value = ''; delete $('key').dataset.editing; });
$('ai-profile-dialog').querySelector('[role="tablist"]').addEventListener('keydown', event => {
  if (aiProfileBusy || !['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
  event.preventDefault();
  const models = event.key === 'Home' || event.key !== 'End' && $('ai-model-tab').getAttribute('aria-selected') !== 'true';
  selectAIProfileTab(models ? 'models' : 'connection');
  $(models ? 'ai-model-tab' : 'ai-connection-tab').focus();
});
$('ai-profile-delete').onclick = async () => {
  if (aiProfileBusy || !aiEditingId || !window.confirm('移除此服务及保存的 Key？')) return;
  try {
    const response = await fetch('/api/ai/profiles/delete', {method:'POST',headers:{'Content-Type':'application/json','X-Token':token},body:JSON.stringify({id:aiEditingId})});
    const result = await response.json(); if (!response.ok) throw Error(result.error);
    closeAIProfile(); await refresh();
  } catch(error) { $('ai-feedback').textContent = error.message; }
};
// Mailbox, AI, calendar and account settings.

function connectionBadge(group, ready) {
  const button = $(group + '-save');
  const connected = ready && !['未保存', '失败'].includes(connectionStates[group]);
  button.textContent = group === 'ai' ? '保存' : connectionStates[group] === '连接中' ? '保存中…' : connected ? '已保存' : '保存设置';
  const summary = $(group + '-nav-status');
  if (summary) {
    summary.textContent = connectionStates[group] === '连接中' ? '连接中' :
      connectionStates[group] === '失败' ? '连接失败' :
      connectionStates[group] === '未保存' ? '待保存' : connected ? '已连接' : '未连接';
    summary.className = 'settings-summary-status' + (connected ? ' is-connected' : '');
  }
  let status = connectionStates[group] || (ready ? '已保存' : '未设置');
  let e = $(group + '-ready');
  e.textContent = status === '已保存' ? '✓ 已保存' : status === '✓ 成功' ? '✓ 连接成功' : status;
  e.className = 'connection-state' + (['✓ 成功', '已保存'].includes(status) ? ' success' : status === '失败' ? ' error' : '');
}

function connectionEdited(group) {
  connectionStates[group] = '未保存';
  connectionBadge(group, false);
  $(group + '-feedback').textContent = '';
  renderFieldStatuses(state);
  if(group==='mail' && typeof renderForwardingForm==='function') renderForwardingForm(state);
}

function modelOptions(models, current = '') {
  const saved = aiProfiles.find(p => p.id === aiEditingId);
  const enabled = aiModelDraft.length ? aiModelDraft.filter(m => m.enabled).map(m => m.id) : saved ? aiProfileModels(saved) : current ? [current] : [];
  const all = [...new Set([...models,...enabled])];
  aiModelDraft = all.map(id => ({id,enabled:enabled.includes(id)}));
  if (!saved && !aiModelDraft.some(m => m.enabled) && aiModelDraft.length) aiModelDraft[0].enabled = true;
  if (!aiProfiles.length && !aiMailModelDraft) aiMailModelDraft = aiModelDraft.find(m => m.enabled)?.id || '';
  $('model').value = enabled[0] || '';
  renderAIModelOptions(); aiRevision++;
}

function renderProviderHelp() {
  const p = providers[$('provider').value];
  const link = $('api-key-help');
  link.hidden = !p?.key_url;
  link.textContent = p?.key_url ? `前往 ${p.key_label || p.name} 获取 ↗` : '';
  if (p?.key_url) link.href = p.key_url;else link.removeAttribute('href');
  $('api-key-help-note').hidden = !!p?.key_url;
}

function providerChanged() {
  aiRevision++;
  const p = providers[$('provider').value];
  $('base').value = p?.base || '';
  $('key').value = ''; $('key').dataset.saved = ''; $('key').dataset.editing = '1';
  aiModelDraft = []; aiMailModelDraft = ''; aiModelNamesDraft = {}; modelOptions([]); renderProviderHelp();
  $('ai-dialog-mark').textContent = $('provider').value === 'deepseek' ? 'DS' : (p?.name || '?')[0];
  $('ai-advanced').open = false; $('ai-feedback').textContent = '';
}

function editSecret(id) {
  let e = $(id);
  if (e.dataset.saved === 'yes') {
    e.value = '';
    e.dataset.saved = '';
  }
  e.readOnly = false;
}

function savedSecret(id, saved) {
  let e = $(id);
  if (e.dataset.editing || e.value && e.dataset.saved !== 'yes') return;
  e.readOnly = false;
  e.dataset.saved = saved ? 'yes' : '';
  e.value = id === 'password' && saved ? '••••••••' : '';
  e.placeholder = saved ? (id === 'password' ? '' : '••••••••') : id === 'password' ? '填写邮箱客户端授权码' : '填写当前服务商的 API Key';
}

function draft(group) {
  let keys = group === 'mail' ? ['account', 'mail_provider', 'school_sender', 'password'] : ['provider', 'base', 'model', 'key'];
  const result = Object.fromEntries(keys.map(k => [k, $(k).dataset.saved === 'yes' ? '' : $(k).value.trim()]));
  if (group === 'ai' && typeof aiEditingId !== 'undefined') Object.assign(result, {profileId:aiEditingId || '',name:providers[$('provider').value]?.name || $('provider').value,models:aiModelDraft.filter(m => m.enabled).map(m => m.id),modelNames:aiModelNamesDraft,makeDefault:!!aiMailModelDraft});
  if(group==='mail' && typeof mailEditingId!=='undefined') result.mailAccountId=mailEditingId||'';
  return result;
}

function renderMailProvider() {
  const provider = $('mail_provider').value,
    selected = provider === 'qq' || provider === 'netease',
    status = $('mail-provider-status');
  $('mail-provider-fields').hidden = false;
  status.textContent = selected ? '✓' : '○';
  status.className = 'field-status' + (selected ? ' success' : '');
  status.title = selected ? '已选择邮箱服务商' : '请选择邮箱服务商';
  $('mail-save').disabled = !selected;
  $('account-label').textContent = '接收邮箱地址';
  $('account').placeholder = provider === 'qq' ? '完整 QQ 邮箱地址' : provider === 'netease' ? '完整网易邮箱地址（163.com 或 126.com）' : '完整邮箱地址';
  $('password-mail-label').textContent = 'IMAP 授权码';
  $('mail-nav-provider').textContent = provider === 'qq' ? 'QQ 邮箱' : provider === 'netease' ? '网易邮箱' : '尚未设置';
  $('mail-auth-guide').textContent = '如何获取 ↗';
  $('mail-auth-guide').href = provider === 'netease' ? '/assets/guides/netease.html' : '/assets/guides/qq.html';
  $('mail-auth-guide').onclick = event => {
    event.preventDefault();
    openSetupGuide(provider === 'netease' ? 'netease' : 'qq');
  };
  $('forwarding-title').textContent = '设置邮件自动转发';
  $('confirm-forwarding').disabled = !$('school_sender').value.trim() || !$('account').value.trim();
  if (typeof renderForwardingForm === 'function') renderForwardingForm(state);
}

function mailProviderChanged() {
  const p = $('mail_provider').value,
    address = $('account').value.trim().toLowerCase(),
    valid = p === 'qq' ? address.endsWith('@qq.com') || address.endsWith('@foxmail.com') : p === 'netease' ? address.endsWith('@163.com') || address.endsWith('@126.com') : false;
  if (!valid) {
    $('account').value = '';
    delete $('account').dataset.saved;
  }
  $('password').value = '';
  delete $('password').dataset.saved;
  delete $('password').dataset.editing;
  connectionEdited('mail');
  renderMailProvider();
  renderSetupGuide(state);
}

function renderFieldStatuses(d) {
  const providerSelected = !!$('provider').value;
  const providerStatus = $('provider-status');
  providerStatus.textContent = providerSelected ? '✓' : '○';
  providerStatus.title = providerSelected ? '已选择服务商' : '请选择服务商';
  providerStatus.className = 'field-status' + (providerSelected ? ' success' : '');
  for (let group of ['mail', 'ai']) {
    const ready = !!d?.ready?.[group] && connectionStates[group] !== '未保存' && connectionStates[group] !== '失败';
    for (let id of group === 'mail' ? ['school_sender', 'account', 'password'] : ['key', 'model']) {
      const el = $(id + '-status');
      el.textContent = ready ? '✓' : '○';
      el.title = ready ? '已连接' : '待验证';
      el.className = 'field-status' + (ready ? ' success' : '');
    }
  }
}

async function connectionAction(group, action) {
  if (group === 'ai' && aiProfileBusy) return false;
  if (group === 'ai') aiProfileBusy = true;
  let data = draft(group),
    revision = aiRevision;
  let controls = document.querySelectorAll(group === 'ai' ? '#ai-profile-dialog button, #ai-profile-dialog input, #ai-profile-dialog select' : '#mail-settings button, #mail-settings input, #mail-settings select');
  controls.forEach(x => x.disabled = true);
  let box = $(group + '-feedback');
  if (action === 'save') {
    connectionStates[group] = '连接中';
    connectionBadge(group, false);
  }
  box.textContent = action === 'models' ? '正在查找模型…' : action === 'test' ? '测试中…' : '正在保存…';
  try {
    if (action === 'save') {
      box.textContent = '正在连接…';
      let check = await fetch('/api/settings/' + group + '/test', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Token': token
        },
        body: JSON.stringify(data)
      });
      let checked = await check.json();
      if (!check.ok) throw Error(checked.error || '连接失败');
      if (group === 'ai' && revision !== aiRevision) throw Error('设置已变更，请重新操作。');
    }
    let path = '/api/settings/' + group + (action === 'save' ? '' : '/' + action);
    let r = await fetch(path, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Token': token
      },
      body: JSON.stringify(data)
    });
    let result = await r.json();
    if (group === 'ai' && revision !== aiRevision) {
      box.textContent = '设置已变更，请重新操作。';
      return;
    }
    if (!r.ok) throw Error(result.error || '操作未完成');
    if (group === 'ai' && action === 'save' && result.profileId) aiEditingId = result.profileId;
    if (action === 'models') {
      if (!Array.isArray(result.models) || !result.models.length) throw Error('未找到模型，请稍后重试');
      aiModelNamesDraft = {...aiModelNamesDraft,...result.modelNames};
      modelOptions(result.models, data.model);
      box.textContent = '';
    } else {
      box.textContent = '';
      connectionStates[group] = '✓ 成功';
      connectionBadge(group, true);
      if (action === 'save') {
        let e = $(group === 'mail' ? 'password' : 'key');
        e.value = '';
        delete e.dataset.editing;
      }
      if (!(await refresh())) throw Error('操作已保存，但页面刷新失败，请刷新页面查看。');
      if (action === 'save') {
        box.textContent = '';
        connectionBadge(group, true);
      }
    }
    return true;
  } catch (e) {
    if (action !== 'models') {
      connectionStates[group] = '失败';
      connectionBadge(group, false);
      renderFieldStatuses(state);
    }
    box.textContent = e.message;
    return false;
  } finally {
    controls.forEach(x => x.disabled = false);
    if (group === 'ai') { aiProfileBusy = false; renderAIModelOptions(); }
    if (group === 'mail' && typeof renderForwardingForm === 'function') renderForwardingForm(state);
  }
}

async function exportCalendar(data) {
  try {
    let r = await fetch('/api/calendar/export', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Token': token
      },
      body: JSON.stringify(data)
    });
    let d = await r.json();
    if (!r.ok) throw Error(d.error);
    const url = URL.createObjectURL(new Blob([d.ics], {
      type: 'text/calendar;charset=utf-8'
    }));
    let link = document.createElement('a');
    link.href = url;
    link.download = '审核后的日程.ics';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    notify('请打开日历文件，确认导入。');
    $('calendar-dialog').close();
  } catch (e) {
    $('status').textContent = e.message;
  }
}

function forwardingKey() {
  return 'mail-forwarding-confirmed:' + loginEmail + ':' + ($('account').value || '').trim().toLowerCase() + ':' + ($('school_sender').value || '').trim().toLowerCase();
}

async function loadSetupGuide(url) {
  if (!setupGuideCache.has(url)) setupGuideCache.set(url, fetch(url).then(async response => {
    if (!response.ok) throw Error('教程加载失败，请重试。');
    return response.text();
  }).catch(error => {
    setupGuideCache.delete(url);
    throw error;
  }));
  return setupGuideCache.get(url);
}

function closeSetupGuide() {
  setupGuideRevision++;
  $('setup-guide-dialog').close();
}

async function openSetupGuide(kind) {
  const guides = {
    outlook: {
      title: '设置邮件自动转发至接收邮箱',
      url: '/assets/guides/outlook.html',
      links: []
    },
    qq: {
      title: '获取 QQ 邮箱授权码',
      url: '/assets/guides/qq.html',
      links: [['打开 QQ 邮箱 ↗', 'https://mail.qq.com/'], ['QQ 邮箱官方授权码说明 ↗', 'https://help.mail.qq.com/detail/106/985']]
    },
    netease: {
      title: '获取网易邮箱客户端授权码',
      url: '/assets/guides/netease.html',
      links: [['打开网易邮箱 ↗', 'https://mail.163.com/'], ['网易邮箱官方帮助 ↗', 'https://help.mail.126.com/faqDetail.do?code=d7a5dc8471cd0c0e8b4b8f4f8e49998b374173cfe9171305fa1ce630d7f67ac286624f309a1a7089']]
    }
  };
  const guide = guides[kind];
  if (!guide) return;
  const revision = ++setupGuideRevision,
    dialog = $('setup-guide-dialog'),
    content = $('setup-guide-content'),
    links = $('setup-guide-links');
  $('setup-guide-title').textContent = guide.title;
  links.replaceChildren(...guide.links.map(([label, url]) => {
    const a = element('a', label);
    a.href = url;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    return a;
  }));
  links.hidden = !guide.links.length;
  content.textContent = '正在加载教程…';
  if (!dialog.open) dialog.showModal();
  dialog.scrollTop = 0;
  try {
    const doc = new DOMParser().parseFromString(await loadSetupGuide(guide.url), 'text/html'),
      main = doc.querySelector('main');
    if (!main) throw Error('教程内容暂不可用。');
    main.querySelectorAll('script,style,h1').forEach(node => node.remove());
    main.querySelectorAll('a').forEach(link => {
      if (link.getAttribute('href')?.startsWith('/assets/')) link.replaceWith(...link.childNodes);
    });
    if (revision === setupGuideRevision && dialog.open) content.replaceChildren(...Array.from(main.childNodes));
  } catch (error) {
    if (revision === setupGuideRevision && dialog.open) content.textContent = error.message;
  }
}

function confirmForwarding() {
  const key = forwardingKey();
  if (localStorage.getItem(key) === 'yes') localStorage.removeItem(key);else localStorage.setItem(key, 'yes');
  renderSetupGuide(state);
}

function renderSetupGuide(d) {
  if (!d?.config) return;
  const forwarded = localStorage.getItem(forwardingKey()) === 'yes';
  const button = $('confirm-forwarding');
  button.checked = forwarded;
  button.disabled = !$('school_sender').value.trim() || !$('account').value.trim();
  if (typeof renderForwardingForm === 'function') renderForwardingForm(d);
}

async function accountRequest(action, data) {
  let r = await fetch('/api/auth/' + action, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Token': token
    },
    body: JSON.stringify(data)
  });
  let d = await r.json();
  if (!r.ok) throw Error(d.error || '操作未完成');
  return d;
}
