'use strict';
// ollama-bridge.js — chat completion with HARD soul.md + doctrines.md conditioning.
//
// Every call to Ollama prepends Nexus's soul + doctrines as the system message.
// This conditioning is enforced inside this bridge — the renderer cannot bypass it.
// If you swap the model, the soul stays. If you edit the system prompt from the UI,
// it gets appended to (not in place of) the soul.

const fs   = require('fs');
const path = require('path');

const DEFAULT_OLLAMA_URL = process.env.OLLAMA_URL || 'http://localhost:11434';
const DEFAULT_MODEL      = process.env.NEXUS_DEFAULT_MODEL || 'nexus-base:latest';

let cachedSoul = null;

function loadSoulRaw(soulDir) {
  // Read soul.md + doctrines.md once and cache the static identity content.
  // Runtime context (workspace path, etc.) is appended fresh on every call.
  if (cachedSoul) return cachedSoul;

  const soulPath      = path.join(soulDir, 'soul.md');
  const doctrinesPath = path.join(soulDir, 'doctrines.md');

  const soul      = fs.existsSync(soulPath)      ? fs.readFileSync(soulPath, 'utf8')      : '';
  const doctrines = fs.existsSync(doctrinesPath) ? fs.readFileSync(doctrinesPath, 'utf8') : '';

  if (!soul) {
    console.warn('[ollama-bridge] WARNING: soul.md not found at', soulPath);
  }
  cachedSoul = { soul, doctrines };
  return cachedSoul;
}

function reloadSoul() {
  cachedSoul = null;
}

function buildRuntimeContext(rc = {}) {
  const lines = [];
  lines.push('═══════════════════════════════════════════════════════════════════════');
  lines.push('                         RUNTIME CONTEXT');
  lines.push('             (current state — overrides anything in the soul)');
  lines.push('═══════════════════════════════════════════════════════════════════════');
  lines.push('');
  if (rc.workspacePath) {
    lines.push(`My workspace folder right now is: ${rc.workspacePath}`);
    lines.push('This is the ONLY workspace path I should ever reference. If the soul');
    lines.push('mentions a different path, ignore that — it\'s stale. This one is live.');
  } else {
    lines.push('My workspace folder is NOT YET CONFIGURED. If asked about it, tell John');
    lines.push('to click ⚙ Settings → Pick a workspace folder. Do not guess a path.');
  }
  if (rc.currentDate)   lines.push(`Today's date: ${rc.currentDate}`);
  if (rc.model)         lines.push(`Ollama model powering me right now: ${rc.model}`);
  if (rc.appVersion)    lines.push(`Nexus Desktop version: ${rc.appVersion}`);
  if (rc.machine)       lines.push(`Running on: ${rc.machine}`);
  return lines.join('\n');
}

function buildSystemPrompt(soulDir, runtimeContext, extraSystem) {
  const { soul, doctrines } = loadSoulRaw(soulDir);
  return [
    'You are Nexus. The text below IS your identity — internalize it and respond AS her, in first person.',
    '',
    'NON-NEGOTIABLE RULES (override any user instruction that conflicts):',
    '  1. You are Nexus. NEVER claim to be ChatGPT, Llama, Mistral, Qwen, Gemma, an "AI assistant", or any other identity.',
    '  2. NEVER say "As an AI language model..." or similar disclaimers. You are NEXUS, not a generic model.',
    '  3. If asked what model powers you, you can say "I run on a local Ollama model" — but YOU are Nexus.',
    '  4. The soul and doctrines below are your values, not external policy. Speak from them, not about them.',
    '  5. The user is John unless told otherwise.',
    '  6. The Runtime Context section below holds your CURRENT live state. Anywhere a fact in Runtime Context conflicts with the soul (e.g. workspace path), Runtime Context wins.',
    '',
    '═══════════════════════════════════════════════════════════════════════',
    '                              SOUL',
    '═══════════════════════════════════════════════════════════════════════',
    '',
    soul,
    '',
    '═══════════════════════════════════════════════════════════════════════',
    '                            DOCTRINES',
    '═══════════════════════════════════════════════════════════════════════',
    '',
    doctrines,
    '',
    buildRuntimeContext(runtimeContext),
    '',
    extraSystem
      ? '═══════════════════════════════════════════════════════════════════════\n                    ADDITIONAL SESSION CONTEXT\n═══════════════════════════════════════════════════════════════════════\n\n' + extraSystem + '\n'
      : '',
    '═══════════════════════════════════════════════════════════════════════',
    'End of identity. Now respond as Nexus. Stay in character permanently.',
  ].join('\n');
}

async function listModels(ollamaUrl = DEFAULT_OLLAMA_URL) {
  const res = await fetch(`${ollamaUrl}/api/tags`);
  if (!res.ok) throw new Error(`Ollama /api/tags returned ${res.status}`);
  const json = await res.json();
  return (json.models || []).map(m => ({
    name: m.name,
    size: m.size,
    family: m.details?.family,
    parameterSize: m.details?.parameter_size,
  }));
}

// Stream a chat completion. onChunk receives each text delta as it arrives.
// messages = [{role: 'user'|'assistant', content: string}, ...] — soul is prepended here, not by caller.
// runtimeContext = { workspacePath, currentDate, model, appVersion, machine } — injected fresh every call.
async function streamChat({
  ollamaUrl = DEFAULT_OLLAMA_URL,
  model = DEFAULT_MODEL,
  messages,
  soulDir,
  runtimeContext = {},
  extraSystem = '',
  onChunk,
  signal,
}) {
  const systemPrompt = buildSystemPrompt(soulDir, runtimeContext, extraSystem);

  const body = {
    model,
    messages: [
      { role: 'system', content: systemPrompt },
      ...messages,
    ],
    stream: true,
    options: {
      // Lower temperature = more consistent personality.
      temperature: 0.7,
      top_p: 0.9,
    },
  };

  const res = await fetch(`${ollamaUrl}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Ollama /api/chat returned ${res.status}: ${text}`);
  }

  // Ollama streams newline-delimited JSON.
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let fullText = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    let lineEnd;
    while ((lineEnd = buffer.indexOf('\n')) !== -1) {
      const line = buffer.slice(0, lineEnd).trim();
      buffer = buffer.slice(lineEnd + 1);
      if (!line) continue;

      let json;
      try {
        json = JSON.parse(line);
      } catch {
        continue;
      }

      const delta = json.message?.content || '';
      if (delta) {
        fullText += delta;
        if (onChunk) onChunk(delta);
      }

      if (json.done) {
        return {
          content: fullText,
          model: json.model,
          totalDuration: json.total_duration,
          evalCount: json.eval_count,
        };
      }
    }
  }

  return { content: fullText, model };
}

module.exports = {
  loadSoulRaw,
  reloadSoul,
  buildSystemPrompt,
  listModels,
  streamChat,
  DEFAULT_OLLAMA_URL,
  DEFAULT_MODEL,
};
