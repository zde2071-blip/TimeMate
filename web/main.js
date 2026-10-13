// Application startup and lightweight update polling. All DOM listeners are registered here.

window.fetch = async (...args) => {
  const response = await nativeFetch(...args);
  if (response.status === 401) location.href = '/login';
  return response;
};

initEventMenus();

const connectionPanels = [
  ['mail-settings', 'mail'],
  ['ai-settings', 'ai'],
  ['calendar-settings', 'calendar']
];
for (const [id, group] of connectionPanels) {
  $(id).addEventListener('toggle', () => {
    const panel = $(id);
    if (panel.open) {
      for (const [otherId] of connectionPanels) {
        if (otherId !== id) $(otherId).open = false;
      }
      $('settings-page').dataset.settingOpen = group;
    } else if ($('settings-page').dataset.settingOpen === group) {
      $('settings-page').removeAttribute('data-setting-open');
    }
  });
}

$('mail-settings-toggle').onclick = () => {
  let menu = $('mail-settings-menu'),
    open = menu.hidden;
  menu.hidden = !open;
  $('mail-settings-toggle').setAttribute('aria-expanded', String(open));
  if (!open) {
    $('mail-check-submenu').hidden = true;
    $('mail-check-toggle').setAttribute('aria-expanded', 'false');
  }
};

$('mail-check-toggle').onclick = event => {
  event.stopPropagation();
  $('mail-check-submenu').hidden = false;
  $('mail-check-toggle').setAttribute('aria-expanded', 'true');
};

$('mail-check-toggle').parentElement.onmouseenter = () => {
  $('mail-check-submenu').hidden = false;
  $('mail-check-toggle').setAttribute('aria-expanded', 'true');
};

$('mail-check-toggle').parentElement.onmouseleave = () => {
  $('mail-check-submenu').hidden = true;
  $('mail-check-toggle').setAttribute('aria-expanded', 'false');
};

$('mark-filtered-read').onclick = markFilteredMailRead;

$('enable-mail-selection').onclick = () => {
  closeMailSettingsMenu();
  mailSelectionMode = true;
  selectedMailIds.clear();
  lastSelectedMailIndex = null;
  render();
};

document.addEventListener('click', event => {
  if (!event.target.closest('.mail-tools')) closeMailSettingsMenu();
});

document.addEventListener('keydown', event => {
  if (event.key === 'Escape') closeMailSettingsMenu();
});

initMailSearch();

async function refresh() {
  let revision = ++refreshIssued;
  try {
    let r = await fetch('/api/state', {
      headers: {
        'X-Token': token
      }
    });
    if (!r.ok) throw Error('无法连接');
    let d = await r.json();
    if (revision < refreshApplied) return true;
    if (!initialized && d.config) {
      providers = d.providers || {};
      for (let [id, p] of Object.entries(providers)) {
        let o = element('option', p.name);
        o.value = id;
        $('provider').append(o);
      }
      for (let k of ['school_sender', 'account', 'base']) $(k).value = d.config[k] || '';
      $('mail_provider').value = d.config.mail_provider || ((d.config.account || '').toLowerCase().endsWith('@163.com') || (d.config.account || '').toLowerCase().endsWith('@126.com') ? 'netease' : d.config.account ? 'qq' : '');
      $('provider').value = d.config.provider || 'custom';
      $('provider-hint').textContent = providers[$('provider').value]?.hint || '';
      renderProviderHelp();
      modelOptions(d.config.model ? [d.config.model] : [], d.config.model || '');
      renderMailProvider();
      initialized = true;
    }
    savedSecret('password', d.ready?.mail && $('account').value === d.config.account);
    savedSecret('key', d.ready?.ai && $('provider').value === d.config.provider && $('base').value === d.config.base);
    connectionBadge('mail', d.ready?.mail);
    connectionBadge('ai', d.ready?.ai);
    if (!settingsFoldsInitialized) {
      $('mail-settings').open = false;
      $('ai-settings').open = false;
      $('calendar-settings').open = false;
      settingsFoldsInitialized = true;
    }
    $('ai-summary-provider').textContent = $('provider').selectedOptions?.[0]?.textContent || '尚未设置';
    calendarMethod = d.config.calendar_method || 'unset';
    renderCalendarSettings(d.config, d.calendarSubscriptionUrl);
    enabled = d.status.auto;
    renderMailControls(d);
    document.querySelectorAll('.task').forEach(x => x.disabled = d.status.busy);
    const previousRevision = state?.revision;
    state = d;
    if (mailSearchQuery.trim() && previousRevision !== d.revision) resolveMailSearch();
    renderSetupGuide(d);
    renderFieldStatuses(d);
    let signature = JSON.stringify([d.mails, d.eventSourceMails, d.calendarEvents, d.pins, d.eventOverrides, d.eventLinks, d.courseCodes, calendarMethod, Math.floor(Date.now() / 60000)]);
    if (signature !== last) {
      render();
      last = signature;
    }
    refreshApplied = revision;
    return true;
  } catch (e) {
    if (revision >= refreshApplied) {
      $('mail-sync-status').textContent = '连接中断，正在重试';
      $('mail-sync-status').className = 'mail-sync-status attention';
      console.error('邮件助手页面刷新失败', e);
    }
    return false;
  }
}

