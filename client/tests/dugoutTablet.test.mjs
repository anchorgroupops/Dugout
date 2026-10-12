import test from 'node:test';
import assert from 'node:assert/strict';
import { zoneSplit, zonePercents, countDots, playTypeGroup, historyLine, bannerFor, isFinalView } from '../src/components/live-tablet/tabletHelpers.js';

const home = [160, 292];

test('zoneSplit buckets by angle off centre', () => {
  const z = zoneSplit([
    { x: 100, y: 200 }, // left of centre, well past 15 deg
    { x: 160, y: 150 }, // dead centre
    { x: 230, y: 220 }, // right
    { x: 'a', y: 1 },   // ignored
  ], home);
  assert.deepEqual(z, { left: 1, centre: 1, right: 1, total: 3 });
});

test('zonePercents is null with no points and sums sensibly', () => {
  assert.equal(zonePercents([], home), null);
  const p = zonePercents([{ x: 100, y: 200 }, { x: 100, y: 200 }, { x: 160, y: 150 }, { x: 230, y: 220 }], home);
  assert.deepEqual(p, { left: 50, centre: 25, right: 25, total: 4 });
});

test('countDots clamps', () => {
  assert.deepEqual(countDots(2, 3), [true, true, false]);
  assert.deepEqual(countDots(9, 2), [true, true]);
  assert.deepEqual(countDots(undefined, 2), [false, false]);
});

test('playTypeGroup', () => {
  assert.equal(playTypeGroup('hard_ground_ball'), 'ground');
  assert.equal(playTypeGroup('line_drive'), 'line');
  assert.equal(playTypeGroup('fly_ball'), 'fly');
  assert.equal(playTypeGroup('popup'), 'fly');
  assert.equal(playTypeGroup(null), 'other');
});

test('historyLine', () => {
  assert.equal(historyLine({ games: 2, pa: 5, hits: 2, in_play: 3 }), '5 PA · 2 H · 3 in play · 2 games');
  assert.equal(historyLine({ games: 1, pa: 1, hits: 0, in_play: 0 }), '1 PA · 0 H · 0 in play · 1 game');
});

test('bannerFor', () => {
  assert.equal(bannerFor({ status: 'live' }, false), null);
  assert.equal(bannerFor({ status: 'starting' }, false).tone, 'starting');
  assert.equal(bannerFor({ status: 'stale', age_s: 75 }, false).text, 'Last update 75s ago');
  assert.equal(bannerFor({ status: 'error', error: 'gc_http_403' }, false).tone, 'error');
  assert.equal(bannerFor({ status: 'live' }, true, 20000, 5000).text, 'Connection lost - last update 15s ago');
  assert.equal(bannerFor({ status: 'idle' }, false), null);
});

test('isFinalView', () => {
  assert.equal(isFinalView({ status: 'idle', game: {} }), true);
  assert.equal(isFinalView({ status: 'idle', game: null }), false);
  assert.equal(isFinalView({ status: 'live', game: {} }), false);
});
