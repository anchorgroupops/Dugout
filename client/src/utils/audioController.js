/**
 * Audio Controller — Web Audio engine for walk-up music + announcer ducking.
 *
 * Routing:
 *   WalkupSource → WalkupGain ─┐
 *                                ├─→ MasterGain → Destination
 *   ClipSource   → ClipGain ───┘
 *
 * Playback flow:
 *   1. Music starts at full volume
 *   2. At the song's start mark: duck music to DUCK_LEVEL over 300ms
 *   3. Play the announcer clip
 *   4. On clip end: restore music over 300ms
 *
 * Exactly one thing plays at a time. Every play() takes a new generation
 * number; anything scheduled by an older play (a fetch still in flight, a
 * duck timer, an `ended` handler, the progress ticker) checks it and does
 * nothing once it is stale. Without that, a second tap during a slow fetch
 * played both clips over each other, and the first batter's `ended` event
 * (which fires asynchronously after stop()) marked the second batter's
 * announcement finished before it had started.
 *
 * The UI never tracks "is playing" itself: it subscribes to one state object
 * (useSyncExternalStore), so the now-playing bar cannot drift from the audio.
 */

const DUCK_LEVEL = 0.4; // keep 40% of the music under the call
const DUCK_RAMP_MS = 300;
const FETCH_TIMEOUT_MS = 15000;
// Decoded audio is large (a 3-minute song is ~60 MB of float PCM), so keep
// only a handful of buffers; the service worker caches the compressed files.
const MAX_CACHE_SIZE = 12;
const MAX_AUDIO_BYTES = 50 * 1024 * 1024;

const BUFFER_CACHE = new Map();

let ctx = null;
let masterGain = null;
let walkupGain = null;
let clipGain = null;
let walkupSource = null;
let clipSource = null;
let duckTimer = null;
let progressTimer = null;
let generation = 0;

const IDLE = Object.freeze({ status: 'idle', key: '', label: '', detail: '', error: '', warning: '', elapsed: 0, duration: 0 });
let state = IDLE;
const listeners = new Set();

function setState(next) {
  state = next;
  listeners.forEach(fn => fn());
}

/** Subscribe to playback state changes. Returns an unsubscribe function. */
export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/**
 * Current playback state:
 *   status  'idle' | 'loading' | 'playing' | 'error'
 *   key     caller's id for what is playing (e.g. a player id)
 *   label / detail  what the bar shows
 *   warning a part that failed while the rest plays ("song didn't load")
 *   error   why nothing played (status 'error')
 */
export function getState() {
  return state;
}

function getContext() {
  if (!ctx || ctx.state === 'closed') {
    const Ctor = window.AudioContext || window.webkitAudioContext;
    ctx = new Ctor();
    masterGain = ctx.createGain();
    walkupGain = ctx.createGain();
    clipGain = ctx.createGain();
    walkupGain.connect(masterGain);
    clipGain.connect(masterGain);
    masterGain.connect(ctx.destination);
  }
  // iOS reports 'interrupted' after a phone call or screen lock, not only
  // 'suspended'. Anything but 'running' needs a resume, and it has to happen
  // inside the tap that asked for sound, so this runs before any await.
  if (ctx.state !== 'running') ctx.resume?.().catch(() => {});
  return ctx;
}

/**
 * Call from the first user gesture. Starts the AudioContext inside the
 * gesture (iOS creates it suspended otherwise) and asks iOS 17+ to treat the
 * page as media playback so the ringer switch doesn't mute it.
 */
export function unlock() {
  try {
    if (typeof navigator !== 'undefined' && navigator.audioSession) navigator.audioSession.type = 'playback';
  } catch { /* not supported */ }
  try {
    const audioCtx = getContext();
    const src = audioCtx.createBufferSource();
    src.buffer = audioCtx.createBuffer(1, 1, 22050);
    src.connect(audioCtx.destination);
    src.start(0);
  } catch { /* no Web Audio */ }
}

