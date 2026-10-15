// Mail-focused LLM conversations. Email retrieval is query-based and server-side.
let chatConversationId = null;
let chatApprovalMode = 'confirm';
let chatProfileId = null;
let chatModelId = null;
let chatModelInitialized = false;
let chatMessages = [];
let chatConversations = [];
let chatBusy = false;
let chatHistoryRequest = 0;
let chatAttachments = [];
let chatAttachmentBusy = false;
let chatRetry = null;
let chatOpenRequest = 0;
const chatEmpty = $('chat-empty');

async function chatRequest(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'X-Token': token, ...(options.headers || {}) }
  });
  const data = await response.json();
  if (!response.ok) throw Error(data.error || '对话请求失败，请稍后重试。');
  return data;
}

function renderChatHistory() {
  const list = $('chat-history-list');
  list.replaceChildren();
  for (const conversation of chatConversations) {
    const row = element('div', '', 'chat-history-row' + (conversation.id === chatConversationId ? ' is-active' : ''));
    const open = element('button', conversation.title || '新对话', 'chat-history-open');
    open.type = 'button';
    open.title = conversation.title || '新对话';
    open.onclick = () => openChatConversation(conversation.id);
    const remove = element('button', '×', 'chat-history-delete');
    remove.type = 'button';
    remove.setAttribute('aria-label', '删除对话：' + (conversation.title || '新对话'));
    remove.onclick = async () => {
      if (chatBusy || !window.confirm('删除这段对话？已加入的重要事项会保留。')) return;
      try {
        await chatRequest('/api/chat/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: conversation.id })
        });
        if (chatConversationId === conversation.id) startNewChat();
        await loadChatConversations(false);
      } catch (error) {
        $('chat-status').textContent = error.message;
      }
    };
    row.append(open, remove);
    list.append(row);
  }
}

function renderChatTranscript() {
  const transcript = $('chat-transcript');
  transcript.replaceChildren();
  if (!chatMessages.length) {
    transcript.append(chatEmpty);
    chatEmpty.hidden = false;
    if (chatBusy) transcript.append(element('p', '正在整理…', 'chat-thinking'));
    return;
  }
  chatEmpty.hidden = true;
  for (const message of chatMessages) {
    const item = element('article', '', 'chat-message ' + (message.role === 'user' ? 'is-user' : 'is-assistant'));
    const label = element('div', message.role === 'user' ? '你' : 'TimeMate', 'chat-message-label');
    const content = element('div', message.content, 'chat-message-content');
    item.append(label, content);
    if (Array.isArray(message.sources) && message.sources.length) {
      const sources = element('div', '', 'chat-message-sources');
      sources.append(element('span', '来源邮件', 'chat-source-label'));
      for (const source of message.sources) {
        const button = element('button', source.title || '查看邮件', 'chat-source-link');
        button.type = 'button';
        button.title = [source.sender, source.date, source.category].filter(Boolean).join(' · ');
        button.onclick = () => openMailById(source.id);
        sources.append(button);
      }
      item.append(sources);
    }
    if (Array.isArray(message.events) && message.events.length) item.append(renderChatEvents(message));
    transcript.append(item);
  }
  if (chatBusy) transcript.append(element('p', '正在整理…', 'chat-thinking'));
  transcript.scrollTop = transcript.scrollHeight;
}

async function loadChatConversations(openLatest = true) {
  const request = ++chatHistoryRequest;
  try {
    const data = await chatRequest('/api/chat/conversations');
    if (request !== chatHistoryRequest) return;
    chatConversations = Array.isArray(data.conversations) ? data.conversations : [];
    renderChatHistory();
    if (openLatest && !chatConversationId && chatConversations.length) await openChatConversation(chatConversations[0].id);
  } catch (error) {
    $('chat-status').textContent = error.message;
  }
}

async function openChatConversation(id) {
  if (chatBusy) return;
  const request = ++chatOpenRequest;
  try {
    const data = await chatRequest('/api/chat/conversation?id=' + encodeURIComponent(id));
    if (request !== chatOpenRequest || chatBusy) return;
    chatConversationId = data.conversation.id;
    chatProfileId = (aiProfiles || []).some(item => item.id === data.conversation.profileId) ? data.conversation.profileId : null;
    chatModelId = data.conversation.model || aiProfiles.find(item => item.id === chatProfileId)?.model || null;
    chatModelInitialized = true;
    renderChatModel(state?.config, aiProfiles);
    chatMessages = data.messages || [];
    $('chat-status').textContent = '';
    renderChatHistory();
    renderChatTranscript();
  } catch (error) {
    $('chat-status').textContent = error.message;
  }
}

