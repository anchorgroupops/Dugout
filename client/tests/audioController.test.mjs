// node --test: the audio controller against a fake Web Audio implementation.
//
// The fake mirrors the browser behaviour that caused the overlap and
// stomp bugs: fetches take time, and AudioBufferSourceNode fires `ended`
// asynchronously after stop(), not synchronously. start(when, offset) is
// honoured: a source scheduled for later only becomes audible at `when`, and
// stop() before then cancels it (legal on a scheduled, unstarted node).
import test from 'node:test';
import assert from 'node:assert/strict';

const live = new Set();
let maxLive = 0;
const started = [];   // names, in the order they became audible
const scheduled = []; // every start(when, offset) call
const t0 = Date.now();
const clock = () => (Date.now() - t0) / 1000;

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
  start(when = 0, offset = 0) {
    scheduled.push({ name: this.buffer.name, when, offset });
    const begin = () => {
      live.add(this);
      maxLive = Math.max(maxLive, live.size);
      started.push(this.buffer.name);
      this._t = setTimeout(() => { live.delete(this); this.onended?.(); }, (this.buffer.duration - offset) * 1000);
    };
    const delay = when - clock();
    if (delay <= 0) begin();
    else this._wait = setTimeout(begin, delay * 1000);
  }
  stop() {
    clearTimeout(this._wait);
    clearTimeout(this._t);
    live.delete(this);
    setTimeout(() => this.onended?.(), 0); // browsers fire `ended` later
  }
}
const buf = (name, duration) => ({ name, duration, sampleRate: 3000, getChannelData: () => new Float32Array(0) });
class FakeCtx {
  state = 'running';
  destination = {};
  get currentTime() { return clock(); }
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
  '/c/call.mp3': { delay: 5, duration: 0.8 },  // longer than the overlap
  '/c/song.mp3': { delay: 5, duration: 1.0 },
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
const reset = () => { ac.cleanup(); live.clear(); maxLive = 0; started.length = 0; scheduled.length = 0; };
const sched = (name) => scheduled.find(x => x.name === name);

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

// ── walk-up order: call first, song in under the call's last 0.5 s ──

test('planWalkup: song enters 0.5 s before the call ends, at its in-point', () => {
  assert.deepEqual(ac.planWalkup({ clipDuration: 3, songDuration: 60, inPoint: 12 }),
    { songAt: 2.5, songOffset: 12, callEnd: 3, total: 50.5 });
});

test('planWalkup: a call shorter than the overlap starts the song at once', () => {
  const p = ac.planWalkup({ clipDuration: 0.3, songDuration: 10, inPoint: 2 });
  assert.equal(p.songAt, 0);
  assert.equal(p.total, 8);
});

test('planWalkup: song only plays from the in-point; call only is the call', () => {
  assert.deepEqual(ac.planWalkup({ songDuration: 30, inPoint: 5 }), { songAt: 0, songOffset: 5, callEnd: 0, total: 25 });
  assert.deepEqual(ac.planWalkup({ clipDuration: 4 }), { songAt: 3.5, songOffset: 0, callEnd: 4, total: 4 });
});

test('planWalkup: bad in-points play the song from the top', () => {
  for (const inPoint of [-3, NaN, undefined, 'abc', 60, 99]) {
    assert.equal(ac.planWalkup({ clipDuration: 2, songDuration: 60, inPoint }).songOffset, 0, `inPoint ${inPoint}`);
  }
  assert.equal(ac.planWalkup({ clipDuration: 2, songDuration: 60, inPoint: '7.5' }).songOffset, 7.5);
});

test('planWalkup: a song started near its end never shortens the total below the call', () => {
  const p = ac.planWalkup({ clipDuration: 3, songDuration: 10, inPoint: 9.8 });
  assert.equal(p.songAt, 2.5);
  assert.equal(p.total, 3);
});

test('play(): call starts now, song is scheduled for call end minus 0.5 s at its in-point', async () => {
  reset();
  await ac.play({ key: 'c', songUrl: '/c/song.mp3', clipUrl: '/c/call.mp3', songStart: 0.2 });
  const call = sched('/c/call.mp3');
  const song = sched('/c/song.mp3');
  assert.ok(call && song, 'both parts scheduled');
  assert.ok(Math.abs((song.when - call.when) - 0.3) < 1e-9, `song at +${song.when - call.when}s, want +0.3s`);
  assert.equal(song.offset, 0.2);
  assert.equal(call.offset, 0);
  assert.deepEqual(started, ['/c/call.mp3'], 'only the call is audible at first');
  const s = ac.getState();
  assert.equal(s.status, 'playing');
  assert.ok(Math.abs(s.duration - ac.planWalkup({ clipDuration: 0.8, songDuration: 1.0, inPoint: 0.2 }).total) < 1e-9);
  assert.ok(Math.abs(s.duration - 1.1) < 1e-9, `duration ${s.duration}`);
  await wait(450);
  assert.deepEqual(started, ['/c/call.mp3', '/c/song.mp3'], 'song came in under the call');
  assert.equal(live.size, 2, 'call tail and song overlap');
  await wait(500); // call has ended (0.8 s); song plays on
  assert.equal(ac.getState().status, 'playing');
  assert.equal(live.size, 1);
  ac.stop();
});

test('stop before the song comes in: the scheduled song never plays', async () => {
  reset();
  await ac.play({ key: 'c', songUrl: '/c/song.mp3', clipUrl: '/c/call.mp3', songStart: 0.2 });
  await wait(100);
  ac.stop();
  await wait(450);
  assert.deepEqual(started, ['/c/call.mp3']);
  assert.equal(live.size, 0);
  assert.equal(ac.getState().status, 'idle');
});

test("switching batter before A's song comes in: A's song never plays", async () => {
  reset();
  await ac.play({ key: 'c', songUrl: '/c/song.mp3', clipUrl: '/c/call.mp3', songStart: 0.2 });
  await wait(100);
  await ac.play({ key: 'b', clipUrl: '/b/call.mp3' });
  await wait(450);
  assert.ok(!started.includes('/c/song.mp3'), "A's scheduled song still came in");
  assert.equal(ac.getState().status, 'idle', "B's call ended the sequence");
});

test('song only: starts at once from the in-point', async () => {
  reset();
  await ac.play({ key: 's', songUrl: '/c/song.mp3', songStart: 0.4 });
  const song = sched('/c/song.mp3');
  assert.equal(song.offset, 0.4);
  assert.deepEqual(started, ['/c/song.mp3']);
  assert.ok(Math.abs(ac.getState().duration - 0.6) < 1e-9);
  ac.stop();
});