function _isAllowedAudioUrl(url) {
  if (!url) return false;
  if (url.startsWith('/')) return true; // same origin (announcer clips)
  try {
    const parsed = new URL(url, window.location.origin);
    if (parsed.protocol !== 'https:' && !(parsed.protocol === 'http:' && parsed.hostname === 'localhost')) return false;
    if (/^(10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|127\.|0\.)/.test(parsed.hostname)) return false;
    return true;
  } catch {
    return false;
  }
}

async function fetchWithTimeout(url) {
  const ctrl = typeof AbortController === 'function' ? new AbortController() : null;
  const timer = ctrl ? setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS) : null;
  try {
    return await fetch(url, ctrl ? { signal: ctrl.signal } : undefined);
  } catch (e) {
    if (e?.name === 'AbortError') throw new Error('timed out');
    throw new Error('no connection');
  } finally {
    if (timer) clearTimeout(timer);
  }
}

export async function loadBuffer(url) {
  if (BUFFER_CACHE.has(url)) {
    const hit = BUFFER_CACHE.get(url);
    BUFFER_CACHE.delete(url); // refresh LRU position
    BUFFER_CACHE.set(url, hit);
    return hit;
  }
  if (!_isAllowedAudioUrl(url)) throw new Error('link not allowed');
  const audioCtx = getContext();
  const resp = await fetchWithTimeout(url);
  if (!resp.ok) throw new Error(resp.status === 404 ? 'file missing' : `server said ${resp.status}`);
  const contentLength = parseInt(resp.headers.get('content-length') || '0', 10);
  if (contentLength > MAX_AUDIO_BYTES) throw new Error('file too large');
  const arrayBuf = await resp.arrayBuffer();
  if (arrayBuf.byteLength > MAX_AUDIO_BYTES) throw new Error('file too large');
  let audioBuf;
  try {
    audioBuf = await audioCtx.decodeAudioData(arrayBuf);
  } catch {
    throw new Error('not a playable audio file');
  }
  if (BUFFER_CACHE.size >= MAX_CACHE_SIZE) BUFFER_CACHE.delete(BUFFER_CACHE.keys().next().value);
  BUFFER_CACHE.set(url, audioBuf);
  return audioBuf;
}

function stopSource(src) {
  if (!src) return;
  src.onended = null;
  try { src.stop(); } catch { /* already stopped */ }
  try { src.disconnect(); } catch { /* ok */ }
}

function haltAudio() {
  if (duckTimer) { clearTimeout(duckTimer); duckTimer = null; }
  if (progressTimer) { clearInterval(progressTimer); progressTimer = null; }
  stopSource(walkupSource);
  stopSource(clipSource);
  walkupSource = null;
  clipSource = null;
  if (ctx && walkupGain) {
    try { walkupGain.gain.cancelScheduledValues?.(ctx.currentTime); walkupGain.gain.setValueAtTime(1.0, ctx.currentTime); } catch { /* ok */ }
  }
  if (ctx && clipGain) {
    try { clipGain.gain.setValueAtTime(1.0, ctx.currentTime); } catch { /* ok */ }
  }
}

/**
 * Detect BPM of an AudioBuffer using autocorrelation on the first 20s.
 * Returns { bpm, confidence } or null if detection fails / confidence < 0.5.
 */
