// chatbar.js — chat + mic overlay, routes via the existing WebSocket connection.
// Sends {type:"user_chat", message} over WS to server.py's ws_endpoint,
// which runs LLM→TTS and broadcasts start_animation back to all clients.
// No cross-origin fetch — avoids cert-trust issues on a different port.

import { WS_URL } from './config.js';

// ── styles ──────────────────────────────────────────────────────────────────
function injectStyles() {
  const css = `
  #nexus-chatbar {
    position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%);
    display: flex; gap: 8px; align-items: center;
    width: min(760px, 92vw);
    padding: 10px 12px;
    background: rgba(16, 18, 24, 0.72);
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 14px;
    backdrop-filter: blur(10px);
    font-family: system-ui, -apple-system, Segoe UI, sans-serif;
    z-index: 1000;
    box-shadow: 0 8px 24px rgba(0,0,0,0.35);
  }
  #nexus-chatbar input[type="text"] {
    flex: 1; min-width: 0;
    background: rgba(0,0,0,0.35);
    color: #fff;
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 10px;
    padding: 10px 12px;
    font-size: 15px;
    outline: none;
  }
  #nexus-chatbar input[type="text"]::placeholder { color: rgba(255,255,255,0.45); }
  #nexus-chatbar button {
    background: rgba(120, 80, 220, 0.85);
    color: #fff; border: 0; border-radius: 10px;
    padding: 10px 14px; font-size: 14px; cursor: pointer;
    transition: transform 0.05s ease, background 0.15s ease;
  }
  #nexus-chatbar button:hover  { background: rgba(140,100,240,0.95); }
  #nexus-chatbar button:active { transform: scale(0.97); }
  #nexus-chatbar button.mic.recording {
    background: rgba(220,60,60,0.9);
    animation: nexus-pulse 1.1s ease-in-out infinite;
  }
  #nexus-chatbar button:disabled { opacity: 0.55; cursor: default; }
  #nexus-status {
    position: fixed; left: 50%; bottom: 86px; transform: translateX(-50%);
    color: rgba(255,255,255,0.85);
    font-family: system-ui, sans-serif; font-size: 12px;
    background: rgba(0,0,0,0.45); padding: 4px 10px; border-radius: 8px;
    pointer-events: none; opacity: 0; transition: opacity 0.2s ease;
    z-index: 1000;
  }
  #nexus-status.visible { opacity: 1; }
  @keyframes nexus-pulse {
    0%,100% { box-shadow: 0 0 0 0 rgba(220,60,60,0.6); }
    50%      { box-shadow: 0 0 0 10px rgba(220,60,60,0); }
  }
  `;
  const style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);
}

// ── status toast ─────────────────────────────────────────────────────────────
let _statusTimer = null;
function showStatus(msg, ms = 2200) {
  let s = document.getElementById('nexus-status');
  if (!s) { s = Object.assign(document.createElement('div'), { id: 'nexus-status' }); document.body.appendChild(s); }
  s.textContent = msg;
  s.classList.add('visible');
  clearTimeout(_statusTimer);
  if (ms > 0) _statusTimer = setTimeout(() => s.classList.remove('visible'), ms);
}

// ── WS sender ────────────────────────────────────────────────────────────────
let _ws = null;
let _wsReady = false;
const _pending = [];
let _wakeAt = 0;
let _sentAt = 0;

function ensureWS() {
  if (_ws && (_ws.readyState === WebSocket.OPEN || _ws.readyState === WebSocket.CONNECTING)) return;
  _ws = new WebSocket(WS_URL);
  _ws.onopen = () => {
    _wsReady = true;
    for (const m of _pending.splice(0)) _ws.send(m);
  };
  _ws.onclose = () => { _wsReady = false; setTimeout(ensureWS, 2000); };
  _ws.onerror = () => { _wsReady = false; };
  _ws.onmessage = (ev) => {
    try {
      const d = JSON.parse(ev.data);
      if (d.type === 'chat_error') {
        showStatus(`Error: ${d.error}`, 5000);
      } else if (d.type === 'start_animation' || d.type === 'chat_response') {
        if (_sentAt) console.log(`[lat] server→response ${Date.now() - _sentAt}ms`);
        // Response arrived — clear the "thinking" toast
        clearTimeout(_statusTimer);
        const s = document.getElementById('nexus-status');
        if (s) s.classList.remove('visible');
        // Pause wake word while Nexus speaks — avoids self-trigger from TTS playback
        const durSec = d.audio_duraction ?? d.audio_duration ?? d.duration;
        const durMs = (typeof durSec === 'number' ? durSec * (durSec < 100 ? 1000 : 1) : 8000) + 500;
        window.wakeListener?.pause(durMs);
      }
    } catch (_) {}
  };
}

function wsSend(obj) {
  const raw = JSON.stringify(obj);
  if (_ws && _ws.readyState === WebSocket.OPEN) {
    _ws.send(raw);
  } else {
    _pending.push(raw);
    ensureWS();
  }
}

