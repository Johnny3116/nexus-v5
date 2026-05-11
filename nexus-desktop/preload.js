'use strict';
const { contextBridge, ipcRenderer } = require('electron');

// ── Main chat API (used by renderer/chat.js) ─────────────────────────────
contextBridge.exposeInMainWorld('nexus', {
  clipboard: {
    read:  () => ipcRenderer.invoke('clipboard:read'),
    write: (text) => ipcRenderer.invoke('clipboard:write', text),
  },
  avatar: {
    url: () => ipcRenderer.invoke('avatar:url'),
  },
  settings: {
    get:    () => ipcRenderer.invoke('settings:get'),
    update: (patch) => ipcRenderer.invoke('settings:update', patch),
  },
  workspace: {
    get:   () => ipcRenderer.invoke('workspace:get'),
    pick:  () => ipcRenderer.invoke('workspace:pick'),
    list:  (sub) => ipcRenderer.invoke('workspace:list', sub),
    read:  (p) => ipcRenderer.invoke('workspace:read', p),
    write: (p, c) => ipcRenderer.invoke('workspace:write', p, c),
  },
  models: {
    list: () => ipcRenderer.invoke('models:list'),
  },
  bridges: {
    status: () => ipcRenderer.invoke('bridges:status'),
  },
  chat: {
    list:   () => ipcRenderer.invoke('chat:list'),
    load:   (id) => ipcRenderer.invoke('chat:load', id),
    create: (opts) => ipcRenderer.invoke('chat:create', opts),
    delete: (id) => ipcRenderer.invoke('chat:delete', id),
    rename: (id, title) => ipcRenderer.invoke('chat:rename', id, title),
    send:   (chatId, message) => ipcRenderer.invoke('chat:send', chatId, message),
    abort:  (chatId) => ipcRenderer.invoke('chat:abort', chatId),

    onChunk: (cb) => ipcRenderer.on('chat:chunk', (_e, payload) => cb(payload)),
    onDone:  (cb) => ipcRenderer.on('chat:done',  (_e, payload) => cb(payload)),
    onError: (cb) => ipcRenderer.on('chat:error', (_e, payload) => cb(payload)),
  },
});

// ── Legacy API (used by the avatar iframe's nexus-client.js) ─────────────
// Kept for backward compatibility — existing avatar code uses window.nexusDesktop.
contextBridge.exposeInMainWorld('nexusDesktop', {
  getClipboard: () => ipcRenderer.invoke('clipboard:read'),
  setClipboard: (text) => ipcRenderer.invoke('clipboard:write', text),
});
