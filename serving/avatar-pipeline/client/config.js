// adjust these paths / URLs as needed
export const VRM_PATH     = './models/yami_no_eyez.vrm';
// Some VRMs (esp. VRM 1.x from VRoid) face +Z at load and render back-to-camera
// with our existing Riko-era camera at +Z. Flip to face the camera. Set false
// for legacy VRM 0.x models (like Riko) that already face -Z.
export const VRM_ROTATE_180 = true;

// Resolve API origin to whatever host the page is loaded from, on :8001.
// This way local (https://localhost:5180) and remote Tailscale
// (https://nexusbody.tail344870.ts.net:5180) both work without edits.
const _API_HOST  = location.hostname;
const _API_PROTO = location.protocol === 'https:' ? 'https:' : 'http:';
const _WS_PROTO  = location.protocol === 'https:' ? 'wss:'   : 'ws:';

export const WS_URL       = `${_WS_PROTO}//${_API_HOST}:8001/ws`;
export const HTTP_URL     = `${_API_PROTO}//${_API_HOST}:8001`;
export const MOUTH_THRESHOLD = 7;
