/**
 * voiceMode.js — Continuous voice interaction for Nexus.
 *
 * State machine:
 *   IDLE → LISTENING → USER_SPEAKING → PROCESSING → RESPONDING → LISTENING
 *
 * Usage:
 *   import { startVoiceMode, stopVoiceMode, pauseMic, resumeMic, getState, STATES }
 *     from './voiceMode.js';
 *
 *   await startVoiceMode((transcript) => sendToNexus(transcript));
 *
 * Tunable via localStorage keys:
 *   vmSpeechThreshold   — RMS level that triggers speech (default 0.02)
 *   vmSilenceThreshold  — RMS level below which counts as silence (default 0.015)
 *   vmSilenceMs         — ms of silence before finalising utterance (default 700)
 *   vmMinSpeechMs       — min utterance length in ms; shorter = noise (default 300)
 *   vmPollMs            — VAD polling interval in ms (default 30)
 */

export const STATES = Object.freeze({
  IDLE:          'IDLE',
  LISTENING:     'LISTENING',
  USER_SPEAKING: 'USER_SPEAKING',
  PROCESSING:    'PROCESSING',
  RESPONDING:    'RESPONDING',
});

// ── Config (read per-tick so localStorage changes take effect live) ───────────

function _cfg() {
  return {
    speechThreshold:  parseFloat(localStorage.getItem('vmSpeechThreshold')  ?? '0.02'),
    silenceThreshold: parseFloat(localStorage.getItem('vmSilenceThreshold') ?? '0.015'),
    silenceDurationMs: parseInt(localStorage.getItem('vmSilenceMs')         ?? '700', 10),
    minSpeechMs:       parseInt(localStorage.getItem('vmMinSpeechMs')       ?? '300', 10),
    pollMs:            parseInt(localStorage.getItem('vmPollMs')            ?? '30',  10),
  };
}

const ASR_URL = '/asr';  // proxied by avatar server :8001 → gateway :8000/v1/asr

// ── Module-level state ────────────────────────────────────────────────────────

let _state       = STATES.IDLE;
let _onTranscript = null;

// Audio pipeline
let _audioCtx    = null;
let _analyser    = null;
let _micStream   = null;
let _mediaRec    = null;
let _audioChunks = [];

// Timers
let _vadTimer      = null;
let _silenceTimer  = null;

// State tracking
let _speechStart = 0;
let _pausedUntil = 0;  // epoch ms — hard suppression window (PTT, external pause)

// ── Internal ──────────────────────────────────────────────────────────────────

function _setState(next) {
  if (_state === next) return;
  const prev = _state;
  _state = next;
  console.log(`[voice] ${prev} → ${next}`);
  window.dispatchEvent(new CustomEvent('voiceStateChange', { detail: { state: next, prev } }));
  _syncAvatarState(next);
}

function _syncAvatarState(vmState) {
  const stateMap = {
    [STATES.LISTENING]:     'listening',
    [STATES.USER_SPEAKING]: 'listening',
    [STATES.PROCESSING]:    'thinking',
    [STATES.RESPONDING]:    'talking',
    [STATES.IDLE]:          'idle',
  };
  fetch('/set_state', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ state: stateMap[vmState] ?? 'idle' }),
  }).catch(() => {});
}

function _getRMS() {
  if (!_analyser) return 0;
  const buf = new Float32Array(_analyser.fftSize);
  _analyser.getFloatTimeDomainData(buf);
  let sum = 0;
  for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
  return Math.sqrt(sum / buf.length);
}

function _startRecording() {
  _audioChunks = [];
  const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
    ? 'audio/webm;codecs=opus'
    : 'audio/webm';
  _mediaRec = new MediaRecorder(_micStream, { mimeType: mime });
  _mediaRec.ondataavailable = (e) => { if (e.data.size > 0) _audioChunks.push(e.data); };
  _mediaRec.start(100);
  _speechStart = Date.now();
}

function _stopRecording() {
  return new Promise((resolve) => {
    if (!_mediaRec || _mediaRec.state === 'inactive') { resolve(null); return; }
    _mediaRec.onstop = () => resolve(new Blob(_audioChunks, { type: _mediaRec.mimeType }));
    _mediaRec.stop();
  });
}

async function _transcribe(blob) {
  const form = new FormData();
  form.append('file', blob, 'speech.webm');
  const resp = await fetch(ASR_URL, { method: 'POST', body: form });
  if (!resp.ok) throw new Error(`ASR HTTP ${resp.status}`);
  const json = await resp.json();
  return (json.text ?? '').trim();
}

// ── VAD loop ──────────────────────────────────────────────────────────────────