// ── chat submit ──────────────────────────────────────────────────────────────
function sendMessage(text) {
  const clean = (text || '').trim();
  if (!clean) return;
  _sentAt = Date.now();
  if (_wakeAt) console.log(`[lat] wake→send ${_sentAt - _wakeAt}ms (text="${clean}")`);
  showStatus('Nexus is thinking…', 0);
  wsSend({ type: 'user_chat', message: clean });
  // Clear thinking status once we get start_animation back (handled via app.js WS)
  // Fallback: clear after 30s
  clearTimeout(_statusTimer);
  _statusTimer = setTimeout(() => {
    const s = document.getElementById('nexus-status');
    if (s && s.textContent === 'Nexus is thinking…') s.classList.remove('visible');
  }, 30000);
}

// ── speech recognition ───────────────────────────────────────────────────────
function setupMic(input, micBtn) {
  const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Rec) {
    micBtn.disabled = true;
    micBtn.title = 'Speech recognition not available — use Chrome or Edge';
    return;
  }
  const rec = new Rec();
  rec.lang = 'en-US';
  rec.interimResults = true;
  rec.continuous = false;

  let _recStartAt = 0;
  rec.onstart = () => { _recStartAt = Date.now(); console.log('[lat] rec start'); };
  rec.onresult = (ev) => {
    let interim = '', final = '';
    for (let i = ev.resultIndex; i < ev.results.length; i++) {
      const r = ev.results[i];
      if (r.isFinal) final += r[0].transcript;
      else interim += r[0].transcript;
    }
    input.value = (final || interim).trim();
    if (final && _recStartAt) console.log(`[lat] rec final after ${Date.now() - _recStartAt}ms: "${final}"`);
  };
  rec.onerror = (ev) => { showStatus(`Mic error: ${ev.error}`, 3000); };
  rec.onend = () => {
    micBtn.classList.remove('recording');
    micBtn.textContent = '🎤';
    const t = input.value.trim();
    if (t) { sendMessage(t); input.value = ''; }
  };

  micBtn.addEventListener('click', async () => {
    if (micBtn.classList.contains('recording')) { rec.stop(); return; }
    try { await navigator.mediaDevices.getUserMedia({ audio: true }); }
    catch { showStatus('Mic permission denied', 3000); return; }
    input.value = '';
    window.wakeListener?.pause(60000); // pause until rec.onend resumes
    try { rec.start(); } catch (e) { console.warn('rec.start', e); window.wakeListener?.resume(); return; }
    micBtn.classList.add('recording');
    micBtn.textContent = '■';
    showStatus('Listening…', 0);
  });

  const _origOnEnd = rec.onend;
  rec.onend = (ev) => {
    _origOnEnd?.(ev);
    // If no message was sent, resume now; otherwise the start_animation handler will pause through TTS.
    if (!input.value.trim()) window.wakeListener?.resume();
  };
}

// ── mount ────────────────────────────────────────────────────────────────────
function mount() {
  injectStyles();
  ensureWS();

  const input = document.createElement('input');
  input.type = 'text'; input.placeholder = 'Say something to Nexus…'; input.autocomplete = 'off';

  const sendBtn = document.createElement('button');
  sendBtn.textContent = 'Send';

  const micBtn = document.createElement('button');
  micBtn.className = 'mic'; micBtn.textContent = '🎤'; micBtn.title = 'Click to talk';

  const wakeBtn = document.createElement('button');
  const wakeOn = () => localStorage.getItem('wakewordEnabled') === 'true';
  const paintWake = () => {
    wakeBtn.textContent = wakeOn() ? '👂 On' : '👂 Off';
    wakeBtn.title = wakeOn() ? 'Hey Nexus wake word: ON' : 'Hey Nexus wake word: OFF';
  };
  paintWake();
  wakeBtn.addEventListener('click', async () => {
    const next = !wakeOn();
    localStorage.setItem('wakewordEnabled', next ? 'true' : 'false');
    paintWake();
    try {
      if (next) await window.wakeListener?.start();
      else await window.wakeListener?.stop();
      showStatus(next ? 'Wake word enabled — say "Hey Nexus"' : 'Wake word disabled', 2500);
    } catch (e) {
      showStatus(`Wake word error: ${e.message}`, 4000);
    }
  });

  const bar = document.createElement('div');
  bar.id = 'nexus-chatbar';
  bar.append(input, micBtn, wakeBtn, sendBtn);
  document.body.appendChild(bar);

  window.addEventListener('wakeword', () => {
    _wakeAt = Date.now();
    console.log('[lat] wake fired');
    showStatus('Hey Nexus detected — listening…', 2000);
    if (!micBtn.classList.contains('recording')) micBtn.click();
  });

  const submit = () => {
    const t = input.value.trim();
    if (!t) return;
    input.value = '';
    sendMessage(t);
  };
  sendBtn.addEventListener('click', submit);
  input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); submit(); } });

  setupMic(input, micBtn);
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, { once: true });
else mount();
