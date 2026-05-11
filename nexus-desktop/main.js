'use strict';

const { app, BrowserWindow, clipboard, shell, ipcMain, dialog } = require('electron');
const express = require('express');
const http    = require('http');
const path    = require('path');
const os      = require('os');
const fs      = require('fs');
const crypto  = require('crypto');

// ── Load .env ─────────────────────────────────────────────────────────────
function loadEnv(p) {
  if (!fs.existsSync(p)) return false;
  fs.readFileSync(p, 'utf8').split('\n').forEach(line => {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) return;
    const [k, ...v] = trimmed.split('=');
    if (k && v.length) process.env[k.trim()] = v.join('=').trim();
  });
  return true;
}
const exeDir = path.dirname(process.execPath);
loadEnv(path.join(exeDir, '.env')) || loadEnv(path.join(__dirname, '.env'));

const TOOL_PORT  = parseInt(process.env.WORKSTATION_TOOL_PORT || '8889', 10);
const TOOL_TOKEN = process.env.WORKSTATION_TOOL_TOKEN || 'dev-token-change-me';
const AVATAR_URL = process.env.NEXUS_AVATAR_URL       || 'http://localhost:3000';

// ── Paths ─────────────────────────────────────────────────────────────────
// User-writable state goes under app.getPath('userData') so it works when
// packaged (where __dirname is inside the read-only app.asar archive).
// Read-only files (soul, doctrines) stay next to main.js — Electron's fs
// shim handles asar paths transparently for reads.
const USER_DATA     = app.getPath('userData');
const DATA_DIR      = path.join(USER_DATA, 'data');
const CHATS_DIR     = path.join(DATA_DIR, 'chats');
const SETTINGS_PATH = path.join(DATA_DIR, 'app-settings.json');
const SOUL_DIR      = path.join(__dirname, 'soul');

for (const d of [DATA_DIR, CHATS_DIR]) {
  if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true });
}
console.log('[nexus-desktop] userData =', USER_DATA);

// ── Bridges ───────────────────────────────────────────────────────────────
const bridges     = require('./bridges/registry');
const chatTools   = require('./bridges/tools');

// Legacy avatar-iframe Express tool server (kept as-is)
let tools;
const mcpClient   = require('./tools/mcp-client');
const supabaseSrv = require('./tools/supabase');
const skillRunner = require('./tools/skill-runner');

// ── App settings ──────────────────────────────────────────────────────────
function loadSettings() {
  if (fs.existsSync(SETTINGS_PATH)) {
    try { return JSON.parse(fs.readFileSync(SETTINGS_PATH, 'utf8')); }
    catch (e) { console.warn('[settings] parse failed:', e.message); }
  }
  return {
    workspace: null,
    model: process.env.NEXUS_DEFAULT_MODEL || 'nexus-base:latest',
    systemExtra: '',
  };
}
function saveSettings(s) {
  fs.writeFileSync(SETTINGS_PATH, JSON.stringify(s, null, 2));
}
let settings = loadSettings();
if (settings.workspace) {
  try { bridges.workspace.setWorkspace(settings.workspace); }
  catch (e) { console.warn('[workspace] failed to restore:', e.message); }
}

// ── Chat storage (one JSON per chat) ──────────────────────────────────────
function chatPath(id) { return path.join(CHATS_DIR, `${id}.json`); }

function listChats() {
  if (!fs.existsSync(CHATS_DIR)) return [];
  return fs.readdirSync(CHATS_DIR)
    .filter(f => f.endsWith('.json'))
    .map(f => {
      try {
        const d = JSON.parse(fs.readFileSync(path.join(CHATS_DIR, f), 'utf8'));
        return {
          id: d.id, title: d.title, folder: d.folder || 'Recent',
          createdAt: d.createdAt, updatedAt: d.updatedAt,
          messageCount: (d.messages || []).length,
        };
      } catch { return null; }
    })
    .filter(Boolean)
    .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
}

