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

const DUCK_LEVEL = 0.4; // 60% volume reduction (keep 40%) per Apex Announcer spec
const DUCK_RAMP_MS = 300;
const BUFFER_CACHE = new Map();
const MAX_CACHE_SIZE = 20;

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

const MAX_AUDIO_BYTES = 50 * 1024 * 1024; // 50 MB hard limit

function _isAllowedAudioUrl(url) {
  if (!url) return false;
  // Allow same-origin (relative paths / announcer clips)
  if (url.startsWith('/')) return true;
  try {
    const parsed = new URL(url, window.location.origin);
    // Only allow https (or http on localhost for dev)
    if (parsed.protocol !== 'https:' && !(parsed.protocol === 'http:' && parsed.hostname === 'localhost')) return false;
    // Block private/internal IPs
    if (/^(10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|127\.|0\.)/.test(parsed.hostname)) return false;
    return true;
  } catch {
    return false;
  }
}

export async function loadBuffer(url) {
  if (BUFFER_CACHE.has(url)) {
    return BUFFER_CACHE.get(url);
  }
  if (!_isAllowedAudioUrl(url)) {
    throw new Error(`Audio URL blocked by security policy: ${url}`);
  }
  const audioCtx = getContext();
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`Failed to fetch audio: ${resp.status} ${url}`);
  const contentLength = parseInt(resp.headers.get('content-length') || '0', 10);
  if (contentLength > MAX_AUDIO_BYTES) {
    throw new Error(`Audio file too large: ${contentLength} bytes (max ${MAX_AUDIO_BYTES})`);
  }
  const arrayBuf = await resp.arrayBuffer();
  if (arrayBuf.byteLength > MAX_AUDIO_BYTES) {
    throw new Error(`Audio file too large: ${arrayBuf.byteLength} bytes`);
  }
  const audioBuf = await audioCtx.decodeAudioData(arrayBuf);
  // LRU eviction: drop oldest entry when cache is full
  if (BUFFER_CACHE.size >= MAX_CACHE_SIZE) {
    const oldest = BUFFER_CACHE.keys().next().value;
    BUFFER_CACHE.delete(oldest);
  }
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
 * Detect BPM of an AudioBuffer using autocorrelation on the first 20s.
 * Returns { bpm, confidence } or null if detection fails / confidence < 0.5.
 *
 * @param {AudioBuffer} audioBuffer
 * @returns {{ bpm: number, confidence: number } | null}
 */
export function detectBPM(audioBuffer) {
  try {
    const sampleRate = audioBuffer.sampleRate;
    const analysisSeconds = Math.min(20, audioBuffer.duration);
    const numSamples = Math.floor(analysisSeconds * sampleRate);

    // Downsample to mono at ~3000 Hz for fast autocorrelation
    const downsampleRate = 3000;
    const downsampleFactor = Math.floor(sampleRate / downsampleRate);
    const channelData = audioBuffer.getChannelData(0);
    const downsampled = [];
    for (let i = 0; i < numSamples; i += downsampleFactor) {
      downsampled.push(channelData[i]);
    }

    const n = downsampled.length;
    if (n < 128) return null;

    // Autocorrelation over lags corresponding to 50–200 BPM
    const minLag = Math.floor(downsampleRate * 60 / 200); // 200 BPM → shortest lag
    const maxLag = Math.floor(downsampleRate * 60 / 50);  // 50 BPM → longest lag

    let bestLag = -1;
    let bestCorr = -Infinity;

    // Normalize signal
    let sum = 0;
    for (let i = 0; i < n; i++) sum += downsampled[i] * downsampled[i];
    const norm = sum / n;
    if (norm === 0) return null;

    for (let lag = minLag; lag <= Math.min(maxLag, n - 1); lag++) {
      let corr = 0;
      for (let i = 0; i < n - lag; i++) {
        corr += downsampled[i] * downsampled[i + lag];
      }
      corr /= (n - lag) * norm;
      if (corr > bestCorr) {
        bestCorr = corr;
        bestLag = lag;
      }
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
 * Calculate the seconds-into-track at which to trigger the announcer TTS
 * so it lands exactly `barsBeforeDrop` bars before the drop/hook.
 *
 * Assumes 4/4 time. Default: trigger 2 bars before bar 8 (common pop structure).
 *
 * @param {number} bpm
 * @param {number} [dropBar=8] - Bar number where the drop occurs (1-indexed)
 * @param {number} [barsBeforeDrop=2] - How many bars before the drop to trigger TTS
 * @returns {number} seconds offset
 */
export function calcBeatOffset(bpm, dropBar = 8, barsBeforeDrop = 2) {
  if (!bpm || bpm <= 0) return 5; // sensible default
  const secondsPerBeat = 60 / bpm;
  const secondsPerBar = secondsPerBeat * 4;
  const triggerBar = Math.max(1, dropBar - barsBeforeDrop);
  return Math.round((triggerBar - 1) * secondsPerBar * 10) / 10;
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
 * @param {boolean} [opts.autoBPM=false] - Auto-detect BPM and override introTimestamp
 * @param {Function} [opts.onEnd] - Called when the full sequence completes
 * @param {Function} [opts.onProgress] - Called with { elapsed, duration } during playback
 */
export async function playIntro({ walkupUrl, clipUrl, introTimestamp = 5, autoBPM = false, onEnd, onProgress }) {
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

  // BPM beat-matching: auto-set intro timestamp when autoBPM is enabled
  // and no explicit timestamp was provided (introTimestamp === 0).
  if (autoBPM && walkupBuf && introTimestamp === 0) {
    const bpmResult = detectBPM(walkupBuf);
    if (bpmResult) {
      introTimestamp = calcBeatOffset(bpmResult.bpm);
    }
  }

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
