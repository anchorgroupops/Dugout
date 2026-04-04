/**
 * Audio Controller — Web Audio API engine for walk-up music + announcer ducking.
 *
 * Routing:
 *   WalkupSource → WalkupGain ─┐
 *                                ├─→ MasterGain → Destination
 *   ClipSource   → ClipGain ───┘
 *
 * Playback flow:
 *   1. Music starts at full volume
 *   2. At introTimestamp: duck music 1.0 → 0.3 over 300ms
 *   3. Play announcer clip
 *   4. On clip end: restore music 0.3 → 1.0 over 300ms
 */

const DUCK_LEVEL = 0.3;
const DUCK_RAMP_MS = 300;
const BUFFER_CACHE = new Map();

let ctx = null;
let masterGain = null;
let walkupGain = null;
let clipGain = null;
let walkupSource = null;
let clipSource = null;
let duckTimer = null;
let isPlaying = false;
let onEndCallback = null;

function getContext() {
  if (!ctx || ctx.state === 'closed') {
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    masterGain = ctx.createGain();
    walkupGain = ctx.createGain();
    clipGain = ctx.createGain();
    walkupGain.connect(masterGain);
    clipGain.connect(masterGain);
    masterGain.connect(ctx.destination);
  }
  // Resume if suspended (browser autoplay policy)
  if (ctx.state === 'suspended') {
    ctx.resume();
  }
  return ctx;
}

async function loadBuffer(url) {
  if (BUFFER_CACHE.has(url)) {
    return BUFFER_CACHE.get(url);
  }
  const audioCtx = getContext();
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`Failed to fetch audio: ${resp.status} ${url}`);
  const arrayBuf = await resp.arrayBuffer();
  const audioBuf = await audioCtx.decodeAudioData(arrayBuf);
  BUFFER_CACHE.set(url, audioBuf);
  return audioBuf;
}

function stopSource(src) {
  if (src) {
    try { src.stop(); } catch { /* already stopped */ }
    try { src.disconnect(); } catch { /* ok */ }
  }
}

/**
 * Preload audio buffers for the next batter (call during current playback).
 */
export async function preload(urls) {
  const loads = (urls || []).filter(Boolean).map(url =>
    loadBuffer(url).catch(() => null)
  );
  await Promise.all(loads);
}

/**
 * Play the full walk-up + announcer intro sequence.
 *
 * @param {Object} opts
 * @param {string} opts.walkupUrl - URL of the walk-up song MP3
 * @param {string} opts.clipUrl - URL of the announcer clip MP3
 * @param {number} [opts.introTimestamp=5] - Seconds into the song to start ducking
 * @param {Function} [opts.onEnd] - Called when the full sequence completes
 * @param {Function} [opts.onProgress] - Called with { elapsed, duration } during playback
 */
