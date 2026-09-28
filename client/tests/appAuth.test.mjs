import test from 'node:test';
import assert from 'node:assert/strict';
import { checkAppAuth, isAuthRequiredResponse, loginWithPassword, logoutApp } from '../src/utils/appAuth.js';

const json = (status, body) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' },
});

test('check: 401 locks, 204 opens', async () => {
  assert.equal(await checkAppAuth(async () => json(401, { error: 'auth_required' })), 'locked');
  assert.equal(await checkAppAuth(async () => new Response(null, { status: 204 })), 'open');
});

test('check: offline, 5xx and a hung server all open (cached PWA must still boot)', async () => {
  assert.equal(await checkAppAuth(async () => { throw new TypeError('Failed to fetch'); }), 'open');
  assert.equal(await checkAppAuth(async () => new Response(null, { status: 502 })), 'open');
  const hang = (_url, { signal }) => new Promise((_, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
  });
  assert.equal(await checkAppAuth(hang, 20), 'open');
});

test('check asks /api/auth/check without the HTTP cache', async () => {
  let seen;
  await checkAppAuth(async (url, init) => { seen = { url, init }; return new Response(null, { status: 204 }); });
  assert.equal(seen.url, '/api/auth/check');
  assert.equal(seen.init.cache, 'no-store');
});

test('only the gate\'s own 401 counts as locked', async () => {
  assert.equal(await isAuthRequiredResponse(json(401, { error: 'auth_required' })), true);
  assert.equal(await isAuthRequiredResponse(json(401, { error: 'write_token_required' })), false);
  assert.equal(await isAuthRequiredResponse(json(200, { roster: [] })), false);
  assert.equal(await isAuthRequiredResponse(null), false);
  // The body stays readable for the caller.
  const res = json(401, { error: 'auth_required' });
  await isAuthRequiredResponse(res);
  assert.deepEqual(await res.json(), { error: 'auth_required' });
});

test('login posts JSON and maps the server answer', async () => {
  let sent;
  const ok = await loginWithPassword('pw', async (url, init) => { sent = { url, init }; return new Response(null, { status: 204 }); });
  assert.equal(ok, 'ok');
  assert.equal(sent.url, '/api/auth/login');
  assert.equal(sent.init.method, 'POST');
  assert.deepEqual(JSON.parse(sent.init.body), { password: 'pw' });
  assert.equal(await loginWithPassword('x', async () => json(401, { error: 'bad_password' })), 'wrong');
  assert.equal(await loginWithPassword('x', async () => json(429, { error: 'rate_limited' })), 'rate_limited');
  assert.equal(await loginWithPassword('x', async () => { throw new TypeError('offline'); }), 'error');
});

test('Lock holds on the device offline and drops the cached roster', async () => {
  const store = new Map();
  globalThis.window = { localStorage: {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  } };
  try {
    store.set('sharks_data_cache', '{"team":{}}');
    await logoutApp(async () => { throw new Error('offline'); });
    assert.equal(store.has('sharks_data_cache'), false, 'cached roster cleared');
    // Server unreachable: without the flag this would open on cached data.
    assert.equal(await checkAppAuth(async () => { throw new Error('offline'); }), 'locked');
    const ok = await loginWithPassword('pw', async () => ({ ok: true, status: 204 }));
    assert.equal(ok, 'ok');
    assert.equal(store.has('dugout_locked'), false, 'login clears the flag');
    assert.equal(await checkAppAuth(async () => ({ status: 204 })), 'open');
  } finally {
    delete globalThis.window;
  }
});
