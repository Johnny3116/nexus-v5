import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';
import { createVRMAnimationClip, VRMAnimationLoaderPlugin } from '@pixiv/three-vrm-animation';

import { VRM_PATH, WS_URL } from './config.js';

// ---- Helper: ensure absolute URL for audio paths ----
function ensureAbsoluteUrl(url) {
  try {
    new URL(url);
    return url;
  } catch (e) {
    if (!url) return url;
    if (url.startsWith('/')) return `${location.origin}${url}`;
    return `${location.origin}/${url}`;
  }
}
import { loadVRM } from './vrmLoader.js';
import { AudioManager } from './audioManager.js';
import { AnimationManager } from './animationManager.js';
import { loadMixamoAnimation } from './loadMixamoAnimation.js';
import { connectWS, getWS } from "./connect.js";
import { setPlanPanelSocket, handlePlanResponse } from "./planPanel.js";
import { handleBuildResponse } from "./buildPanel.js";
import { showSubtitleStreaming } from "./subtitles.js";


// Strip root motion (hips position) from animation clip - keeps animation in place
function stripRootMotionFromClip(clip, vrm) {
  const hipsNodeName = vrm.humanoid?.getNormalizedBoneNode('hips')?.name;
  if (!hipsNodeName) return clip;

  const newTracks = [];

  for (const track of clip.tracks) {
    // Check if this is a hips position track
    if (track.name.includes(hipsNodeName) && track.name.includes('.position')) {
      // Zero out X and Z, keep Y for vertical motion
      const newValues = new Float32Array(track.values.length);
      const stride = track.getValueSize();

      for (let i = 0; i < track.values.length; i += stride) {
        newValues[i] = 0;     // X - zero
        newValues[i + 1] = track.values[i + 1]; // Y - keep
        newValues[i + 2] = 0; // Z - zero
      }

      const newTrack = new track.constructor(track.name, track.times, newValues);
      newTracks.push(newTrack);
      console.log('🦶 Stripped root motion from VRMA hips position');
    } else {
      newTracks.push(track);
    }
  }

  return new THREE.AnimationClip(clip.name + '_locked', clip.duration, newTracks);
}

// Get the final position offset from an animation clip's hips track
function getAnimationEndPosition(clip, vrm) {
  const hipsNodeName = vrm.humanoid?.getNormalizedBoneNode('hips')?.name;
  if (!hipsNodeName) return null;

  for (const track of clip.tracks) {
    if (track.name.includes(hipsNodeName) && track.name.includes('.position')) {
      const stride = track.getValueSize();
      const lastIndex = track.values.length - stride;

      // Get first and last positions
      const startX = track.values[0];
      const startZ = track.values[2];
      const endX = track.values[lastIndex];
      const endZ = track.values[lastIndex + 2];

      // Return the delta (movement during animation)
      return new THREE.Vector3(endX - startX, 0, endZ - startZ);
    }
  }
  return null;
}

// Apply animation end position to VRM scene
function applyAnimationEndPosition(vrm, positionDelta, rotation = null) {
  if (!positionDelta) return;

  // Apply the position offset to the VRM scene
  // The hips animation moves relative to scene, so we add to scene position
  vrm.scene.position.x += positionDelta.x;
  vrm.scene.position.z += positionDelta.z;

  console.log(`📍 Applied end position: (${positionDelta.x.toFixed(2)}, ${positionDelta.z.toFixed(2)})`);
}

// Get current hips world position (for real-time tracking)
function getHipsWorldPosition(vrm) {
  const hipsNode = vrm.humanoid?.getNormalizedBoneNode('hips');
  if (!hipsNode) return null;

  const worldPos = new THREE.Vector3();
  hipsNode.getWorldPosition(worldPos);
  return worldPos;
}

