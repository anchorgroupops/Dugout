// Team-password gate, client side (SIGN-021). The server half is
// tools/sync_daemon.py `_guard_app_session` and /api/auth/{check,login,logout};
// the session lives in an HttpOnly cookie, so JS never sees it.
//
// Only a 401 means "locked". A network failure, timeout or 5xx means "open":
// the installed PWA must still boot from cached data in a dugout with no signal.

const CHECK_TIMEOUT_MS = 4000;

export async function checkAppAuth(fetchImpl = fetch, timeoutMs = CHECK_TIMEOUT_MS) {
  const ctrl = typeof AbortController === 'function' ? new AbortController() : null;
  const timer = ctrl ? setTimeout(() => ctrl.abort(), timeoutMs) : null;
  try {
    const res = await fetchImpl('/api/auth/check', {
      cache: 'no-store',
      credentials: 'same-origin',
      signal: ctrl?.signal,
    });
    return res.status === 401 ? 'locked' : 'open';
  } catch {
    return 'open';
  } finally {
    if (timer) clearTimeout(timer);
  }
}

// True for the gate's own 401 (not a write-token 401 or any other error).
export async function isAuthRequiredResponse(res) {
  if (!res || res.status !== 401) return false;
  try {
    const data = await res.clone().json();
    return data?.error === 'auth_required';
  } catch {
    return false;
  }
}

// Resolves to 'ok' | 'wrong' | 'rate_limited' | 'error'.
export async function loginWithPassword(password, fetchImpl = fetch) {
  try {
    const res = await fetchImpl('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ password }),
    });
    if (res.ok) return 'ok';
    if (res.status === 401) return 'wrong';
    if (res.status === 429) return 'rate_limited';
    return 'error';
  } catch {
    return 'error';
  }
}

export async function logoutApp(fetchImpl = fetch) {
  try {
    await fetchImpl('/api/auth/logout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: '{}',
    });
  } catch { /* offline: the gate still shows; the cookie is cleared next time */ }
}
