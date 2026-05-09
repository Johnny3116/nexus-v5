// Hey Nexus wake-word listener
// mic (16kHz) -> melspec.onnx -> embedding.onnx -> hey_nexus.onnx -> "wakeword" CustomEvent
// Gated by localStorage.wakewordEnabled === 'true'. Threshold via localStorage.wakewordThreshold.

import * as ort from 'onnxruntime-web';

const SR = 16000;
const CHUNK_SAMPLES = 1280;              // 80 ms @ 16 kHz — openWakeWord streaming step
const MEL_BUFFER_FRAMES = 76;            // embedding input window (~760 ms of mels)
const MEL_STRIDE = 8;                    // slide 80 ms per embedding
const EMBED_BUFFER = 16;                 // wake classifier input (1.28 s of embeddings)
const MEL_SCALE = 10;                    // openWakeWord mel normalization: mel/10 + 2
const MEL_BIAS = 2;
const DEFAULT_THRESHOLD = 0.5;
const COOLDOWN_MS = 2000;
const MEL_ACCUM_CAP = 240;               // hard cap to survive inference stalls
const PCM_CHUNK_CAP = 16;                // max pending chunks before dropping
const PAUSE_AFTER_FIRE_MS = 6000;        // pause until downstream mic/TTS finishes

let running = false;
let paused = false;
let busy = false;
let audioCtx, micStream, workletNode;
let melSession, embedSession, wakeSession;

let pcmChunks = [];                      // queue of Float32Array chunks from worklet
let pcmLeftover = new Float32Array(0);   // < CHUNK_SAMPLES remainder between drains
let melAccum = [];                       // Float32Array(32) per mel frame
const embedAccum = [];                   // Float32Array(96) rolling window
let lastFireAt = 0;

function concatF32(arrays) {
    let total = 0;
    for (const a of arrays) total += a.length;
    const out = new Float32Array(total);
    let off = 0;
    for (const a of arrays) { out.set(a, off); off += a.length; }
    return out;
}

async function loadModels() {
    ort.env.wasm.numThreads = 1;
    ort.env.wasm.proxy = false;
    ort.env.wasm.simd = true;
    ort.env.wasm.wasmPaths = new URL('./node_modules/onnxruntime-web/dist/', window.location.href).href;
    const opts = { executionProviders: ['wasm'] };
    melSession   = await ort.InferenceSession.create('./models/wakeword/melspectrogram.onnx', opts);
    embedSession = await ort.InferenceSession.create('./models/wakeword/embedding_model.onnx', opts);
    wakeSession  = await ort.InferenceSession.create('./models/wakeword/hey_nexus.onnx', opts);
    console.log('[wake] models loaded');
}

async function runMel(pcm) {
    // openWakeWord melspec expects int16-scaled floats, not [-1, 1]
    const scaled = new Float32Array(pcm.length);
    for (let i = 0; i < pcm.length; i++) scaled[i] = pcm[i] * 32767;
    const input = new ort.Tensor('float32', scaled, [1, scaled.length]);
    const out = await melSession.run({ [melSession.inputNames[0]]: input });
    const data = out[melSession.outputNames[0]].data;
    const frames = [];
    const nFrames = data.length / 32;
    for (let f = 0; f < nFrames; f++) {
        const frame = new Float32Array(32);
        for (let i = 0; i < 32; i++) frame[i] = data[f * 32 + i] / MEL_SCALE + MEL_BIAS;
        frames.push(frame);
    }
    return frames;
}

async function runEmbedding(melFrames76) {
    const flat = new Float32Array(76 * 32);
    for (let i = 0; i < 76; i++) flat.set(melFrames76[i], i * 32);
    const input = new ort.Tensor('float32', flat, [1, 76, 32, 1]);
    const out = await embedSession.run({ [embedSession.inputNames[0]]: input });
    return new Float32Array(out[embedSession.outputNames[0]].data);
}

async function runWake(embeds16) {
    const flat = new Float32Array(16 * 96);
    for (let i = 0; i < 16; i++) flat.set(embeds16[i], i * 96);
    const input = new ort.Tensor('float32', flat, [1, 16, 96]);
    const out = await wakeSession.run({ [wakeSession.inputNames[0]]: input });
    return out[wakeSession.outputNames[0]].data[0];
}

function getThreshold() {
    const raw = localStorage.getItem('wakewordThreshold');
    const parsed = raw ? parseFloat(raw) : NaN;
    return Number.isFinite(parsed) ? parsed : DEFAULT_THRESHOLD;
}