// Trim animation clip utility
function trimAnimationClip(clip, startTime, endTime) {
  startTime = Math.max(0, startTime || 0);
  const fullDuration = clip.duration;
  endTime = (typeof endTime === 'number' && endTime >= 0) ? Math.min(fullDuration, endTime) : fullDuration;

  if (endTime <= startTime) {
    console.warn('trimAnimationClip: invalid range', { startTime, endTime, duration: fullDuration });
    return null;
  }

  const newTracks = [];

  for (const track of clip.tracks) {
    const times = track.times;
    const values = track.values;
    const stride = track.getValueSize();

    const keptTimes = [];
    const keptValues = [];

    for (let i = 0; i < times.length; i++) {
      const t = times[i];
      if (t >= startTime && t <= endTime) {
        keptTimes.push(t - startTime);
        const baseIndex = i * stride;
        for (let s = 0; s < stride; s++) {
          keptValues.push(values[baseIndex + s]);
        }
      }
    }

    if (keptTimes.length > 0) {
      const newTimes = new Float32Array(keptTimes);
      const newValues = new Float32Array(keptValues);
      
      let NewTrack;
      try {
        NewTrack = new track.constructor(track.name, newTimes, newValues, track.getInterpolation ? track.getInterpolation() : undefined);
      } catch (err) {
        NewTrack = new track.constructor(track.name, newTimes, newValues);
      }
      
      newTracks.push(NewTrack);
    }
  }

  const newDuration = endTime - startTime;
  const newName = `${clip.name || 'vrma_clip'}_trimmed_${startTime.toFixed(3)}-${endTime.toFixed(3)}`;
  return new THREE.AnimationClip(newName, newDuration, newTracks);
}


// ---- PlaybackController (persistent audio element for mobile) ----
class PlaybackController {
  constructor(audioMgr) {
    this.audioMgr = audioMgr;
    this._inited = false;
    this._unlocked = false;
    this.el = null;
    this._analyserAttached = false;
  }

  initPersistent() {
    if (this._inited) return;
    this._inited = true;

    // Create persistent audio element
    if (!this.audioMgr.audioElement) {
      const a = document.createElement('audio');
      a.crossOrigin = 'anonymous';
      a.preload = 'auto';
      a.playsInline = true;
      a.setAttribute('playsinline', '');
      a.setAttribute('webkit-playsinline', '');
      a.style.display = 'none';
      document.body.appendChild(a);
      this.audioMgr.audioElement = a;
    }
    this.el = this.audioMgr.audioElement;

    // Create AudioContext if needed
    try {
      if (!this.audioMgr.audioContext) {
        const AC = window.AudioContext || window.webkitAudioContext;
        if (AC) {
          this.audioMgr.audioContext = new AC();
        }
      }

      // Create analyser if we have context but not analyser
      if (this.audioMgr.audioContext && !this.audioMgr.analyser) {
        this._tryAttachAnalyser();
      }

      // Visibility resume helper
      document.addEventListener('visibilitychange', async () => {
        if (document.visibilityState === 'visible' &&
            this.audioMgr.audioContext &&
            this.audioMgr.audioContext.state === 'suspended') {
          try {
            await this.audioMgr.audioContext.resume();
            console.log('🔁 Resumed audio context on visibility change');
          } catch (e) {}
        }
      });
    } catch (e) {
      console.warn('PlaybackController init error:', e);
    }
  }

  // Unlock audio on user gesture - tries multiple strategies
  async unlockOnce() {
    if (this._unlocked) return true;

    this.initPersistent();

    // 1) Try to resume/create AudioContext
    let ctx = null;
    try {
      if (!this.audioMgr.audioContext) {
        const AC = window.AudioContext || window.webkitAudioContext;
        if (AC) {
          this.audioMgr.audioContext = new AC();
          console.log('🔧 Created AudioContext (unlock)');
        }
      }
      ctx = this.audioMgr.audioContext;
      if (ctx && ctx.state === 'suspended') {
        try { await ctx.resume(); } catch (e) { console.warn('resume() failed:', e); }
      }
    } catch (e) {
      console.warn('AudioContext creation/resume failed:', e);
    }

    // 2) Silent buffer unlocks AudioContext (for analyser/lip-sync). BUT iOS
    //    gates HTMLAudioElement.play() independently — it must be primed in
    //    the SAME gesture. So we run both here and fall through to step 3 if
    //    the element prime fails.
    let ctxUnlocked = false;
    try {
      if (ctx && ctx.state === 'running') {
        const sampleRate = ctx.sampleRate || 44100;
        const length = Math.max(1, Math.floor(sampleRate * 0.01));
        const buffer = ctx.createBuffer(1, length, sampleRate);
        const src = ctx.createBufferSource();
        src.buffer = buffer;
        src.connect(ctx.destination);
        src.start(0);
        await new Promise(res => setTimeout(res, 40));
        try { src.stop(); } catch (e) {}
        ctxUnlocked = true;
        console.log('🔓 AudioContext unlocked via silent buffer');
      }
    } catch (e) {
      console.warn('Silent buffer unlock failed:', e);
    }

    // 3) Fallback: muted play/pause on persistent element
    try {
      const el = this.el;
      if (!el) throw new Error('No audio element');
      const hadSrc = !!el.src;
      if (!hadSrc) {
        el.src = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQAAAAA=';
      }
      el.muted = true;
      el.playsInline = true;
      el.setAttribute('playsinline', '');
      el.setAttribute('webkit-playsinline', '');

      const p = new Promise((resolve, reject) => {
        let done = false;
        const onPlaying = () => { if (!done) { done = true; cleanup(); resolve(true); } };
        const onError = () => { if (!done) { done = true; cleanup(); reject(new Error('audio error')); } };
        const timeoutId = setTimeout(() => { if (!done) { done = true; cleanup(); reject(new Error('timeout')); } }, 1200);
        function cleanup() {
          el.removeEventListener('playing', onPlaying);
          el.removeEventListener('error', onError);
          clearTimeout(timeoutId);
        }
        el.addEventListener('playing', onPlaying);
        el.addEventListener('error', onError);
        try {
          const prom = el.play();
          if (prom && prom.catch) prom.catch(() => {});
        } catch (err) { cleanup(); reject(err); }
      });

      await p;
      try { el.pause(); el.currentTime = 0; } catch (e) {}
      el.muted = false;
      this._unlocked = true;
      this._tryAttachAnalyser();
      console.log('🔓 Unlocked via muted audio element fallback');
      return true;
    } catch (e) {
      console.warn('Muted element fallback failed:', e);
    }

    // Partial win: AudioContext unlocked but element prime failed.
    // Lip-sync will work; audio playback may still need a fallback on first message.
    if (ctxUnlocked) {
      this._unlocked = true;
      this._tryAttachAnalyser();
      console.log('🔓 Partial unlock: AudioContext only (element prime failed)');
      return true;
    }
    console.warn('unlockOnce: could not unlock audio on this gesture');
    return false;
  }

