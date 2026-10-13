let mailReadingMode = "summary", mailReadingId = null;
// Mail list, search, selection, actions and persistent synchronization status.

async function checkMail() {
  manualMailCheck = true;
  if (!(await call('/api/fetch', {}))) manualMailCheck = false;
}
async function toggleAuto() {
  let starting = !enabled;
  if (await call('/api/auto', {
    enabled: starting
  })) {
    eventActionFeedback(starting ? '自动检查已开启，每分钟检查新邮件。' : '自动检查已关闭。');
  }
}
function displaySubject(subject) {
  return String(subject || '').replace(/^(?:\s*(?:转发|轉發|fw|fwd)\s*[:：]\s*)+/i, '').trim() || '无主题';
}
function courseCodes(m) {
  const codes = Array.isArray(m.course_codes) ? m.course_codes : Array.from([m.subject, m.body, m.source_body].join('\n').matchAll(/(?:^|[^A-Za-z0-9])([A-Za-z]{3})[ \t]*(\d{3})(?![A-Za-z0-9])/g), x => x[1].toUpperCase() + x[2]);
  return [...new Set(codes.map(x => String(x).replace(/\s+/g, '').toUpperCase().replace(/([A-Z]{3})(\d{3})/, '$1 $2')))];
}
function renderCourses(d) {
  let box = $('course-filters');
  box.replaceChildren();
  box.hidden = selected !== '课程与教学';
  if (box.hidden) return;
  let items = d.mails.filter(m => m.category === '课程与教学' && matchesMailSearch(m)),
    codes = [...new Set([...items.flatMap(courseCodes), ...(d.courseCodes || []).map(code => code.replace(/([A-Z]{3})(\d{3})/, '$1 $2'))])].sort();
  if (items.some(m => !courseCodes(m).length)) codes.push('未识别课程');
  if (selectedCourse !== '全部课程' && !codes.includes(selectedCourse)) selectedCourse = '全部课程';
  for (let code of ['全部课程', ...codes]) {
    let count = items.filter(m => matchesCourse(m, code)).length;
    let b = element('button', code, code === selectedCourse ? 'active' : '');
    b.append(countLabel(count));
    b.setAttribute('aria-label', code + '，' + count + ' 封邮件');
    b.setAttribute('aria-pressed', String(code === selectedCourse));
    b.onclick = () => {
      selectedCourse = code;
      render();
    };
    box.append(b);
  }
  let add = element('button', '＋ 手工添加');
  add.onclick = () => {
    $('course-code-input').value = '';
    $('course-add-error').hidden = true;
    $('course-add-dialog').showModal();
    $('course-code-input').focus();
  };
  box.append(add);
}
async function saveMailCategory(m, category) {
  if (category === m.category) return;
  let ok = await call('/api/mail/category', {
    id: m.id,
    category
  });
  if (ok) {
    selected = category;
    selectedCourse = '全部课程';
    activeMailId = m.id;
    render();
    notify('已修改分类');
  }
  return ok;
}
function mailCategoryPicker(m) {
  let label = element('label', '', 'mail-category-picker');
  label.setAttribute('aria-label', '修改邮件分类');
  let select = element('select');
  select.setAttribute('aria-label', '修改邮件分类');
  for (let category of categories) {
    let option = element('option', category);
    option.value = category;
    select.append(option);
  }
  select.value = m.category;
  select.onchange = async () => {
    select.disabled = true;
    let ok = await saveMailCategory(m, select.value);
    if (!ok) select.value = m.category;
    select.disabled = false;
  };
  label.append(select);
  return label;
}
function matchesCourse(m, code) {
  let codes = courseCodes(m);
  return code === '全部课程' || (code === '未识别课程' ? !codes.length : codes.includes(code));
}
function mailDateLabel(m) {
  let source = m.sent_date || m.date,
    date = new Date(source);
  return Number.isNaN(date.getTime()) ? source : date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  });
}
function mailActionIcon(action) {
  let svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', '18');
  svg.setAttribute('height', '18');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.8');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  let paths = action === 'delete' ? ['M3 6h18', 'M8 6V4h8v2', 'M19 6l-1 14H6L5 6', 'M10 11v5', 'M14 11v5'] : action === 'read' ? ['M3 9 12 15 21 9', 'M5 7 12 3l7 4', 'M3 9v10h18V9', 'M3 9l6 5', 'M21 9l-6 5'] : ['M3 6.5A2.5 2.5 0 0 1 5.5 4h13A2.5 2.5 0 0 1 21 6.5v11a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z', 'm4 6 8 6 8-6'];
  for (let d of paths) {
    let path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', d);
    svg.append(path);
  }
  return svg;
}
function renderMailSelection(d) {
  let pane = $('mail-detail-pane');
  pane.replaceChildren();
  let card = element('div', '', 'mail-detail-card mail-selection-card'),
    heading = element('header', '', 'mail-detail-heading');
  heading.append(element('h2', '选择处理的信息', 'mail-title'));
  card.append(heading);
  let visibleIds = new Set(d.mails.filter(m => selectedMailIds.has(m.id) && !m.is_deleted).map(m => m.id));
  selectedMailIds = visibleIds;
  let count = element('p', `已选择 ${selectedMailIds.size} 封邮件`, 'mail-selection-count');
  card.append(count);
  if (!selectedMailIds.size) card.append(element('p', '从左侧邮件列表勾选邮件', 'mail-detail-empty'));
  let actions = element('div', '', 'mail-bulk-actions');
  for (let [action, label] of [['read', '标已读'], ['unread', '标未读'], ['delete', '删除']]) {
    let button = element('button', '', 'mail-bulk-action' + (action === 'delete' ? ' destructive' : ''));
    let mark = element('span', '', 'mail-bulk-icon');
    mark.append(mailActionIcon(action));
    button.append(mark, element('span', label));
    button.disabled = !selectedMailIds.size;
    button.onclick = () => bulkMailAction(action);
    actions.append(button);
  }
  card.append(actions);
  let footer = element('div', '', 'mail-selection-footer');
  footer.append(document.createElement('hr'));
  let cancel = element('button', '取消', 'text-button');
  cancel.onclick = () => {
    mailSelectionMode = false;
    selectedMailIds.clear();
    lastSelectedMailIndex = null;
    render();
  };
  footer.append(cancel);
  card.append(footer);
  pane.append(card);
}
function renderMailDetail(m, d, written) {
  let pane = $('mail-detail-pane');
  const previousSource = pane.querySelector('.inline-mail-source');
  pane.replaceChildren();
  if (mailSelectionMode) {
    renderMailSelection(d);
    return;
  }
  if (!m) {
    pane.append(element('div', '选择左侧邮件以查看内容', 'mail-detail-empty'));
    return;
  }
  let card = element('div', '', 'mail-detail-card'),
    heading = element('header', '', 'mail-detail-heading');
  const top = element('div', '', 'mail-detail-top');
  top.append(mailCategoryPicker(m));
  heading.append(top, element('h2', displaySubject(m.subject), 'mail-title'), element('time', mailDateLabel(m), 'meta'));
  let actions = element('div', '', 'mail-detail-actions'),
    read = element('button', '', 'mail-icon-action');
  read.setAttribute('aria-label', m.is_read ? '标为未读' : '标为已读');
  read.title = read.getAttribute('aria-label');
  read.append(mailActionIcon(m.is_read ? 'unread' : 'read'));
  read.onclick = () => call('/api/mail', {
    id: m.id,
    action: m.is_read ? 'unread' : 'read'
  });
  let remove = element('button', '', 'mail-icon-action');
  remove.setAttribute('aria-label', '删除');
  remove.title = '删除';
  remove.append(mailActionIcon('delete'));
  remove.onclick = () => deleteMails([m.id]);
  actions.append(read, remove);
  top.append(actions);
  card.append(heading);
  let a = element('div', '', 'mail-detail'),
    v = m.result ? JSON.parse(m.result) : null;
  if (v) {
    a.append(element('h4', '智能摘要', 'summary-heading'), element('p', value(v.summary), 'summary-text'));
    let events = (v.events || []).map((event, index) => ({
        event,
        index
      })).filter(({
        event
      }) => (event.kind === '活动' || event.kind === '截止') && typeof event.start === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(event.start)),
      hasItems = events.length;
    if (hasItems) a.append(element('hr', '', 'todo-divider'), element('h4', '待处理事项', 'summary-heading todo-heading'));
    let overflow = events.length > 3 ? element('details', '', 'event-overflow') : null;
    if (overflow) overflow.append(element('summary', '展开其余 ' + (events.length - 3) + ' 项'));
    for (let [visibleIndex, item] of events.entries()) {
      let i = item.index,
        event = mailEventForDisplay(d, m, i, item.event, written),
        row = element('div', '', 'event-row'),
        isDeadline = event.kind === '截止';
      let itemAction = eventAction(event, v);
      let copy = eventContent(event, itemAction, event.location || (events.length === 1 && v.location && v.location !== '未说明' ? v.location : '待确认'));
      row.append(copy);
      let target = eventTarget(d, m.id, i),
        saved = written.get(target.id + ':' + target.index);
      if (isDeadline) {
        let pin = d.pins.find(p => p.mail_id === target.id && p.event_index === target.index && ['active', 'completed'].includes(p.state));
        let b = element('button', pin ? '取消加入截止事项' : '加入截止事项', 'secondary');
        b.onclick = () => pin ? call('/api/pin', {
          id: target.id,
          index: target.index,
          action: 'remove'
        }) : joinEvent({
          id: m.id,
          index: i
        }, data => call('/api/pin', {
          ...data,
          action: 'pin'
        }));
        let controls = element('div', '', 'event-row-controls');
        controls.append(b);
        row.append(controls);
      } else {
        if (saved && saved.status === 'subscribed') {
          let cancel = element('button', '取消同步日历', 'secondary');
          cancel.onclick = () => call('/api/calendar/cancel', {
            id: target.id,
            index: target.index
          });
          row.append(cancel);
        } else {
          let b = element('button', '加入日程安排', 'secondary task');
          b.disabled = d.status.busy;
          b.onclick = () => addSchedule(m, event, i);
          row.append(b);
        }
      }
      (visibleIndex < 3 ? a : overflow).append(row);
    }
    if (overflow) a.append(overflow);
    if (!Object.hasOwn(v, 'events')) {
      let b = element('button', '提取日程与截止日期', 'secondary task');
      b.disabled = d.status.busy;
      b.onclick = () => call('/api/events/extract', {
        id: m.id
      });
      a.append(b);
    }
  } else {
    if (m.analysis_error) {
      a.append(element('p', m.analysis_error, 'meta'));
      a.append(element('p', d.status.auto ? '后续检查会自动重试；也可以立即重试。' : '下次点击“立即检查”会重试；也可以单独重试。', 'meta'));
    }
    let b = element('button', m.analysis_error ? '重试分析' : '分析邮件', 'task');
    b.disabled = d.status.busy;
    b.onclick = () => call('/api/analyze', {
      id: m.id
    });
    a.append(b);
  }
  if (mailReadingId !== m.id) { mailReadingId = m.id; mailReadingMode = 'summary'; }
  const tabs = element('nav', '', 'mail-reading-tabs');
  tabs.setAttribute('aria-label', '阅读模式');
  const source = previousSource?.dataset.mailId === String(m.id) ? previousSource : element('div', '', 'inline-mail-source');
  source.dataset.mailId = m.id;
  for (const [mode, label] of [['summary', '摘要与事项'], ['original', '原邮件']]) {
    const tab = element('button', label, mode === mailReadingMode ? 'active' : '');
    tab.setAttribute('aria-pressed', String(mode === mailReadingMode));
    tab.onclick = () => { mailReadingMode = mode; renderMailDetail(m, d, written); };
    tabs.append(tab);
  }
  a.hidden = mailReadingMode !== 'summary';
  source.hidden = mailReadingMode !== 'original';
  card.append(tabs, a, source);
  pane.append(card);
  if (mailReadingMode === 'original' && !source.childNodes.length) openSource(m, source);

}
function visibleMails(d) {
  return d.mails.filter(m => matchesMailSearch(m) && (selected === '全部' || m.category === selected) && (selected !== '课程与教学' || matchesCourse(m, selectedCourse)));
}
function selectMailInList(id, index, shift, visible, checked = null) {
  if (shift && lastSelectedMailIndex !== null && checked !== false) {
    let start = Math.min(lastSelectedMailIndex, index),
      end = Math.max(lastSelectedMailIndex, index);
    for (let i = start; i <= end; i++) selectedMailIds.add(visible[i].id);
  } else if (typeof checked === 'boolean') {
    if (checked) selectedMailIds.add(id);else selectedMailIds.delete(id);
  } else if (selectedMailIds.has(id)) selectedMailIds.delete(id);else selectedMailIds.add(id);
  lastSelectedMailIndex = index;
  render();
}
async function bulkMailAction(action) {
  const ids = [...selectedMailIds];
  if (!ids.length) return;
  if (action === 'delete') return deleteMails(ids);
  if (await call('/api/mail/batch', {
    ids,
    action
  })) {
    selectedMailIds.clear();
    lastSelectedMailIndex = null;
    render();
    eventActionFeedback(`${action === 'read' ? '已标为已读' : '已标为未读'}（${ids.length} 封）`);
  }
}
async function markFilteredMailRead() {
  closeMailSettingsMenu();
  if (!state) return;
  let ids = visibleMails(state).filter(m => !m.is_read).map(m => m.id);
  if (!ids.length) {
    eventActionFeedback('当前筛选邮件均已读。');
    return;
  }
  if (!confirm(`将当前筛选的 ${ids.length} 封未读邮件标为已读？`)) return;
  if (await call('/api/mail/batch', {
    ids,
    action: 'read'
  })) eventActionFeedback(`已将 ${ids.length} 封邮件标为已读`);
}
function closeMailSettingsMenu() {
  $('mail-settings-menu').hidden = true;
  $('mail-settings-toggle').setAttribute('aria-expanded', 'false');
  $('mail-check-submenu').hidden = true;
  $('mail-check-toggle').setAttribute('aria-expanded', 'false');
}
function countLabel(count) {
  let label = element('span', '(' + count + ')', 'filter-count');
  label.setAttribute('aria-hidden', 'true');
  return label;
}
function mailListTitle(m) {
  return m.display_title || displaySubject(m.subject);
}
function matchesMailSearch(m) {
  if (!mailSearchQuery.trim()) return true;
  if (mailSearchIds !== null && mailSearchResolvedQuery === mailSearchQuery) return mailSearchIds.has(m.id);
  // Older complete snapshots and immediate typing feedback can still match locally.
  const words = mailSearchQuery.normalize('NFKC').toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
  const text = [m.display_title, m.subject, m.sender, m.body, m.source_body];
  try {
    const collect = value => {
      if (typeof value === 'string') text.push(value);else if (Array.isArray(value)) value.forEach(collect);else if (value && typeof value === 'object') Object.values(value).forEach(collect);
    };
    collect(typeof m.result === 'string' ? JSON.parse(m.result) : m.result);
  } catch {}
  const haystack = text.filter(Boolean).join('\n').normalize('NFKC').toLocaleLowerCase();
  return words.every(word => haystack.includes(word));
}
function setMailSearch(value) {
  mailSearchRequest++;
  mailSearchQuery = value;
  selected = '全部';
  selectedCourse = '全部课程';
  lastSelectedMailIndex = null;
  mailSearchIds = null;
  mailSearchResolvedQuery = '';
  mailSearchError = '';
  mailSearchPending = !!value.trim();
  clearTimeout(mailSearchTimer);
  if (mailSearchPending) mailSearchTimer = setTimeout(resolveMailSearch, 180);
  render();
}
function render() {
  if (!state) return;
  if (typeof requestAnimationFrame === 'function') requestAnimationFrame(updateMailWorkspaceHeight);
  let d = state;
  $('filters').replaceChildren();
  const categorySelect = element('select');
  categorySelect.setAttribute('aria-label', '邮件分类');
  for (const cat of ['全部', ...categories]) {
    const option = element('option', cat === '全部' ? '全部邮件' : cat);
    option.value = cat;
    categorySelect.append(option);
  }
  categorySelect.value = selected;
  categorySelect.onchange = () => { selected = categorySelect.value; selectedCourse = '全部课程'; render(); };
  const count = d.mails.filter(m => matchesMailSearch(m) && (selected === '全部' || m.category === selected) && (selected !== '课程与教学' || matchesCourse(m, selectedCourse))).length;
  $('filters').append(categorySelect, element('span', count + ' 封', 'mail-filter-total'));
  renderImportant(d);
  renderCourses(d);
  const listScroll = $('mails').scrollTop;
  $('mails').replaceChildren();
  let mails = d.mails.filter(m => matchesMailSearch(m) && (selected === '全部' || m.category === selected) && (selected !== '课程与教学' || matchesCourse(m, selectedCourse)));
  let searching = !!mailSearchQuery.trim();
  $('mail-search-clear').hidden = !mailSearchQuery;
  $('mail-search-status').hidden = !searching;
  $('mail-search-status').textContent = (mailSearchPending ? '正在搜索… ' : mailSearchError ? mailSearchError + ' · ' : '') + '找到 ' + mails.length + ' 封邮件' + (selected === '全部' ? '' : '（' + selected + '）') + '；点击结果查看，按回车打开第一封。';
  if (!mails.length) {
    $('mails').append(element('section', searching ? mailSearchPending ? '正在搜索邮件…' : mailSearchError || '没有匹配的邮件，请更换关键词或分类' : '暂无邮件'));
    activeMailId = null;
    renderMailDetail(null, d, new Map());
    return;
  }
  if (!mails.some(m => m.id === activeMailId)) activeMailId = mails[0].id;
  let written = new Map((d.calendarEvents || []).map(x => [x.mail_id + ':' + x.event_index, x]));
  const filterKey = [selected, selectedCourse, mailSearchQuery].join('|');
  if (filterKey !== mailRenderFilter) {
    mailRenderFilter = filterKey;
    mailRenderLimit = 50;
    lastSelectedMailIndex = null;
  }
  const activeIndex = mails.findIndex(m => m.id === activeMailId);
  if (activeIndex >= mailRenderLimit) mailRenderLimit = Math.ceil((activeIndex + 1) / 50) * 50;
  for (let [index, m] of mails.slice(0, mailRenderLimit).entries()) {
    let row = element('article', '', 'mail-list-item' + (typeof mailSelectionMode !== 'undefined' && mailSelectionMode ? ' multi-select-mode' : '') + (m.is_read ? '' : ' unread') + (!(typeof mailSelectionMode !== 'undefined' && mailSelectionMode) && m.id === activeMailId ? ' selected' : '') + (typeof selectedMailIds !== 'undefined' && selectedMailIds.has(m.id) ? ' multi-selected' : ''));
    row.id = 'mail-' + m.id;
    row.tabIndex = 0;
    row.setAttribute('role', typeof mailSelectionMode !== 'undefined' && mailSelectionMode ? 'group' : 'button');
    row.setAttribute('aria-current', String(!(typeof mailSelectionMode !== 'undefined' && mailSelectionMode) && m.id === activeMailId));
    row.title = displaySubject(m.subject);
    row.setAttribute('aria-label', m.category + '，' + displaySubject(m.subject) + '，' + mailDateLabel(m));
    if (typeof mailSelectionMode !== 'undefined' && mailSelectionMode) {
      let checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.className = 'mail-select-checkbox';
      checkbox.checked = selectedMailIds.has(m.id);
      checkbox.setAttribute('aria-label', '选择邮件：' + displaySubject(m.subject));
      checkbox.onclick = e => {
        e.stopPropagation();
        checkbox.dataset.shift = String(e.shiftKey);
      };
      checkbox.onchange = e => {
        e.stopPropagation();
        selectMailInList(m.id, index, checkbox.dataset.shift === 'true', mails, checkbox.checked);
      };
      checkbox.onkeydown = e => e.stopPropagation();
      row.append(checkbox);
    }
    let content = element('div', '', 'mail-list-content');
    const categoryRow = element('div', '', 'mail-list-category-row');
    if (row.querySelector('input')) categoryRow.append(row.querySelector('input'));
    categoryRow.append(element('span', m.category, 'mail-list-category'), element('time', mailListDateLabel(m), 'mail-list-date'));
    content.append(categoryRow, element('div', mailListTitle(m), 'mail-list-title'));
    row.append(content);
    let selectMail = e => {
      if (typeof mailSelectionMode !== 'undefined' && mailSelectionMode) {
        selectMailInList(m.id, index, e?.shiftKey, mails);
        return;
      }
      activeMailId = m.id;
      if (!m.is_read) call('/api/mail', {
        id: m.id,
        action: 'read'
      });
      render();
      $('mail-detail-pane').scrollTop = 0;
    };
    row.onclick = selectMail;
    row.onkeydown = e => {
      if ((e.key === 'Enter' || e.key === ' ') && e.target === row) {
        e.preventDefault();
        selectMail(e);
      }
    };
    $('mails').append(row);
  }
  if (mails.length > mailRenderLimit) {
    const more = element('button', '加载更多（还有 ' + (mails.length - mailRenderLimit) + ' 封）', 'secondary mail-load-more');
    more.onclick = () => {
      const scroll = $('mails').scrollTop;
      mailRenderLimit += 50;
      render();
      $('mails').scrollTop = scroll;
    };
    $('mails').append(more);
  }
  $('mails').scrollTop = listScroll;
  renderMailDetail(mails.find(m => m.id === activeMailId), d, written);
}
function updateMailWorkspaceHeight() {
  let workspace = document.querySelector('.mail-workspace');
  if (!workspace || $('mail-page').hidden || window.innerWidth <= 650) return;
  const bottom = 12;
  let top = Math.max(12, workspace.getBoundingClientRect().top);
  workspace.style.setProperty('--mail-reading-height', Math.max(160, window.innerHeight - top - bottom) + 'px');
}
function compactMailStatus(status) {
  if (status.phase === 'checking') return '正在检查新邮件…';
  if (status.phase === 'analyzing') return '正在分析 ' + (status.completed || 0) + '/' + (status.total || 0);
  if (status.busy) return '正在处理…';
  if (status.phase === 'complete') {
    if (status.kind !== 'check') return status.message || '';
    let text = status.added || status.success ? '新增 ' + (status.added || 0) + ' 封，已分析 ' + (status.success || 0) + ' 封' : '没有新邮件';
    if (status.failed) text += '；' + status.failed + ' 封分析失败，将自动重试';
    if (status.deferred) text += '；' + status.deferred + ' 封等待重试';
    return text;
  }
  return status.phase === 'error' ? status.message || '操作未完成，请重试。' : '';
}
function renderMailControls(d) {
  $('auto').setAttribute('aria-checked', String(!!d.status.auto));
  $('auto').setAttribute('aria-label', d.status.auto ? '关闭自动检查' : '开启自动检查');
  const ready = !!(d.ready?.mail && d.ready?.ai);
  $('setup-link').hidden = ready;
  $('header-mail-feedback').hidden = ready || $('mail-page').hidden;
  const message = ready ? compactMailStatus(d.status) : '请先连接邮箱和 AI 服务';
  $('status').hidden = true;
  $('status').textContent = message;
  const persistent = persistentMailStatus(d);
  $('mail-sync-status').textContent = persistent.text;
  $('mail-sync-status').className = 'mail-sync-status' + (persistent.attention ? ' attention' : '');
  $('mail-sync-status').title = d.status.sync_message || d.status.message || '';
  if (manualMailCheck && !d.status.busy && d.status.phase === 'complete' && d.status.kind === 'check') {
    eventActionFeedback(message || '检查完成');
    manualMailCheck = false;
  } else if (d.status.phase === 'error' && manualMailCheck) {
    eventActionFeedback(message);
    manualMailCheck = false;
  }
}
async function deleteMails(ids) {
  if (!ids.length) return;
  if (!confirm(ids.length === 1 ? '从邮件助手删除这封邮件？已保存的事项和原邮箱中的邮件会保留' : `从邮件助手删除选中的 ${ids.length} 封邮件？已保存的事项和原邮箱中的邮件会保留`)) return;
  const snapshots = state ? state.mails.filter(m => ids.includes(m.id)) : [];
  if (await mutateMailDeletion(ids, 'delete')) {
    selectedMailIds.clear();
    lastSelectedMailIndex = null;
    render();
    showDeleteUndo(ids, snapshots);
  }
}
function showDeleteUndo(ids, snapshots = []) {
  const box = $('mail-delete-feedback');
  clearTimeout(deleteUndoTimer);
  box.replaceChildren(element('span', `已删除 ${ids.length} 封邮件`));
  const undo = element('button', '撤销', 'text-button');
  undo.type = 'button';
  undo.onclick = async () => {
    clearTimeout(deleteUndoTimer);
    undo.disabled = true;
    if (await mutateMailDeletion(ids, 'restore', snapshots)) {
      box.hidden = true;
      eventActionFeedback('邮件已恢复');
    } else {
      undo.disabled = false;
    }
  };
  box.append(undo);
  box.hidden = false;
  deleteUndoTimer = setTimeout(() => {
    box.hidden = true;
  }, 15000);
}
async function resolveMailSearch() {
  const query = mailSearchQuery;
  const request = ++mailSearchRequest;
  if (!query.trim()) return;
  mailSearchPending = true;
  try {
    const response = await fetch('/api/mail/search?q=' + encodeURIComponent(query), {
      headers: {
        'X-Token': token
      }
    });
    const data = await response.json();
    if (!response.ok) throw Error(data.error || '搜索失败，请重试');
    if (request !== mailSearchRequest || query !== mailSearchQuery) return;
    mailSearchIds = new Set(data.ids);
    mailSearchResolvedQuery = query;
    mailSearchError = '';
  } catch (error) {
    if (request !== mailSearchRequest || query !== mailSearchQuery) return;
    mailSearchError = '搜索暂不可用，请重试';
  } finally {
    if (request === mailSearchRequest && query === mailSearchQuery) {
      mailSearchPending = false;
      render();
    }
  }
}
function persistentMailStatus(d) {
  const status = d.status || {};
  if (!(d.ready?.mail && d.ready?.ai)) return {
    text: '请先连接邮箱和 AI 服务',
    attention: true
  };
  if (status.sync_state === 'paused') return {
    text: cleanFeedbackText(status.sync_message || '邮箱授权已失效，请重新连接'),
    attention: true
  };
  if (status.sync_state === 'retrying') return {
    text: cleanFeedbackText(status.sync_message || '连接中断，正在重试'),
    attention: true
  };
  if (status.busy) return {
    text: compactMailStatus(status),
    attention: false
  };
  const parts = [];
  if (status.last_sync_at) {
    const date = new Date(Number(status.last_sync_at) * 1000);
    parts.push('已更新于 ' + date.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    }));
  } else parts.push('尚未检查邮件');
  const waiting = Math.max(0, (d.pendingCount || 0) - (d.failedCount || 0));
  if (waiting) parts.push(waiting + ' 封待分析');
  if (d.failedCount) parts.push(d.failedCount + ' 封分析失败');
  if (!status.auto) parts.push('自动检查已关闭');
  if (status.phase === 'error') parts.push(cleanFeedbackText(status.message || '检查未完成'));
  return {
    text: parts.join(' · '),
    attention: !!d.failedCount || status.phase === 'error'
  };
}
function initMailSearch() {
  $('mail-search-input').oninput = e => setMailSearch(e.target.value);
  $('mail-search-input').onkeydown = e => {
    if (e.key === 'Enter') {
      e.preventDefault();
      let row = $('mails').children[0];
      if (row?.onclick) {
        row.onclick();
        $('mails').children[0]?.focus();
        $('mail-detail-pane').scrollTop = 0;
      }
    }
  };
  $('mail-search-clear').onclick = () => {
    $('mail-search-input').value = '';
    setMailSearch('');
    $('mail-search-input').focus();
  };
}

