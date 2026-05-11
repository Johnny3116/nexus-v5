'use strict';
// chat.js — renderer logic for Nexus Desktop chat UI.

(async () => {
  const api = window.nexus;
  if (!api) {
    document.body.innerHTML = '<div style="color:#f55;padding:20px">window.nexus not exposed — preload.js failed to load.</div>';
    return;
  }

  // ── State ──────────────────────────────────────────────────────────
  let currentChatId = null;
  let currentChat   = null;
  let chats         = [];
  let streaming     = false;
  let streamEl      = null;
  let settings      = null;

  // ── Elements ───────────────────────────────────────────────────────
  const $ = (id) => document.getElementById(id);
  const tabs        = document.querySelectorAll('.tab[data-tab]');
  const tabContents = document.querySelectorAll('.tab-content');
  const chatList    = $('chat-list');
  const newChatBtn  = $('new-chat');
  const settingsBtn = $('open-settings');
  const workspaceBtn= $('open-workspace');
  const bridgesBtn  = $('open-bridges');
  const messagesEl  = $('messages');
  const composer    = $('composer-form');
  const inputEl     = $('composer-input');
  const sendBtn     = $('composer-send');
  const chatTitleEl = $('chat-title');
  const modelBadge  = $('model-badge');
  const avatarFrame = $('avatar-frame');
  const modal       = $('settings-modal');
  const modalCancel = $('modal-cancel');
  const modalSave   = $('modal-save');
  const wsPathInput = $('workspace-path');
  const wsPickBtn   = $('workspace-pick');
  const modelSelect = $('model-select');
  const systemExtra = $('system-extra');
  const bridgeStatus= $('bridge-status');

  // ── Init ───────────────────────────────────────────────────────────
  settings = await api.settings.get();
  modelBadge.textContent = settings.model || '—';

  const avatarUrl = await api.avatar.url();
  avatarFrame.src = avatarUrl;

  await refreshChats();
  if (chats.length === 0) {
    await createNewChat();
  } else {
    await loadChat(chats[0].id);
  }

  // First-run: if no workspace, gently nag via system message
  const ws = await api.workspace.get();
  if (!ws) {
    appendSystemMessage('No workspace folder chosen yet. Click ⚙ Settings to pick one — Nexus will read/write files there.');
  }

  // ── Tab switching ──────────────────────────────────────────────────
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      tabContents.forEach(c => c.classList.remove('active'));
      tab.classList.add('active');
      $('tab-' + tab.dataset.tab).classList.add('active');
    });
  });

  // ── Chat list / new chat ───────────────────────────────────────────
  newChatBtn.addEventListener('click', createNewChat);

  async function refreshChats() {
    chats = await api.chat.list();
    renderChatList();
  }

  function renderChatList() {
    const byFolder = {};
    for (const c of chats) {
      const f = c.folder || 'Recent';
      if (!byFolder[f]) byFolder[f] = [];
      byFolder[f].push(c);
    }
    chatList.innerHTML = '';
    for (const [folder, items] of Object.entries(byFolder)) {
      const folderEl = document.createElement('div');
      folderEl.className = 'folder';
      const titleEl = document.createElement('div');
      titleEl.className = 'folder-title';
      titleEl.textContent = folder;
      folderEl.appendChild(titleEl);
      for (const c of items) {
        const item = document.createElement('div');
        item.className = 'chat-item' + (c.id === currentChatId ? ' active' : '');
        item.textContent = c.title || 'Untitled chat';
        item.title = c.title;
        item.addEventListener('click', () => loadChat(c.id));
        folderEl.appendChild(item);
      }
      chatList.appendChild(folderEl);
    }
  }

  async function createNewChat() {
    const newChat = await api.chat.create({ title: 'New chat', folder: 'Recent' });
    await refreshChats();
    await loadChat(newChat.id);
    inputEl.focus();
  }

  async function loadChat(id) {
    currentChatId = id;
    currentChat = await api.chat.load(id);
    chatTitleEl.textContent = currentChat?.title || 'Untitled chat';
    messagesEl.innerHTML = '';
    for (const m of currentChat?.messages || []) {
      appendMessage(m);
    }
    renderChatList();
  }

  function appendMessage(m) {
    // Render tool calls that happened on this assistant turn (when reloading
    // a chat from storage) before the assistant's text.
    if (m.role === 'assistant' && Array.isArray(m.toolCalls)) {
      for (const tc of m.toolCalls) {
        appendToolCallEl(tc);
        if (tc.result || tc.error) appendToolResultEl(tc);
      }
    }
    const el = document.createElement('div');
    el.className = 'message ' + m.role;
    el.textContent = m.content;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return el;
  }

  function appendToolCallEl({ name, args }) {
    const el = document.createElement('div');
    el.className = 'tool-call';
    const argSummary = summarizeArgs(args);
    el.innerHTML = `<span class="tool-icon">&#128295;</span> <span class="tool-name">${escape(name)}</span>${argSummary ? '<span class="tool-args">' + escape(argSummary) + '</span>' : ''}`;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return el;
  }

  function appendToolResultEl({ name, result, error }) {
    const el = document.createElement('div');
    el.className = 'tool-result ' + (error ? 'err' : 'ok');
    el.textContent = error
      ? `⚠ ${name}: ${error}`
      : `✓ ${summarizeResult(name, result)}`;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return el;
  }

  function summarizeArgs(args) {
    if (!args || typeof args !== 'object') return '';
    if (args.path && args.content !== undefined) return `${args.path}  (${args.content.length} chars)`;
    if (args.path)    return args.path;
    if (args.content) return args.content.slice(0, 60) + (args.content.length > 60 ? '…' : '');
    return JSON.stringify(args);
  }

  function summarizeResult(name, result) {
    if (!result) return name;
    if (name === 'workspace_list')  return `listed ${(result.items || []).length} items`;
    if (name === 'workspace_read')  return `read ${result.path} (${result.bytes ?? '?'} bytes)`;
    if (name === 'workspace_write') return `wrote ${result.path} (${result.bytes ?? '?'} bytes)`;
    if (name === 'workspace_delete')return `deleted ${result.path}`;
    if (name === 'discord_send')    return result.disabled ? 'discord disabled' : 'sent to discord';
    return name + ' ok';
  }

  function escape(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function appendSystemMessage(text) {
    const el = document.createElement('div');
    el.className = 'message system';
    el.textContent = text;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  // ── Send + stream ──────────────────────────────────────────────────
  composer.addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = inputEl.value.trim();
    if (!text || streaming || !currentChatId) return;
    inputEl.value = '';
    inputEl.style.height = 'auto';
    await sendMessage(text);
  });

  inputEl.addEventListener('input', () => {
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 200) + 'px';
  });

  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      composer.requestSubmit();
    }
  });

  async function sendMessage(text) {
    appendMessage({ role: 'user', content: text });
    streaming = true;
    sendBtn.disabled = true;
    sendBtn.textContent = '…';
    await api.chat.send(currentChatId, text);
  }

  api.chat.onChunk(({ chatId, delta }) => {
    if (chatId !== currentChatId) return;
    if (!streamEl) {
      streamEl = document.createElement('div');
      streamEl.className = 'message assistant streaming';
      streamEl.textContent = '';
      messagesEl.appendChild(streamEl);
    }
    streamEl.textContent += delta;
    messagesEl.scrollTop = messagesEl.scrollHeight;
  });

  api.chat.onDone(({ chatId }) => {
    if (chatId !== currentChatId) return;
    if (streamEl) {
      streamEl.classList.remove('streaming');
      streamEl = null;
    }
    streaming = false;
    sendBtn.disabled = false;
    sendBtn.textContent = 'Send';
    refreshChats();
  });

  api.chat.onError(({ chatId, error }) => {
    if (chatId !== currentChatId) return;
    appendSystemMessage('Error: ' + error);
    streamEl = null;
    streaming = false;
    sendBtn.disabled = false;
    sendBtn.textContent = 'Send';
  });

  api.chat.onToolCall(({ chatId, name, args }) => {
    if (chatId !== currentChatId) return;
    // Tool execution started — close any in-progress streaming bubble.
    if (streamEl) { streamEl.classList.remove('streaming'); streamEl = null; }
    appendToolCallEl({ name, args });
  });

  api.chat.onToolResult(({ chatId, name, result, error }) => {
    if (chatId !== currentChatId) return;
    appendToolResultEl({ name, result, error });
  });

  // ── Settings modal ─────────────────────────────────────────────────
  settingsBtn.addEventListener('click', openSettings);
  workspaceBtn.addEventListener('click', openSettings);
  bridgesBtn.addEventListener('click', openSettings);
  modalCancel.addEventListener('click', closeSettings);
  modal.addEventListener('click', (e) => { if (e.target === modal) closeSettings(); });
  wsPickBtn.addEventListener('click', async () => {
    const picked = await api.workspace.pick();
    if (picked) wsPathInput.value = picked;
  });
  modalSave.addEventListener('click', saveSettings);

  async function openSettings() {
    const ws = await api.workspace.get();
    const models = await api.models.list();
    const bridges = await api.bridges.status();

    wsPathInput.value = ws || '';
    systemExtra.value = settings.systemExtra || '';

    modelSelect.innerHTML = '';
    if (models.length === 0) {
      const opt = document.createElement('option');
      opt.value = settings.model;
      opt.textContent = `${settings.model} (Ollama unreachable)`;
      modelSelect.appendChild(opt);
    } else {
      for (const m of models) {
        const opt = document.createElement('option');
        opt.value = m.name;
        opt.textContent = m.name + (m.parameterSize ? ` (${m.parameterSize})` : '');
        if (m.name === settings.model) opt.selected = true;
        modelSelect.appendChild(opt);
      }
    }

    bridgeStatus.innerHTML = '';
    for (const [, v] of Object.entries(bridges)) {
      const row = document.createElement('div');
      row.className = 'bridge';
      const meta = v.url || v.path || v.defaultModel || '';
      row.innerHTML = `<div class="bridge-dot ${v.enabled ? 'on' : 'off'}"></div>
                       <span>${v.name}</span>
                       <span class="bridge-meta">${meta}</span>`;
      bridgeStatus.appendChild(row);
    }

    modal.classList.add('open');
  }

  function closeSettings() { modal.classList.remove('open'); }

  async function saveSettings() {
    settings = await api.settings.update({
      model: modelSelect.value,
      systemExtra: systemExtra.value,
    });
    modelBadge.textContent = settings.model;
    closeSettings();
  }
})();
