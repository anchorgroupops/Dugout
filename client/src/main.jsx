import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import './index.css';

// Global chunk-load error handler — when a JS chunk fails to load
// (stale SW cache, deploy mid-session), purge it from caches and force
// a hard reload so the browser fetches the fresh manifest. Cooldown
// prevents reload storms.
const RELOAD_FLAG = 'pwa_chunk_reload_attempted_at';
const RELOAD_COOLDOWN_MS = 30_000;
function maybeReloadOnChunkError(url) {
  const last = Number(window.sessionStorage.getItem(RELOAD_FLAG) || 0);
  if (Date.now() - last < RELOAD_COOLDOWN_MS) return;
  window.sessionStorage.setItem(RELOAD_FLAG, String(Date.now()));
  const purge = (typeof caches !== 'undefined')
    ? caches.keys().then(keys => Promise.all(
        keys.map(name => caches.open(name).then(c => url ? c.delete(url).catch(() => {}) : null))
      )).catch(() => {})
    : Promise.resolve();
  purge.finally(() => window.location.reload());
}
window.addEventListener('error', (e) => {
  const target = e.target;
  if (target && (target.tagName === 'SCRIPT' || target.tagName === 'LINK') && target.src) {
    if (/\/assets\/.+\.(js|css)(\?.*)?$/.test(target.src)) {
      maybeReloadOnChunkError(target.src);
    }
  }
}, true);
window.addEventListener('unhandledrejection', (e) => {
  const reason = e.reason;
  if (!reason) return;
  const msg = String(reason.message || reason);
  if (
    reason.name === 'ChunkLoadError' ||
    /Loading chunk [\w-]+ failed/i.test(msg) ||
    /Failed to fetch dynamically imported module/i.test(msg)
  ) {
    maybeReloadOnChunkError(reason.request || null);
  }
});

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

// Manual SW registration. Vite-PWA's `injectRegister: 'script-defer'` was
// racing the page load on slow connections and surfacing as
// `AbortError: Failed to register a ServiceWorker`. Doing it ourselves
// after `load`, with a stale-worker sweep, fixes both the race and the
// "old SW from a prior install scope" edge cases.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', async () => {
    try {
      const expectedScope = window.location.origin + '/';
      const registrations = await navigator.serviceWorker.getRegistrations();
      for (const reg of registrations) {
        if (reg.scope !== expectedScope) {
          try { await reg.unregister(); } catch { /* ignore */ }
        }
      }
      await navigator.serviceWorker.register('/sw.js', { scope: '/' });
    } catch (err) {
      console.warn('[SW] registration failed:', err);
    }
  });

  // `skipWaiting` + `clientsClaim` (vite.config.js) mean a newly-installed
  // SW takes control of this tab right after a deploy, but the tab's
  // in-memory JS keeps running the old build until something reloads it.
  // Reload once when control changes so an already-open dugout tab picks
  // up the new build immediately instead of waiting for a stale-chunk
  // fetch to fail first. Guarded (module-level flag, not sessionStorage)
  // so a pathological repeated-controllerchange burst can't reload-loop —
  // this only ever needs to fire once per page life.
  let hasReloadedForController = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (hasReloadedForController) return;
    hasReloadedForController = true;
    window.location.reload();
  });
}
