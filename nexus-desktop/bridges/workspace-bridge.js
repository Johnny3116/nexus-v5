'use strict';
// workspace-bridge.js — scoped read/write to the user-chosen workspace folder.
//
// Every path the renderer passes is resolved against the workspace root and
// rejected if it escapes (no `..` traversal, no absolute paths). Nexus has
// full read/write inside the workspace, and nothing outside it.

const fs   = require('fs');
const fsp  = require('fs/promises');
const path = require('path');

let workspaceRoot = null;

function setWorkspace(absPath) {
  if (!absPath) {
    workspaceRoot = null;
    return null;
  }
  const resolved = path.resolve(absPath);
  if (!fs.existsSync(resolved)) {
    fs.mkdirSync(resolved, { recursive: true });
  }
  const stat = fs.statSync(resolved);
  if (!stat.isDirectory()) {
    throw new Error(`Workspace path is not a directory: ${resolved}`);
  }
  workspaceRoot = resolved;
  return workspaceRoot;
}

function getWorkspace() {
  return workspaceRoot;
}

function resolveInside(relPath) {
  if (!workspaceRoot) {
    throw new Error('Workspace not set — pick a folder first.');
  }
  if (typeof relPath !== 'string') {
    throw new Error('Path must be a string.');
  }
  // Reject absolute paths and traversal attempts.
  if (path.isAbsolute(relPath)) {
    throw new Error('Absolute paths are not allowed — paths must be relative to the workspace.');
  }
  const resolved = path.resolve(workspaceRoot, relPath);
  if (!resolved.startsWith(workspaceRoot + path.sep) && resolved !== workspaceRoot) {
    throw new Error(`Path escapes workspace: ${relPath}`);
  }
  return resolved;
}

async function list(subpath = '.') {
  const dir = resolveInside(subpath);
  const entries = await fsp.readdir(dir, { withFileTypes: true });
  return entries.map(e => ({
    name: e.name,
    type: e.isDirectory() ? 'directory' : 'file',
    path: path.posix.join(subpath.replace(/\\/g, '/'), e.name).replace(/^\.\//, ''),
  }));
}

async function read(relPath) {
  const file = resolveInside(relPath);
  return fsp.readFile(file, 'utf8');
}

async function write(relPath, content) {
  const file = resolveInside(relPath);
  await fsp.mkdir(path.dirname(file), { recursive: true });
  await fsp.writeFile(file, content, 'utf8');
  return { path: relPath, bytes: Buffer.byteLength(content, 'utf8') };
}

async function exists(relPath) {
  try {
    await fsp.access(resolveInside(relPath));
    return true;
  } catch {
    return false;
  }
}

async function remove(relPath) {
  const file = resolveInside(relPath);
  await fsp.rm(file, { recursive: true, force: true });
  return { path: relPath };
}

module.exports = {
  setWorkspace,
  getWorkspace,
  list,
  read,
  write,
  exists,
  remove,
};
