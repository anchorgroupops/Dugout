import test from 'node:test';
import assert from 'node:assert/strict';
import { planWalkup, clampGap, mainAction, DEFAULT_GAP, GAP_MIN, GAP_MAX } from '../src/utils/audioController.js';

// The engine's pure parts: the timeline plan and the one-button state
// machine. Nothing here touches an AudioContext.

test('default gap brings the song in half a second before the call ends', () => {
  assert.equal(DEFAULT_GAP, -0.5);
  assert.equal(planWalkup({ clipDuration: 4, songDuration: 30 }).songAt, 3.5);
});

test('a positive gap leaves silence after the call, a negative one overlaps it', () => {
  assert.equal(planWalkup({ clipDuration: 4, songDuration: 30, gap: 1 }).songAt, 5);
  assert.equal(planWalkup({ clipDuration: 4, songDuration: 30, gap: -1 }).songAt, 3);
});

test('an overlap longer than the call still starts the song at 0, never before', () => {
  assert.equal(planWalkup({ clipDuration: 1, songDuration: 30, gap: -3 }).songAt, 0);
});

test('with no call the song starts at once whatever the gap', () => {
  assert.equal(planWalkup({ songDuration: 30, gap: 2 }).songAt, 0);
  assert.equal(planWalkup({ songDuration: 30, gap: -2 }).songAt, 0);
});

test('total covers whichever part ends last', () => {
  const p = planWalkup({ clipDuration: 4, songDuration: 10, inPoint: 8, gap: 1 });
  assert.equal(p.songAt, 5);
  assert.equal(p.total, 7); // song plays 2s from 5s; the call ended at 4s
  assert.equal(planWalkup({ clipDuration: 4, songDuration: 0.5, gap: -3 }).total, 4);
});

test('gap is clamped to the engine range and falls back to the default', () => {
  assert.equal(clampGap(9), GAP_MAX);
  assert.equal(clampGap(-9), GAP_MIN);
  assert.equal(clampGap(1.25), 1.25);
  assert.equal(clampGap('abc'), DEFAULT_GAP);
  assert.equal(clampGap(null), DEFAULT_GAP);
  assert.equal(clampGap(''), DEFAULT_GAP);
  assert.equal(clampGap(0), 0);
});

test('the big button: play when idle, fade while playing, stop dead during a fade, retry on error', () => {
  assert.equal(mainAction('idle'), 'play');
  assert.equal(mainAction('loading'), 'fade');
  assert.equal(mainAction('playing'), 'fade');
  assert.equal(mainAction('fading'), 'stop');
  assert.equal(mainAction('error'), 'retry');
});
