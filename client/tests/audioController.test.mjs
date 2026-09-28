// node --test: the audio controller against a fake Web Audio implementation.
//
// The fake mirrors the browser behaviour that caused the overlap and
// stomp bugs: fetches take time, and AudioBufferSourceNode fires `ended`
// asynchronously after stop(), not synchronously.
import test from 'node:test';
import assert from 'node:assert/strict';

const live = new Set();
let maxLive = 0;
const started = [];
const t0 = Date.now();

class FakeParam {
  value = 1;
  setValueAtTime(v) { this.value = v; }
  linearRampToValueAtTime(v) { this.value = v; }
  cancelScheduledValues() {}
}
class FakeGain { gain = new FakeParam(); connect() {} disconnect() {} }
class FakeSource {
  buffer = null;
  onended = null;
  connect() {}
  disconnect() {}
  start() {
    live.add(this);
    maxLive = Math.max(maxLive, live.size);
    started.push(this.buffer.name);
    this._t = setTimeout(() => { live.delete(this); this.onended?.(); }, this.buffer.duration * 1000);
  }
  stop() {
    clearTimeout(this._t);
    live.delete(this);
    setTimeout(() => this.onended?.(), 0); // browsers fire `ended` later
  }
}
const buf = (name, duration) => ({ name, duration, sampleRate: 3000, getChannelData: () => new Float32Array(0) });
class FakeCtx {
  state = 'running';
  destination = {};
  get currentTime() { return (Date.now() - t0) / 1000; }
  createGain() { return new FakeGain(); }
  createBufferSource() { return new FakeSource(); }
  createBuffer() { return buf('unlock', 0); }
  decodeAudioData(ab) { return ab.bad ? Promise.reject(new Error('decode')) : Promise.resolve(buf(ab.name, ab.duration)); }
  resume() { this.state = 'running'; return Promise.resolve(); }
  close() { return Promise.resolve(); }
}

// url → { delay ms, duration s, status }
const FILES = {
  '/a/call.mp3': { delay: 5, duration: 0.15 },
  '/a/song.mp3': { delay: 5, duration: 0.6 },
  '/b/call.mp3': { delay: 5, duration: 0.15 },
  '/b/song.mp3': { delay: 5, duration: 0.6 },
  '/slow/call.mp3': { delay: 120, duration: 0.15 },
  '/gone.mp3': { delay: 5, status: 404 },
  '/html.mp3': { delay: 5, bad: true },
};
globalThis.window = { AudioContext: FakeCtx, location: { origin: 'http://localhost' } };
globalThis.fetch = (url) => new Promise((resolve) => {
  const f = FILES[url.split('?')[0]] || { delay: 5, status: 404 };
  setTimeout(() => resolve({
    ok: !f.status,
    status: f.status || 200,
    headers: { get: () => null },
    arrayBuffer: async () => ({ name: url, duration: f.duration || 0, bad: f.bad }),
  }), f.delay);
});

const ac = await import('../src/utils/audioController.js');
const wait = (ms) => new Promise(r => setTimeout(r, ms));
const reset = () => { ac.cleanup(); live.clear(); maxLive = 0; started.length = 0; };

test('a second tap while the first is still loading plays only the second', async () => {
  reset();
  const first = ac.play({ key: 'slow', clipUrl: '/slow/call.mp3' });
  await ac.play({ key: 'b', clipUrl: '/b/call.mp3' });
  assert.equal(ac.getState().key, 'b');
  assert.equal(ac.getState().status, 'playing');
  await first; // the slow fetch lands after B started
  await wait(20);
  assert.equal(maxLive, 1, 'two clips played over each other');
  assert.deepEqual(started, ['/b/call.mp3']);
  ac.stop();
});

test("switching batter mid-song: the old batter's late `ended` doesn't cancel the new call", async () => {
  reset();
  await ac.play({ key: 'a', songUrl: '/a/song.mp3', clipUrl: '/a/call.mp3', songStart: 0.01 });
  await wait(60);
  await ac.play({ key: 'b', songUrl: '/b/song.mp3', clipUrl: '/b/call.mp3', songStart: 0.05 });
  await wait(120);
  assert.ok(started.includes('/b/call.mp3'), "B's call never started");
  const s = ac.getState();
  assert.equal(s.status, 'playing');
  assert.equal(s.key, 'b');
  assert.ok(live.size <= 2, 'song + call at most');
  ac.stop();
});

test('a missing song still plays the call, and says so', async () => {
  reset();
  await ac.play({ key: 'a', songUrl: '/gone.mp3', clipUrl: '/a/call.mp3' });
  const s = ac.getState();
  assert.equal(s.status, 'playing');
  assert.match(s.warning, /Song didn't load \(file missing\)/);
  assert.deepEqual(started, ['/a/call.mp3']);
  await wait(250);
  assert.equal(ac.getState().status, 'idle', 'clip-only playback should end when the clip ends');
});

test('nothing playable is an error with the reason, not silence', async () => {
  reset();
  await ac.play({ key: 'a', songUrl: '/gone.mp3', clipUrl: '/html.mp3' });
  const s = ac.getState();
  assert.equal(s.status, 'error');
  assert.match(s.error, /call: not a playable audio file/);
  assert.match(s.error, /song: file missing/);
  ac.dismissError();
  assert.equal(ac.getState().status, 'idle');
});

test('stop while loading starts nothing', async () => {
  reset();
  const p = ac.play({ key: 'slow', clipUrl: '/slow/call.mp3' });
  assert.equal(ac.getState().status, 'loading');
  ac.stop();
  await p;
  await wait(20);
  assert.deepEqual(started, []);
  assert.equal(ac.getState().status, 'idle');
});

test('subscribers hear every state change', async () => {
  reset();
  const seen = [];
  const off = ac.subscribe(() => seen.push(ac.getState().status));
  await ac.play({ key: 'a', clipUrl: '/a/call.mp3' });
  await wait(250);
  off();
  assert.deepEqual([...new Set(seen)], ['loading', 'playing', 'idle']);
  assert.equal(seen.at(-1), 'idle');
});