function loadChat(id) {
  const p = chatPath(id);
  if (!fs.existsSync(p)) return null;
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

function saveChat(chat) {
  chat.updatedAt = Date.now();
  fs.writeFileSync(chatPath(chat.id), JSON.stringify(chat, null, 2));
}

function createChat({ title, folder } = {}) {
  const id = crypto.randomUUID();
  const chat = {
    id,
    title: title || 'New chat',
    folder: folder || 'Recent',
    createdAt: Date.now(),
    updatedAt: Date.now(),
    messages: [],
  };
  saveChat(chat);
  return chat;
}

// ── Legacy Express tool server (for avatar iframe → local tools) ─────────
function startToolServer() {
  const srv = express();
  srv.use(express.json({ limit: '10mb' }));

  srv.use((req, res, next) => {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Authorization, Content-Type');
    if (req.method === 'OPTIONS') return res.sendStatus(204);
    next();
  });

  srv.use((req, res, next) => {
    const auth = req.headers['authorization'] || '';
    if (auth !== `Bearer ${TOOL_TOKEN}`) {
      return res.status(401).json({ error: 'Unauthorized' });
    }
    next();
  });

  srv.get('/health', (_req, res) => {
    res.json({
      status: 'ok',
      machine: os.hostname(),
      platform: process.platform,
      capabilities: ['tools', 'mcp', 'db', 'skills', 'chat', 'workspace'],
    });
  });

  mcpClient.mount(srv);
  supabaseSrv.mount(srv);
  skillRunner.mount(srv);

  srv.post('/tool/:name', async (req, res) => {
    const { name } = req.params;
    const handler = tools[name];
    if (!handler) return res.status(404).json({ error: `Unknown tool: ${name}` });
    try {
      const result = await handler(req.body, { clipboard, shell });
      res.json({ ok: true, result });
    } catch (err) {
      res.status(500).json({ ok: false, error: err.message });
    }
  });

  const server = http.createServer(srv);
  server.listen(TOOL_PORT, '0.0.0.0', () => {
    console.log(`[nexus-desktop] Tool server listening on 0.0.0.0:${TOOL_PORT}`);
  });
  return server;
}

// ── Electron window ───────────────────────────────────────────────────────
let mainWindow;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    title: 'Nexus Desktop',
    icon: path.join(__dirname, 'icon.ico'),
    backgroundColor: '#0a0a0f',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: false, // avatar iframe is cross-origin
    },
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'chat.html'));

  // Inject NexusDesktop client into iframes only (not the main chat.html frame).
  const clientSrc = fs.readFileSync(path.join(__dirname, 'renderer', 'nexus-client.js'), 'utf8');
  const clientCode = `(${clientSrc})('http://127.0.0.1:${TOOL_PORT}', '${TOOL_TOKEN}');`;

  mainWindow.webContents.on('frame-created', (_e, { frame }) => {
    frame.once('dom-ready', () => {
      if (!frame.parent) return;
      frame.executeJavaScript(clientCode).catch(() => {});
    });
  });

  mainWindow.on('closed', () => { mainWindow = null; });
}

// ── IPC handlers ──────────────────────────────────────────────────────────
ipcMain.handle('clipboard:read',  () => clipboard.readText());
ipcMain.handle('clipboard:write', (_e, text) => { clipboard.writeText(text); });
ipcMain.handle('avatar:url',      () => AVATAR_URL);

ipcMain.handle('settings:get',    () => settings);
ipcMain.handle('settings:update', (_e, patch) => {
  settings = { ...settings, ...(patch || {}) };
  if (patch && patch.workspace) {
    try { bridges.workspace.setWorkspace(patch.workspace); }
    catch (e) { console.warn('[workspace] failed to set:', e.message); }
  }
  saveSettings(settings);
  return settings;
});

ipcMain.handle('workspace:get', () => bridges.workspace.getWorkspace());
ipcMain.handle('workspace:pick', async () => {
  if (!mainWindow) return null;
  const result = await dialog.showOpenDialog(mainWindow, {
    title: 'Choose Nexus workspace folder',
    properties: ['openDirectory', 'createDirectory'],
  });
  if (result.canceled || !result.filePaths[0]) return null;
  const picked = result.filePaths[0];
  bridges.workspace.setWorkspace(picked);
  settings.workspace = picked;
  saveSettings(settings);
  return picked;
});
ipcMain.handle('workspace:list',  (_e, sub) => bridges.workspace.list(sub || '.'));
ipcMain.handle('workspace:read',  (_e, p) => bridges.workspace.read(p));
ipcMain.handle('workspace:write', (_e, p, c) => bridges.workspace.write(p, c));