export function detectBPM(audioBuffer) {
  try {
    const sampleRate = audioBuffer.sampleRate;
    const analysisSeconds = Math.min(20, audioBuffer.duration);
    const numSamples = Math.floor(analysisSeconds * sampleRate);
    const downsampleRate = 3000;
    const downsampleFactor = Math.floor(sampleRate / downsampleRate);
    const channelData = audioBuffer.getChannelData(0);
    const downsampled = [];
    for (let i = 0; i < numSamples; i += downsampleFactor) downsampled.push(channelData[i]);
    const n = downsampled.length;
    if (n < 128) return null;
    const minLag = Math.floor(downsampleRate * 60 / 200);
    const maxLag = Math.floor(downsampleRate * 60 / 50);
    let bestLag = -1;
    let bestCorr = -Infinity;
    let sum = 0;
    for (let i = 0; i < n; i++) sum += downsampled[i] * downsampled[i];
    const norm = sum / n;
    if (norm === 0) return null;
    for (let lag = minLag; lag <= Math.min(maxLag, n - 1); lag++) {
      let corr = 0;
      for (let i = 0; i < n - lag; i++) corr += downsampled[i] * downsampled[i + lag];
      corr /= (n - lag) * norm;
      if (corr > bestCorr) { bestCorr = corr; bestLag = lag; }
    }
    if (bestLag < 1 || bestCorr < 0.1) return null;
    const bpm = Math.round((downsampleRate * 60) / bestLag);
    const confidence = Math.min(1, bestCorr);
    if (confidence < 0.5) return null;
    return { bpm, confidence: Math.round(confidence * 100) / 100 };
  } catch {
    return null;
  }
}

/**
 * Seconds into the track at which to start the call so it lands
 * `barsBeforeDrop` bars before the drop. Assumes 4/4.
 */
export function calcBeatOffset(bpm, dropBar = 8, barsBeforeDrop = 2) {
  if (!bpm || bpm <= 0) return 5;
  const secondsPerBar = (60 / bpm) * 4;
  const triggerBar = Math.max(1, dropBar - barsBeforeDrop);
  return Math.round((triggerBar - 1) * secondsPerBar * 10) / 10;
}

/** Fetch and decode the next batter's audio ahead of time. Never throws. */
export async function preload(urls) {
  await Promise.all((urls || []).filter(Boolean).map(url => loadBuffer(url).catch(() => null)));
}

/**
 * Fetch files without decoding them, so the service worker's clip cache holds
 * them if the network drops mid-game. Cheap: clips are ~100 KB each.
 */
export async function warm(urls, concurrency = 3) {
  const queue = [...new Set((urls || []).filter(u => u && _isAllowedAudioUrl(u) && !BUFFER_CACHE.has(u)))];
  const worker = async () => {
    while (queue.length) {
      const url = queue.shift();
      try { await (await fetchWithTimeout(url)).arrayBuffer(); } catch { /* best effort */ }
    }
  };
  await Promise.all(Array.from({ length: Math.min(concurrency, queue.length) }, worker));
}

/**
 * Play a walk-up: optional song, optional announcer clip ducked over it.
 * Replaces whatever is playing. Resolves once playback has started (or
 * failed); the outcome is in getState(), never thrown.
 *
 * @param {Object} o
 * @param {string} o.key        caller's id for this playback (shown as "playing")
 * @param {string} [o.label]    headline for the now-playing bar
 * @param {string} [o.detail]   secondary line (voice + song)
 * @param {string} [o.songUrl]
 * @param {string} [o.clipUrl]
 * @param {number} [o.songStart=5] seconds into the song to start the call; 0 = find the beat
 */