function startNewChat() {
  if (chatBusy) return;
  ++chatOpenRequest;
  ++chatHistoryRequest;
  chatRetry = null;
  chatAttachments = [];
  renderChatAttachments();
  chatConversationId = null;
  chatMessages = [];
  $('chat-status').textContent = '';
  $('chat-input').value = '';
  resizeChatInput();
  renderChatHistory();
  renderChatTranscript();
  $('chat-input').focus();
}

async function sendChatMessage(message) {
  const question = String(message || '').trim() || (chatAttachments.length ? '整理图片中的考试和截止信息。' : '');
  if (!question || chatBusy || chatAttachmentBusy) return;
  if (aiProfiles.length && (!chatProfileId || !chatModelId)) {
    $('chat-status').textContent = '请选择聊天模型。';
    return;
  }
  ++chatOpenRequest;
  const images = chatAttachments.map(({name, dataUrl}) => ({name, dataUrl}));
  const mode = chatApprovalMode;
  const key = JSON.stringify([chatConversationId, question, images, mode, chatProfileId, chatModelId]);
  if (!chatRetry || chatRetry.key !== key) chatRetry = {key, id: crypto.randomUUID()};
  const unsaved = chatMessages.length;
  chatMessages.push({ role: 'user', content: question + images.map(image => '\n[图片：' + image.name + ']').join(''), sources: [] });
  chatBusy = true;
  $('chat-status').textContent = '';
  setChatBusy(true);
  renderChatTranscript();
  try {
    const data = await chatRequest('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conversationId: chatConversationId, message: question, images, approvalMode: mode, profileId: chatProfileId, model: chatModelId, requestId: chatRetry.id })
    });
    chatConversationId = data.conversationId;
    chatMessages.push({ role: 'assistant', content: data.reply, sources: data.sources || [], events: data.events || [] });
    chatRetry = null;
    chatAttachments = [];
    renderChatAttachments();
    if ((data.events || []).some(item => item.status === 'added')) await refresh();
    if (!chatConversations.some(item => item.id === chatConversationId)) {
      chatConversations.unshift({ id: chatConversationId, title: data.title || question.slice(0, 48), updated: Date.now() / 1000 });
    } else {
      const item = chatConversations.find(entry => entry.id === chatConversationId);
      item.updated = Date.now() / 1000;
    }
    chatConversations.sort((a, b) => b.updated - a.updated);
    $('chat-status').textContent = data.truncated
      ? `从 ${data.total} 封邮件中检索了 ${data.included} 封相关邮件。`
      : '';
    $('chat-input').value = '';
    resizeChatInput();
    renderChatHistory();
  } catch (error) {
    chatMessages.splice(unsaved);
    $('chat-input').value = question;
    $('chat-status').textContent = error.message;
  } finally {
    chatBusy = false;
    setChatBusy(false);
    renderChatTranscript();
    $('chat-input').focus();
  }
}

for (const button of document.querySelectorAll('[data-chat-prompt]')) {
  button.onclick = () => sendChatMessage(button.dataset.chatPrompt);
}
$('chat-new').onclick = startNewChat;
$('chat-form').onsubmit = event => {
  event.preventDefault();
  sendChatMessage($('chat-input').value);
};
$('chat-input').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    $('chat-form').requestSubmit();
  }
});
renderChatTranscript();

function setChatBusy(busy) {
  for (const id of ['chat-send', 'chat-upload', 'chat-new']) $(id).disabled = busy;
  if (busy) { $('chat-model-menu').open = false; $('chat-approval-menu').open = false; }
}

