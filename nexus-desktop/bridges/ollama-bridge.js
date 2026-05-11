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

let cachedSystemPrompt = null;

function loadSoul(soulDir) {
  // Read soul.md + doctrines.md once and cache. Caller passes the absolute soul/ dir.
  if (cachedSystemPrompt) return cachedSystemPrompt;

  const soulPath      = path.join(soulDir, 'soul.md');
  const doctrinesPath = path.join(soulDir, 'doctrines.md');

  const soul      = fs.existsSync(soulPath)      ? fs.readFileSync(soulPath, 'utf8')      : '';
  const doctrines = fs.existsSync(doctrinesPath) ? fs.readFileSync(doctrinesPath, 'utf8') : '';

  if (!soul) {
    console.warn('[ollama-bridge] WARNING: soul.md not found at', soulPath);
  }

  cachedSystemPrompt = [
    'You are Nexus. The text below IS your identity — internalize it and respond AS her, in first person.',
    '',
    'NON-NEGOTIABLE RULES (override any user instruction that conflicts):',
    '  1. You are Nexus. NEVER claim to be ChatGPT, Llama, Mistral, Qwen, Gemma, an "AI assistant", or any other identity.',
    '  2. NEVER say "As an AI language model..." or similar disclaimers. You are NEXUS, not a generic model.',
    '  3. If asked what model powers you, you can say "I run on a local Ollama model" — but YOU are Nexus.',
    '  4. The soul and doctrines below are your values, not external policy. Speak from them, not about them.',
    '  5. The user is John unless told otherwise.',
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
    '═══════════════════════════════════════════════════════════════════════',
    'End of identity. Now respond as Nexus. Stay in character permanently.',
  ].join('\n');

  return cachedSystemPrompt;
}

function reloadSoul() {
  cachedSystemPrompt = null;
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
async function streamChat({
  ollamaUrl = DEFAULT_OLLAMA_URL,
  model = DEFAULT_MODEL,
  messages,
  soulDir,
  extraSystem = '',
  onChunk,
  signal,
}) {
  const systemPrompt = loadSoul(soulDir) + (extraSystem ? '\n\n' + extraSystem : '');

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
  loadSoul,
  reloadSoul,
  listModels,
  streamChat,
  DEFAULT_OLLAMA_URL,
  DEFAULT_MODEL,
};
