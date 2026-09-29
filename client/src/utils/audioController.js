/**
 * Audio Controller — Web Audio engine for walk-up music + announcer ducking.
 *
 * Routing:
 *   WalkupSource → WalkupGain ─┐
 *   ClipSource   → ClipGain ───┼─→ MasterGain → Destination
 *   EffectSource(s) ───────────┘   (soundboard: see playEffect)
 *
 * Playback flow (walk-up = call + song):
 *   1. The announcer call plays first, from t = 0
 *   2. The song comes in OVERLAP seconds before the call ends, at its
 *      in-point (the per-song `start`, seconds into the track), ducked to
 *      DUCK_LEVEL under the call's tail
 *   3. When the call ends the song ramps to full over DUCK_RAMP_MS and plays on
 * Both sources and the gain ramp are scheduled up front on the AudioContext
 * clock (planWalkup gives the numbers), so there are no timers to drift.
 *
 * Exactly one walk-up / preview plays at a time (soundboard effects are a
 * separate channel on top of it). Every play() takes a new generation
 * number; anything scheduled by an older play (a fetch still in flight, an
 * `ended` handler, the progress ticker) checks it and does nothing once it
 * is stale, and haltAudio() stops a song that is scheduled but not yet
 * audible, so it never comes in after a Stop or a batter switch. Without that, a second tap during a slow fetch
 * played both clips over each other, and the first batter's `ended` event
 * (which fires asynchronously after stop()) marked the second batter's
 * announcement finished before it had started.
 *
 * The UI never tracks "is playing" itself: it subscribes to one state object
 * (useSyncExternalStore), so the now-playing bar cannot drift from the audio.
 */

const DUCK_LEVEL = 0.4; // keep 40% of the music under the call
const DUCK_RAMP_MS = 300;
const OVERLAP = 0.5; // seconds the song comes in before the call ends
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
 * Where each part of a walk-up sits on the timeline, in seconds from the tap.
 * The call starts at 0; the song starts OVERLAP seconds before the call ends
 * (at 0 if the call is shorter than that, or if there is no call), playing
 * from `inPoint` seconds into the track. An in-point that is negative, not a
 * number, or past the end of the song plays the song from the top.
 *
 * @returns {{ songAt: number, songOffset: number, callEnd: number, total: number }}
 *   total is when the last part ends (drives the progress bar).
 */
export function planWalkup({ clipDuration = 0, songDuration = 0, inPoint = 0, overlap = OVERLAP } = {}) {
  const callEnd = Math.max(0, Number(clipDuration) || 0);
  const songLen = Math.max(0, Number(songDuration) || 0);
  let songOffset = Math.max(0, Number(inPoint) || 0);
  if (songOffset >= songLen) songOffset = 0;
  const songAt = Math.max(0, callEnd - Math.max(0, overlap));
  const songEnd = songLen ? songAt + (songLen - songOffset) : 0;
  return { songAt, songOffset, callEnd, total: Math.max(callEnd, songEnd) };
}

/**
 * Play a walk-up: the announcer call first, then the song coming in under
 * the call's last half-second (see planWalkup). Either part may be missing.
 * Replaces whatever is playing. Resolves once playback has been scheduled
 * (or failed); the outcome is in getState(), never thrown.
 *
 * @param {Object} o
 * @param {string} o.key        caller's id for this playback (shown as "playing")
 * @param {string} [o.label]    headline for the now-playing bar
 * @param {string} [o.detail]   secondary line (voice + song)
 * @param {string} [o.songUrl]
 * @param {string} [o.clipUrl]
 * @param {number} [o.songStart=0] the song's in-point: seconds into the track it starts from
 */
