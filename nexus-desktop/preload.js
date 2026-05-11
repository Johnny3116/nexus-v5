'use strict';
const { contextBridge, ipcRenderer } = require('electron');

// Minimal bridge — renderer can query host info and trigger clipboard via IPC
contextBridge.exposeInMainWorld('nexusDesktop', {
  getClipboard: () => ipcRenderer.invoke('clipboard:read'),
  setClipboard: (text) => ipcRenderer.invoke('clipboard:write', text),
});