async function drain() {
    if (busy) return;
    busy = true;
    try {
        // 1. Consolidate pending mic chunks + leftover into one buffer
        if (pcmChunks.length > 0 || pcmLeftover.length > 0) {
            const merged = concatF32([pcmLeftover, ...pcmChunks]);
            pcmChunks = [];
            // 2. Drain CHUNK_SAMPLES at a time, preserve remainder
            let off = 0;
            while (off + CHUNK_SAMPLES <= merged.length) {
                if (!running || paused) { pcmLeftover = new Float32Array(0); return; }
                const chunk = merged.subarray(off, off + CHUNK_SAMPLES);
                off += CHUNK_SAMPLES;
                try {
                    const newMels = await runMel(chunk);
                    melAccum.push(...newMels);
                } catch (err) {
                    console.error('[wake] mel inference failed', err);
                }
            }
            pcmLeftover = merged.slice(off);
        }

        // 3. Cap mel accumulator defensively
        if (melAccum.length > MEL_ACCUM_CAP) melAccum = melAccum.slice(-MEL_ACCUM_CAP);

        // 4. Slide embedding window
        while (melAccum.length >= MEL_BUFFER_FRAMES) {
            if (!running || paused) return;
            const melWindow = melAccum.slice(0, MEL_BUFFER_FRAMES);
            melAccum = melAccum.slice(MEL_STRIDE);
            try {
                const embed = await runEmbedding(melWindow);
                embedAccum.push(embed);
                if (embedAccum.length > EMBED_BUFFER) embedAccum.shift();
            } catch (err) {
                console.error('[wake] embedding inference failed', err);
                continue;
            }

            if (embedAccum.length === EMBED_BUFFER) {
                try {
                    const score = await runWake(embedAccum);
                    if (localStorage.getItem('wakeDebug') === 'true') {
                        const lastEmb = embedAccum[embedAccum.length - 1];
                        let emin = Infinity, emax = -Infinity, esum = 0;
                        for (const v of lastEmb) { if (v < emin) emin = v; if (v > emax) emax = v; esum += v; }
                        const lastMel = melWindow[75];
                        let mmin = Infinity, mmax = -Infinity;
                        for (const v of lastMel) { if (v < mmin) mmin = v; if (v > mmax) mmax = v; }
                        console.log(`[wake] score=${score.toFixed(3)} mel[${mmin.toFixed(2)},${mmax.toFixed(2)}] emb[${emin.toFixed(2)},${emax.toFixed(2)}] eAvg=${(esum/96).toFixed(2)}`);
                    }
                    const now = Date.now();
                    if (running && !paused && score > getThreshold() && now - lastFireAt > COOLDOWN_MS) {
                        lastFireAt = now;
                        console.log(`[wake] FIRED score=${score.toFixed(3)}`);
                        pause(PAUSE_AFTER_FIRE_MS);
                        window.dispatchEvent(new CustomEvent('wakeword', { detail: { score } }));
                    }
                } catch (err) {
                    console.error('[wake] wake inference failed', err);
                }
            }
        }
    } finally {
        busy = false;
    }
}

function onAudioChunk(chunk) {
    if (!running || paused) return;
    if (pcmChunks.length >= PCM_CHUNK_CAP) pcmChunks.shift(); // drop oldest under backpressure
    pcmChunks.push(chunk);
    drain();
}

function pause(ms) {
    paused = true;
    pcmChunks = [];
    pcmLeftover = new Float32Array(0);
    melAccum = [];
    embedAccum.length = 0;
    if (ms && ms > 0) setTimeout(resume, ms);
}

function resume() {
    if (!running) return;
    paused = false;
}

let starting = false;
async function start() {
    if (running || starting) return;
    starting = true;
    try {
    await loadModels();

    micStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, sampleRate: SR, echoCancellation: true, noiseSuppression: true }
    });
    audioCtx = new AudioContext({ sampleRate: SR });
    if (audioCtx.sampleRate !== SR) {
        // AudioContext rejected the requested rate — melspec model will get wrong-rate audio
        console.error(`[wake] AudioContext sampleRate=${audioCtx.sampleRate}, expected ${SR}. Aborting.`);
        try { await audioCtx.close(); } catch {}
        micStream.getTracks().forEach(t => t.stop());
        throw new Error(`Browser forced sampleRate=${audioCtx.sampleRate}; wake word needs 16000`);
    }
    const src = audioCtx.createMediaStreamSource(micStream);

    const workletCode = `
        class WakeTap extends AudioWorkletProcessor {
            process(inputs) {
                const ch = inputs[0][0];
                if (ch) this.port.postMessage(ch.slice(0));
                return true;
            }
        }
        registerProcessor('wake-tap', WakeTap);
    `;
    const blob = new Blob([workletCode], { type: 'application/javascript' });
    await audioCtx.audioWorklet.addModule(URL.createObjectURL(blob));
    workletNode = new AudioWorkletNode(audioCtx, 'wake-tap');
    workletNode.port.onmessage = (e) => onAudioChunk(e.data);
    src.connect(workletNode);
    running = true;
    paused = false;
    console.log('[wake] listening for "Hey Nexus"');
    } finally {
        starting = false;
    }
}

async function stop() {
    if (!running) return;
    running = false;
    paused = false;
    try { workletNode?.disconnect(); } catch {}
    try { await audioCtx?.close(); } catch {}
    micStream?.getTracks().forEach(t => t.stop());
    pcmChunks = [];
    pcmLeftover = new Float32Array(0);
    melAccum = [];
    embedAccum.length = 0;
    console.log('[wake] stopped');
}

function autoStart() {
    if (localStorage.getItem('wakewordEnabled') === 'true') {
        start().catch(err => console.error('[wake] start failed', err));
    }
}

window.wakeListener = { start, stop, pause, resume, isRunning: () => running, isPaused: () => paused };
window.addEventListener('load', autoStart);