function _vadTick() {
  // Only run VAD when mic should be active
  if (_state === STATES.IDLE)        return;
  if (_state === STATES.RESPONDING)  return;
  if (_state === STATES.PROCESSING)  return;

  // Hard suppression window (set by pauseMic or PTT)
  if (Date.now() < _pausedUntil) {
    if (_state !== STATES.LISTENING) _setState(STATES.LISTENING);
    return;
  }

  const { speechThreshold, silenceThreshold, silenceDurationMs } = _cfg();
  const rms = _getRMS();

  if (_state === STATES.LISTENING) {
    if (rms > speechThreshold) {
      clearTimeout(_silenceTimer);
      _silenceTimer = null;
      _setState(STATES.USER_SPEAKING);
      _startRecording();
    }

  } else if (_state === STATES.USER_SPEAKING) {
    if (rms < silenceThreshold) {
      if (!_silenceTimer) {
        _silenceTimer = setTimeout(_onSilenceTimeout, silenceDurationMs);
      }
    } else {
      // Still talking — reset silence timer
      clearTimeout(_silenceTimer);
      _silenceTimer = null;
    }
  }
}

async function _onSilenceTimeout() {
  _silenceTimer = null;
  const elapsed = Date.now() - _speechStart;
  const blob    = await _stopRecording();

  const { minSpeechMs } = _cfg();
  if (elapsed < minSpeechMs || !blob || blob.size < 500) {
    // Too short — noise or accidental trigger
    _setState(STATES.LISTENING);
    return;
  }

  _setState(STATES.PROCESSING);
  try {
    const transcript = await _transcribe(blob);
    if (transcript) {
      _setState(STATES.RESPONDING);
      _onTranscript?.(transcript);
    } else {
      // Empty transcript (silence passed Whisper VAD) — keep listening
      _setState(STATES.LISTENING);
    }
  } catch (err) {
    console.error('[voice] ASR error:', err);
    _setState(STATES.LISTENING);
  }
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Start continuous voice mode.
 * @param {(transcript: string) => void} onTranscript  Called with each utterance.
 */
export async function startVoiceMode(onTranscript) {
  if (_state !== STATES.IDLE) return;
  _onTranscript = onTranscript;

  _micStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount:    1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl:  true,
    },
  });

  _audioCtx = new AudioContext();
  const src = _audioCtx.createMediaStreamSource(_micStream);
  _analyser = _audioCtx.createAnalyser();
  _analyser.fftSize = 512;
  _analyser.smoothingTimeConstant = 0;  // instant response — no trailing
  src.connect(_analyser);               // NOT wired to destination — no monitoring

  const { pollMs } = _cfg();
  _setState(STATES.LISTENING);
  _vadTimer = setInterval(_vadTick, pollMs);
  console.log('[voice] started — say something');
}

/**
 * Stop voice mode and release all audio resources.
 */
export function stopVoiceMode() {
  clearInterval(_vadTimer);
  clearTimeout(_silenceTimer);
  _vadTimer = _silenceTimer = null;

  if (_mediaRec && _mediaRec.state !== 'inactive') {
    try { _mediaRec.stop(); } catch {}
  }
  _micStream?.getTracks().forEach(t => t.stop());
  _audioCtx?.close().catch(() => {});

  _audioCtx = _analyser = _micStream = _mediaRec = null;
  _audioChunks = [];
  _onTranscript = null;
  _pausedUntil  = 0;

  _setState(STATES.IDLE);
  console.log('[voice] stopped');
}

/**
 * Suppress mic input for at least `ms` milliseconds (e.g. while Nexus speaks).
 * Safe to call repeatedly — always extends to the latest deadline.
 */
export function pauseMic(ms) {
  const until = Date.now() + ms;
  if (until > _pausedUntil) _pausedUntil = until;

  // Abort any in-progress recording immediately
  if (_state === STATES.USER_SPEAKING) {
    clearTimeout(_silenceTimer);
    _silenceTimer = null;
    if (_mediaRec && _mediaRec.state !== 'inactive') {
      try { _mediaRec.stop(); } catch {}
    }
  }
  if (_state !== STATES.IDLE && _state !== STATES.PROCESSING && _state !== STATES.RESPONDING) {
    _setState(STATES.RESPONDING);
  }
}

/**
 * Force-return to LISTENING regardless of pause deadline.
 * Called when Nexus finishes all TTS playback.
 */
export function resumeMic() {
  _pausedUntil = 0;
  if (_state === STATES.RESPONDING) {
    _setState(STATES.LISTENING);
  }
}

/** Current voice mode state string. */
export function getState() { return _state; }
