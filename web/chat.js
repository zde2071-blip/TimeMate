// Mail-focused LLM conversations. Email retrieval is query-based and server-side.
let chatConversationId = null;
let chatMessages = [];
let chatConversations = [];
let chatBusy = false;
let chatHistoryRequest = 0;
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
      if (!window.confirm('删除这段对话？')) return;
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
    transcript.append(item);
  }
  if (chatBusy) transcript.append(element('p', '正在整理相关邮件…', 'chat-thinking'));
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
  try {
    const data = await chatRequest('/api/chat/conversation?id=' + encodeURIComponent(id));
    chatConversationId = data.conversation.id;
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
  chatConversationId = null;
  chatMessages = [];
  $('chat-status').textContent = '';
  $('chat-input').value = '';
  renderChatHistory();
  renderChatTranscript();
  $('chat-input').focus();
}

async function sendChatMessage(message) {
  const question = String(message || '').trim();
  if (!question || chatBusy) return;
  const unsaved = chatMessages.length;
  chatMessages.push({ role: 'user', content: question, sources: [] });
  chatBusy = true;
  $('chat-status').textContent = '';
  $('chat-send').disabled = true;
  renderChatTranscript();
  try {
    const data = await chatRequest('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conversationId: chatConversationId, message: question })
    });
    chatConversationId = data.conversationId;
    chatMessages.push({ role: 'assistant', content: data.reply, sources: data.sources || [] });
    if (!chatConversations.some(item => item.id === chatConversationId)) {
      chatConversations.unshift({ id: chatConversationId, title: data.title || question.slice(0, 48), updated: Date.now() / 1000 });
    } else {
      const item = chatConversations.find(entry => entry.id === chatConversationId);
      item.updated = Date.now() / 1000;
    }
    chatConversations.sort((a, b) => b.updated - a.updated);
    $('chat-status').textContent = data.truncated
      ? `从 ${data.total} 封邮件中检索了 ${data.included} 封相关邮件。`
      : (data.included ? `已检索 ${data.included} 封邮件。` : '暂时没有可用于回答的邮件摘要。');
    $('chat-input').value = '';
    renderChatHistory();
  } catch (error) {
    chatMessages.splice(unsaved);
    $('chat-input').value = question;
    $('chat-status').textContent = error.message;
  } finally {
    chatBusy = false;
    $('chat-send').disabled = false;
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
