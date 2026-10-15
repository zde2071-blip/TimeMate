// Saved deadlines, calendar events and explicit source-mail links.

function formatEventTime(start, end, allDay) {
  let begin = String(start || ''),
    finish = String(end || '');
  if (!begin) return '时间待确认';
  if (allDay) {
    let first = begin.slice(0, 10),
      last = finish.slice(0, 10);
    if (last > first && finish.slice(11, 16) === '00:00') {
      let date = new Date(last + 'T00:00:00Z');
      date.setUTCDate(date.getUTCDate() - 1);
      last = date.toISOString().slice(0, 10);
    }
    return first + (last && last > first ? '–' + last : '') + '（全天）';
  }
  let first = begin.slice(0, 16).replace('T', ' ');
  if (!finish) return first + ' · 结束时间待补充';
  return first + '–' + (finish.slice(0, 10) === begin.slice(0, 10) ? finish.slice(11, 16) : finish.slice(0, 16).replace('T', ' '));
}
function eventContent(event, action, locationFallback = '待确认', deadlineReminder = null, titleControl = null) {
  let copy = element('div', '', 'event-copy'),
    title = element('strong', titleControl ? '' : event.title || '事项');
  if (titleControl) title.append(titleControl);
  if (deadlineReminder) {
    let badge = element('span', deadlineReminder.label, 'deadline-badge');
    badge.style.cssText = 'display:inline-flex;vertical-align:middle;margin-left:9px;padding:2px 8px;border-radius:999px;font-size:12px;line-height:1.5;font-weight:600;white-space:nowrap;background:' + deadlineReminder.background + ';color:' + deadlineReminder.color;
    title.append(badge);
  }
  copy.append(title);
  if (action && action !== event.title) copy.append(element('p', '待办：' + action, 'meta'));
  if (event.kind === '截止') copy.append(element('p', '截止时间：' + (event.allDay ? String(event.start || '').slice(0, 10) : String(event.start || '').slice(0, 16).replace('T', ' ')), 'meta'));else copy.append(element('p', '时间：' + formatEventTime(event.start, event.end, event.allDay), 'meta'));
  let location = event.location || locationFallback;
  if (location) copy.append(element('p', '地点：' + location, 'meta'));
  return copy;
}
function eventTarget(d, id, index) {
  let link = (d?.eventLinks || []).find(x => x.mail_id === id && x.event_index === index);
  return link ? {
    id: link.target_mail_id,
    index: link.target_index
  } : {
    id,
    index
  };
}
function eventOverrideData(d, id, index) {
  ({
    id,
    index
  } = eventTarget(d, id, index));
  let row = (d?.eventOverrides || []).find(x => x.mail_id === id && x.event_index === index);
  if (!row) return {
    fields: {},
    state: 'active'
  };
  try {
    return {
      fields: typeof row.fields === 'string' ? JSON.parse(row.fields || '{}') : row.fields || {},
      state: row.state || 'active'
    };
  } catch {
    return {
      fields: {},
      state: row.state || 'active'
    };
  }
}
function applyEventOverride(d, id, index, event) {
  return {
    ...event,
    ...eventOverrideData(d, id, index).fields
  };
}
function mailEventForDisplay(d, m, index, event, written) {
  let target = eventTarget(d, m.id, index),
    source = allEventMails(d).find(x => x.id === target.id);
  if (source?.result && (target.id !== m.id || target.index !== index)) {
    try {
      event = JSON.parse(source.result).events[target.index] || event;
    } catch {}
  }
  let base = {
      ...event
    },
    saved = written.get(target.id + ':' + target.index);
  if (event.kind === '活动' && saved && saved.status === 'subscribed') {
    try {
      let detail = typeof saved.detail === 'string' ? JSON.parse(saved.detail || '{}') : saved.detail || {};
      base = {
        ...base,
        title: detail.title || base.title,
        start: detail.start || base.start,
        end: detail.end || base.end,
        location: detail.location ?? base.location,
        allDay: detail.allDay ?? base.allDay
      };
    } catch {}
  }
  return applyEventOverride(d, target.id, target.index, base);
}
function editEventMenu(item) {
  let menu = element('details', '', 'event-manage'),
    summary = element('summary', '编辑'),
    options = element('div', '', 'event-manage-options');
  menu.append(summary);
  let edit = element('button', '修改信息', 'secondary');
  edit.type = 'button';
  edit.onclick = () => {
    menu.open = false;
    openEventEditor(item);
  };
  options.append(edit);
  if (item.kind === 'deadline') {
    let completed = item.state === 'completed',
      toggle = element('button', completed ? '恢复' : '标记完成', 'secondary');
    toggle.type = 'button';
    toggle.onclick = () => performEventAction(menu, item, completed ? 'restore' : 'complete');
    options.append(toggle);
  }
  let remove = element('button', '移除', 'secondary');
  remove.type = 'button';
  remove.onclick = () => performEventAction(menu, item, 'remove');
  options.append(remove);
  menu.append(options);
  menu.addEventListener('toggle', () => {
    if (menu.open) closeEventMenus(menu);
  });
  return menu;
}
function eventActionFeedback(text) {
  let box = document.getElementById('event-action-feedback');
  if (!box) {
    box = element('div', '', 'event-action-feedback');
    box.id = 'event-action-feedback';
    box.setAttribute('role', 'status');
    box.setAttribute('aria-live', 'polite');
    document.body.append(box);
  }
  box.textContent = cleanFeedbackText(text);
  box.hidden = false;
  clearTimeout(eventFeedbackTimer);
  eventFeedbackTimer = setTimeout(() => {
    box.hidden = true;
  }, 3500);
}
async function performEventAction(menu, item, action) {
  menu.open = false;
  if (await call('/api/event/manage', {
    id: item.mail_id,
    index: item.index,
    action
  })) eventActionFeedback({
    complete: '已标记完成',
    remove: '已移除',
    restore: '已恢复'
  }[action]);
}
function closeEventMenus(except = null) {
  document.querySelectorAll('.event-manage[open]').forEach(menu => {
    if (menu !== except) menu.open = false;
  });
}
function openEventEditor(item) {
  let dialog = $('event-edit-dialog'),
    form = $('event-edit-form'),
    event = item.event;
  form.replaceChildren();
  let message = element('p', '', 'edit-event-message');
  message.hidden = true;
  let [titleWrap, title] = field('事项主题', event.title);
  title.maxLength = 160;
  let actionWrap = element('label', '待办'),
    actionArea = document.createElement('textarea');
  actionArea.value = item.action || event.action || '';
  actionArea.maxLength = 1000;
  actionWrap.append(actionArea);
  let allDay = event.allDay === true;
  let dayLabel = element('label', '', 'edit-all-day'),
    dayInput = document.createElement('input');
  dayInput.type = 'checkbox';
  dayInput.checked = allDay;
  dayLabel.append(dayInput, document.createTextNode(' 全天'));
  let startWrap, start, endWrap, end;
  [startWrap, start] = field(item.kind === 'deadline' ? '截止时间' : '开始时间', '');
  [endWrap, end] = field('结束时间', '');
  let selectedDuration = null,
    durationShortcuts = element('div', '', 'calendar-duration-shortcuts');
  for (let [label, minutes] of [['+30分钟', 30], ['+1小时', 60], ['+2小时', 120]]) {
    let button = element('button', label, 'secondary');
    button.type = 'button';
    button.onclick = () => {
      selectedDuration = minutes;
      end.value = addDurationToDateTime(start.value, minutes);
    };
    durationShortcuts.append(button);
  }
  let locationWrap, location;
  [locationWrap, location] = field('地点', event.location || '');
  location.maxLength = 300;
  function editValue(value, day) {
    if (!value) return '';
    if (day) return value.slice(0, 10);
    return value.slice(0, 16);
  }
  function inclusiveEnd(value, day) {
    if (!day || !value) return editValue(value, false);
    let d = value.slice(0, 10);
    if (value.slice(11, 16) === '00:00') {
      let date = new Date(d + 'T00:00:00');
      date.setDate(date.getDate() - 1);
      return localDateKey(date);
    }
    return d;
  }
  start.value = editValue(event.start, allDay);
  if (item.kind === 'schedule') end.value = inclusiveEnd(event.end, allDay);
  start.type = allDay ? 'date' : 'datetime-local';
  if (item.kind === 'schedule') end.type = allDay ? 'date' : 'datetime-local';
  if (item.kind === 'schedule') {
    let endGroup = element('div', '', 'calendar-end-group');
    endGroup.append(endWrap, durationShortcuts);
    form.append(titleWrap, actionWrap, startWrap, endGroup, dayLabel);
  } else form.append(titleWrap, actionWrap, startWrap);
  if (item.kind === 'schedule') {
    durationShortcuts.hidden = allDay;
    let updateShortcuts = () => {
      for (let button of durationShortcuts.children) button.disabled = allDay || !start.value;
    };
    start.oninput = () => {
      updateShortcuts();
      if (selectedDuration !== null) end.value = addDurationToDateTime(start.value, selectedDuration);
    };
    end.oninput = () => {
      selectedDuration = null;
    };
    updateShortcuts();
    dayInput.onchange = () => {
      let was = allDay;
      allDay = dayInput.checked;
      selectedDuration = null;
      start.value = editValue(start.value + (was ? 'T00:00' : ''), allDay);
      if (was && !allDay && end.value) {
        let next = new Date(end.value + 'T00:00:00');
        next.setDate(next.getDate() + 1);
        end.value = localDateKey(next) + 'T00:00';
      } else end.value = editValue(end.value, allDay);
      start.type = allDay ? 'date' : 'datetime-local';
      end.type = allDay ? 'date' : 'datetime-local';
      durationShortcuts.hidden = allDay;
      updateShortcuts();
    };
  }
  form.append(locationWrap, message);
  let footer = element('div', '', 'calendar-form-actions'),
    cancel = element('button', '取消', 'secondary'),
    save = element('button', '保存修改');
  cancel.type = save.type = 'button';
  cancel.onclick = () => dialog.close();
  save.onclick = async () => {
    let startValue = start.value,
      endValue = item.kind === 'schedule' ? end.value : '';
    if (allDay) {
      startValue = startValue + 'T00:00';
      if (endValue) {
        let next = new Date(endValue + 'T00:00:00');
        next.setDate(next.getDate() + 1);
        endValue = localDateKey(next) + 'T00:00';
      }
    }
    let fields = {
      title: title.value,
      action: actionArea.value,
      start: startValue,
      end: endValue,
      location: location.value,
      allDay
    };
    save.disabled = true;
    let ok = await call('/api/event/manage', {
      id: item.mail_id,
      index: item.index,
      action: 'edit',
      fields
    });
    save.disabled = false;
    if (ok) dialog.close();
  };
  footer.append(cancel, save);
  form.append(footer);
  dialog.showModal();
}
async function joinEvent(data, submit) {
  try {
    const response = await fetch('/api/event/check', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Token': token
        },
        body: JSON.stringify(data)
      }),
      check = await response.json();
    if (!response.ok) throw Error(check.error);
    const candidates = check.candidates || [];
    const linked = (candidate, mode = 'link', selectedFields = []) => call('/api/event/link', {
      ...data,
      targetId: candidate.id,
      targetIndex: candidate.index,
      expected: candidate.event,
      mode,
      selectedFields
    });
    if (!candidates.length) return submit(data);
    if (candidates.length === 1 && candidates[0].exact) {
      const done = await linked(candidates[0]);
      if (done) {
        notify('已关联到已有事项，没有重复添加。');
        focusImportantEvent(candidates[0].id, candidates[0].index);
      }
      return done;
    }
    return await new Promise(resolve => {
      let dialog = $('event-join-dialog'),
        box = $('event-join-content');
      box.replaceChildren();
      box.append(element('p', '勾选要采用的新内容，未勾选的字段保持原样。', 'event-join-intro'));
      let saveError = element('p', '', 'event-join-error');
      saveError.hidden = true;
      saveError.setAttribute('role', 'alert');
      box.append(saveError);
      let controls = [],
        singleActions = [],
        busy = false;
      const finish = async (operation, target) => {
        if (busy) return;
        busy = true;
        saveError.hidden = true;
        for (let button of controls) button.disabled = true;
        try {
          if (await operation()) {
            dialog.close();
            if (target) focusImportantEvent(target.id, target.index);
            resolve(true);
          } else {
            saveError.textContent = $('notice').textContent || '保存失败，请重试。';
            saveError.hidden = false;
          }
        } catch (error) {
          saveError.textContent = error.message || '保存失败，请重试。';
          saveError.hidden = false;
        } finally {
          busy = false;
          for (let button of controls) button.disabled = false;
        }
      };
      const displayValue = (field, value) => {
        if (field === 'allDay') return value ? '全天' : '具体时间';
        if (!value) return '未填写';
        if (['start', 'end'].includes(field)) return String(value).replace('T', ' ').slice(0, 16);
        return String(value);
      };
      for (let [candidateIndex, candidate] of candidates.entries()) {
        let section = element('section', '', 'event-join-candidate');
        section.append(element('h3', candidate.event.title));
        if (candidate.confidence === 'uncertain') section.append(element('p', '主题相似，请确认是同一件事后再合并。', 'meta'));
        let checks = [];
        for (let change of candidate.changes) {
          let row = element('div', '', 'event-join-diff'),
            input = document.createElement('input'),
            body = element('div'),
            heading = element('div', '', 'event-join-field');
          input.type = 'checkbox';
          input.id = 'join-field-' + candidateIndex + '-' + change.field;
          input.checked = !change.edited;
          checks.push({
            input,
            field: change.field
          });
          let name = change.field === 'start' ? check.kind === '截止' ? '截止时间' : '开始时间' : change.field === 'allDay' ? '时间类型' : change.label,
            label = element('label', name);
          label.htmlFor = input.id;
          input.setAttribute('aria-label', '采用新邮件的' + name);
          heading.append(label);
          if (change.edited) heading.append(element('span', '你修改过，默认保留', 'event-join-edited'));
          body.append(heading);
          let values = element('div', '', 'event-join-values');
          for (let [title, value, cls] of [['当前内容', change.before, ''], ['新邮件内容', change.after, ' new']]) {
            let cell = element('div', '', 'event-join-value' + cls);
            cell.append(element('small', title), element('p', displayValue(change.field, value)));
            values.append(cell);
          }
          body.append(values);
          row.append(input, body);
          section.append(row);
        }
        if (!candidate.changes.length) section.append(element('p', '内容一致，合并后保留已有事项。', 'meta'));
        let actions = element('div', '', 'event-join-candidate-actions'),
          merge = element('button', candidate.changes.length ? '更新并合并' : '合并到已有事项');
        merge.type = 'button';
        const updateLabel = () => {
          if (candidate.changes.length) merge.textContent = checks.some(x => x.input.checked) ? '更新并合并' : '保留原始';
        };
        for (let {
          input
        } of checks) input.onchange = updateLabel;
        updateLabel();
        merge.onclick = () => {
          let fields = checks.filter(x => x.input.checked).map(x => x.field);
          finish(() => linked(candidate, fields.length ? 'update' : 'link', fields), candidate);
        };
        controls.push(merge);
        if (candidate.changes.length) {
          let keep = element('button', '保留原始', 'secondary');
          keep.type = 'button';
          keep.onclick = () => finish(() => linked(candidate), candidate);
          controls.push(keep);
          actions.append(keep);
        }
        actions.append(merge);
        if (candidates.length === 1) singleActions = [...actions.children];else section.append(actions);
        box.append(section);
      }
      let footer = element('div', '', 'calendar-form-actions'),
        cancel = element('button', '取消', 'secondary'),
        separate = element('button', '另建事项', 'secondary');
      cancel.onclick = () => {
        if (!busy) {
          dialog.close();
          resolve(false);
        }
      };
      separate.onclick = () => finish(() => submit({
        ...data,
        joinDecision: 'new'
      }));
      controls.push(cancel, separate);
      footer.append(cancel, separate, ...singleActions);
      box.append(footer);
      dialog.oncancel = event => {
        if (busy) event.preventDefault();else resolve(false);
      };
      dialog.showModal();
    });
  } catch (error) {
    notify(error.message);
    return false;
  }
}
function focusImportantEvent(id, index) {
  importantView = 'all';
  calendarSelected = '';
  renderImportant(state);
  showPage('important');
  requestAnimationFrame(() => {
    let card = $('important-' + id + '-' + index);
    if (!card) return;
    let folded = card.closest('details');
    if (folded) folded.open = true;
    card.scrollIntoView({
      behavior: 'smooth',
      block: 'center'
    });
    card.tabIndex = -1;
    card.focus({
      preventScroll: true
    });
  });
}
function addSchedule(m, event, index) {
  openCalendar(m, event, index);
}
function addDurationToDateTime(value, minutes) {
  if (!value) return '';
  let date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  date.setMinutes(date.getMinutes() + minutes);
  return date.getFullYear() + '-' + String(date.getMonth() + 1).padStart(2, '0') + '-' + String(date.getDate()).padStart(2, '0') + 'T' + String(date.getHours()).padStart(2, '0') + ':' + String(date.getMinutes()).padStart(2, '0');
}
function isVagueTimetableWeek(event) {
  let evidence = String(event.evidence || ''),
    title = String(event.title || ''),
    action = String(event.action || ''),
    allText = (evidence + ' ' + title + ' ' + action).toLowerCase(),
    start = new Date(event.start || ''),
    end = new Date(event.end || '');
  if (!event.allDay || Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return false;
  let span = (end - start) / 86400000;
  return span >= 2 && span <= 14 && /(week\s*\d*|this week|本周|第\s*\d+\s*周)/i.test(allText) && /(timetable|check your schedule|课表|查看.*安排|开始本周)/i.test(allText);
}
function openCalendar(m, event, index) {
  let box = $('calendar-form'),
    message = $('calendar-message');
  box.replaceChildren();
  message.textContent = '';
  message.hidden = true;
  let vagueWeek = isVagueTimetableWeek(event),
    allDay = event.allDay === true && !vagueWeek;
  let [tw, title] = field('标题', event.title),
    titleInput = title;
  tw.className = 'calendar-title-field';
  let timeGroup = element('fieldset', '', 'calendar-time-group'),
    timeHead = element('div', '', 'calendar-time-heading'),
    timeLabel = element('strong', '时间');
  let dayLabel = element('label', '全天', 'calendar-all-day');
  let day = document.createElement('input');
  day.type = 'checkbox';
  day.checked = allDay;
  dayLabel.append(day);
  timeHead.append(timeLabel, dayLabel);
  timeGroup.append(timeHead);
  let [sw, start] = field('开始', event.start ? allDay ? event.start.slice(0, 10) : event.start.slice(0, 16) : '', allDay ? 'date' : 'datetime-local'),
    [ew, end] = field('结束', event.end ? allDay ? (() => {
      let date = new Date(event.end);
      if (date.getHours() === 0 && date.getMinutes() === 0 && date > new Date(event.start)) date.setDate(date.getDate() - 1);
      return localDateKey(date);
    })() : event.end.slice(0, 16) : '', allDay ? 'date' : 'datetime-local');
  sw.className = 'calendar-time-field';
  ew.className = 'calendar-time-field';
  let durationShortcuts = element('div', '', 'calendar-duration-shortcuts');
  for (let [label, minutes] of [['+30分钟', 30], ['+1小时', 60], ['+2小时', 120]]) {
    let shortcut = element('button', label, 'secondary');
    shortcut.type = 'button';
    shortcut.disabled = allDay || !start.value;
    shortcut.onclick = () => {
      if (!start.value) {
        message.textContent = '请先填写开始时间。';
        message.hidden = false;
        return;
      }
      selectedDuration = minutes;
      end.value = addDurationToDateTime(start.value, minutes);
      message.hidden = true;
    };
    durationShortcuts.append(shortcut);
  }
  let endGroup = element('div', '', 'calendar-end-group');
  endGroup.append(ew, durationShortcuts);
  let timeFields = element('div', '', 'calendar-time-fields');
  timeFields.append(sw, endGroup);
  timeGroup.append(timeFields);
  let selectedDuration = null;
  let [lw, place] = field('地点', event.location === '地点待确认' ? '' : event.location);
  lw.className = 'calendar-location-field';
  let fields = element('div', '', 'calendar-fields');
  fields.append(tw, timeGroup, lw);
  box.append(fields, message);
  start.oninput = () => {
    for (let button of durationShortcuts.children) button.disabled = day.checked || !start.value;
    if (selectedDuration !== null) end.value = addDurationToDateTime(start.value, selectedDuration);
  };
  end.oninput = () => {
    selectedDuration = null;
  };
  day.onchange = () => {
    selectedDuration = null;
    let toDate = day.checked;
    for (let input of [start, end]) {
      if (toDate) {
        input.value = input.value.slice(0, 10);
        input.type = 'date';
      } else {
        let date = input.value.slice(0, 10);
        input.type = 'datetime-local';
        input.value = date ? date + 'T00:00' : '';
      }
    }
    for (let button of durationShortcuts.children) button.disabled = toDate || !start.value;
    durationShortcuts.hidden = toDate;
  };
  durationShortcuts.hidden = allDay;
  if (vagueWeek) {
    message.textContent = '邮件只提到教学周，未提供你的具体课次时间。请按个人课表填写。';
    message.hidden = false;
  }
  let footer = element('div', '', 'calendar-form-actions'),
    cancel = element('button', '取消', 'secondary');
  cancel.type = 'button';
  cancel.onclick = () => $('calendar-dialog').close();
  let b = element('button', calendarMethod === 'unset' ? '连接日历' : calendarMethod === 'ics' ? '确认并下载' : '确认添加');
  b.type = 'button';
  b.onclick = async () => {
    if (calendarMethod === 'unset') {
      chooseCalendar();
      return;
    }
    let startValue = start.value,
      endValue = end.value;
    if (day.checked) {
      if (!startValue || !endValue) {
        message.textContent = '请填写开始和结束日期。';
        message.hidden = false;
        return;
      }
      let exclusiveEnd = new Date(endValue + 'T00:00:00');
      exclusiveEnd.setDate(exclusiveEnd.getDate() + 1);
      startValue += 'T00:00';
      endValue = localDateKey(exclusiveEnd) + 'T00:00';
    }
    if (!titleInput.value.trim() || !startValue || !endValue || endValue <= startValue) {
      message.textContent = '请填写有效的标题和开始、结束时间。';
      message.hidden = false;
      return;
    }
    message.hidden = true;
    let data = {
      id: m.id,
      index,
      title: titleInput.value,
      start: startValue,
      end: endValue,
      location: place.value,
      action: event.action || '',
      allDay: day.checked,
      timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone
    };
    b.disabled = true;
    try {
      await joinEvent(data, async approved => {
        if (calendarMethod === 'ics') {
          await exportCalendar(approved);
          return true;
        }
        return call('/api/calendar/approve', approved);
      }).then(done => {
        if (done) $('calendar-dialog').close();
      });
    } finally {
      b.disabled = false;
    }
  };
  footer.append(cancel, b);
  box.append(footer);
  $('calendar-dialog').showModal();
}
function jumpMail(id) {
  let m = allEventMails(state).find(x => x.id === id);
  if (!m) return;
  if (m.is_deleted) {
    openSource(m);
    return;
  }
  mailSearchQuery = '';
  mailSearchIds = null;
  mailSearchResolvedQuery = '';
  mailSearchPending = false;
  $('mail-search-input').value = '';
  selected = m.category;
  selectedCourse = '全部课程';
  activeMailId = id;
  showPage('mail');
  render();
  let card = document.getElementById('mail-' + id);
  card?.scrollIntoView({
    behavior: 'smooth',
    block: 'nearest'
  });
  card?.classList.add('highlight');
}
function importantTime(pin, event, now = new Date()) {
  let start = new Date(pin.due),
    limit = new Date(start);
  if (event?.allDay) limit.setHours(23, 59, 59, 999);
  let ms = limit - now,
    days = Math.ceil(ms / 86400000),
    relative = ms < 0 ? event?.kind === '截止' ? '已过截止时间' : '已过活动时间' : ms < 3600000 ? '不足 1 小时' : ms < 86400000 ? '还剩 ' + Math.ceil(ms / 3600000) + ' 小时' : '还剩 ' + days + ' 天';
  let date = event?.allDay ? pin.due.slice(0, 10) : pin.due.slice(0, 16).replace('T', ' ');
  if (event?.kind === '截止') date += ' 截止';else if (event?.end && !event.allDay) date += ' – ' + event.end.slice(0, 16).replace('T', ' ');
  return {
    date,
    relative,
    expired: ms < 0
  };
}
function selectCalendarDate(key) {
  selectedDeadlineKey = '';
  calendarSelected = key;
  let [year, month] = key.split('-').map(Number);
  calendarMonth = new Date(year, month - 1, 1);
  renderImportant(state);
}
function calendarDayDifference(dateKey) {
  let [y, m, d] = dateKey.split('-').map(Number),
    now = new Date(),
    today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()),
    due = Date.UTC(y, m - 1, d);
  return Math.round((due - today) / 86400000);
}
function deadlineRemainingMs(item, now = new Date()) {
  let value = item?.event?.start || item?.start || '';
  if (!value) return NaN;
  let due = new Date(value);
  if (Number.isNaN(due.getTime())) return NaN;
  if (item.event?.allDay) due.setHours(23, 59, 59, 999);
  return due.getTime() - now.getTime();
}
function deadlineReminder(item, now = new Date()) {
  let remaining = deadlineRemainingMs(item, now);
  if (!Number.isFinite(remaining)) return null;
  if (remaining <= 0) return {
    label: '已截止',
    color: '#9f3d32',
    background: '#f7e8e5'
  };
  if (remaining <= 86400000) return {
    label: '1天内截止',
    color: '#a63f31',
    background: '#fae9e5'
  };
  if (remaining <= 3 * 86400000) return {
    label: '3天内截止',
    color: '#936014',
    background: '#fbf1dc'
  };
  if (remaining <= 7 * 86400000) return {
    label: '7天内截止',
    color: '#526b80',
    background: '#edf2f6'
  };
  return null;
}
function compareDeadlineItems(a, b, now = new Date()) {
  let da = deadlineRemainingMs(a, now),
    db = deadlineRemainingMs(b, now),
    pa = da <= 0,
    pb = db <= 0;
  if (pa !== pb) return pa ? 1 : -1;
  if (Number.isFinite(da) && Number.isFinite(db) && da !== db) return da - db;
  return String(a.start || a.event?.start || '').localeCompare(String(b.start || b.event?.start || ''));
}
function sortDeadlineItems(items, now = new Date()) {
  return [...items].sort((a, b) => compareDeadlineItems(a, b, now));
}
function renderImportantCard(item, d) {
  let row = element('article', '', 'calendar-entry ' + item.kind);
  row.id = 'important-' + item.mail_id + '-' + item.index;
  let titleControl = null;
  let sources = item.m ? [item.m, ...(d.eventLinks || []).filter(x => x.target_mail_id === item.mail_id && x.target_index === item.index).map(x => allEventMails(d).find(m => m.id === x.mail_id)).filter(Boolean)] : [];
  sources = [...new Map(sources.map(m => [m.id, m])).values()];
  if (sources.length) {
    let label = item.event.title || '事项';
    if (sources.length === 1) {
      titleControl = element('button', label, 'important-source-title');
      titleControl.type = 'button';
      const fromChat = sources[0].source === 'chat';
      titleControl.title = fromChat ? '查看来源对话' : '查看来源邮件';
      titleControl.setAttribute('aria-label', (item.event.title || '事项') + '，' + titleControl.title);
      titleControl.onclick = () => {
        if (fromChat) {
          showPage('chat');
          const conversationId = item.result?.conversationId || JSON.parse(sources[0].result || '{}').conversationId;
          if (conversationId) openChatConversation(conversationId);
        } else jumpMail(sources[0].id);
      };
    } else {
      titleControl = element('details', '', 'important-source-group');
      let summary = element('summary', label, 'important-source-title');
      summary.title = '选择来源邮件（' + sources.length + '封）';
      titleControl.append(summary);
      let options = element('div', '', 'important-source-options');
      for (let mail of sources) {
        let source = element('button', displaySubject(mail.subject) + ' · ' + mailDateLabel(mail), 'secondary');
        source.onclick = () => jumpMail(mail.id);
        options.append(source);
      }
      titleControl.append(options);
    }
    let sourceIcon = element('span', '', 'source-mail-icon');
    sourceIcon.setAttribute('aria-hidden', 'true');
    (sources.length === 1 ? titleControl : titleControl.children[0]).append(sourceIcon);
  }
  row.append(eventContent(item.event, item.action, item.kind === 'schedule' ? '待确认' : '', item.kind === 'deadline' && item.state !== 'completed' ? deadlineReminder(item) : null, titleControl));
  let actions = element('div', '', 'important-actions');
  actions.append(editEventMenu(item));
  row.append(actions);
  return row;
}
function moveCalendarMonth(step) {
  calendarMonth = new Date(calendarMonth.getFullYear(), calendarMonth.getMonth() + step, 1);
  calendarSelected = '';
  selectedDeadlineKey = '';
  renderImportant(state);
}
function goCalendarToday() {
  let now = new Date();
  calendarMonth = new Date(now.getFullYear(), now.getMonth(), 1);
  calendarSelected = calendarSelected === localDateKey(now) ? '' : localDateKey(now);
  selectedDeadlineKey = '';
  renderImportant(state);
}
function openCalendarMonthPicker() {
  let dialog = $('calendar-month-dialog'),
    form = $('calendar-month-form'),
    year = $('calendar-year-input'),
    month = $('calendar-month-input');
  year.value = calendarMonth.getFullYear();
  month.value = calendarMonth.getMonth() + 1;
  form.onsubmit = e => {
    e.preventDefault();
    let y = Number(year.value),
      m = Number(month.value);
    if (!Number.isInteger(y) || y < 1 || y > 9999 || !Number.isInteger(m) || m < 1 || m > 12) return;
    calendarMonth = new Date(0);
    calendarMonth.setFullYear(y, m - 1, 1);
    calendarMonth.setHours(0, 0, 0, 0);
    calendarSelected = '';
    selectedDeadlineKey = '';
    dialog.close();
    renderImportant(state);
  };
  dialog.showModal();
}
function renderMonthCalendar(items, completed = [], d) {
  let box = $('calendar-view'),
    listBox = $('important-list-view'),
    panel = element('section', '', 'calendar-month'),
    head = element('div', '', 'calendar-month-head'),
    title = element('button', calendarMonth.getFullYear() + '年' + (calendarMonth.getMonth() + 1) + '月', 'calendar-month-picker');
  title.type = 'button';
  title.setAttribute('aria-label', '选择年月');
  title.setAttribute('aria-haspopup', 'dialog');
  title.onclick = openCalendarMonthPicker;
  let chevrons = element('span', '', 'calendar-picker-chevrons');
  chevrons.setAttribute('aria-hidden', 'true');
  chevrons.append(element('span', '', 'picker-chevron-up'), element('span', '', 'picker-chevron-down'));
  title.append(chevrons);
  head.append(title);
  panel.append(head);
  let legend = element('div', '', 'calendar-legend');
  for (let [kind, label] of [['schedule', '日程'], ['deadline', '截止']]) {
    let entry = element('span', '', 'calendar-legend-entry'),
      icon = element('span', kind === 'deadline' ? '→' : '', 'calendar-day-marker ' + kind);
    icon.setAttribute('aria-hidden', 'true');
    entry.append(icon, element('span', label));
    legend.append(entry);
  }
  panel.append(legend);
  let grid = element('div', '', 'calendar-grid');
  grid.setAttribute('role', 'grid');
  for (let day of ['一', '二', '三', '四', '五', '六', '日']) {
    let label = element('div', day, 'calendar-weekday');
    label.setAttribute('role', 'columnheader');
    grid.append(label);
  }
  let monthStart = new Date(calendarMonth.getFullYear(), calendarMonth.getMonth(), 1),
    offset = (monthStart.getDay() + 6) % 7,
    days = new Date(calendarMonth.getFullYear(), calendarMonth.getMonth() + 1, 0).getDate(),
    todayKey = localDateKey(new Date()),
    byDate = new Map();
  for (let item of items) {
    let key = item.date;
    if (!key) continue;
    if (!byDate.has(key)) byDate.set(key, []);
    byDate.get(key).push(item);
  }
  for (let blank = 0; blank < offset; blank++) {
    let cell = element('div');
    cell.setAttribute('role', 'gridcell');
    grid.append(cell);
  }
  for (let day = 1; day <= days; day++) {
    let key = localDateKey(new Date(calendarMonth.getFullYear(), calendarMonth.getMonth(), day)),
      matches = byDate.get(key) || [],
      button = element('button', '', 'calendar-day' + (matches.length ? ' has-events' : '') + (key === calendarSelected ? ' selected' : '') + (key === todayKey ? ' today' : ''));
    button.setAttribute('role', 'gridcell');
    button.setAttribute('aria-pressed', String(key === calendarSelected));
    button.setAttribute('aria-label', key + (key === todayKey ? '，今天' : '') + (matches.length ? '，' + matches.length + '项事项' : ''));
    button.append(element('span', String(day), 'calendar-day-number'));
    let marks = element('span', '', 'calendar-day-markers');
    for (let kind of ['schedule', 'deadline']) {
      if (!matches.some(item => item.kind === kind)) continue;
      let mark = element('span', kind === 'deadline' ? '→' : '', 'calendar-day-marker ' + kind);
      mark.title = kind === 'deadline' ? '当天有截止事项' : '当天有日程安排';
      mark.setAttribute('aria-hidden', 'true');
      marks.append(mark);
    }
    button.append(marks);
    button.onclick = () => selectCalendarDate(key);
    grid.append(button);
  }
  panel.append(grid);
  let controls = element('div', '', 'calendar-month-nav');
  let previous = element('button', '', 'secondary'),
    today = element('button', '今天', 'secondary'),
    next = element('button', '', 'secondary');
  previous.append(element('span', '', 'month-nav-chevron previous'));
  next.append(element('span', '', 'month-nav-chevron next'));
  previous.setAttribute('aria-label', '上个月');
  next.setAttribute('aria-label', '下个月');
  previous.onclick = () => moveCalendarMonth(-1);
  next.onclick = () => moveCalendarMonth(1);
  today.onclick = goCalendarToday;
  today.setAttribute('aria-pressed', String(calendarSelected === todayKey));
  controls.append(previous, today, next);
  panel.append(controls);
  box.append(panel);
  let chosen = items.filter(item => !calendarSelected || item.date === calendarSelected).sort((a, b) => {
    if (a.kind !== b.kind) return importantView === 'deadline' ? 0 : a.kind === 'deadline' ? 1 : -1;
    if (a.kind === 'deadline') return compareDeadlineItems(a, b);
    let da = calendarDayDifference(a.date),
      db = calendarDayDifference(b.date);
    if (da >= 0 !== db >= 0) return da >= 0 ? -1 : 1;
    return (da >= 0 ? da - db : db - da) || String(a.start || '').localeCompare(String(b.start || ''));
  });
  let heading = importantView === 'schedule' ? '日程安排' : importantView === 'deadline' ? '截止事项' : '全部事项';
  let listHead = element('div', '', 'calendar-list-head');
  listHead.append(element('h3', (calendarSelected ? calendarSelected.replace(/-/g, ' / ') + ' · ' : '') + heading + '（' + chosen.length + '）', 'calendar-selected-title'));
  if (calendarSelected) {
    let reset = element('button', '查看全部', 'secondary');
    reset.onclick = () => {
      calendarSelected = '';
      renderImportant(state);
    };
    listHead.append(reset);
  }
  listBox.append(listHead);
  let list = element('div', '', 'calendar-day-events');
  if (!chosen.length) list.append(element('div', calendarSelected ? '当天暂无已加入的事项。' : '暂无已加入的事项。', 'calendar-empty'));
  for (let item of chosen) list.append(renderImportantCard(item, d));
  listBox.append(list);
  let shownCompleted = completed.filter(item => !calendarSelected || item.date === calendarSelected);
  if (shownCompleted.length) {
    let folded = element('details', '', 'calendar-completed');
    folded.append(element('summary', '已完成截止事项（' + shownCompleted.length + '）'));
    for (let item of shownCompleted) folded.append(renderImportantCard(item, d));
    listBox.append(folded);
  }
}
function setImportantView(view) {
  importantView = view;
  selectedDeadlineKey = '';
  renderImportant(state);
}
function renderImportant(d) {
  if (!d) return;
  for (let [id, view] of [['view-all', 'all'], ['view-schedule', 'schedule'], ['view-deadline', 'deadline']]) {
    $(id).className = importantView === view ? 'active' : 'secondary';
    $(id).setAttribute('aria-pressed', String(importantView === view));
  }
  $('calendar-view').replaceChildren();
  $('important-list-view').replaceChildren();
  let pins = [...(d.pins || [])].sort((a, b) => new Date(a.due) - new Date(b.due) || a.title.localeCompare(b.title));
  let items = [],
    completed = [];
  for (let item of d.calendarEvents || []) {
    if (item.status !== 'subscribed') continue;
    let detail = {};
    try {
      detail = typeof item.detail === 'string' ? JSON.parse(item.detail || '{}') : item.detail || {};
    } catch {}
    let m = allEventMails(d).find(x => x.id === item.mail_id),
      result = m && m.result ? JSON.parse(m.result) : {},
      event = result.events?.[item.event_index],
      start = detail.start || event?.start || '',
      date = start.slice(0, 10);
    if (!date || eventOverrideData(d, item.mail_id, item.event_index).state === 'removed') continue;
    if (importantView === 'deadline') continue;
    let savedEvent = applyEventOverride(d, item.mail_id, item.event_index, {
      ...(event || {}),
      kind: '活动',
      title: detail.title || event?.title || '日程安排',
      start,
      end: detail.end || event?.end || '',
      location: detail.location || event?.location || '',
      allDay: detail.allDay === true || detail.allDay === undefined && event?.allDay === true
    });
    items.push({
      key: item.mail_id + ':' + item.event_index,
      mail_id: item.mail_id,
      kind: 'schedule',
      date,
      m,
      index: item.event_index,
      title: savedEvent.title,
      event: savedEvent,
      result,
      status: item.status
    });
  }
  // Cards are linked only by the user's explicit join decision.
  for (let item of items) item.action = eventAction(item.event, item.result);
  for (let pin of pins) {
    if (importantView === 'schedule') continue;
    let m = allEventMails(d).find(x => x.id === pin.mail_id);
    if (!m || !m.result) continue;
    let result = JSON.parse(m.result),
      raw = result.events?.[pin.event_index];
    if (raw?.kind !== '截止') continue;
    let event = applyEventOverride(d, pin.mail_id, pin.event_index, raw);
    let date = String(pin.due || event.start || '').slice(0, 10);
    if (!date) continue;
    let savedEvent = {
      ...event,
      title: pin.title || event.title,
      start: pin.due || event.start
    };
    let item = {
      key: pin.mail_id + ':' + pin.event_index,
      mail_id: pin.mail_id,
      index: pin.event_index,
      kind: 'deadline',
      date,
      m,
      title: savedEvent.title,
      start: savedEvent.start,
      location: savedEvent.location || '',
      allDay: savedEvent.allDay === true,
      action: eventAction(savedEvent, result),
      event: savedEvent,
      state: pin.state
    };
    if (pin.state === 'completed') completed.push(item);else if (pin.state === 'active') items.push(item);
  }
  if (importantView === 'schedule') items = items.filter(x => x.kind === 'schedule');
  if (importantView === 'deadline') items = items.filter(x => x.kind === 'deadline');
  if (!items.some(x => x.kind === 'deadline') && importantView !== 'schedule') selectedDeadlineKey = '';
  renderMonthCalendar(items, completed, d);
}
function genericHelpSuggestion(line) {
  return /(?:如有|如遇|如果遇到|若遇到|遇到).{0,24}(?:困难|问题|疑问).{0,20}(?:向.{0,10}(?:求助|咨询)|联系|求助|咨询)/i.test(line) || /(?:if|should you).{0,60}(?:questions?|difficult(?:y|ies)|issues?).{0,40}(?:contact|reach out|ask|seek help)|please feel free to (?:contact|reach out|ask)/i.test(line);
}
function eventAction(event, result) {
  let action = String(event?.action || '').trim();
  if (action && !genericHelpSuggestion(action)) return action;
  if ((result?.events || []).length !== 1) return '';
  let legacy = String(result?.action || '').trim();
  return legacy && !genericHelpSuggestion(legacy) ? legacy : '';
}
function normalizeEventLabel(value) {
  return String(value || '').toLocaleLowerCase().replace(/^\s*(?:活动邀请|邀请|活动)\s*[|｜:：\-—]?\s*/, '').replace(/[\s\p{P}\p{S}_]+/gu, '');
}
function sameScheduledEvent(a, b) {
  let x = a?.event || a,
    y = b?.event || b;
  if (!x?.title || !y?.title || !x?.start || !y?.start) return false;
  if (normalizeEventLabel(x.title) !== normalizeEventLabel(y.title) || String(x.start).slice(0, 16) !== String(y.start).slice(0, 16)) return false;
  let lx = normalizeEventLabel(x.location),
    ly = normalizeEventLabel(y.location);
  return !lx || !ly || lx === ly;
}
function mergeScheduleDuplicates(items, mails) {
  let groups = [];
  for (let item of items) {
    let group = groups.find(entries => sameScheduledEvent(entries[0], item));
    if (group) group.push(item);else groups.push([item]);
  }
  return groups.map(group => {
    let canonical = [...group].sort((a, b) => Date.parse(b.m?.sent_date || b.m?.date || '') - Date.parse(a.m?.sent_date || a.m?.date || ''))[0],
      ends = [...new Set(group.map(x => String(x.event.end || '').slice(0, 16)).filter(Boolean))];
    let event = {
      ...canonical.event
    };
    if (ends.length > 1) event.end = '';else if (!event.end && ends.length === 1) event.end = ends[0];
    if (!event.location) event.location = group.find(x => x.event.location)?.event.location || '';
    let actions = [...new Set(group.flatMap(x => relatedEventAction(x.event, x.result, mails).split('；').map(s => s.trim()).filter(Boolean)))];
    return {
      ...canonical,
      event,
      title: event.title,
      action: actions.join('；')
    };
  });
}
function relatedEventAction(event, result, mails) {
  let actions = [];
  let direct = eventAction(event, result);
  if (direct) actions.push(direct);
  if (!event?.title || !event?.start) return [...new Set(actions)].join('；');
  for (let mail of mails || []) {
    if (!mail.result) continue;
    let other;
    try {
      other = JSON.parse(mail.result);
    } catch {
      continue;
    }
    for (let candidate of other.events || []) {
      if (!sameScheduledEvent({
        event
      }, {
        event: candidate
      })) continue;
      let action = eventAction(candidate, other);
      if (action) actions.push(action);
    }
  }
  return [...new Set(actions)].join('；');
}
function allEventMails(d) {
  return [...(d?.mails || []), ...(d?.eventSourceMails || [])];
}
function initEventMenus() {
  document.addEventListener('click', event => {
    document.querySelectorAll('.event-manage[open]').forEach(menu => {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') closeEventMenus();
  });
}