$('account-email').textContent = loginEmail;

if (domain === 'qq.com') {
  providerMark = 'QQ';
  providerClass = 'provider-qq';
} else if (['163.com', '126.com', 'yeah.net', '188.com'].includes(domain)) {
  providerMark = '网易';
  providerClass = 'provider-netease';
} else if (['gmail.com', 'googlemail.com'].includes(domain)) {
  providerMark = 'M';
  providerClass = 'provider-gmail';
} else if (['outlook.com', 'hotmail.com', 'live.com', 'msn.com'].includes(domain)) {
  providerMark = 'O';
  providerClass = 'provider-outlook';
} else if (domain === 'xjtlu.edu.cn' || domain.endsWith('.xjtlu.edu.cn')) {
  providerMark = 'XJ';
  providerClass = 'provider-school';
}

providerLogo.textContent = providerMark;

providerLogo.classList.add(...providerClass.split(' ').filter(Boolean));

providerLogo.setAttribute('aria-label', providerMark === '网易' ? '网易邮箱' : providerMark === 'QQ' ? 'QQ 邮箱' : providerMark === 'M' ? 'Gmail' : providerMark === 'O' ? 'Outlook' : providerMark === 'XJ' ? '学校邮箱' : '邮箱');

$('account-avatar').onclick = () => {
  const menu = $('account-menu'),
    open = menu.hidden;
  menu.hidden = !open;
  $('account-avatar').setAttribute('aria-expanded', String(open));
};

document.addEventListener('pointerdown', event => {
  if (!event.target.closest('.account-menu-wrap')) {
    $('account-menu').hidden = true;
    $('account-avatar').setAttribute('aria-expanded', 'false');
  }
});

document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !$('account-menu').hidden) {
    $('account-menu').hidden = true;
    $('account-avatar').setAttribute('aria-expanded', 'false');
    $('account-avatar').focus();
  }
});

$('open-password-settings').onclick = () => {
  $('account-menu').hidden = true;
  $('account-avatar').setAttribute('aria-expanded', 'false');
  $('password-dialog').showModal();
  $('old-password').focus();
};

$('account-form').onsubmit = async e => {
  e.preventDefault();
  let button = e.submitter;
  button.disabled = true;
  try {
    await accountRequest('password', {
      old: $('old-password').value,
      password: $('new-password').value
    });
    $('password-dialog').close();
    $('account-form').reset();
    $('account-feedback').textContent = '';
    notify('密码已更新');
  } catch (err) {
    $('account-feedback').textContent = err.message;
  } finally {
    button.disabled = false;
  }
};

$('logout').onclick = async () => {
  try {
    await accountRequest('logout', {});
    location.href = '/login';
  } catch (err) {
    $('account-feedback').textContent = err.message;
  }
};

