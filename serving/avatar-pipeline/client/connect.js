import { VRM_PATH, WS_URL, HTTP_URL }       from './config.js';

let ws;

// Add these variables at the top
let mediaRecorder;
let audioChunks = [];
let currentImageFile = null;
let isTranscriptionMode = false;

// Connect WebSocket
export function connectWS(onMessage) {
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    console.log("✅ Connected to WebSocket");
  };

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    onMessage(msg); // Pass message to VRM app.js
    
    // Handle transcription results
    if (msg.type === "transcription_result") {
      handleTranscriptionResult(msg.text);
    }
  };

  ws.onclose = () => {
    console.warn("❌ WebSocket disconnected. Reconnecting in 2s...");
    setTimeout(() => connectWS(onMessage), 2000);
  };
}

export function getWS() { return ws; }
