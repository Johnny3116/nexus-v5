// Quick standalone test of the HTTP tool server (no Electron needed)
'use strict';

const express = require('express');
const http = require('http');
const os = require('os');
const fs = require('fs');
const path = require('path');

// Load .env
const envPath = path.join(__dirname, '.env');
if (fs.existsSync(envPath)) {
  fs.readFileSync(envPath, 'utf8').split('\n').forEach(line => {
    const [k, ...v] = line.split('=');
    if (k && v.length) process.env[k.trim()] = v.join('=').trim();
  });
}

const TOOL_PORT  = parseInt(process.env.WORKSTATION_TOOL_PORT || '8889', 10);
const TOOL_TOKEN = process.env.WORKSTATION_TOOL_TOKEN || 'dev-token-change-me';

const tools = require('./tools/index');
const srv = express();
srv.use(express.json({ limit: '10mb' }));

srv.use((req, res, next) => {
  const auth = req.headers['authorization'] || '';
  if (auth !== `Bearer ${TOOL_TOKEN}`) return res.status(401).json({ error: 'Unauthorized' });
  next();
});

srv.get('/health', (_req, res) => {
  res.json({ status: 'ok', machine: os.hostname() });
});

// Clipboard stub (no Electron in test mode)
const clipboardStub = {
  readText: () => '(clipboard not available in test mode)',
  writeText: (t) => console.log('[clipboard stub] write:', t),
};

srv.post('/tool/:name', async (req, res) => {
  const { name } = req.params;
  const handler = tools[name];
  if (!handler) return res.status(404).json({ error: `Unknown tool: ${name}` });
  try {
    const result = await handler(req.body, { clipboard: clipboardStub, shell: { openPath: (p) => { console.log('[shell stub] open:', p); return ''; } } });
    res.json({ ok: true, result });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
});

const server = http.createServer(srv);
server.listen(TOOL_PORT, '0.0.0.0', async () => {
  console.log(`\nTool server running on http://0.0.0.0:${TOOL_PORT}`);
  console.log(`Token: ${TOOL_TOKEN}\n`);

  // Run self-tests
  const base = `http://127.0.0.1:${TOOL_PORT}`;
  const headers = { 'Authorization': `Bearer ${TOOL_TOKEN}`, 'Content-Type': 'application/json' };

  async function call(tool, params = {}) {
    const r = await fetch(`${base}/tool/${tool}`, { method: 'POST', headers, body: JSON.stringify(params) });
    return r.json();
  }

  console.log('--- Running self-tests ---\n');

  // 1. health
  const health = await (await fetch(`${base}/health`, { headers })).json();
  console.log('[1] /health:', health);

  // 2. get_info
  const info = await call('get_info');
  console.log('[2] get_info:', info.ok ? `OK — ${info.result.hostname}` : info.error);

  // 3. list_dir
  const ls = await call('list_dir', { dir_path: '~', recursive: false });
  console.log('[3] list_dir ~:', ls.ok ? `OK — ${ls.result.count} entries` : ls.error);

  // 4. run_command
  const cmd = await call('run_command', { command: 'echo hello from nexus-desktop', timeout_ms: 5000 });
  console.log('[4] run_command:', cmd.ok ? `OK — stdout: "${cmd.result.stdout}"` : cmd.error);

  // 5. read_file (this file itself)
  const rf = await call('read_file', { file_path: __filename, max_bytes: 32768 });
  console.log('[5] read_file:', rf.ok ? `OK — ${rf.result.size} bytes` : rf.error);

  // 6. write_file + read back
  const tmpPath = require('os').tmpdir() + '/nexus-desktop-test.txt';
  const wf = await call('write_file', { file_path: tmpPath, content: 'nexus-desktop write_file test' });
  const rb = await call('read_file', { file_path: tmpPath });
  console.log('[6] write+read:', wf.ok && rb.ok ? `OK — "${rb.result.content}"` : 'FAIL');

  // 7. screenshot (just check it doesn't throw; skip saving)
  const ss = await call('screenshot', {});
  console.log('[7] screenshot:', ss.ok ? `OK — ${ss.result.bytes} bytes PNG` : `FAIL: ${ss.error}`);

  // 8. get_clipboard
  const gc = await call('get_clipboard', {});
  console.log('[8] get_clipboard:', gc.ok ? `OK — "${gc.result.text}"` : gc.error);

  // 9. auth rejection
  const bad = await (await fetch(`${base}/tool/get_info`, { method: 'POST', headers: { 'Authorization': 'Bearer wrong', 'Content-Type': 'application/json' }, body: '{}' })).json();
  console.log('[9] auth reject:', bad.error === 'Unauthorized' ? 'OK' : 'FAIL');

  console.log('\n--- All tests complete. Ctrl+C to stop. ---');
});
