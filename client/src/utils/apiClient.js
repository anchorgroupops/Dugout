// Centralized API client with:
//  - Global 429 pause: when ANY endpoint returns 429, set a 30s pause window
//    that affects all non-critical polling. Components opt in by checking
//    `isPolingPausedUntil()` before scheduling their next fetch.
//  - Stale-while-revalidate cache: shared across the app so tab switches
//    don't trigger redundant network fetches.

const PAUSE_KEY = '__sharks_polling_paused_until';
const PAUSE_MS = 30_000;

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
