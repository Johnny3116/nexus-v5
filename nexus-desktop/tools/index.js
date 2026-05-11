'use strict';

const fs   = require('fs').promises;
const path = require('path');
const os   = require('os');
const { exec } = require('child_process');
const { promisify } = require('util');
const execAsync = promisify(exec);

// screenshot-desktop: optional, falls back to PowerShell on Windows
let screenshotFn;
try { screenshotFn = require('screenshot-desktop'); } catch (_) { screenshotFn = null; }

// clipboardy (ESM) — loaded lazily
let _clipboardy = null;
async function clipboardy() {
  if (!_clipboardy) _clipboardy = await import('clipboardy');
  return _clipboardy;
}

// ── Helpers ────────────────────────────────────────────────────────────────

function safePath(rawPath) {
  // Expand ~ to home dir
  if (rawPath.startsWith('~')) rawPath = os.homedir() + rawPath.slice(1);
  return path.resolve(rawPath);
}

// ── Tool implementations ───────────────────────────────────────────────────

async function read_file({ file_path, encoding = 'utf8', max_bytes = 512 * 1024 }) {
  const p = safePath(file_path);
  const stat = await fs.stat(p);
  if (stat.size > max_bytes) {
    throw new Error(`File too large: ${stat.size} bytes (limit ${max_bytes})`);
  }
  const content = await fs.readFile(p, encoding);
  return { path: p, size: stat.size, content };
}

async function write_file({ file_path, content, encoding = 'utf8', create_dirs = true }) {
  const p = safePath(file_path);
  if (create_dirs) await fs.mkdir(path.dirname(p), { recursive: true });
  await fs.writeFile(p, content, encoding);
  return { path: p, bytes_written: Buffer.byteLength(content, encoding) };
}

async function list_dir({ dir_path, recursive = false, show_hidden = false }) {
  const p = safePath(dir_path);

  async function walk(dir, depth) {
    const entries = await fs.readdir(dir, { withFileTypes: true });
    const results = [];
    for (const e of entries) {
      if (!show_hidden && e.name.startsWith('.')) continue;
      const full = path.join(dir, e.name);
      const isDir = e.isDirectory();
      const entry = { name: e.name, path: full, type: isDir ? 'dir' : 'file' };
      if (!isDir) {
        try { entry.size = (await fs.stat(full)).size; } catch (_) {}
      }
      results.push(entry);
      if (isDir && recursive && depth < 4) {
        entry.children = await walk(full, depth + 1);
      }
    }
    return results;
  }

  const entries = await walk(p, 0);
  return { path: p, count: entries.length, entries };
}

async function run_command({ command, cwd, timeout_ms = 30000, shell: useShell = true }) {
  const opts = {
    timeout: timeout_ms,
    shell: useShell,
    cwd: cwd ? safePath(cwd) : os.homedir(),
    maxBuffer: 1024 * 1024, // 1 MB stdout cap
  };
  try {
    const { stdout, stderr } = await execAsync(command, opts);
    return { exit_code: 0, stdout: stdout.trimEnd(), stderr: stderr.trimEnd() };
  } catch (err) {
    return {
      exit_code: err.code ?? 1,
      stdout: (err.stdout || '').trimEnd(),
      stderr: (err.stderr || err.message || '').trimEnd(),
    };
  }
}

async function get_clipboard(_params, { clipboard }) {
  // Try Electron IPC clipboard first, fall back to clipboardy
  if (clipboard) return { text: clipboard.readText() };
  const cb = await clipboardy();
  return { text: await cb.default.read() };
}

async function set_clipboard({ text }, { clipboard }) {
  if (clipboard) { clipboard.writeText(text); return { ok: true }; }
  const cb = await clipboardy();
  await cb.default.write(text);
  return { ok: true };
}

async function screenshot({ output_path } = {}) {
  const tmpFile = path.join(os.tmpdir(), `nexus-ss-${Date.now()}.png`);

  // Try screenshot-desktop first; fall back to PowerShell on Windows
  let buf;
  if (screenshotFn) {
    try {
      buf = await screenshotFn({ filename: tmpFile, format: 'png' });
      if (!buf) buf = await fs.readFile(tmpFile);
    } catch (_) { buf = null; }
  }

  if (!buf && process.platform === 'win32') {
    const ps = [
      'Add-Type -AssemblyName System.Windows.Forms',
      'Add-Type -AssemblyName System.Drawing',
      '$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds',
      '$bmp=New-Object System.Drawing.Bitmap($b.Width,$b.Height)',
      '$g=[System.Drawing.Graphics]::FromImage($bmp)',
      '$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size)',
      `$bmp.Save('${tmpFile.replace(/\\/g, '\\\\')}')`,
      '$g.Dispose();$bmp.Dispose()',
    ].join(';');
    await execAsync(`powershell -NoProfile -Command "${ps}"`);
    buf = await fs.readFile(tmpFile);
    await fs.unlink(tmpFile).catch(() => {});
  }

  if (!buf) throw new Error('No screenshot backend available on this platform');

  if (output_path) {
    const p = safePath(output_path);
    await fs.writeFile(p, buf);
    return { saved_to: p, bytes: buf.length };
  }
  return { base64: buf.toString('base64'), mime: 'image/png', bytes: buf.length };
}

async function open_path({ target_path }, { shell }) {
  const p = safePath(target_path);
  const err = await shell.openPath(p);
  if (err) throw new Error(err);
  return { opened: p };
}

async function get_info() {
  return {
    hostname:  os.hostname(),
    platform:  process.platform,
    arch:      os.arch(),
    home:      os.homedir(),
    cwd:       process.cwd(),
    uptime_s:  os.uptime(),
    free_mem:  os.freemem(),
    total_mem: os.totalmem(),
    cpus:      os.cpus().length,
    node:      process.version,
  };
}

module.exports = {
  read_file,
  write_file,
  list_dir,
  run_command,
  get_clipboard,
  set_clipboard,
  screenshot,
  open_path,
  get_info,
};
