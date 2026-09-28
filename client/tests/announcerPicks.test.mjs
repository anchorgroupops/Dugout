import test from 'node:test';
import assert from 'node:assert/strict';
import {
  orderBattingLineup, pairFor, randomOther, rowState, pickMode, previewLine, describeApiError, needsRender,
} from '../src/utils/announcerPicks.js';

const P = (id, first, last, number, extra = {}) => ({ id, first, last, number, status: 'ready', ...extra });

test('a player with no surname and no number keeps her GameChanger slot', () => {
  // GC sends { first: "Amelia", last: "" }. The old matcher compared
  // "amelia " (roster side untrimmed) to "amelia" and dropped her to the end.
  const active = [P('00-ember', 'Ember', 'Hourahan', '00'), P('amelia-', 'Amelia', '', ''), P('11-addy', 'Addy', 'A', '11')];
  const gc = { players: [
    { first: 'Ember', last: 'Hourahan', number: '00', id: '' },
    { first: 'Amelia', last: '', number: '', id: '' },
    { first: 'Addy', last: 'A', number: '11', id: '' },
  ] };
  const { battingOrder } = orderBattingLineup(active, gc, null);
  assert.deepEqual(battingOrder.map(p => p.id), ['00-ember', 'amelia-', '11-addy']);
});

test('blank numbers never match each other', () => {
  const active = [P('a', 'Ann', 'Lee', ''), P('b', 'Bea', 'Moe', '')];
  const { battingOrder } = orderBattingLineup(active, { players: [{ first: 'Bea', last: 'Moe', number: '' }] }, null);
  assert.deepEqual(battingOrder.map(p => p.id), ['b', 'a']);
});

test('a lineup that names nobody on the roster falls back, and duplicates are dropped', () => {
  const active = [P('a', 'Ann', 'Lee', '1'), P('b', 'Bea', 'Moe', '2')];
  assert.equal(orderBattingLineup(active, { players: [{ first: 'Zed', last: 'Q', number: '99' }] }, null).lineupSource, 'Roster order');
  const dup = orderBattingLineup(active, { players: [{ number: '2' }, { first: 'Bea', last: 'Moe' }] }, null);
  assert.deepEqual(dup.battingOrder.map(p => p.id), ['b', 'a']);
});

test('optimiser lineup is used when there is no game lineup', () => {
  const active = [P('a', 'Ann', 'Lee', '1'), P('b', 'Bea', 'Moe', '2')];
  const lineups = { recommended_strategy: 'balanced', balanced: { lineup: [{ slot: 2, number: '1' }, { slot: 1, number: '2' }] } };
  const r = orderBattingLineup(active, null, lineups);
  assert.equal(r.lineupSource, 'Optimiser lineup');
  assert.deepEqual(r.battingOrder.map(p => p.id), ['b', 'a']);
});

test('a pin beats the queued pick; a stale pin is ignored', () => {
  const p = { intros: [{ id: 'i1' }, { id: 'i2' }], songs: [{ id: 's1', url: 'x' }], intro_pick: 'i2' };
  assert.equal(pairFor(p, { intro: 'i1' }).intro.id, 'i2');
  assert.equal(pairFor({ ...p, intro_pick: 'gone' }, { intro: 'i1' }).intro.id, 'i1');
});

test('shuffle never repeats the call just played when there is a choice', () => {
  const items = [{ id: 'a' }, { id: 'b' }];
  for (let i = 0; i < 20; i++) assert.equal(randomOther(items, 'a', Math.random), 'b');
  assert.equal(randomOther([{ id: 'a' }], 'a'), 'a');
});

test('row states say what the button does', () => {
  assert.equal(rowState(P('a', 'A', 'B', '1', { intros: [{ id: 'x' }] })).kind, 'ready');
  const failedWithOldCall = rowState(P('a', 'A', 'B', '1', { status: 'error', error_message: 'OOM', intros: [{ id: 'x' }] }));
  assert.deepEqual([failedWithOldCall.kind, failedWithOldCall.canPlay, failedWithOldCall.error], ['failed', true, 'OOM']);
  assert.equal(rowState(P('a', 'A', 'B', '1', { status: 'pending', intros: [] })).canPlay, false);
  assert.equal(rowState(P('a', 'A', 'B', '1', { status: 'pending', intros: [], songs: [{ id: 's', url: 'u' }] })).kind, 'song-only');
  assert.equal(rowState(P('a', 'A', 'B', '1', { status: 'rendering', intros: [] })).label, 'Making call…');
  assert.ok(needsRender({ status: 'error' }) && needsRender({ status: 'pending' }) && !needsRender({ status: 'rendering' }));
});

test('pick mode is spelled out', () => {
  const name = (x) => x.name;
  assert.equal(pickMode([{ id: 'a', name: 'Brian' }, { id: 'b', name: 'Halo' }], 'a', 'call', name), 'Always Brian');
  assert.equal(pickMode([{ id: 'a' }, { id: 'b' }], '', 'call', name), 'Shuffles 2 calls');
  assert.equal(pickMode([{ id: 'a' }], '', 'song', name), '1 song');
  assert.equal(pickMode([], '', 'song', name), '');
});

test('preview reads as words and skips a missing number', () => {
  assert.equal(previewLine({ first: 'Ember', last: 'Hourahan', number: '00' }, ''), 'Now batting… number double-zero… Ember Hourahan!');
  assert.equal(previewLine({ first: 'Amelia', last: '', number: '' }, ''), 'Now batting… Amelia!');
  assert.equal(previewLine({ first: 'Ava', last: 'W', number: '28' }, 'AH-vuh'), 'Now batting… number twenty-eight… AH-vuh!');
});

test('server error codes become instructions', () => {
  assert.match(describeApiError(403, 'forbidden_origin'), /not allowed/);
  assert.match(describeApiError(401, 'write_token_required'), /write token/);
  assert.match(describeApiError(429, undefined), /Too many/);
  assert.match(describeApiError(500, 'delete_failed'), /server had a problem \(500: delete_failed\)/);
});
