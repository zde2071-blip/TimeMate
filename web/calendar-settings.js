// Each calendar app subscribes to the same approved items, with its own setup state.
let calendarProfileId = null;
let calendarBusy = false;

function calendarProfiles(cfg) {
  let rows;
  try { rows = JSON.parse(cfg.calendar_subscriptions || '[]'); } catch (_) { rows = []; }
  if (!Array.isArray(rows)) rows = [];
  rows = rows.filter(row => row && ['apple', 'outlook'].includes(row.provider));
  if (!rows.length && cfg.calendar_method === 'subscribe' && ['apple', 'outlook'].includes(cfg.calendar_provider)) {
    rows = [{provider: cfg.calendar_provider, confirmed: cfg.calendar_subscription_confirmed}];
  }
  return rows;
}

function calendarProviderName(provider) {
  return provider === 'apple' ? 'Apple 日历' : 'Outlook 日历';
}

function renderCalendarSettings(cfg, url) {
  calendarConfig = cfg;
  calendarUrl = url;
  const rows = calendarProfiles(cfg), list = $('calendar-profile-list');
  list.replaceChildren();
  for (const profile of rows) {
    const name = calendarProviderName(profile.provider), confirmed = profile.confirmed === 'yes';
    const row = element('button', '', 'calendar-provider-row settings-clickable-entry');
    row.type = 'button'; row.setAttribute('aria-label', '设置 ' + name);
    row.onclick = () => openCalendarProfile(profile.provider);
    const mark = element('span', '', 'calendar-provider-mark'); mark.setAttribute('aria-hidden', 'true');
    mark.append($('settings-nav-calendar').querySelector('svg').cloneNode(true));
    const copy = element('span', '', 'calendar-provider-copy'); copy.append(element('strong', name));
    const tail = element('span', '', 'settings-entry-tail');
    tail.append(element('span', confirmed ? '✓ 已订阅' : '待确认', confirmed ? 'settings-entry-connected' : 'calendar-entry-pending'), element('span', '›', 'settings-entry-chevron'));
    row.append(mark, copy, tail); list.append(row);
  }
  if (!rows.length) list.append(element('p', '尚未添加日历', 'mail-account-empty'));
  $('calendar-profile-new').disabled = rows.length >= 2;
  $('calendar-profile-new').title = rows.length >= 2 ? '已添加所有支持的日历' : '';
  const current = rows.find(row => row.provider === calendarProfileId);
  const confirmed = current?.confirmed === 'yes';
  if (calendarProfileId) $('calendar_provider').value = calendarProfileId;
  $('calendar_provider').disabled = !!calendarProfileId || calendarBusy;
  for (const option of $('calendar_provider').options) {
    option.disabled = !option.value || (calendarProfileId !== option.value && rows.some(row => row.provider === option.value));
  }
  const name = calendarProfileId ? calendarProviderName(calendarProfileId) : '添加日历';
  $('calendar-profile-title').textContent = name;
  $('calendar-profile-mark').replaceChildren($('settings-nav-calendar').querySelector('svg').cloneNode(true));
  $('calendar-nav-provider').textContent = '';
  $('calendar-nav-status').textContent = '';
  const button = $('calendar-connect');
  button.disabled = calendarBusy || !$('calendar_provider').value;
  button.textContent = calendarBusy ? '处理中…' : !current || !url ? '获取订阅链接' : confirmed ? '取消确认' : '确认订阅';
  button.setAttribute('aria-pressed', String(confirmed));
  $('calendar-show-guide').hidden = !$('calendar_provider').value;
  $('calendar-confirm').hidden = !current;
  $('calendar-confirm').textContent = confirmed ? '✓' : '○';
  $('calendar-confirm').className = 'field-status' + (confirmed ? ' success' : '');
  $('calendar-confirm').title = confirmed ? '已确认订阅' : '待确认订阅';
  $('calendar-subscription').hidden = !url || !current;
  $('calendar-url').value = url || '';
}

function openCalendarProfile(id = '') {
  if (calendarBusy) return;
  if (id && !calendarProfiles(calendarConfig).some(row => row.provider === id)) return;
  calendarProfileId = id;
  calendarEditing = !id;
  $('calendar_provider').value = id;
  $('calendar-feedback').textContent = '';
  renderCalendarSettings(calendarConfig, calendarUrl);
  if (!$('calendar-profile-dialog').open) $('calendar-profile-dialog').showModal();
}

