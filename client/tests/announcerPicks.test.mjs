import test from 'node:test';
import assert from 'node:assert/strict';
import {
  orderBattingLineup, pairFor, randomOther, rowState, pickMode, previewLine, describeApiError, needsRender, songStartLabel,
  moveItem, dropIndex, songTitle, uploadProblem, MAX_UPLOAD_BYTES, undoTarget, songGapLabel,
} from '../src/utils/announcerPicks.js';

const P = (id, first, last, number, extra = {}) => ({ id, first, last, number, status: 'ready', ...extra });

test('a player with no surname and no number keeps her GameChanger slot', () => {
  // GC sends { first: "Alaina", last: "" }. The old matcher compared
  // "alaina " (roster side untrimmed) to "alaina" and dropped her to the end.
  const active = [P('00-elsie', 'Elsie', 'Hennessy', '00'), P('alaina-', 'Alaina', '', ''), P('11-abby', 'Abby', 'A', '11')];
  const gc = { players: [
    { first: 'Elsie', last: 'Hennessy', number: '00', id: '' },
    { first: 'Alaina', last: '', number: '', id: '' },
    { first: 'Abby', last: 'A', number: '11', id: '' },
  ] };
  const { battingOrder } = orderBattingLineup(active, gc, null);
  assert.deepEqual(battingOrder.map(p => p.id), ['00-elsie', 'alaina-', '11-abby']);
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
  assert.equal(previewLine({ first: 'Elsie', last: 'Hennessy', number: '00' }, ''), 'Now batting… number double-zero… Elsie Hennessy!');
  assert.equal(previewLine({ first: 'Alaina', last: '', number: '' }, ''), 'Now batting… Alaina!');
  assert.equal(previewLine({ first: 'Aya', last: 'W', number: '28' }, 'AH-vuh'), 'Now batting… number twenty-eight… AH-vuh!');
});

test('server error codes become instructions', () => {
  assert.match(describeApiError(403, 'forbidden_origin'), /not allowed/);
  assert.match(describeApiError(401, 'write_token_required'), /write token/);
  assert.match(describeApiError(429, undefined), /Too many/);
  assert.match(describeApiError(500, 'delete_failed'), /server had a problem \(500: delete_failed\)/);
});

test("a song's in-point reads as a clock time, not a call mark", () => {
  assert.equal(songStartLabel(12), 'Song starts at 0:12');
  assert.equal(songStartLabel('5'), 'Song starts at 0:05');
  assert.equal(songStartLabel(72.5), 'Song starts at 1:12.5');
  assert.equal(songStartLabel(0), 'Song starts at the top');
  assert.equal(songStartLabel(undefined), 'Song starts at the top');
  assert.equal(songStartLabel(-4), 'Song starts at the top');
});

// ── Coach's own batting order ──────────────────────────────────────────────
const TEAM = [P('a', 'Ann', 'Lee', '1'), P('b', 'Bea', 'Moe', '2'), P('c', 'Cat', 'Ng', '3')];
const GC = { players: [{ number: '3' }, { number: '1' }, { number: '2' }], source_label: 'GC 2026-09-20 vs Rays' };
const OPT = { balanced: { lineup: [{ slot: 1, number: '2' }, { slot: 2, number: '3' }, { slot: 3, number: '1' }] } };

test('precedence: manual order, then GameChanger, then optimiser, then roster', () => {
  const manual = orderBattingLineup(TEAM, GC, OPT, ['b', 'a', 'c']);
  assert.deepEqual(manual.battingOrder.map(p => p.id), ['b', 'a', 'c']);
  assert.equal(manual.lineupSource, 'Your order');
  assert.equal(manual.manual, true);
  const gc = orderBattingLineup(TEAM, GC, OPT, []);
  assert.deepEqual(gc.battingOrder.map(p => p.id), ['c', 'a', 'b']);
  assert.equal(gc.lineupSource, 'GC 2026-09-20 vs Rays');
  assert.ok(!gc.manual);
  assert.deepEqual(orderBattingLineup(TEAM, null, OPT, null).battingOrder.map(p => p.id), ['b', 'c', 'a']);
  assert.deepEqual(orderBattingLineup(TEAM, null, null).battingOrder.map(p => p.id), ['a', 'b', 'c']);
});