// A successful delete must remain undoable even when its subsequent refresh fails.
async function mutateMailDeletion(ids, action, snapshots = []) {
  try {
    const response = await fetch('/api/mail/batch', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Token': token
      },
      body: JSON.stringify({
        ids,
        action
      })
    });
    const result = await response.json();
    if (!response.ok) throw Error(result.error || '操作未完成');
    const affected = new Set(ids);
    if (state && action === 'delete') {
      const removed = state.mails.filter(m => affected.has(m.id)).map(m => ({
        ...m,
        is_deleted: true
      }));
      state.eventSourceMails = [...(state.eventSourceMails || []).filter(m => !affected.has(m.id)), ...removed];
      state.mails = state.mails.filter(m => !affected.has(m.id));
    } else if (state && action === 'restore') {
      const sources = new Map([...snapshots, ...(state.eventSourceMails || [])].map(m => [m.id, m]));
      const restored = [...sources.values()].filter(m => affected.has(m.id)).map(m => ({
        ...m,
        is_deleted: false
      }));
      const existing = new Set(state.mails.map(m => m.id));
      state.mails.push(...restored.filter(m => !existing.has(m.id)));
      state.mails.sort((a, b) => new Date(b.sent_date || b.date) - new Date(a.sent_date || a.date));
      state.eventSourceMails = (state.eventSourceMails || []).filter(m => !affected.has(m.id));
    }
    const refreshed = await refresh();
    if (!refreshed) render();
    return true;
  } catch (error) {
    notify(error.message);
    return false;
  }
}

function mailSenderLabel(m) {
  const sender = String(m.sender || '').trim();
  const name = sender.match(/^([^<]+)\s*</)?.[1]?.trim().replace(/^"|"$/g, '');
  return name || sender || '发件人未提供';
}
function mailListDateLabel(m) {
  const date = new Date(m.sent_date || m.date), now = new Date();
  if (Number.isNaN(date.getTime())) return m.sent_date || m.date || '';
  if (date.toDateString() === now.toDateString()) return date.toLocaleTimeString('zh-CN', {hour:'2-digit', minute:'2-digit', hour12:false});
  const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return '昨天';
  return date.toLocaleDateString('zh-CN', {month:'2-digit', day:'2-digit', ...(date.getFullYear() !== now.getFullYear() ? {year:'numeric'} : {})});
}
