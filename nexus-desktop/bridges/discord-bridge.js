'use strict';
// discord-bridge.js — webhook send (read-only listening lands in Phase 2).
//
// Reads DISCORD_WEBHOOK_URL from .env. If unset, every call returns disabled=true.

const DISCORD_WEBHOOK_URL = process.env.DISCORD_WEBHOOK_URL || '';

function isEnabled() {
  return Boolean(DISCORD_WEBHOOK_URL);
}

async function send({ content, username, embeds }) {
  if (!isEnabled()) {
    return { disabled: true, reason: 'DISCORD_WEBHOOK_URL not set in .env' };
  }
  const body = {};
  if (content)  body.content  = content;
  if (username) body.username = username;
  if (embeds)   body.embeds   = embeds;

  const res = await fetch(DISCORD_WEBHOOK_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Discord webhook returned ${res.status}: ${text}`);
  }
  return { ok: true };
}

module.exports = { isEnabled, send };