test('a manual order drops players who left and appends players it never named', () => {
  const r = orderBattingLineup(TEAM, GC, null, ['c', 'gone', 'a', 'c']);
  assert.deepEqual(r.battingOrder.map(p => p.id), ['c', 'a', 'b']);
});

test('a manual order naming nobody on the roster falls through to GameChanger', () => {
  const r = orderBattingLineup(TEAM, GC, null, ['gone', 'left']);
  assert.equal(r.lineupSource, 'GC 2026-09-20 vs Rays');
  assert.deepEqual(r.battingOrder.map(p => p.id), ['c', 'a', 'b']);
});

test('moveItem moves one row and clamps, without mutating', () => {
  const ids = ['a', 'b', 'c', 'd'];
  assert.deepEqual(moveItem(ids, 0, 2), ['b', 'c', 'a', 'd']);
  assert.deepEqual(moveItem(ids, 3, 0), ['d', 'a', 'b', 'c']);
  assert.deepEqual(moveItem(ids, 1, 99), ['a', 'c', 'd', 'b']);
  assert.deepEqual(moveItem(ids, 2, 2), ids);
  assert.deepEqual(ids, ['a', 'b', 'c', 'd']);
  assert.deepEqual(moveItem([], 0, 1), []);
});

test('dropIndex follows the pointer by whole rows and stays in the list', () => {
  assert.equal(dropIndex(2, 0, 60, 5), 2);
  assert.equal(dropIndex(2, 29, 60, 5), 2);
  assert.equal(dropIndex(2, 31, 60, 5), 3);
  assert.equal(dropIndex(2, -125, 60, 5), 0);
  assert.equal(dropIndex(2, 1000, 60, 5), 4);
  assert.equal(dropIndex(1, 50, 0, 5), 1);
});

test('uploaded songs show their own name; link songs their file name', () => {
  assert.equal(songTitle({ url: '/audio/music/a/x-1a2b3c4d.mp3', label: 'Sweet Tune' }), 'Sweet Tune');
  assert.equal(songTitle({ url: 'https://x.test/Walk%20Up.mp3' }), 'Walk Up');
});

test('uploads are checked for type and size before they are sent', () => {
  assert.equal(uploadProblem({ name: 'song.MP3', type: '', size: 10 }), '');
  assert.equal(uploadProblem({ name: 'memo', type: 'audio/x-m4a', size: 10 }), '');
  assert.match(uploadProblem({ name: 'pic.jpg', type: 'image/jpeg', size: 10 }), /MP3, WAV or M4A/);
  assert.match(uploadProblem({ name: 'big.wav', type: 'audio/wav', size: MAX_UPLOAD_BYTES + 1 }), /25 MB/);
  assert.match(uploadProblem(null), /Pick a file/);
});

test('upload errors read as instructions, including nginx 413 with no code', () => {
  assert.match(describeApiError(413, undefined), /25 MB/);
  assert.match(describeApiError(415, 'unsupported_audio'), /MP3, WAV or M4A/);
  assert.match(describeApiError(422, 'audio_unreadable'), /wouldn’t play/);
  assert.match(describeApiError(400, 'builtin_sound'), /Built-in/);
});

test('undo after a later drag restores the previous coach order', () => {
  const u = undoTarget(['b', 'a', 'c']);
  assert.deepEqual(u, { kind: 'restore', order: ['b', 'a', 'c'] });
});

test('undo after the first drag resets to the source order rather than copying it as manual', () => {
  assert.deepEqual(undoTarget(null), { kind: 'reset' });
  assert.deepEqual(undoTarget([]), { kind: 'reset' });
});

test('the gap caption reads as before / as / after the call ends', () => {
  assert.equal(songGapLabel(-0.5), 'Song starts 0.5s before the call ends');
  assert.equal(songGapLabel(0), 'Song starts right as the call ends');
  assert.equal(songGapLabel(1.25), 'Song starts 1.25s after the call ends');
  assert.equal(songGapLabel('x'), 'Song starts right as the call ends');
});