if (location.hash === '#settings') showPage('settings');

$('account').addEventListener('input', () => {
  if ($('password').dataset.saved === 'yes') editSecret('password');
});

$('base').addEventListener('input', () => {
  if ($('key').dataset.saved === 'yes') editSecret('key');
});

for (let id of ['password', 'key']) $(id).addEventListener('input', () => {
  $(id).dataset.saved = '';
  $(id).dataset.editing = '1';
});

for (let id of ['school_sender', 'account']) $(id).addEventListener('input', () => renderSetupGuide(state));

$('mail_provider').addEventListener('change', mailProviderChanged);

for (let id of ['key', 'base', 'model']) $(id).addEventListener('input', () => {
  aiRevision++;
  $('ai-feedback').textContent = '未保存';
});

for (let group of ['mail', 'ai']) document.querySelectorAll('#' + group + '-settings input, #' + group + '-settings select').forEach(e => e.addEventListener('input', () => connectionEdited(group)));

$('course-add-form').onsubmit = async event => {
  event.preventDefault();
  let error = $('course-add-error'),
    form = $('course-add-form'),
    button = form.querySelector('button[type=submit]');
  button.disabled = true;
  try {
    let response = await fetch('/api/courses/add', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Token': token
        },
        body: JSON.stringify({
          code: $('course-code-input').value
        })
      }),
      data = await response.json();
    if (!response.ok) throw Error(data.error);
    if (!(await refresh())) throw Error('课程已保存，但页面刷新失败，请刷新页面查看。');
    $('course-add-dialog').close();
    notify('课程已添加');
  } catch (e) {
    error.textContent = e.message;
    error.hidden = false;
  } finally {
    button.disabled = false;
  }
};

window.addEventListener('resize', updateMailWorkspaceHeight);

window.addEventListener('scroll', updateMailWorkspaceHeight, {
  passive: true
});

if (typeof ResizeObserver === 'function') {
  let readingObserver = new ResizeObserver(updateMailWorkspaceHeight);
  for (let id of ['filters', 'course-filters', 'header-mail-feedback']) readingObserver.observe($(id));
}

function scheduleStatePoll(delay = 5000) {
  clearTimeout(statePollTimer);
  if (!document.hidden) statePollTimer = setTimeout(pollState, delay);
}

async function pollState() {
  if (document.hidden || statePollInFlight) return;
  statePollInFlight = true;
  try {
    const response = await fetch('/api/updates', {
      headers: {
        'X-Token': token
      }
    });
    if (!response.ok) throw Error('无法连接');
    const update = await response.json();
    if (!state || update.revision !== state.revision) await refresh();else {
      Object.assign(state, {
        status: update.status,
        pendingCount: update.pendingCount,
        failedCount: update.failedCount
      });
      enabled = !!state.status.auto;
      renderMailControls(state);
      document.querySelectorAll('.task').forEach(button => {
        button.disabled = !!state.status.busy;
      });
      const minute = Math.floor(Date.now() / 60000);
      if (minute !== lastCalendarMinute) {
        lastCalendarMinute = minute;
        renderImportant(state);
      }
    }
  } catch (error) {
    $('mail-sync-status').textContent = '连接中断，正在重试';
    $('mail-sync-status').className = 'mail-sync-status attention';
  } finally {
    statePollInFlight = false;
    scheduleStatePoll(5000);
  }
}

refresh();

scheduleStatePoll(5000);

document.addEventListener('visibilitychange', () => {
  clearTimeout(statePollTimer);
  if (!document.hidden) scheduleStatePoll(0);
});

$('setup-guide-dialog').addEventListener('click', event => {
  if (event.target !== $('setup-guide-dialog')) return;
  const box = event.target.getBoundingClientRect();
  if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) closeSetupGuide();
});

$('setup-guide-dialog').addEventListener('cancel', () => {
  setupGuideRevision++;
});

$('source-dialog').addEventListener('click', closeSourceOnBackdrop);
