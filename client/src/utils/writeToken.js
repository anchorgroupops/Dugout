// Storage for the shared write-token gate (DUGOUT_WRITE_TOKEN on the API).
// See tools/sync_daemon.py: `_guard_write_token()` / `X-Dugout-Token`.
//
// The token is opaque to the client — we just remember whatever the coach
// typed into the `window.prompt()` in apiClient.js and replay it on every
// mutating /api/* request. Wrapped in try/catch: localStorage can throw in
// private-browsing / storage-blocked contexts, and a missing token there
// should degrade to "prompt again," not crash the app.

const STORAGE_KEY = 'dugout_write_token';

export function getWriteToken() {
  try {
    return window.localStorage.getItem(STORAGE_KEY) || '';
  } catch {
    return '';
  }
}

export function setWriteToken(token) {
  try {
    if (token) {
      window.localStorage.setItem(STORAGE_KEY, token);
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  } catch { /* ignore — private mode / storage blocked */ }
}

export function clearWriteToken() {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch { /* ignore */ }
}