  _tryAttachAnalyser() {
    try {
      if (this.audioMgr.audioContext && this.el && !this.audioMgr.analyser && !this._analyserAttached) {
        try {
          const src = this.audioMgr.audioContext.createMediaElementSource(this.el);
          const analyser = this.audioMgr.audioContext.createAnalyser();
          analyser.fftSize = 2048;
          src.connect(analyser);
          analyser.connect(this.audioMgr.audioContext.destination);
          this.audioMgr.analyser = analyser;
          this.audioMgr.timeDomainData = new Uint8Array(analyser.fftSize);
          this.audioMgr.freqData = new Uint8Array(analyser.frequencyBinCount);
          this._analyserAttached = true;
          console.log('🎛️ Analyser attached to persistent element');
        } catch (e) {
          console.warn('attachAnalyser failed:', e);
        }
      }
    } catch (e) {
      console.warn('Error in _tryAttachAnalyser:', e);
    }
  }

  // Play audio URL using persistent element
  async playAudioUrl(url) {
    if (!url) return false;
    this.initPersistent();

    // Ensure unlocked
    if (!this._unlocked) {
      console.warn('playAudioUrl: audio not unlocked yet. Attempting auto-unlock...');
      try { await this.unlockOnce(); } catch (e) {}
    }

    const abs = ensureAbsoluteUrl(url);
    console.log(`🔊 playAudioUrl → ${abs}`);
    // Non-blocking probe: reveals 404 / CORS / wrong-origin issues immediately in console.
    fetch(abs, { method: 'HEAD' })
      .then(r => console.log(`🔍 audio probe: ${r.status} ${r.ok ? 'OK' : 'FAILED'} — ${abs}`))
      .catch(e => console.error(`🔴 audio unreachable: ${abs} — ${e.message}`));

    const el = this.el;

    // Stop current playback
    try { el.pause(); el.currentTime = 0; } catch (e) {}

    // Set src only if changed
    if (!el.src || el.src !== abs) {
      el.src = abs;
      try { el.load(); } catch (e) {}
    }

    // Ensure AudioContext running
    try {
      if (this.audioMgr.audioContext && this.audioMgr.audioContext.state === 'suspended') {
        await this.audioMgr.audioContext.resume();
      }
    } catch (e) {}

    // Try to play
    try {
      await el.play();
      this._tryAttachAnalyser();
      console.log('▶️ Play started', abs);
      return true;
    } catch (err) {
      console.warn('play() blocked, attempting muted-first fallback:', err);
    }

    // Muted-first fallback
    try {
      el.muted = true;
      await el.play();
      await new Promise(r => setTimeout(r, 80));
      el.muted = false;
      this._tryAttachAnalyser();
      console.log('▶️ Play started via muted-first path', abs);
      return true;
    } catch (err) {
      console.warn('Muted-first failed:', err);
    }

    // Transient fallback (rare)
    try {
      const tmp = new Audio(abs);
      tmp.playsInline = true;
      tmp.crossOrigin = 'anonymous';
      tmp.setAttribute('playsinline', '');
      tmp.setAttribute('webkit-playsinline', '');
      document.body.appendChild(tmp);
      await tmp.play();
      el.src = abs;
      try { el.load(); } catch (e) {}
      tmp.pause();
      tmp.remove();
      this._tryAttachAnalyser();
      console.log('▶️ Transient played', abs);
      return true;
    } catch (err) {
      console.warn('Transient fallback failed:', err);
    }

    console.error('All playback strategies failed for', abs);
    return false;
  }
}