function renderChatEvents(message) {
  const list = element('section', '', 'chat-event-list');
  list.setAttribute('aria-label', '识别到的重要事项');
  for (const proposal of message.events) {
    const event = proposal.event;
    const row = element('article', '', 'chat-event-card');
    const heading = element('div', '', 'chat-event-heading');
    heading.append(element('span', event.kind === '截止' ? '截止事项' : '日程安排', 'chat-event-kind'), element('strong', event.title));
    row.append(heading);
    const when = event.allDay ? String(event.start || '').slice(0, 10) + '（全天）' : String(event.start || '时间待补充').replace('T', ' ') + (event.end ? ' — ' + (event.end.slice(0, 10) === event.start.slice(0, 10) ? event.end.slice(11, 16) : event.end.replace('T', ' ')) : '');
    row.append(element('p', when, 'chat-event-time'));
    if (event.location) row.append(element('p', event.location, 'chat-event-detail'));
    if (event.action) row.append(element('p', event.action, 'chat-event-detail'));
    if (event.evidence) row.append(element('p', '依据：' + event.evidence, 'chat-event-evidence'));
    const footer = element('div', '', 'chat-event-footer');
    const saved = ['added', 'duplicate', 'completed', 'removed'].includes(proposal.status);
    const statusText = {added: '✓ 已添加', duplicate: '✓ 已有相同事项', completed: '✓ 已完成', removed: '已移除', needs_info: '需要补充信息', conflict: '需要核对'};
    if (proposal.note && !saved) row.append(element('p', proposal.note, 'chat-event-note'));
    if (saved) {
      footer.append(element('span', statusText[proposal.status], 'chat-event-state'));
      if (proposal.status !== 'removed') {
        const view = element('button', '查看重要事项', 'secondary');
        view.type = 'button';
        view.onclick = async () => {
          await refresh();
          showPage('important');
          if (typeof focusImportantEvent === 'function') focusImportantEvent(proposal.savedId, proposal.savedIndex);
        };
        footer.append(view);
      }
    } else if (proposal.status === 'needs_info') {
      const clarify = element('button', '补充信息', 'secondary');
      clarify.type = 'button';
      clarify.onclick = () => {
        $('chat-input').value = '补充“' + event.title + '”的时间信息：';
        $('chat-input').focus();
      };
      footer.append(clarify);
    } else {
      if (proposal.status === 'conflict') {
        const view = element('button', '查看重要事项', 'secondary');
        view.type = 'button';
        view.onclick = () => showPage('important');
        footer.append(view);
      }
      const add = element('button', proposal.status === 'conflict' ? '另行添加' : '添加', 'chat-event-add');
      add.type = 'button';
      add.onclick = async () => {
        if (proposal.status === 'conflict' && !window.confirm('已有相似事项，仍要另行添加吗？')) return;
        add.disabled = true;
        try {
          const data = await chatRequest('/api/chat/events/add', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({id: proposal.id, separate: proposal.status === 'conflict'})
          });
          message.events = data.events;
          renderChatTranscript();
          await refresh();
        } catch (error) {
          $('chat-status').textContent = error.message;
          add.disabled = false;
        }
      };
      footer.append(add);
    }
    row.append(footer);
    list.append(row);
  }
  return list;
}

function renderChatAttachments() {
  const box = $('chat-attachments');
  box.replaceChildren();
  box.hidden = !chatAttachments.length;
  for (const image of chatAttachments) {
    const item = element('div', '', 'chat-attachment');
    const preview = document.createElement('img');
    preview.src = image.dataUrl;
    preview.alt = image.name;
    const remove = element('button', '×', 'secondary');
    remove.type = 'button';
    remove.setAttribute('aria-label', '移除图片：' + image.name);
    remove.onclick = () => {
      if (chatBusy) return;
      chatAttachments = chatAttachments.filter(entry => entry !== image);
      chatRetry = null;
      renderChatAttachments();
    };
    item.append(preview, element('span', image.name), remove);
    box.append(item);
  }
}

async function prepareChatImage(file) {
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) throw Error('请上传 PNG、JPEG 或 WebP 图片。');
  if (file.size > 15 * 1024 * 1024) throw Error('原始图片不能超过 15 MB，请缩小后上传。');
  const image = await createImageBitmap(file);
  try {
    if (image.width * image.height > 40000000) throw Error('图片尺寸过大，请裁剪后上传。');
    const scale = Math.min(1, 2400 / Math.max(image.width, image.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(image.width * scale));
    canvas.height = Math.max(1, Math.round(image.height * scale));
    const context = canvas.getContext('2d');
    context.fillStyle = '#fff';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    // Re-encoding also removes EXIF/location metadata before transmission.
    const dataUrl = canvas.toDataURL('image/jpeg', .9);
    if (dataUrl.length > 4 * 1024 * 1024) throw Error('图片压缩后仍超过 3 MB，请裁剪后上传。');
    return {name: file.name || '粘贴的图片', dataUrl};
  } finally {
    image.close();
  }
}

async function attachChatImages(files) {
  if (chatBusy || chatAttachmentBusy) return;
  if (chatAttachments.length + files.length > 3) {
    $('chat-status').textContent = '每次最多上传 3 张图片。';
    return;
  }
  chatAttachmentBusy = true;
  setChatBusy(true);
  try {
    const prepared = [];
    for (const file of files) prepared.push(await prepareChatImage(file));
    const images = [...chatAttachments, ...prepared];
    if (images.reduce((total, image) => total + image.dataUrl.length * .75, 0) > 6 * 1024 * 1024) throw Error('本次图片总大小不能超过 6 MB，请减少图片。');
    chatAttachments = images;
    chatRetry = null;
    $('chat-status').textContent = '';
    renderChatAttachments();
  } catch (error) {
    $('chat-status').textContent = error.message || '图片读取失败，请重新上传。';
  } finally {
    chatAttachmentBusy = false;
    setChatBusy(false);
    $('chat-image-input').value = '';
  }
}

