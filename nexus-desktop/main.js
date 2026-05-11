'use strict';

const { app, BrowserWindow, clipboard, shell, ipcMain } = require('electron');
const express = require('express');
const http = require('http');
const path = require('path');
const os = require('os');
const fs = require('fs');

// Load .env — check next to exe first, then next to source __dirname
function loadEnv(p) {
  if (fs.existsSync(p)) {
    fs.readFileSync(p, 'utf8').split('\n').forEach(line => {
      const [k, ...v] = line.split('=');
      if (k && v.length) process.env[k.trim()] = v.join('=').trim();
    });
    return true;
  }
  return false;
}
const exeDir = path.dirname(process.execPath);
loadEnv(path.join(exeDir, '.env')) || loadEnv(path.join(__dirname, '.env'));

const TOOL_PORT   = parseInt(process.env.WORKSTATION_TOOL_PORT  || '8889', 10);
const TOOL_TOKEN  = process.env.WORKSTATION_TOOL_TOKEN || 'dev-token-change-me';
const AVATAR_URL  = process.env.NEXUS_AVATAR_URL       || 'http://localhost:3000';

// ── Capability modules ────────────────────────────────────────────────────
let tools;
const mcpClient   = require('./tools/mcp-client');
const supabase    = require('./tools/supabase');
const skillRunner = require('./tools/skill-runner');

// ── Express tool server ───────────────────────────────────────────────────
function startToolServer() {
  const srv = express();
  srv.use(express.json({ limit: '10mb' }));

  // CORS — allow the avatar iframe (on NexusBody) to call back to the tool server
  srv.use((req, res, next) => {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Authorization, Content-Type');
    if (req.method === 'OPTIONS') return res.sendStatus(204);
    next();
  });

  // Bearer auth middleware
  srv.use((req, res, next) => {
    const auth = req.headers['authorization'] || '';
    if (auth !== `Bearer ${TOOL_TOKEN}`) {
      return res.status(401).json({ error: 'Unauthorized' });
    }
    next();
  });

  // Health + capability index
  srv.get('/health', (_req, res) => {
    res.json({
      status: 'ok',
      machine: os.hostname(),
      platform: process.platform,
      capabilities: ['tools', 'mcp', 'db', 'skills'],
    });
  });

  // Mount MCP proxy, Supabase, and skill runner
  mcpClient.mount(srv);
  supabase.mount(srv);
  skillRunner.mount(srv);

  // Tool dispatch
  srv.post('/tool/:name', async (req, res) => {
    const { name } = req.params;
    const handler = tools[name];
    if (!handler) {
      return res.status(404).json({ error: `Unknown tool: ${name}` });
    }
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
    title: 'Nexus',
    icon: path.join(__dirname, 'icon.ico'),
    backgroundColor: '#0a0a0f',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: false, // allow iframe to load cross-origin avatar URL
    },
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'), {
    query: { url: AVATAR_URL },
  });

  // Inject NexusDesktop client into the avatar iframe when it loads
  const clientSrc = fs.readFileSync(path.join(__dirname, 'renderer', 'nexus-client.js'), 'utf8');
  const clientCode = `(${clientSrc})('http://127.0.0.1:${TOOL_PORT}', '${TOOL_TOKEN}');`;

  mainWindow.webContents.on('frame-created', (_e, { frame }) => {
    frame.once('dom-ready', () => {
      frame.executeJavaScript(clientCode).catch(() => {}); // ignore if frame navigates away
      console.log('[nexus-desktop] NexusDesktop client injected into avatar frame');
    });
  });

  mainWindow.on('closed', () => { mainWindow = null; });
}

// ── IPC — clipboard bridge (renderer can't use Node clipboard directly) ───
ipcMain.handle('clipboard:read',  () => clipboard.readText());
ipcMain.handle('clipboard:write', (_e, text) => { clipboard.writeText(text); });

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
