// Centralized API client with:
//  - Global 429 pause: when ANY endpoint returns 429, set a 30s pause window
//    that affects all non-critical polling. Components opt in by checking
//    `isPolingPausedUntil()` before scheduling their next fetch.
//  - Stale-while-revalidate cache: shared across the app so tab switches
//    don't trigger redundant network fetches.

const PAUSE_KEY = '__sharks_polling_paused_until';
const PAUSE_MS = 60_000;

let pausedUntil = 0;
const subscribers = new Set();

export function isPollingPaused() {
  return Date.now() < pausedUntil;
}

export function getPausedUntil() {
  return pausedUntil;
}

export function pausePollingFor(ms = PAUSE_MS) {
  pausedUntil = Math.max(pausedUntil, Date.now() + ms);
  try { window.sessionStorage.setItem(PAUSE_KEY, String(pausedUntil)); } catch { /* ignore */ }
  for (const s of subscribers) s(pausedUntil);
}

export function subscribePauseChange(fn) {
  subscribers.add(fn);
  return () => subscribers.delete(fn);
}

// Restore pausedUntil on page reload so a refresh storm doesn't escape
// the cooldown.
try {
  const saved = Number(window.sessionStorage.getItem(PAUSE_KEY) || 0);
  if (saved > Date.now()) pausedUntil = saved;
} catch { /* ignore */ }

// Wrapper around fetch — observes 429 globally and short-circuits during
// the pause window for non-critical (`pollable: true`) requests. Critical
// user-triggered requests (`critical: true`) always go through.
export async function apiFetch(url, options = {}) {
  const { pollable = false, critical = false, ...init } = options;
  if (pollable && !critical && isPollingPaused()) {
    return new Response(null, { status: 503, statusText: 'paused-locally' });
  }
  const res = await fetch(url, init);
  if (res.status === 429) pausePollingFor();
  return res;
}

// Exponential-backoff fetch with jitter for read-only API polls.
// On 429 / 5xx / network error: sleep for `min(BASE * 2**attempt + jitter, MAX)`
// and retry up to `maxRetries` times. Hard-aborts (caller AbortController)
// pass through unchanged.
//
// Use ONLY for idempotent GETs. Do NOT wrap mutating POST/PUT/DELETE — a
// retry after a successful write that returned a flaky response would
// double-apply the mutation. Mutations should fail loudly to the caller.
export async function fetchWithBackoff(url, options = {}, maxRetries = 3) {
  const BASE = 1000;
  const MAX = 10_000;
  const sleep = (attempt) => new Promise((r) =>
    setTimeout(r, Math.min(BASE * 2 ** attempt + Math.random() * 500, MAX))
  );
  // Honor the global pause window on the very first call so we don't burn
  // a retry slot when we already know the backend is rate-limiting us.
  if (isPollingPaused()) {
    return new Response(null, { status: 503, statusText: 'paused-locally' });
  }
  let lastErr = null;
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      const res = await fetch(url, options);
      if (res.status === 429) {
        pausePollingFor();
        if (attempt === maxRetries - 1) return res;
        await sleep(attempt);
        continue;
      }
      if (res.status >= 500 && res.status < 600) {
        if (attempt === maxRetries - 1) return res;
        await sleep(attempt);
        continue;
      }
      return res;
    } catch (err) {
      lastErr = err;
      // Pass-through for caller-initiated aborts.
      if (err && err.name === 'AbortError') throw err;
      if (attempt === maxRetries - 1) throw err;
      await sleep(attempt);
    }
  }
  // Unreachable, but keep TS-friendly.
  if (lastErr) throw lastErr;
  return new Response(null, { status: 599, statusText: 'backoff-exhausted' });
}

// ---------------------------------------------------------------------------
// Stale-while-revalidate cache for shared GET endpoints
// ---------------------------------------------------------------------------
// Map<key, { data, fetchedAt, promise }>
const cache = new Map();
const cacheSubs = new Map(); // key -> Set<fn>
const DEFAULT_TTL_MS = 2 * 60 * 1000;
const inflight = new Map(); // key -> Promise

function notifyKey(key) {
  const subs = cacheSubs.get(key);
  if (!subs) return;
  const entry = cache.get(key);
  for (const fn of subs) {
    try { fn(entry ? entry.data : null); } catch { /* ignore */ }
  }
}

export async function getCached(key, fetcher, { ttl = DEFAULT_TTL_MS, force = false } = {}) {
  const now = Date.now();
  const entry = cache.get(key);
  const fresh = entry && (now - entry.fetchedAt) < ttl;
  if (entry && fresh && !force) return entry.data;

  if (inflight.has(key)) return inflight.get(key);

  const p = (async () => {
    try {
      const data = await fetcher();
      cache.set(key, { data, fetchedAt: Date.now() });
      notifyKey(key);
      return data;
    } catch (err) {
      // On error, return stale data if we have it; otherwise re-throw.
      if (entry) return entry.data;
      throw err;
    } finally {
      inflight.delete(key);
    }
  })();
  inflight.set(key, p);
  return p;
}