// Handle server messages — routes to the main WS handler
// (initialized after VRM loads, see below)
let _onServerMessage = (msg) => { console.log("📩 Queued (VRM not ready):", msg); };

// ─── Streaming animation queue ────────────────────────────────────────────
// When the gateway streams sentences, each sentence arrives as its own
// start_animation with `queue: true`. We play them in order, waiting for
// each audio to end before starting the next so nothing overlaps.
const _streamQueue = [];
let _streamPlaying = false;
// Audio that arrived before the user gesture; replayed on first unlock.
let _pendingAudio = null;

async function _playAnimation(msg) {
  const { audio_path, audio_text, audio_duraction, expression = 'neutral' } = msg;
  audioMgr.setExpression(expression);
  try {
    if (audio_text) {
      const totalSec = Math.max(1, (Number(audio_duraction) || 3000) / 1000);
      showSubtitleStreaming(audio_text, totalSec, "word");
    }
  } catch (e) { console.warn('subtitle render failed:', e); }
  try {
    try { await playbackController.unlockOnce(); } catch (e) {}
    if (!playbackController._unlocked) {
      // Context still locked (no gesture yet) — save for replay on first click.
      _pendingAudio = msg;
      console.warn('⏸️ Audio context locked; saved for replay after gesture. Click the overlay.');
      animationMgr.play();
      return;
    }
    const ok = await playbackController.playAudioUrl(audio_path);
    if (!ok) console.warn('Playback failed (animation will still run)');
    animationMgr.play();
  } catch (e) {
    console.error('Failed to start audio/animation:', e);
  }
}

async function _drainStreamQueue() {
  if (_streamPlaying) return;
  _streamPlaying = true;
  try {
    while (_streamQueue.length) {
      const next = _streamQueue.shift();
      await _playAnimation(next);
      // Wait for the audio element's `ended` event (or a duration fallback).
      const el = audioMgr.audioElement;
      const waitMs = Math.max(500, Number(next.audio_duraction) || 3000) + 200;
      await new Promise((resolve) => {
        let done = false;
        const finish = () => { if (!done) { done = true; resolve(); } };
        const timer = setTimeout(finish, waitMs);
        if (el) {
          const onEnd = () => { clearTimeout(timer); el.removeEventListener('ended', onEnd); finish(); };
          el.addEventListener('ended', onEnd, { once: true });
        } else {
          // No element available — fall back to duration timer.
        }
      });
    }
  } finally {
    _streamPlaying = false;
  }
}

function handleServerMessage(msg) {
  console.log("📩 Received from server:", msg);
  _onServerMessage(msg);
}

// Connect WebSocket + UI
connectWS(handleServerMessage);
// Give planPanel access to the WS for approve/reject decisions
setTimeout(() => setPlanPanelSocket(getWS()), 500);


// Global variables
let currentMixer = null;
let vrm = null;
let renderer = null;
let scene = null;
let camera = null;
let controls = null;
let audioMgr = null;
let animationMgr = null;
let movementController = null;
let playbackController = null; // Mobile-compatible audio controller
let obstacleCourse = null; // Obstacle course reference
const clock = new THREE.Clock();
let currentVrm = null;
let currentAction = null;