export async function playIntro({ walkupUrl, clipUrl, introTimestamp = 5, onEnd, onProgress }) {
  stop(); // Stop any previous playback
  const audioCtx = getContext();

  isPlaying = true;
  onEndCallback = onEnd || null;

  // Load both audio buffers (may be cached)
  const [walkupBuf, clipBuf] = await Promise.all([
    walkupUrl ? loadBuffer(walkupUrl) : null,
    clipUrl ? loadBuffer(clipUrl) : null,
  ]);

  if (!isPlaying) return; // User called stop() while loading

  // Reset gains
  walkupGain.gain.setValueAtTime(1.0, audioCtx.currentTime);
  clipGain.gain.setValueAtTime(1.0, audioCtx.currentTime);

  // Start walk-up music
  if (walkupBuf) {
    walkupSource = audioCtx.createBufferSource();
    walkupSource.buffer = walkupBuf;
    walkupSource.connect(walkupGain);
    walkupSource.start(0);
  }

  // Progress reporting
  let progressInterval = null;
  const startTime = audioCtx.currentTime;
  const totalDuration = walkupBuf ? walkupBuf.duration : (clipBuf ? clipBuf.duration : 0);
  if (onProgress && totalDuration > 0) {
    progressInterval = setInterval(() => {
      if (!isPlaying) {
        clearInterval(progressInterval);
        return;
      }
      const elapsed = audioCtx.currentTime - startTime;
      onProgress({ elapsed, duration: totalDuration });
    }, 250);
  }

  // Schedule ducking and clip playback
  if (clipBuf) {
    const duckDelay = walkupBuf ? Math.max(0, introTimestamp) * 1000 : 0;
    duckTimer = setTimeout(() => {
      if (!isPlaying) return;

      // Duck the music
      if (walkupBuf) {
        const now = audioCtx.currentTime;
        walkupGain.gain.setValueAtTime(walkupGain.gain.value, now);
        walkupGain.gain.linearRampToValueAtTime(DUCK_LEVEL, now + DUCK_RAMP_MS / 1000);
      }

      // Play the announcer clip
      clipSource = audioCtx.createBufferSource();
      clipSource.buffer = clipBuf;
      clipSource.connect(clipGain);
      clipSource.start(0);

      clipSource.onended = () => {
        if (!isPlaying) return;
        // Restore music volume
        if (walkupBuf && walkupSource) {
          const now = audioCtx.currentTime;
          walkupGain.gain.setValueAtTime(DUCK_LEVEL, now);
          walkupGain.gain.linearRampToValueAtTime(1.0, now + DUCK_RAMP_MS / 1000);
        }
      };
    }, duckDelay);

    // If no walkup, the clip ending means the sequence is done
    if (!walkupBuf) {
      const clipSrc = await new Promise(resolve => {
        const checkTimer = setTimeout(() => {
          resolve(clipSource);
        }, duckDelay + 50);
        if (!isPlaying) { clearTimeout(checkTimer); resolve(null); }
      });
      if (clipSrc) {
        clipSrc.onended = () => {
          if (progressInterval) clearInterval(progressInterval);
          isPlaying = false;
          if (onEndCallback) onEndCallback();
        };
      }
    }
  }

  // If walkup exists, it controls overall sequence end
  if (walkupSource) {
    walkupSource.onended = () => {
      if (progressInterval) clearInterval(progressInterval);
      isPlaying = false;
      if (onEndCallback) onEndCallback();
    };
  }
}

/**
 * Play a single clip (no walkup music). Used for previewing announcer clips.
 */
export async function playClip(url, onEnd) {
  stop();
  const audioCtx = getContext();
  isPlaying = true;

  const buf = await loadBuffer(url);
  if (!isPlaying) return;

  clipGain.gain.setValueAtTime(1.0, audioCtx.currentTime);
  clipSource = audioCtx.createBufferSource();
  clipSource.buffer = buf;
  clipSource.connect(clipGain);
  clipSource.start(0);

  clipSource.onended = () => {
    isPlaying = false;
    if (onEnd) onEnd();
  };
}

/**
 * Stop all playback immediately.
 */
export function stop() {
  isPlaying = false;
  onEndCallback = null;
  if (duckTimer) {
    clearTimeout(duckTimer);
    duckTimer = null;
  }
  stopSource(walkupSource);
  stopSource(clipSource);
  walkupSource = null;
  clipSource = null;

  // Reset gains instantly
  if (ctx && walkupGain) {
    try { walkupGain.gain.setValueAtTime(1.0, ctx.currentTime); } catch { /* ok */ }
  }
  if (ctx && clipGain) {
    try { clipGain.gain.setValueAtTime(1.0, ctx.currentTime); } catch { /* ok */ }
  }
}

/**
 * Clean up the AudioContext entirely. Call on app unmount.
 */
export function cleanup() {
  stop();
  BUFFER_CACHE.clear();
  if (ctx && ctx.state !== 'closed') {
    ctx.close().catch(() => {});
  }
  ctx = null;
  masterGain = null;
  walkupGain = null;
  clipGain = null;
}

/**
 * @returns {boolean} Whether audio is currently playing.
 */
export function getIsPlaying() {
  return isPlaying;
}

/**
 * Set the master volume (0.0 to 1.0).
 */
export function setVolume(level) {
  getContext();
  if (masterGain) {
    masterGain.gain.setValueAtTime(Math.max(0, Math.min(1, level)), ctx.currentTime);
  }
}