$('chat-upload').onclick = () => $('chat-image-input').click();
$('chat-image-input').onchange = event => attachChatImages(Array.from(event.target.files || []));
$('chat-form').addEventListener('paste', event => {
  const clipboard = event.clipboardData;
  let files = Array.from(clipboard?.files || []).filter(file => file.type.startsWith('image/'));
  if (!files.length) files = Array.from(clipboard?.items || []).filter(item => item.kind === 'file' && item.type.startsWith('image/')).map(item => item.getAsFile()).filter(Boolean);
  if (!files.length) return;
  event.preventDefault();
  if (chatBusy || chatAttachmentBusy) return;
  const text = clipboard.getData('text/plain');
  const input = $('chat-input');
  if (text && event.target === input) {
    const available = input.maxLength - input.value.length + input.selectionEnd - input.selectionStart;
    input.setRangeText(text.slice(0, Math.max(0, available)), input.selectionStart, input.selectionEnd, 'end');
  }
  resizeChatInput();
  attachChatImages(files);
});
for (const button of document.querySelectorAll('[data-approval-mode]')) {
  button.onclick = () => {
    if (chatBusy || chatAttachmentBusy) return;
    chatApprovalMode = button.dataset.approvalMode;
    chatRetry = null;
    $('chat-approval-name').textContent = chatApprovalMode === 'auto' ? '自动添加' : '逐项确认';
    $('chat-approval-menu').classList.toggle('is-auto', chatApprovalMode === 'auto');
    for (const option of document.querySelectorAll('[data-approval-mode]')) {
      option.setAttribute('aria-pressed', String(option.dataset.approvalMode === chatApprovalMode));
      option.querySelector('.chat-choice-check').textContent = option.dataset.approvalMode === chatApprovalMode ? '✓' : '';
    }
    $('chat-approval-menu').open = false;
  };
}
$('chat-model-settings').onclick = () => {
  $('chat-model-menu').open = false;
  showPage('settings');
  selectConnectionSettings('ai');
};
document.addEventListener('click', event => {
  for (const id of ['chat-model-menu','chat-approval-menu']) if (!$(id).contains(event.target)) $(id).open = false;
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') for (const id of ['chat-model-menu','chat-approval-menu']) $(id).open = false;
});

function renderChatModel(config, profiles = []) {
  if (!chatModelInitialized && profiles.length) {
    chatProfileId = profiles[0].id;
    chatModelId = (profiles[0].models || [profiles[0].model])[0];
    chatModelInitialized = true;
  }
  const profile = profiles.find(item => item.id === chatProfileId && (item.models || [item.model]).includes(chatModelId));
  if (!profile) { chatProfileId = null; chatModelId = null; }
  const name = profile ? (providers[profile.provider]?.name || profile.provider) + ' · ' + chatModelId : profiles.length ? '选择模型' : config?.model || '选择模型';
  $('chat-model-name').textContent = name;
  $('chat-model-menu').querySelector('summary').setAttribute('aria-label', '模型：' + name);
  const list = $('chat-model-list');
  list.replaceChildren();
  if (!profiles.length) list.append(element('span', config?.model || '尚未连接', 'chat-model-empty'));
  for (const item of profiles) {
    list.append(element('div', providers[item.provider]?.name || item.provider, 'chat-model-group'));
    for (const model of item.models || [item.model]) {
    const button = element('button', '', 'chat-model-option');
    button.type = 'button';
    const selected = item.id === chatProfileId && model === chatModelId;
    button.setAttribute('aria-pressed', String(selected));
    const copy = element('span', '', 'chat-model-copy');
    copy.append(element('strong', model));
    button.append(copy, element('span', selected ? '✓' : '', 'chat-choice-check'));
    button.onclick = () => {
      if (chatBusy || chatAttachmentBusy) return;
      chatProfileId = item.id;
      chatModelId = model;
      chatRetry = null;
      $('chat-model-menu').open = false;
      renderChatModel(config, profiles);
    };
    list.append(button);
    }
  }
}

function resizeChatInput() {
  const input = $('chat-input');
  input.style.height = 'auto';
  input.style.height = Math.min(180, input.scrollHeight) + 'px';
}
$('chat-input').addEventListener('input', resizeChatInput);