export async function play({ key, label = '', detail = '', songUrl = '', clipUrl = '', songStart = 0 }) {
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

  const plan = planWalkup({
    clipDuration: clipBuf ? clipBuf.duration : 0,
    songDuration: walkupBuf ? walkupBuf.duration : 0,
    inPoint: songStart,
  });
  const duration = plan.total;
  const now = audioCtx.currentTime;
  const startedAt = now;

  // The sequence ends when every part has ended: a song started near its end
  // can finish before the call does.
  let running = (walkupBuf ? 1 : 0) + (clipBuf ? 1 : 0);
  const finish = () => {
    if (gen !== generation) return;
    haltAudio();
    setState(IDLE);
  };
  const partEnded = () => {
    if (gen !== generation) return;
    if (--running <= 0) finish();
  };

  clipGain.gain.setValueAtTime(1.0, now);
  walkupGain.gain.cancelScheduledValues?.(now);
  if (walkupBuf && clipBuf) {
    // Ducked under the call's tail, back to full as the call ends.
    const callEnd = now + plan.callEnd;
    walkupGain.gain.setValueAtTime(DUCK_LEVEL, now);
    walkupGain.gain.setValueAtTime(DUCK_LEVEL, callEnd);
    walkupGain.gain.linearRampToValueAtTime(1.0, callEnd + DUCK_RAMP_MS / 1000);
  } else {
    walkupGain.gain.setValueAtTime(1.0, now);
  }

  setState({ ...IDLE, status: 'playing', key, label, detail, warning, duration });
  progressTimer = setInterval(() => {
    if (gen !== generation) return;
    setState({ ...state, elapsed: Math.min(duration, Math.max(0, audioCtx.currentTime - startedAt)) });
  }, 250);

  if (clipBuf) {
    clipSource = audioCtx.createBufferSource();
    clipSource.buffer = clipBuf;
    clipSource.connect(clipGain);
    clipSource.onended = partEnded;
    clipSource.start(now);
  }

  if (walkupBuf) {
    // Scheduled ahead; haltAudio()'s stop() cancels it if it hasn't begun.
    walkupSource = audioCtx.createBufferSource();
    walkupSource.buffer = walkupBuf;
    walkupSource.connect(walkupGain);
    walkupSource.onended = partEnded;
    walkupSource.start(now + plan.songAt, plan.songOffset);
  }
}

// ── Soundboard effects ─────────────────────────────────────────────────────
// A second, independent channel. Effects go straight to the master gain, so
// the walk-up's duck ramp never touches them; they never read or bump
// `generation`, never set the store, and never stop the walk-up. Any number
// of different effects can overlap; tapping one that is still playing
// restarts it. Decoded effects live in their own small cache so they can't
// evict the up-next batter's song and call from BUFFER_CACHE.
const MAX_EFFECT_CACHE = 24;
const EFFECT_CACHE = new Map();
const effectSources = new Map(); // url → the source playing it
const effectTaps = new Map();    // url → tap count, so a slow first load can't play over a later tap

async function loadEffect(url) {
  if (EFFECT_CACHE.has(url)) return EFFECT_CACHE.get(url);
  if (!_isAllowedAudioUrl(url)) throw new Error('link not allowed');
  const audioCtx = getContext();
  const resp = await fetchWithTimeout(url);
  if (!resp.ok) throw new Error(resp.status === 404 ? 'file missing' : `server said ${resp.status}`);
  const arrayBuf = await resp.arrayBuffer();
  if (arrayBuf.byteLength > MAX_AUDIO_BYTES) throw new Error('file too large');
  let audioBuf;
  try {
    audioBuf = await audioCtx.decodeAudioData(arrayBuf);
  } catch {
    throw new Error('not a playable audio file');
  }
  if (EFFECT_CACHE.size >= MAX_EFFECT_CACHE) EFFECT_CACHE.delete(EFFECT_CACHE.keys().next().value);
  EFFECT_CACHE.set(url, audioBuf);
  return audioBuf;
}

/** Decode soundboard effects ahead of time so the first tap is instant. Never throws. */
export async function preloadEffects(urls) {
  await Promise.all((urls || []).filter(Boolean).map(url => loadEffect(url).catch(() => null)));
}

/**
 * Fire a soundboard effect over whatever is playing.
 * @returns {Promise<{ok: boolean, duration?: number, error?: string}>}
 */
export async function playEffect(url) {
  const audioCtx = getContext(); // before any await: must run inside the tap
  const tap = (effectTaps.get(url) || 0) + 1;
  effectTaps.set(url, tap);
  const prev = effectSources.get(url);
  if (prev) { stopSource(prev); effectSources.delete(url); }
  let buf;
  try {
    buf = await loadEffect(url);
  } catch (e) {
    return { ok: false, error: e?.message || 'failed' };
  }
  if (effectTaps.get(url) !== tap) return { ok: true, duration: buf.duration }; // a later tap took over
  const src = audioCtx.createBufferSource();
  src.buffer = buf;
  src.connect(masterGain);
  src.onended = () => {
    if (effectSources.get(url) === src) effectSources.delete(url);
    try { src.disconnect(); } catch { /* ok */ }
  };
  effectSources.set(url, src);
  src.start();
  return { ok: true, duration: buf.duration };
}

/** Stop every effect (teardown). The walk-up is left alone. */
export function stopEffects() {
  effectSources.forEach(stopSource);
  effectSources.clear();
  effectTaps.clear();
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
  stopEffects();
  BUFFER_CACHE.clear();
  EFFECT_CACHE.clear();
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