export async function play({ key, label = '', detail = '', songUrl = '', clipUrl = '', songStart = 5 }) {
  haltAudio();
  const gen = ++generation;
  const audioCtx = getContext(); // before any await: must run inside the tap
  setState({ ...IDLE, status: 'loading', key, label, detail });

  if (!songUrl && !clipUrl) {
    setState({ ...IDLE, status: 'error', key, label, error: 'Nothing to play yet' });
    return;
  }

  const [songRes, clipRes] = await Promise.allSettled([
    songUrl ? loadBuffer(songUrl) : Promise.resolve(null),
    clipUrl ? loadBuffer(clipUrl) : Promise.resolve(null),
  ]);
  if (gen !== generation) return; // replaced or stopped while loading

  const walkupBuf = songRes.status === 'fulfilled' ? songRes.value : null;
  const clipBuf = clipRes.status === 'fulfilled' ? clipRes.value : null;
  const songErr = songRes.status === 'rejected' ? songRes.reason?.message || 'failed' : '';
  const clipErr = clipRes.status === 'rejected' ? clipRes.reason?.message || 'failed' : '';

  if (!walkupBuf && !clipBuf) {
    const why = [clipErr && `call: ${clipErr}`, songErr && `song: ${songErr}`].filter(Boolean).join(' · ');
    setState({ ...IDLE, status: 'error', key, label, detail, error: `Couldn't play (${why})` });
    return;
  }
  const warning = songErr ? `Song didn't load (${songErr}) — call only`
    : clipErr ? `Call didn't load (${clipErr}) — song only` : '';

  let introAt = Math.max(0, Number(songStart) || 0);
  if (walkupBuf && introAt === 0) {
    const bpm = detectBPM(walkupBuf);
    if (bpm) introAt = calcBeatOffset(bpm.bpm);
  }

  const now = audioCtx.currentTime;
  walkupGain.gain.setValueAtTime(1.0, now);
  clipGain.gain.setValueAtTime(1.0, now);

  const duration = walkupBuf ? walkupBuf.duration : clipBuf.duration;
  const startedAt = now;
  const finish = () => {
    if (gen !== generation) return;
    haltAudio();
    setState(IDLE);
  };

  setState({ ...IDLE, status: 'playing', key, label, detail, warning, duration });
  progressTimer = setInterval(() => {
    if (gen !== generation) return;
    setState({ ...state, elapsed: Math.min(duration, audioCtx.currentTime - startedAt) });
  }, 250);

  if (walkupBuf) {
    walkupSource = audioCtx.createBufferSource();
    walkupSource.buffer = walkupBuf;
    walkupSource.connect(walkupGain);
    walkupSource.onended = finish; // the song ends the sequence
    walkupSource.start(0);
  }

  if (clipBuf) {
    const startClip = () => {
      duckTimer = null;
      if (gen !== generation) return;
      if (walkupBuf) {
        const t = audioCtx.currentTime;
        walkupGain.gain.setValueAtTime(walkupGain.gain.value, t);
        walkupGain.gain.linearRampToValueAtTime(DUCK_LEVEL, t + DUCK_RAMP_MS / 1000);
      }
      clipSource = audioCtx.createBufferSource();
      clipSource.buffer = clipBuf;
      clipSource.connect(clipGain);
      clipSource.onended = () => {
        if (gen !== generation) return;
        if (walkupBuf) {
          const t = audioCtx.currentTime;
          walkupGain.gain.setValueAtTime(DUCK_LEVEL, t);
          walkupGain.gain.linearRampToValueAtTime(1.0, t + DUCK_RAMP_MS / 1000);
        } else {
          finish(); // clip only: the clip ends the sequence
        }
      };
      clipSource.start(0);
    };
    if (walkupBuf) duckTimer = setTimeout(startClip, introAt * 1000);
    else startClip();
  }
}

/** Play one clip on its own (previews, PA announcements). */
export function playClip(url, { key = url, label = '', detail = '' } = {}) {
  return play({ key, label, detail, clipUrl: url });
}

/** Stop everything now. Safe to call at any time. */
export function stop() {
  generation++;
  haltAudio();
  setState(IDLE);
}

/** Clear a finished error so the bar goes back to idle. */
export function dismissError() {
  if (state.status === 'error') setState(IDLE);
}

/** Stop playback and release the AudioContext (app teardown only). */
export function cleanup() {
  stop();
  BUFFER_CACHE.clear();
  if (ctx && ctx.state !== 'closed') ctx.close().catch(() => {});
  ctx = null;
  masterGain = null;
  walkupGain = null;
  clipGain = null;
}

export function getIsPlaying() {
  return state.status === 'playing' || state.status === 'loading';
}

/** Set the master volume (0.0 to 1.0). */
export function setVolume(level) {
  getContext();
  if (masterGain) masterGain.gain.setValueAtTime(Math.max(0, Math.min(1, level)), ctx.currentTime);
}