function closeCalendarProfile() {
  if (calendarBusy) return;
  $('calendar-profile-dialog').close();
  calendarProfileId = null;
  calendarEditing = false;
}

function calendarHelp() {
  $('calendar-feedback').textContent = '';
  renderCalendarSettings(calendarConfig, calendarUrl);
}

function changeCalendar() {
  openCalendarProfile();
}

function showCalendarGuide() {
  setupGuideRevision++;
  const dialog = $('setup-guide-dialog'), content = $('setup-guide-content');
  $('setup-guide-title').textContent = '订阅' + ($('calendar_provider').value === 'outlook' ? ' Outlook' : ' Apple') + ' 日历';
  const steps = $('calendar_provider').value === 'outlook' ? '在 Outlook 网页版打开日历 → 添加日历 → 从 Web 订阅，粘贴订阅链接并导入。' : 'Mac：日历 → 文件 → 新建日历订阅，粘贴订阅链接。iPhone：日历 → 添加日历 → 添加订阅日历。';
  content.replaceChildren(element('p', steps), element('p', '只同步你确认加入的日程。订阅日历只读，更新可能延迟；请勿分享链接。', 'meta'));
  if (calendarUrl && /^http:\/\/(127\.0\.0\.1|localhost)(:|\/)/.test(calendarUrl)) content.append(element('p', '本机预览：此链接仅限本机使用。iPhone 和 Outlook 网页版需等网站上线后再连接。', 'meta'));
  if (!dialog.open) dialog.showModal();
  dialog.scrollTop = 0;
}

async function calendarAction() {
  if (calendarBusy) return;
  if (!calendarProfileId || !calendarUrl) await saveCalendar();
  else await confirmCalendar();
}

async function saveCalendar() {
  const provider = $('calendar_provider').value;
  if (!provider || calendarBusy) return;
  calendarBusy = true;
  renderCalendarSettings(calendarConfig, calendarUrl);
  try {
    let r = await fetch('/api/calendar/settings', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-Token': token},
      body: JSON.stringify({calendar_method: 'subscribe', calendar_provider: provider, calendarProfileId: calendarProfileId || ''})
    });
    let d = await r.json();
    if (!r.ok) throw Error(d.error || '日历设置未保存');
    calendarProfileId = provider; calendarEditing = false;
    r = await fetch('/api/calendar/subscription', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-Token': token}, body: '{}'
    });
    d = await r.json();
    if (!r.ok) {
      await refresh();
      throw Error(d.error || '订阅链接未生成');
    }
    if (!(await refresh())) throw Error('日历设置已保存，请刷新页面查看订阅链接。');
    $('calendar-feedback').textContent = '';
    showCalendarGuide();
  } catch (e) {
    $('calendar-feedback').textContent = e.message;
  } finally {
    calendarBusy = false;
    renderCalendarSettings(calendarConfig, calendarUrl);
  }
}

async function confirmCalendar() {
  const current = calendarProfiles(calendarConfig).find(row => row.provider === calendarProfileId);
  if (!current || calendarBusy) return;
  calendarBusy = true;
  renderCalendarSettings(calendarConfig, calendarUrl);
  try {
    if (await call('/api/calendar/settings', {
      calendar_method: 'subscribe', calendar_provider: current.provider, calendarProfileId: current.provider,
      calendar_subscription_confirmed: current.confirmed === 'yes' ? 'no' : 'yes'
    })) {
      $('calendar-feedback').textContent = '';
      if (current.confirmed !== 'yes') $('calendar-profile-dialog').close();
    } else {
      $('calendar-feedback').textContent = $('settings-status').textContent || '日历状态未保存，请重试。';
    }
  } finally {
    calendarBusy = false;
    renderCalendarSettings(calendarConfig, calendarUrl);
  }
}

async function copyCalendarUrl() {
  try {
    await navigator.clipboard.writeText($('calendar-url').value);
    $('calendar-feedback').textContent = '链接已复制。';
  } catch (_) {
    $('calendar-url').select();
    $('calendar-feedback').textContent = '请复制选中的链接。';
  }
}

function chooseCalendar() {
  $('calendar-dialog').close();
  showPage('settings');
  selectConnectionSettings('calendar');
  $('settings-detail-title').scrollIntoView({behavior: 'smooth'});
}

$('calendar-profile-dialog').addEventListener('cancel', event => {
  if (calendarBusy) event.preventDefault();
});
