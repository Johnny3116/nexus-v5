'use strict';
// tools.js — tool definitions and executor for chat.
//
// Tools follow OpenAI's function-calling schema (Ollama is wire-compatible).
// When the model produces a tool_call, ollama-bridge calls execute() with
// the tool name and arguments. execute() dispatches to the right bridge.
//
// Phase 2A scope: workspace file ops only. Phase 2B adds Discord send,
// Supabase memory read/write, and MCP server invocation.

const workspace = require('./workspace-bridge');
const discord   = require('./discord-bridge');

const WORKSPACE_TOOLS = [
  {
    type: 'function',
    function: {
      name: 'workspace_list',
      description: 'List files and folders inside the user\'s workspace. Use this when the user asks "what\'s in my workspace" or before reading/writing files.',
      parameters: {
        type: 'object',
        properties: {
          path: {
            type: 'string',
            description: 'Optional subdirectory relative to the workspace root. Use "." or omit for the root.',
          },
        },
        required: [],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'workspace_read',
      description: 'Read the contents of a text file in the workspace. Use this when the user asks you to look at, summarize, or modify an existing file.',
      parameters: {
        type: 'object',
        properties: {
          path: {
            type: 'string',
            description: 'Path relative to the workspace root, e.g. "notes.md" or "src/main.py".',
          },
        },
        required: ['path'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'workspace_write',
      description: 'Create a new file or overwrite an existing file in the workspace. You MUST use this whenever the user asks you to create, save, write, or make a file — do NOT just paste file contents in chat as a substitute.',
      parameters: {
        type: 'object',
        properties: {
          path: {
            type: 'string',
            description: 'Path relative to the workspace root, e.g. "hello.py" or "docs/readme.md". Parent directories are created automatically.',
          },
          content: {
            type: 'string',
            description: 'The full file contents to write.',
          },
        },
        required: ['path', 'content'],
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'workspace_delete',
      description: 'Delete a file or folder from the workspace. Use sparingly. When unclear, ask the user to confirm before calling this.',
      parameters: {
        type: 'object',
        properties: {
          path: {
            type: 'string',
            description: 'Path relative to the workspace root.',
          },
        },
        required: ['path'],
      },
    },
  },
];

const DISCORD_TOOLS = [
  {
    type: 'function',
    function: {
      name: 'discord_send',
      description: 'Send a message to Discord via the configured webhook. Use only when the user explicitly asks you to send/post/notify Discord.',
      parameters: {
        type: 'object',
        properties: {
          content: { type: 'string', description: 'Message text to send.' },
        },
        required: ['content'],
      },
    },
  },
];

function allTools() {
  const tools = [...WORKSPACE_TOOLS];
  if (discord.isEnabled()) tools.push(...DISCORD_TOOLS);
  return tools;
}

async function execute(name, args = {}) {
  switch (name) {
    case 'workspace_list': {
      const items = await workspace.list(args.path || '.');
      return { ok: true, items };
    }
    case 'workspace_read': {
      const content = await workspace.read(args.path);
      return { ok: true, path: args.path, content, bytes: Buffer.byteLength(content, 'utf8') };
    }
    case 'workspace_write': {
      const r = await workspace.write(args.path, args.content);
      return { ok: true, ...r };
    }
    case 'workspace_delete': {
      const r = await workspace.remove(args.path);
      return { ok: true, ...r };
    }
    case 'discord_send': {
      const r = await discord.send({ content: args.content });
      return r;
    }
    default:
      throw new Error(`Unknown tool: ${name}`);
  }
}

module.exports = { allTools, execute };
