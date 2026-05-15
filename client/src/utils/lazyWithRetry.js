import React from 'react';

const RELOAD_FLAG = 'pwa_chunk_reload_attempted_at';
const RELOAD_COOLDOWN_MS = 30_000;

function purgeStaleChunkFromCaches(url) {
  if (typeof caches === 'undefined' || typeof url !== 'string') return Promise.resolve();
  return caches.keys()
    .then(keys => Promise.all(
      keys.map(name => caches.open(name).then(cache => cache.delete(url).catch(() => {})))
    ))
    .catch(() => {});
}

function isChunkLoadError(err) {
  if (!err) return false;
  const msg = String(err.message || err);
  return (
    err.name === 'ChunkLoadError' ||
    /Loading chunk [\w-]+ failed/i.test(msg) ||
    /Failed to fetch dynamically imported module/i.test(msg) ||
    /error loading dynamically imported module/i.test(msg) ||
    /Importing a module script failed/i.test(msg)
  );
}

export function lazyWithRetry(factory) {
  return React.lazy(async () => {
    try {
      return await factory();
    } catch (err) {
      if (!isChunkLoadError(err)) throw err;

      const failedUrl = err && err.request ? err.request : null;
      await purgeStaleChunkFromCaches(failedUrl);

      const last = Number(window.sessionStorage.getItem(RELOAD_FLAG) || 0);
      const now = Date.now();
      if (now - last > RELOAD_COOLDOWN_MS) {
        window.sessionStorage.setItem(RELOAD_FLAG, String(now));
        try {
          if ('serviceWorker' in navigator) {
            const regs = await navigator.serviceWorker.getRegistrations();
            await Promise.all(regs.map(r => r.update().catch(() => {})));
          }
        } catch { /* ignore */ }
        window.location.reload();
        return { default: () => null };
      }

      return await factory();
    }
  });
}
