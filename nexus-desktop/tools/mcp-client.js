'use strict';

/**
 * MCP proxy layer — spawns stdio MCP servers and exposes their tools via HTTP.
 * Config loaded from config/mcp.json.
 *
 * API (mounted on main Express server):
 *   GET  /mcp/servers              — list configured servers + connection status
 *   GET  /mcp/:server/tools        — list tools from a server (connects on demand)
 *   POST /mcp/:server/call/:tool   — call a tool on a server
 */

const path   = require('path');
const fs     = require('fs');
const { Client }               = require('@modelcontextprotocol/sdk/client/index.js');
const { StdioClientTransport } = require('@modelcontextprotocol/sdk/client/stdio.js');

const CONFIG_PATH = path.join(__dirname, '..', 'config', 'mcp.json');

// In-memory client pool — one client per server, lazy-initialized
const _clients = new Map();

function loadConfig() {
  if (!fs.existsSync(CONFIG_PATH)) return {};
  try {
    return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
  } catch (e) {
    console.error('[mcp] Failed to parse mcp.json:', e.message);
    return {};
  }
}

async function getClient(serverName) {
  if (_clients.has(serverName)) return _clients.get(serverName);

  const config = loadConfig();
  const srv = config[serverName];
  if (!srv) throw new Error(`MCP server '${serverName}' not found in config/mcp.json`);

  const transport = new StdioClientTransport({
    command: srv.command,
    args:    srv.args    || [],
    env:     { ...process.env, ...(srv.env || {}) },
  });

  const client = new Client(
    { name: 'nexus-desktop', version: '1.0.0' },
    { capabilities: { tools: {} } }
  );

  await client.connect(transport);
  _clients.set(serverName, client);
  console.log(`[mcp] Connected to '${serverName}'`);
  return client;
}

// ── Route handlers ────────────────────────────────────────────────────────────

async function listServers(_req, res) {
  const config = loadConfig();
  const servers = Object.entries(config).map(([name, cfg]) => ({
    name,
    command:   cfg.command,
    connected: _clients.has(name),
  }));
  res.json({ ok: true, servers });
}

async function listTools(req, res) {
  try {
    const client = await getClient(req.params.server);
    const { tools } = await client.listTools();
    res.json({ ok: true, tools });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
}

async function callTool(req, res) {
  try {
    const client = await getClient(req.params.server);
    const result = await client.callTool({
      name:      req.params.tool,
      arguments: req.body || {},
    });
    res.json({ ok: true, result });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
}

function mount(app) {
  app.get('/mcp/servers',             listServers);
  app.get('/mcp/:server/tools',       listTools);
  app.post('/mcp/:server/call/:tool', callTool);
}

module.exports = { mount };