export function peekCached(key) {
  const entry = cache.get(key);
  return entry ? entry.data : null;
}

export function subscribeCache(key, fn) {
  if (!cacheSubs.has(key)) cacheSubs.set(key, new Set());
  cacheSubs.get(key).add(fn);
  return () => {
    const subs = cacheSubs.get(key);
    if (subs) subs.delete(fn);
  };
}

export function invalidateCache(key) {
  cache.delete(key);
  notifyKey(key);
}

// Convenience: shared GET that returns parsed JSON (or fallback on error/non-OK).
// Multiple call sites get one network request; result cached for `ttl` ms.
export function fetchSharedJson(url, { ttl = DEFAULT_TTL_MS, fallback = null, force = false } = {}) {
  return getCached(url, async () => {
    if (isPollingPaused()) return fallback;
    const res = await fetch(url);
    if (!res.ok) {
      if (res.status === 429) pausePollingFor();
      return fallback;
    }
    try {
      return await res.json();
    } catch {
      return fallback;
    }
  }, { ttl, force });
}

// ---------------------------------------------------------------------------
// localStorage-backed never-downgrade cache for offline fallbacks
// ---------------------------------------------------------------------------
// Each key is namespaced to avoid colliding with App.jsx's `sharks_data_cache`.
// Stores `{value, savedAt}` so consumers can show a "stale data — last
// updated <time>" indicator when reading the cached fallback.

const LS_PREFIX = 'sharks_local_cache:';

function isUsefulValue(v) {
  if (v == null) return false;
  if (Array.isArray(v)) return v.length > 0;
  if (typeof v === 'object') {
    if (Array.isArray(v.standings)) return v.standings.length > 0;
    if (Array.isArray(v.upcoming) || Array.isArray(v.past)) {
      return (v.upcoming?.length || 0) + (v.past?.length || 0) > 0;
    }
    return Object.keys(v).length > 0;
  }
  return true;
}

export function getLocalCachedJson(key) {
  try {
    const raw = window.localStorage.getItem(LS_PREFIX + key);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    return parsed;  // {value, savedAt}
  } catch {
    return null;
  }
}

export function setLocalCachedJson(key, value) {
  // "Never downgrade": don't clobber a useful previous value with null/empty.
  if (!isUsefulValue(value)) {
    if (typeof console !== 'undefined' && console.warn) {
      console.warn(`[localCache] skipping non-useful write for "${key}"`);
    }
    return false;
  }
  try {
    window.localStorage.setItem(LS_PREFIX + key, JSON.stringify({
      value,
      savedAt: new Date().toISOString(),
    }));
    return true;
  } catch {
    return false;
  }
}

/**
 * Fetch a JSON endpoint with a localStorage fallback.
 *
 * On success: returns {value, fromCache: false, savedAt}; persists value.
 * On 4xx/5xx: returns {value: cachedValue, fromCache: true, savedAt} if
 *   cached; otherwise {value: null, fromCache: false, error}.
 * On 429: triggers global polling pause AND returns the cached value.
 *
 * Only writes to localStorage when the new value is "useful" (not null,
 * not empty array, not empty object) — preserves last-known-good data.
 */
export async function fetchWithLocalCache(url, key, { fallback = null } = {}) {
  const cached = getLocalCachedJson(key);
  // Honor global pause: serve cached + don't hit the network at all.
  if (isPollingPaused() && cached) {
    return { value: cached.value, fromCache: true, savedAt: cached.savedAt };
  }
  try {
    const res = await fetch(url);
    if (res.status === 429) {
      pausePollingFor();
      return cached
        ? { value: cached.value, fromCache: true, savedAt: cached.savedAt, rateLimited: true }
        : { value: fallback, fromCache: false, error: 'rate_limited' };
    }
    if (!res.ok) {
      return cached
        ? { value: cached.value, fromCache: true, savedAt: cached.savedAt, httpStatus: res.status }
        : { value: fallback, fromCache: false, httpStatus: res.status };
    }
    let data;
    try {
      data = await res.json();
    } catch {
      return cached
        ? { value: cached.value, fromCache: true, savedAt: cached.savedAt, error: 'parse_error' }
        : { value: fallback, fromCache: false, error: 'parse_error' };
    }
    if (isUsefulValue(data)) {
      setLocalCachedJson(key, data);
      return { value: data, fromCache: false, savedAt: new Date().toISOString() };
    }
    // Successful fetch but empty payload — return cached if available, else
    // the empty value as-is (don't write the empty value to cache).
    return cached
      ? { value: cached.value, fromCache: true, savedAt: cached.savedAt, empty: true }
      : { value: data, fromCache: false, empty: true };
  } catch (err) {
    return cached
      ? { value: cached.value, fromCache: true, savedAt: cached.savedAt, error: String(err) }
      : { value: fallback, fromCache: false, error: String(err) };
  }
}
