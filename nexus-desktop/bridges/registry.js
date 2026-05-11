'use strict';
// registry.js — single place that knows which bridges exist and their status.
//
// Each bridge is independently loadable. When a bridge can't initialize (missing
// env var, server down), it reports disabled — the chat UI shows it greyed out.

const ollama    = require('./ollama-bridge');
const workspace = require('./workspace-bridge');
const discord   = require('./discord-bridge');

// Existing tools/ modules (MCP + Supabase) are still mounted on the Express
// tool server in main.js — we just expose their availability here too.

function status() {
  return {
    ollama: {
      name: 'Ollama (local chat)',
      enabled: true,
      url: ollama.DEFAULT_OLLAMA_URL,
      defaultModel: ollama.DEFAULT_MODEL,
    },
    workspace: {
      name: 'Workspace (local R/W)',
      enabled: Boolean(workspace.getWorkspace()),
      path: workspace.getWorkspace(),
    },
    discord: {
      name: 'Discord (webhook send)',
      enabled: discord.isEnabled(),
    },
    supabase: {
      name: 'Supabase (memories/notes)',
      enabled: Boolean(process.env.SUPABASE_URL && process.env.SUPABASE_KEY),
    },
    mcp: {
      name: 'MCP servers',
      enabled: true, // configured per config/mcp.json
      configFile: 'config/mcp.json',
    },
  };
}

module.exports = {
  ollama,
  workspace,
  discord,
  status,
};