(async () => {
  // Setup renderer with transparent background
  renderer = new THREE.WebGLRenderer({ alpha: true });
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  document.body.appendChild(renderer.domElement);

  // Scene
  scene = new THREE.Scene();


  // helpers

  // scene.background = new THREE.Color(0x000000); // Black background

  // const gridHelper = new THREE.GridHelper( 50, 50 );
  // scene.add( gridHelper );

  // const axesHelper = new THREE.AxesHelper( 5 );
  // scene.add( axesHelper );

  // // Create obstacle course
  // obstacleCourse = createObstacleCourse(scene);
  // obstacleCourse.group.rotation.y = Math.PI; // 180 degrees in radians
  // console.log('✅ Obstacle course added to scene');

  // Camera
  camera = new THREE.PerspectiveCamera(30, window.innerWidth/window.innerHeight, 0.1, 50);
  camera.position.set(0, 1.3, 2.2);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 1.2, 0);
  controls.update();

  // Lighting
  const dirLight = new THREE.DirectionalLight(0xffffff, 1);
  dirLight.position.set(3, 15, -5);
  scene.add(dirLight);
  scene.add(new THREE.AmbientLight(0xffffff, 2.1));

  // Load VRM
  const vrmData = await loadVRM(VRM_PATH, scene);
  vrm = vrmData.vrm;
  window.vrm = vrm; // debug hook
  window.scene = scene; // debug hook
  const loader = vrmData.loader;
  currentMixer = new THREE.AnimationMixer(vrm.scene);


  // Initialize managers - AudioManager and AnimationManager first
  audioMgr = new AudioManager(vrm);
  animationMgr = new AnimationManager(vrm, audioMgr, renderer, scene, camera, controls);

  // Initialize avatar state to idle immediately (so state animations run from the start)
  animationMgr.setState('idle');
  console.log('✅ Avatar initialized in idle state');

  // Auto-play Idle.fbx so the VRM doesn't sit in T-pose waiting on a backend cue.
  try {
    const idleClip = await loadMixamoAnimation('./animations/mixamo/Idle.fbx', vrm, { stripRootMotion: false });
    const idleAction = currentMixer.clipAction(idleClip);
    idleAction.setLoop(THREE.LoopRepeat, Infinity);
    idleAction.play();
    currentAction = idleAction;
    console.log('✅ Idle animation auto-loaded');
  } catch (e) {
    console.warn('idle auto-load failed:', e);
  }


  // Initialize PlaybackController for mobile-compatible audio
  playbackController = new PlaybackController(audioMgr);
  playbackController.initPersistent();

  // Expose for debugging
  window.playbackController = playbackController;
  window.audioMgr = audioMgr;
  window.animationMgr = animationMgr;

  // ── Audio unlock overlay ───────────────────────────────────────────────────
  // Chrome blocks AudioContext.resume() unless called inside a real user gesture.
  // This overlay forces one click before any audio can arrive from the server.
  const audioUnlockOverlay = document.getElementById('audio-unlock-overlay');

  const dismissOverlay = () => {
    if (audioUnlockOverlay) audioUnlockOverlay.classList.add('hidden');
  };

  // Drain any audio that was queued before the first gesture.
  const drainPendingAudio = async () => {
    if (_pendingAudio) {
      const msg = _pendingAudio;
      _pendingAudio = null;
      console.log('▶️ Replaying audio held before gesture unlock');
      await _playAnimation(msg);
    }
  };

  if (audioUnlockOverlay) {
    audioUnlockOverlay.addEventListener('click', async () => {
      await playbackController.unlockOnce();
      dismissOverlay();
      await drainPendingAudio();
      console.log('🔊 Audio unlocked via overlay click');
    }, { once: true });
  }

  // Fallback gesture listeners — also hide the overlay if the user happens to
  // interact somewhere else first (e.g. OrbitControls drag, keypress).
  const onFirstGesture = async () => {
    try {
      await playbackController.unlockOnce();
    } catch (e) {
      console.warn('unlockOnce error:', e);
    }
    if (playbackController._unlocked) {
      dismissOverlay();
      await drainPendingAudio();
      window.removeEventListener('pointerdown', onFirstGesture, { capture: true });
      window.removeEventListener('touchend', onFirstGesture, { capture: true });
      window.removeEventListener('keydown', onFirstGesture, { capture: true });
      console.log('🔓 Audio unlocked — gesture listeners removed');
    }
  };

  window.addEventListener('pointerdown', onFirstGesture, { capture: true });
  window.addEventListener('touchend', onFirstGesture, { capture: true });
  window.addEventListener('keydown', onFirstGesture, { capture: true });

  // Start animation loop
  clock.start();
  
  function animate() {
    requestAnimationFrame(animate);
    const deltaTime = clock.getDelta();
    
    // Update VRMA mixer
    if (currentMixer) {
      currentMixer.update(deltaTime);
    }
    
    // Update animation manager (idle animations)
    if (animationMgr) {
      animationMgr.update(deltaTime);
    }
    
    // Update movement controller
    if (movementController) {
      movementController.update(deltaTime);
    }

    // Animate obstacle course (pulsing lasers, etc.)
    if (obstacleCourse) {
      animateObstacleCourse(obstacleCourse.group, deltaTime, clock.elapsedTime);
    }

    // Update VRM and render
    vrm.update(deltaTime);
    renderer.render(scene, camera);
    controls.update();
  }
  
  animate();

  // Wire up server message handler now that VRM is ready
  _onServerMessage = async (msg) => {
    console.log('📨 Handling message:', msg.type);
    
    // Movement commands
    if (msg.type === 'walk_to') {
      const { x, y, z, speed } = msg;
      if (speed) movementController.setSpeed(speed);
      movementController.walkTo(x, y, z);
    }
    
    if (msg.type === 'stop_movement') {
      movementController.stop();
    }
    
    if (msg.type === 'teleport_to') {
      const { x, y, z } = msg;
      movementController.teleportTo(x, y, z);
    }
    
    if (msg.type === 'set_speed') {
      movementController.setSpeed(msg.speed);
    }
    
    if (msg.type === 'load_walk_animation') {
      await movementController.loadWalkAnimation(msg.url);
    }
    
    if (msg.type === 'load_idle_animation') {
      await movementController.loadIdleAnimation(msg.url);
    }
    
    // Additive blending
    if (msg.type === 'set_additive_weight') {
      const { anim_name, weight, duration } = msg;
      movementController.setAdditiveWeight(anim_name, weight, duration || 0.25);
    }

    // Play additive animation once (for gestures)
    if (msg.type === 'play_additive_once') {
      const { anim_name, fade_in, fade_out } = msg;
      movementController.playAdditiveOnce(anim_name, fade_in || 0.25, fade_out || 0.25);
    }

    // Load a new additive animation dynamically
    if (msg.type === 'load_additive_animation') {
      const { url, name } = msg;
      await movementController.loadAdditiveAnimation(url, name);
    }

    // Load and immediately play an additive animation
    if (msg.type === 'load_and_play_additive') {
      const { url, name, weight = 1.0, play_once = false, fade_in = 0.25, fade_out = 0.25 } = msg;
      try {
        // First load the animation
        const loaded = await movementController.loadAdditiveAnimation(url, name);
        if (loaded) {
          // Then play it
          if (play_once) {
            movementController.playAdditiveOnce(name, fade_in, fade_out);
          } else {
            movementController.setAdditiveWeight(name, weight, fade_in);
          }
          console.log(`✅ Loaded and playing additive animation: ${name}`);
        }
      } catch (err) {
        console.error(`Failed to load and play additive animation ${name}:`, err);
      }
    }

    // State control (idle, listening, thinking, talking)
    if (msg.type === 'set_state') {
      const { state } = msg;
      if (animationMgr && ['idle', 'listening', 'thinking', 'talking'].includes(state)) {
        animationMgr.setState(state);
        console.log(`✅ Avatar state changed to: ${state}`);
      } else {
        console.warn(`Invalid state: ${state}`);
      }
    }

    // Set movement lock duration
    if (msg.type === 'set_movement_lock_duration') {
      const { duration } = msg;
      if (animationMgr && typeof duration === 'number') {
        animationMgr.setMovementLockDuration(duration);
        console.log(`✅ Movement lock duration set to: ${duration}s`);
      }
    }

    // Original animation commands - now using PlaybackController for mobile compatibility
    if (msg.type === 'plan_response') {
      handlePlanResponse(msg);
      return;
    }

    if (msg.type === 'plan_approved') {
      console.log('[V5] Plan approved:', msg.plan_id);
      return;
    }

    if (msg.type === 'plan_rejected') {
      console.log('[V5] Plan rejected:', msg.plan_id);
      return;
    }

    if (msg.type === 'build_response') {
      handleBuildResponse(msg);
      return;
    }

    if (msg.type === 'start_animation') {
      // Streaming path: if msg.queue === true, queue instead of interrupting
      // current playback. Drained on the audio element's `ended` event.
      if (msg.queue === true) {
        _streamQueue.push(msg);
        if (!_streamPlaying) _drainStreamQueue();
        return;
      }
      await _playAnimation(msg);
    }

    if (msg.type === 'start_vrma') {
      const {
        animation_url,
        play_once = false,
        crop_start = 0.0,
        crop_end = 0.0,
        lock_position = false,
        track_position = true
      } = msg;

      try {
        console.log("Loading VRMA animation:", animation_url, "lock_position:", lock_position, "track_position:", track_position);
        const gltfVrma = await loader.loadAsync(animation_url);
        const vrmAnimation = gltfVrma.userData.vrmAnimations[0];
        let clip = createVRMAnimationClip(vrmAnimation, vrm);

        // Store original clip for position tracking (before any modifications)
        const originalClip = clip;

        // Strip root motion if lock_position is enabled
        if (lock_position) {
          clip = stripRootMotionFromClip(clip, vrm);
        }

        const startTime = Math.max(0, parseFloat(crop_start) || 0);
        const endTime = Math.max(0, clip.duration - (parseFloat(crop_end) || 0));
        if (startTime > 0 || (parseFloat(crop_end) || 0) > 0) {
          const trimmed = trimAnimationClip(clip, startTime, endTime);
          if (trimmed) clip = trimmed;
        }

        // Pause movementController (fade out its animations)
        if (movementController) {
          movementController.pause(0.3);
        }

        animationMgr.setVRMAPlaying(true);

        if (!currentMixer) {
          currentMixer = new THREE.AnimationMixer(vrm.scene);
        }

        const newAction = currentMixer.clipAction(clip);

        if (play_once) {
          newAction.setLoop(THREE.LoopOnce, 0);
          newAction.clampWhenFinished = true;
          newAction.enabled = true;
        } else {
          newAction.setLoop(THREE.LoopRepeat, Infinity);
          newAction.clampWhenFinished = false;
        }

        // Reset and play new action
        newAction.reset();
        newAction.play();

        // Crossfade from current action if exists (same mixer, proper blend)
        if (currentAction && currentAction !== newAction) {
          currentAction.crossFadeTo(newAction, 0.5, false);
        }

        if (currentMixer._vrmaFinishedListener) {
          try {
            currentMixer.removeEventListener('finished', currentMixer._vrmaFinishedListener);
          } catch (e) {}
          currentMixer._vrmaFinishedListener = null;
        }

        const onFinished = (e) => {
          if (e.action === newAction) {
            animationMgr.setVRMAPlaying(false);

            if (play_once) {
              // Get hips node for position tracking
              const hipsNode = vrm.humanoid?.getNormalizedBoneNode('hips');

              // Capture the target world position we want to maintain
              // This is where the character should end up
              let targetWorldX = vrm.scene.position.x;
              let targetWorldZ = vrm.scene.position.z;

              if (track_position && !lock_position && hipsNode) {
                targetWorldX += hipsNode.position.x;
                targetWorldZ += hipsNode.position.z;
                console.log(`📍 VRMA target position: (${targetWorldX.toFixed(2)}, ${targetWorldZ.toFixed(2)})`);
              }

              // Freeze the action at its end frame
              newAction.paused = true;

              // Gradually fade out while compensating for hips movement
              const fadeOutDuration = 0.5;
              let fadeStartTime = null;

              const fadeOutUpdate = () => {
                if (fadeStartTime === null) fadeStartTime = performance.now();
                const elapsed = (performance.now() - fadeStartTime) / 1000;
                const progress = Math.min(elapsed / fadeOutDuration, 1.0);

                newAction.setEffectiveWeight(1.0 - progress);

                // Compensate for changing hips position during fade
                // This keeps the character's visual world position constant
                if (track_position && !lock_position && hipsNode) {
                  vrm.scene.position.x = targetWorldX - hipsNode.position.x;
                  vrm.scene.position.z = targetWorldZ - hipsNode.position.z;
                }

                if (progress < 1.0) {
                  requestAnimationFrame(fadeOutUpdate);
                } else {
                  // Fade complete - finalize position (hips should be ~0 from idle now)
                  if (track_position && !lock_position) {
                    vrm.scene.position.x = targetWorldX;
                    vrm.scene.position.z = targetWorldZ;
                  }
                  try { newAction.stop(); } catch (err) {}
                }
              };

              // Start the fade out
              requestAnimationFrame(fadeOutUpdate);

              // Resume movementController (fade in idle)
              if (movementController) {
                movementController.resume(fadeOutDuration);
              }
            }

            if (currentMixer && currentMixer._vrmaFinishedListener) {
              currentMixer.removeEventListener('finished', currentMixer._vrmaFinishedListener);
              currentMixer._vrmaFinishedListener = null;
            }
          }
        };

        currentMixer._vrmaFinishedListener = onFinished;
        currentMixer.addEventListener('finished', onFinished);
        currentAction = newAction;

      } catch (err) {
        console.error("Failed to load VRMA animation:", err);
        // Resume movementController on error
        if (movementController) {
          movementController.resume();
        }
      }
    }

    if (msg.type === 'start_mixamo') {
      const { animation_url, play_once = false, lock_position = false, track_position = true } = msg;
      try {
        console.log("Loading Mixamo animation:", animation_url, "lock_position:", lock_position, "track_position:", track_position);
        currentVrm = vrm;

        // Pause movementController (fade out its animations)
        if (movementController) {
          movementController.pause(0.3);
        }

        // Load the clip
        const clip = await loadMixamoAnimation(animation_url, currentVrm, {
          stripRootMotion: lock_position
        });

        // Load original clip for position tracking if needed
        let originalClip = clip;
        if (track_position && !lock_position) {
          originalClip = await loadMixamoAnimation(animation_url, currentVrm, {
            stripRootMotion: false
          });
        }

        const newAction = currentMixer.clipAction(clip);

        // Configure loop mode
        if (play_once) {
          newAction.setLoop(THREE.LoopOnce, 0);
          newAction.clampWhenFinished = true;
        } else {
          newAction.setLoop(THREE.LoopRepeat, Infinity);
        }

        // Reset and play new action
        newAction.reset();
        newAction.play();

        // Crossfade from current action if exists (same mixer, proper blend)
        if (currentAction && currentAction !== newAction) {
          currentAction.crossFadeTo(newAction, 0.5, false);
        }
        currentAction = newAction;

        // Handle play_once completion
        if (play_once) {
          if (currentMixer._mixamoFinishedListener) {
            try {
              currentMixer.removeEventListener('finished', currentMixer._mixamoFinishedListener);
            } catch (e) {}
          }

          const onFinished = (e) => {
            if (e.action === newAction) {
              // Get hips node for position tracking
              const hipsNode = vrm.humanoid?.getNormalizedBoneNode('hips');

              // Capture target world position (scene position + hips offset)
              let targetWorldX = vrm.scene.position.x;
              let targetWorldZ = vrm.scene.position.z;

              if (track_position && !lock_position && hipsNode) {
                targetWorldX += hipsNode.position.x;
                targetWorldZ += hipsNode.position.z;
                console.log(`📍 Mixamo target position: (${targetWorldX.toFixed(2)}, ${targetWorldZ.toFixed(2)})`);
              }

              // Don't stop the action immediately - let it hold the final pose
              // Freeze the action at its end frame
              newAction.paused = true;

              // Gradually fade out while movementController fades in
              const fadeOutDuration = 0.5;
              let fadeStartTime = null;

              const fadeOutUpdate = () => {
                if (fadeStartTime === null) fadeStartTime = performance.now();
                const elapsed = (performance.now() - fadeStartTime) / 1000;
                const progress = Math.min(elapsed / fadeOutDuration, 1.0);

                newAction.setEffectiveWeight(1.0 - progress);

                // Continuously compensate for changing hips position during fade
                // As idle fades in, hips position changes - we adjust scene position to maintain world position
                if (track_position && !lock_position && hipsNode) {
                  vrm.scene.position.x = targetWorldX - hipsNode.position.x;
                  vrm.scene.position.z = targetWorldZ - hipsNode.position.z;
                }

                if (progress < 1.0) {
                  requestAnimationFrame(fadeOutUpdate);
                } else {
                  // Finalize position when fade completes
                  if (track_position && !lock_position) {
                    vrm.scene.position.x = targetWorldX;
                    vrm.scene.position.z = targetWorldZ;
                  }
                  try { newAction.stop(); } catch (err) {}
                }
              };

              requestAnimationFrame(fadeOutUpdate);

              // Resume movementController (fade in idle)
              if (movementController) {
                movementController.resume(fadeOutDuration);
              }

              if (currentMixer._mixamoFinishedListener) {
                currentMixer.removeEventListener('finished', currentMixer._mixamoFinishedListener);
                currentMixer._mixamoFinishedListener = null;
              }
            }
          };

          currentMixer._mixamoFinishedListener = onFinished;
          currentMixer.addEventListener('finished', onFinished);
        }
      } catch (err) {
        console.error("Failed to load Mixamo animation:", err);
        // Resume movementController on error
        if (movementController) {
          movementController.resume();
        }
      }
    }

    if (msg.type === 'take_picture') {
      console.log("📸 Taking picture");
      await takePictureAndUpload();
    }
  };

  // Handle resize
  window.addEventListener('resize', () => {
    camera.aspect = window.innerWidth/window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  });

})();