ipcMain.handle('models:list', async () => {
  try { return await bridges.ollama.listModels(); }
  catch (e) { console.warn('[ollama] listModels failed:', e.message); return []; }
});

ipcMain.handle('bridges:status', () => bridges.status());

ipcMain.handle('chat:list',   () => listChats());
ipcMain.handle('chat:load',   (_e, id) => loadChat(id));
ipcMain.handle('chat:create', (_e, opts) => createChat(opts || {}));
ipcMain.handle('chat:delete', (_e, id) => {
  const p = chatPath(id);
  if (fs.existsSync(p)) fs.unlinkSync(p);
  return { ok: true };
});
ipcMain.handle('chat:rename', (_e, id, title) => {
  const chat = loadChat(id);
  if (!chat) return null;
  chat.title = title;
  saveChat(chat);
  return chat;
});

const activeStreams = new Map();
ipcMain.handle('chat:send', async (_e, chatId, userMessage) => {
  const chat = loadChat(chatId);
  if (!chat) throw new Error(`Chat not found: ${chatId}`);

  chat.messages.push({ role: 'user', content: userMessage, ts: Date.now() });
  if (chat.title === 'New chat' && chat.messages.filter(m => m.role === 'user').length === 1) {
    chat.title = userMessage.slice(0, 48);
  }
  saveChat(chat);

  const ac = new AbortController();
  activeStreams.set(chatId, ac);

  const historyForLLM = chat.messages.map(m => ({ role: m.role, content: m.content }));
  const send = (channel, payload) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send(channel, payload);
    }
  };

  (async () => {
    let fullContent = '';
    try {
      // Only enable tools when a workspace is configured — otherwise the
      // model could call workspace tools that immediately fail.
      const workspaceReady = Boolean(bridges.workspace.getWorkspace());
      const tools = workspaceReady ? chatTools.allTools() : null;
      const toolCallsThisTurn = [];

      const result = await bridges.ollama.streamChat({
        model: settings.model,
        messages: historyForLLM,
        soulDir: SOUL_DIR,
        runtimeContext: {
          workspacePath: bridges.workspace.getWorkspace(),
          currentDate: new Date().toISOString().slice(0, 10),
          model: settings.model,
          appVersion: app.getVersion(),
          machine: os.hostname(),
        },
        extraSystem: settings.systemExtra || '',
        tools,
        toolExecutor: tools ? chatTools.execute : null,
        onChunk: (delta) => {
          fullContent += delta;
          send('chat:chunk', { chatId, delta });
        },
        onToolCall: (call) => {
          toolCallsThisTurn.push({ ...call, ts: Date.now() });
          send('chat:tool-call', { chatId, ...call });
        },
        onToolResult: ({ id, name, args, result, error }) => {
          const entry = toolCallsThisTurn.find(t => t.id === id);
          if (entry) { entry.result = result; entry.error = error; }
          send('chat:tool-result', { chatId, id, name, args, result, error });
        },
        signal: ac.signal,
      });

      chat.messages.push({
        role: 'assistant',
        content: result.content,
        ts: Date.now(),
        model: result.model,
        toolCalls: toolCallsThisTurn.length ? toolCallsThisTurn : undefined,
      });
      saveChat(chat);
      send('chat:done', { chatId, message: { role: 'assistant', content: result.content } });
    } catch (e) {
      console.error('[chat] stream failed:', e);
      send('chat:error', { chatId, error: e.message || String(e) });
    } finally {
      activeStreams.delete(chatId);
    }
  })();

  return { chatId, status: 'streaming' };
});

ipcMain.handle('chat:abort', (_e, chatId) => {
  const ac = activeStreams.get(chatId);
  if (ac) { ac.abort(); return { aborted: true }; }
  return { aborted: false };
});

// ── App lifecycle ─────────────────────────────────────────────────────────
app.whenReady().then(() => {
  tools = require('./tools/index');
  startToolServer();
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
