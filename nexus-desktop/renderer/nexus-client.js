/**
 * NexusDesktop client — injected into the avatar iframe by Electron.
 * Available on window.NexusDesktop inside the avatar page.
 *
 * Usage (inside the avatar page):
 *   const info  = await NexusDesktop.tool('get_info');
 *   const rows  = await NexusDesktop.db.select('memories', { limit: 10 });
 *   const data  = await NexusDesktop.skill('system-info');
 *   const tools = await NexusDesktop.mcp.tools('filesystem');
 *   const out   = await NexusDesktop.mcp.call('filesystem', 'read_file', { path: '...' });
 */

(function (BASE_URL, TOKEN) {
  async function _fetch(method, path, body) {
    const opts = {
      method,
      headers: {
        'Authorization': `Bearer ${TOKEN}`,
        'Content-Type': 'application/json',
      },
    };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const r = await fetch(BASE_URL + path, opts);
    const json = await r.json();
    if (!r.ok || json.ok === false) throw new Error(json.error || `HTTP ${r.status}`);
    return json;
  }

  const post = (path, body) => _fetch('POST', path, body);
  const get  = (path)       => _fetch('GET',  path);

  window.NexusDesktop = {
    // ── Meta ───────────────────────────────────────────────────────────────
    health: () => get('/health'),

    // ── Local tools (filesystem, shell, screenshot, clipboard, etc.) ───────
    tool: (name, params = {}) => post(`/tool/${name}`, params),

    // Convenience shorthands
    readFile:    (filePath, maxBytes)      => post('/tool/read_file',     { file_path: filePath, max_bytes: maxBytes }),
    writeFile:   (filePath, content)       => post('/tool/write_file',    { file_path: filePath, content }),
    listDir:     (dirPath, recursive)      => post('/tool/list_dir',      { dir_path: dirPath, recursive }),
    runCommand:  (command, cwd, timeoutMs) => post('/tool/run_command',   { command, cwd, timeout_ms: timeoutMs }),
    screenshot:  (outputPath)              => post('/tool/screenshot',    outputPath ? { output_path: outputPath } : {}),
    getClipboard:()                        => post('/tool/get_clipboard', {}),
    setClipboard:(text)                    => post('/tool/set_clipboard', { text }),
    getInfo:     ()                        => post('/tool/get_info',      {}),
    openPath:    (targetPath)              => post('/tool/open_path',     { target_path: targetPath }),

    // ── Supabase ────────────────────────────────────────────────────────────
    db: {
      select: (table, opts = {})       => post(`/db/${table}/select`,  opts),
      insert: (table, rows)            => post(`/db/${table}/insert`,  { rows: Array.isArray(rows) ? rows : [rows] }),
      update: (table, match, values)   => post(`/db/${table}/update`,  { match, values }),
      delete: (table, match)           => post(`/db/${table}/delete`,  { match }),
      rpc:    (fn, params = {})        => post(`/db/rpc/${fn}`,        params),
    },

    // ── MCP servers ──────────────────────────────────────────────────────────
    mcp: {
      servers: ()                       => get('/mcp/servers'),
      tools:   (server)                 => get(`/mcp/${server}/tools`),
      call:    (server, tool, params={})=> post(`/mcp/${server}/call/${tool}`, params),
    },

    // ── Local skills ─────────────────────────────────────────────────────────
    skills:       ()                    => get('/skills'),
    skill:        (name, params = {})   => post(`/skill/${name}`,      params),
    reloadSkills: ()                    => post('/skills/reload',       {}),

    _meta: { baseUrl: BASE_URL, injected: new Date().toISOString() },
  };

  console.log('[NexusDesktop] Client ready —', BASE_URL);
});
