// Load original mail bodies only when opened; render originals and translations in sandboxed frames.

function closeSource() {
  $('source-dialog').close();
}

function closeSourceOnBackdrop(event) {
  const dialog = $('source-dialog');
  if (event.target !== dialog) return;
  const box = dialog.getBoundingClientRect();
  if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) closeSource();
}

async function openSource(m, inlineBox = null) {
  const box = inlineBox || $('source-content'),
    dialog = $('source-dialog'),
    heading = element('h3', m.subject);
  const status = element('p', '加载原文…', 'meta'),
    toolbar = element('div', '', 'source-toolbar');
  const originalButton = element('button', '原文', 'source-mode active'),
    chineseButton = element('button', '中文', 'source-mode secondary');
  const hint = element('p', '点击“中文”后才会调用 AI；完整正文会翻译并缓存。', 'meta');
  const translated = element('div', '', 'source-translation');
  function makeFrame(title) {
    const frame = document.createElement('iframe');
    frame.title = title;
    frame.setAttribute('sandbox', 'allow-popups allow-popups-to-escape-sandbox');
    frame.referrerPolicy = 'no-referrer';
    frame.className = 'original-frame';
    frame.hidden = true;
    // Chromium can leave a navigated sandboxed frame outside the modal's painted
    // top layer. Re-enter it after loading without changing focus or scroll.
    frame.onload = () => {
      if (inlineBox || !dialog.open || !box.contains(frame) || frame.hidden) return;
      const focus = document.activeElement,
        scroll = dialog.scrollTop;
      dialog.close();
      dialog.showModal();
      dialog.scrollTop = scroll;
      if (focus && dialog.contains(focus)) focus.focus({
        preventScroll: true
      });
    };
    return frame;
  }
  // Attach both browsing contexts before opening the modal. Switching modes never
  // navigates the other frame or replaces a frame inside an already open dialog.
  const originalFrame = makeFrame('原邮件正文'),
    chineseFrame = makeFrame('中文译文正文');
  translated.hidden = true;
  toolbar.append(originalButton, chineseButton);
  toolbar.hidden = true;
  hint.hidden = true;
  box.replaceChildren(...(inlineBox ? [] : [heading]), status, toolbar, hint, originalFrame, chineseFrame, translated);
  if (!inlineBox && !dialog.open) dialog.showModal();
  try {
    m = await getMailDetail(m);
  } catch {}
  let data = null,
    chineseData = null,
    sourceMode = 'original',
    externalLoaded = false;
  const current = () => (inlineBox ? box.isConnected : dialog.open) && box.contains(originalFrame);
  function display(frame, markup) {
    let content = markup;
    if (externalLoaded) content = content.replace(/data-external="(\d+)"/g, (_, i) => 'src="' + String(data.external[Number(i)] || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;') + '"');
    frame.srcdoc = `<!doctype html><html><head><meta charset="utf-8"><meta name="referrer" content="no-referrer"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: ${externalLoaded ? 'https:' : ''}; style-src 'unsafe-inline'"><style>body{font:15px -apple-system,sans-serif;line-height:1.7;overflow-wrap:anywhere;margin:12px}img{max-width:100%;height:auto}table{max-width:100%}pre{white-space:pre-wrap}a{color:#2f6654}</style></head><body>${content}</body></html>`;
  }
  function showMode(mode) {
    sourceMode = mode;
    const zh = mode === 'zh';
    originalFrame.hidden = zh || !data;
    chineseFrame.hidden = !zh || !chineseData;
    translated.hidden = !zh || !!chineseData;
    heading.textContent = zh && chineseData ? chineseData.subject : m.subject;
    originalButton.className = 'source-mode' + (zh ? ' secondary' : ' active');
    chineseButton.className = 'source-mode' + (zh ? ' active' : ' secondary');
  }
  originalButton.onclick = () => showMode('original');
  chineseButton.onclick = async () => {
    showMode('zh');
    if (chineseData || chineseButton.disabled || !data) return;
    chineseButton.disabled = true;
    const started = performance.now();
    translated.textContent = '正在翻译这封邮件… 0 秒';
    const timer = setInterval(() => {
      if (current() && !chineseData) translated.textContent = '正在翻译这封邮件… ' + Math.floor((performance.now() - started) / 1000) + ' 秒';
    }, 500);
    try {
      const response = await fetch('/api/source/translate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Token': token
        },
        body: JSON.stringify({
          id: m.id
        })
      });
      const result = await response.json();
      if (!current()) return;
      if (!response.ok) throw Error(result.error);
      if (typeof result.html !== 'string' || !result.html.trim()) throw Error('译文内容为空，请重试。');
      chineseData = result;
      display(chineseFrame, result.html);
      translated.replaceChildren();
      showMode(sourceMode);
      hint.textContent = result.cached ? '已使用缓存译文；本次无需调用 AI。' : '翻译完成，用时 ' + (result.elapsedMs / 1000).toFixed(1) + ' 秒；译文已缓存，之后切换不会再次调用 AI。';
    } catch (error) {
      if (current()) {
        translated.textContent = '翻译失败：' + error.message;
        translated.append(element('p', '你可以稍后重试；原文仍可切换查看。', 'meta'));
      }
    } finally {
      clearInterval(timer);
      chineseButton.disabled = false;
    }
  };
  try {
    const response = await fetch('/api/source', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Token': token
      },
      body: JSON.stringify({
        id: m.id
      })
    });
    const result = await response.json();
    if (!current()) return;
    if (!response.ok) throw Error(result.error);
    data = result;
    status.remove();
    toolbar.hidden = false;
    hint.hidden = false;
    display(originalFrame, data.html);
    showMode('original');
    if (data.external.length) {
      const load = element('button', '加载外部图片', 'secondary');
      load.onclick = () => {
        externalLoaded = true;
        display(originalFrame, data.html);
        if (chineseData) display(chineseFrame, chineseData.html);
        load.remove();
      };
      toolbar.append(load);
    }
  } catch (error) {
    if (current()) {
      status.textContent = error.message;
      box.append(element('p', m.body, 'body'));
    }
  }
}

async function getMailDetail(m) {
  if (m.body !== undefined || m.source_body !== undefined) return m;
  let cached = mailDetailCache.get(m.id);
  if (!cached) {
    const response = await fetch('/api/mail/detail?id=' + encodeURIComponent(m.id), {
      headers: {
        'X-Token': token
      }
    });
    const data = await response.json();
    if (!response.ok || !data.mail) throw Error(data.error || '邮件内容加载失败');
    cached = {
      body: data.mail.body,
      source_body: data.mail.source_body
    };
    mailDetailCache.set(m.id, cached);
    // Keep only recently opened bodies, instead of retaining a semester of mail.
    if (mailDetailCache.size > 20) mailDetailCache.delete(mailDetailCache.keys().next().value);
  }
  return {
    ...m,
    ...cached
  };
}
