// Shared application state and DOM/request helpers. Feature functions are loaded before main.js starts the app.

function localDateKey(date) {
  return date.getFullYear() + '-' + String(date.getMonth() + 1).padStart(2, '0') + '-' + String(date.getDate()).padStart(2, '0');
}

const categories = ['课程与教学', '活动与机会', '学籍与行政', '校园服务', '其他'];

let selected = '全部',
  selectedCourse = '全部课程',
  state = null,
  importantView = 'all',
  selectedDeadlineKey = '',
  calendarMonth = new Date(new Date().getFullYear(), new Date().getMonth(), 1),
  calendarSelected = '';

let activeMailId = null,
  mailSearchQuery = '',
  mailSelectionMode = false,
  selectedMailIds = new Set(),
  lastSelectedMailIndex = null;

const nativeFetch = window.fetch.bind(window);

const token = document.querySelector('meta[name="csrf-token"]').content;

let enabled = false,
  last = '',
  initialized = false,
  calendarMethod = 'unset',
  refreshIssued = 0,
  refreshApplied = 0;

const $ = id => document.getElementById(id);

async function call(path, data) {
  try {
    let r = await fetch(path, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Token': token
      },
      body: JSON.stringify(data)
    });
    let d = await r.json();
    if (!r.ok) throw Error(d.error);
    if (!(await refresh())) throw Error('操作已保存，但页面刷新失败，请刷新页面查看。');
    return true;
  } catch (e) {
    notify(e.message);
    return false;
  }
}

let providers = {},
  aiRevision = 0,
  settingsFoldsInitialized = false;

const connectionStates = {
  mail: '',
  ai: ''
};

let calendarEditing = false,
  calendarConfig = {},
  calendarUrl = null;

let manualMailCheck = false;

let mailDetailCache = new Map(),
  deleteUndoTimer = null;

let mailSearchIds = null,
  mailSearchResolvedQuery = '',
  mailSearchPending = false,
  mailSearchError = '',
  mailSearchTimer = null,
  mailSearchRequest = 0;

let mailRenderLimit = 50,
  mailRenderFilter = '',
  lastCalendarMinute = 0;

function element(tag, text, cls) {
  let e = document.createElement(tag);
  e.textContent = text;
  if (cls) e.className = cls;
  return e;
}

function field(label, value, type) {
  let wrap = element('label', label);
  let input = document.createElement('input');
  input.type = type || 'text';
  input.value = value || '';
  wrap.append(input);
  return [wrap, input];
}

function cleanFeedbackText(text) {
  return String(text ?? '').trim().replace(/[。.]+$/u, '');
}

function notify(text) {
  text = cleanFeedbackText(text);
  if (!$('mail-page').hidden) {
    eventActionFeedback(text);
    return;
  }
  $('notice').hidden = false;
  $('notice').textContent = text;
  let target = $('settings-page').hidden ? $('notice') : $('settings-status');
  if (target) target.textContent = text;
}

function showSetup() {
  showPage('settings');
  if (!state?.ready?.mail) selectConnectionSettings('mail');
  else if (!state?.ready?.ai) selectConnectionSettings('ai');
  else if (!calendarProfiles(state?.config || {}).some(profile => profile.confirmed === 'yes')) selectConnectionSettings('calendar');
}

let setupGuideRevision = 0;

const setupGuideCache = new Map();

function showPage(name) {
  if (name === 'settings' && !document.querySelector('.settings-nav-item[aria-current="page"]')) selectConnectionSettings('account');
  for (let page of ['important', 'mail', 'chat', 'settings']) {
    $(page + '-page').hidden = page !== name;
    $('nav-' + page).classList.toggle('is-active', page === name);
    $('nav-' + page).setAttribute('aria-current', page === name ? 'page' : 'false');
  }
  $('account-avatar').classList.toggle('is-active', name === 'settings');
  const titles = {
      important: '重要事项',
      mail: '邮件处理',
      chat: 'AI 对话',
      settings: '账户设置'
    },
    title = titles[name] || 'TimeMate';
  document.title = title + ' - TimeMate';
  document.body.classList.toggle('mail-layout', name === 'mail');
  document.body.classList.toggle('chat-layout-page', name === 'chat');
  document.body.classList.toggle('settings-view', name === 'settings');
  $('header-mail-feedback').hidden = name !== 'mail';
  closeMailSettingsMenu();
  window.scrollTo(0, 0);
  requestAnimationFrame(updateMailWorkspaceHeight);
  if (typeof positionConnectionCard === 'function') requestAnimationFrame(positionConnectionCard);
  if (name === 'chat') loadChatConversations();
}

function selectConnectionSettings(group) {
  const labels = {
    account: ['账户', ''],
    mail: ['邮箱', ''],
    ai: ['AI 服务', ''],
    calendar: ['日历', ''],
    agents: ['个人 Agent', '']
  };
  if (!labels[group]) return;
  for (const key of Object.keys(labels)) {
    const selected = key === group;
    $('settings-nav-' + key)?.setAttribute('aria-current', selected ? 'page' : 'false');
    $(key + '-settings').hidden = !selected;
    const actions = document.querySelector('[data-setting-actions="' + key + '"]');
    if (actions) actions.hidden = !selected;
    const summary = document.querySelector('[data-setting-summary="' + key + '"]');
    if (summary) summary.hidden = !selected;
  }
  $('settings-detail-title').textContent = labels[group][0];
  $('settings-detail-description').textContent = labels[group][1];
  $('settings-page').dataset.settingOpen = group;
  if (group === 'agents' && typeof loadAgentConnections === 'function') void loadAgentConnections();
  if (typeof renderMailboxConnection === 'function') renderMailboxConnection(state);
}

function closeConnectionSettings(group) {
  selectConnectionSettings(group);
}

function value(text) {
  return !text || /^(未说明|此封邮件暂无|无)$/.test(text) ? '此封邮件暂无' : text;
}

let eventFeedbackTimer = null;

const loginEmail = document.querySelector('meta[name="account-email"]').content;

const providerLogo = $('account-provider-logo'),
  domain = (loginEmail.split('@')[1] || '').toLowerCase();

let providerMark = '✉',
  providerClass = '';

let statePollTimer = null,
  statePollInFlight = false;
