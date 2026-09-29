// Pure helpers behind the Announcer tab: batting order, which call and song
// play at the next at-bat, and what each row's status means. No React and no
// audio here, so `npm test` can cover them with node --test.

// Mirrors MAX_INTROS / MAX_SONGS in tools/announcer_engine.py.
export const MAX_ITEMS = 4;

const ONES = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten',
  'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen'];
const TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety'];

export function numToWord(raw) {
  const s = String(raw ?? '').trim();
  if (!/^\d+$/.test(s)) return s;
  if (s === '00') return 'double-zero';
  const n = parseInt(s, 10);
  if (n >= 100) return s;
  if (n < 20) return ONES[n];
  const t = Math.floor(n / 10), o = n % 10;
  return o ? `${TENS[t]}-${ONES[o]}` : TENS[t];
}

// Mirrors tools/announcer_engine._spoken_name: a one-letter surname ("Aya W")
// is dropped so the voice doesn't read out a letter.
export function spokenName(first, last) {
  const f = (first || '').trim();
  const l = (last || '').trim();
  if (!f) return l;
  return l.replace(/\.$/, '').trim().length <= 1 ? f : `${f} ${l}`;
}

// What the coach sees while fixing a name. Plain words: the stretched
// spelling the voice is fed is a delivery detail, not something to read.
export function previewLine(player, phonetic) {
  const name = (phonetic || '').trim() || spokenName(player.first, player.last);
  const num = numToWord(player.number);
  return `Now batting… ${num ? `number ${num}… ` : ''}${name}!`;
}

// Rosters cached before multiple calls existed carry one clip and one song.
export const introsOf = (p) => p.intros
  || (p.announcer_audio_url ? [{ id: 'legacy', clip_url: p.announcer_audio_url, voice: p.voice_rendered || '' }] : []);
export const songsOf = (p) => p.songs
  || (p.walkup_song_url ? [{ id: 'legacy', url: p.walkup_song_url, start: p.intro_timestamp ?? 5 }] : []);

export function randomOther(items, lastId, rand = Math.random) {
  const pool = items.length > 1 ? items.filter(x => x.id !== lastId) : items;
  return pool[Math.floor(rand() * pool.length)]?.id || '';
}

export const rollPair = (p, last = {}, rand = Math.random) => ({
  intro: randomOther(introsOf(p), last.intro, rand),
  song: randomOther(songsOf(p), last.song, rand),
});

// A pin wins, then the queued pick, then the first item. A pin pointing at an
// item that no longer exists is ignored rather than blocking playback.
export function pairFor(p, q = {}) {
  const pick = (items, pinnedId, id) => items.find(x => x.id === pinnedId) || items.find(x => x.id === id) || items[0] || null;
  return { intro: pick(introsOf(p), p.intro_pick, q.intro), song: pick(songsOf(p), p.song_pick, q.song) };
}

export const isPinned = (items, pinnedId) => Boolean(pinnedId) && items.some(x => x.id === pinnedId);

// "Always Brian" / "Shuffles 3 calls" / "1 call" / "" — how this player's
// calls or songs are chosen, in words, so pinning is never hidden state.
export function pickMode(items, pinnedId, noun, nameOf) {
  if (!items.length) return '';
  const pinned = items.find(x => x.id === pinnedId);
  if (pinned) return `Always ${nameOf(pinned)}`;
  if (items.length === 1) return `1 ${noun}`;
  return `Shuffles ${items.length} ${noun}s`;
}

export function songLabel(url) {
  try {
    return decodeURIComponent(new URL(url, 'https://x.invalid').pathname.split('/').pop()).replace(/\.[a-z0-9]+$/i, '') || 'Walk-up song';
  } catch {
    return 'Walk-up song';
  }
}

// An uploaded song carries the name it was uploaded under; a link song is
// named after its file.
export const songTitle = (s) => (s?.label || '').trim() || songLabel(s?.url || '');

// Voice id the server stores on an uploaded (pre-recorded) call.
export const UPLOAD_VOICE = 'upload';

// A song's in-point (its `start`, seconds into the track) as the row shows
// it: 12 -> "Song starts at 0:12", 72.5 -> "Song starts at 1:12.5".
export function songStartLabel(start) {
  const sec = Math.max(0, Number(start) || 0);
  if (!sec) return 'Song starts at the top';
  const m = Math.floor(sec / 60);
  const rest = Math.round((sec - m * 60) * 10) / 10;
  const [whole, frac] = String(rest).split('.');
  return `Song starts at ${m}:${whole.padStart(2, '0')}${frac ? `.${frac}` : ''}`;
}

// One status per row. `canPlay` is what the big button does, independent of
// whether a newer render is in flight or failed: an old call still plays.
export function rowState(p) {
  const calls = introsOf(p).length;
  const songs = songsOf(p).length;
  const canPlay = calls > 0 || songs > 0;
  if (p.status === 'rendering') return { kind: 'rendering', label: calls ? 'Making a new call…' : 'Making call…', canPlay };
  if (p.status === 'error') return { kind: 'failed', label: calls ? 'New call failed' : 'Call failed', canPlay, error: p.error_message || '' };
  if (!calls && songs) return { kind: 'song-only', label: 'Song only · no call yet', canPlay };
  if (!calls) return { kind: 'empty', label: 'No call yet', canPlay };
  if (p.status === 'pending') return { kind: 'stale', label: 'Name or voice changed · remake', canPlay };
  return { kind: 'ready', label: 'Ready', canPlay };
}

// Players the "Make calls" button would render: the server renders active
// players whose status is pending or error (announcer_engine.claim_render_batch).
export const needsRender = (p) => p.status === 'pending' || p.status === 'error';

const nameKey = (first, last) => `${first || ''} ${last || ''}`.trim().replace(/\s+/g, ' ').toLowerCase();

// Batting order: the coach's own order (ids, saved from the Reorder screen),
// else the GameChanger game lineup, else the optimiser lineup, else roster
// order. Ids no longer on the roster are dropped; anyone on the roster the
// chosen order doesn't name goes after it.
export function orderBattingLineup(active, gcLineup, lineups, manualOrder = null) {
  if (Array.isArray(manualOrder) && manualOrder.length) {
    const byId = new Map(active.map(p => [p.id, p]));
    const seen = new Set();
    const ordered = [];
    for (const id of manualOrder) {
      const p = byId.get(id);
      if (p && !seen.has(id)) { seen.add(id); ordered.push(p); }
    }
    if (ordered.length) {
      return { battingOrder: [...ordered, ...active.filter(p => !seen.has(p.id))], lineupSource: 'Your order', manual: true };
    }
  }
  const byRef = (ref) => active.find(r => ref.id && r.id === ref.id)
    || active.find(r => ref.number && r.number && String(r.number).trim() === String(ref.number).trim())
    || active.find(r => nameKey(r.first, r.last) && nameKey(r.first, r.last) === nameKey(ref.first, ref.last))
    || null;
  const withRest = (refs) => {
    const seen = new Set();
    const ordered = [];
    for (const ref of refs) {
      const p = byRef(ref);
      if (p && !seen.has(p.id)) { seen.add(p.id); ordered.push(p); }
    }
    return ordered.length ? [...ordered, ...active.filter(p => !seen.has(p.id))] : null;
  };
  if (gcLineup?.players?.length) {
    const order = withRest(gcLineup.players);
    if (order) return { battingOrder: order, lineupSource: gcLineup.source_label || 'GameChanger lineup' };
  }
  if (lineups) {
    // lineups.json: { balanced: { lineup: [...] }, ... } — the array is under `lineup`.
    const strategy = lineups[lineups.recommended_strategy || 'balanced'] || lineups.balanced;
    const lineup = Array.isArray(strategy) ? strategy : strategy?.lineup;
    if (Array.isArray(lineup) && lineup.length) {
      const order = withRest([...lineup].sort((a, b) => (a.slot || 0) - (b.slot || 0)));
      if (order) return { battingOrder: order, lineupSource: 'Optimiser lineup' };
    }
  }
  return { battingOrder: active, lineupSource: 'Roster order' };
}

// `list` with the item at `from` moved to `to` (both clamped). Never mutates.
export function moveItem(list, from, to) {
  const n = list.length;
  if (!n) return [];
  const f = Math.max(0, Math.min(n - 1, from));
  const t = Math.max(0, Math.min(n - 1, to));
  const out = [...list];
  const [item] = out.splice(f, 1);
  out.splice(t, 0, item);
  return out;
}

// Where the row being dragged would land: its start index plus however many
// row pitches the pointer has travelled, clamped to the list.
export function dropIndex(from, dy, pitch, count) {
  if (!pitch || count < 1) return from;
  return Math.max(0, Math.min(count - 1, from + Math.round(dy / pitch)));
}

// What Undo puts back after a reorder. If the coach already had her own
// order, that order; if this was the first drag, a reset, so the list goes
// back to the GameChanger / optimiser order instead of a copy of it that
// reads "Your order".
export function undoTarget(prevManualOrder) {
  return Array.isArray(prevManualOrder) && prevManualOrder.length
    ? { kind: 'restore', order: [...prevManualOrder] }
    : { kind: 'reset' };
}

// The gap slider's caption: -0.5 -> "Song starts 0.5s before the call ends".
export function songGapLabel(gap) {
  const g = Number(gap) || 0;
  const n = Number(Math.abs(g).toFixed(2));
  if (g < 0) return `Song starts ${n}s before the call ends`;
  if (g > 0) return `Song starts ${n}s after the call ends`;
  return 'Song starts right as the call ends';
}

// Uploads the server takes, by extension or MIME type.
export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
export function uploadProblem(file) {
  if (!file) return 'Pick a file.';
  const okType = /\.(mp3|wav|m4a)$/i.test(file.name || '') || /^audio\/(mpeg|mp3|wav|x-wav|wave|mp4|x-m4a|aac)$/i.test(file.type || '');
  if (!okType) return 'Use an MP3, WAV or M4A file.';
  if (file.size > MAX_UPLOAD_BYTES) return `That file is ${Math.round(file.size / 1048576)} MB; the limit is 25 MB.`;
  return '';
}

// Server error codes → words a coach can act on.
const ERROR_WORDS = {
  forbidden_origin: 'This address is not allowed to make changes. Open the app from its normal address.',
  origin_required: 'This browser did not say where the request came from, so the change was refused.',
  write_token_required: 'Changes need the Dugout write token. Nothing was saved.',
  write_token_invalid: 'That write token was not accepted. Nothing was saved.',
  player_not_found: 'That player is no longer on the announcer roster. Refresh the list.',
  unknown_voice_profile: 'That voice no longer exists. Pick another.',
  songs_invalid: `A player can have up to ${MAX_ITEMS} songs.`,
  'song url must be HTTP(S)': 'Song links must start with http:// or https://.',
  player_already_exists: 'That player is already on the roster.',
  player_on_team: 'She is on the GameChanger roster, so she can’t be removed here.',
  first_name_required: 'First name is required.',
  text_required: 'Type what the announcer should say.',
  text_too_long: 'That is too long for one announcement.',
  rate_limited: 'Too many changes at once. Wait a moment and try again.',
  unknown_profile: 'That voice no longer exists. Pick another.',
  voice_unavailable: 'That voice is not set up on the server yet (its service key is missing).',
  builtin_voice: 'Built-in voices can’t be removed.',
  voice_already_added: 'That voice is already in the list.',
  voice_id_taken: 'A voice with a very similar id is already in the list.',
  invalid_fish_reference_id: 'That is not a fish.audio voice id.',
  voice_not_found: 'fish.audio has no public voice with that id.',
  voice_lookup_failed: 'Couldn’t reach fish.audio to look that voice up. Try again.',
  voice_search_failed: 'Couldn’t reach fish.audio to search. Try again.',
  invalid_query: 'Search for 2 to 60 letters.',
  too_many_custom_voices: 'That’s the most voices you can add. Remove one first.',
  unsupported_audio: 'That isn’t an MP3, WAV or M4A file.',
  audio_unreadable: 'That file wouldn’t play. Export it again as an MP3 and retry.',
  file_too_large: 'That file is too big. The limit is 25 MB.',
  payload_too_large: 'That file is too big. The limit is 25 MB.',
  file_required: 'Pick a file to upload.',
  songs_full: `A player can have up to ${MAX_ITEMS} songs. Remove one first.`,
  sounds_full: 'The soundboard is full. Remove a sound first.',
  sound_not_found: 'That sound is already gone.',
  builtin_sound: 'Built-in sounds can’t be removed.',
  order_invalid: 'That batting order didn’t match the roster. Refresh and try again.',
};

export function describeApiError(status, code) {
  if (code && ERROR_WORDS[code]) return ERROR_WORDS[code];
  if (status === 413) return ERROR_WORDS.file_too_large; // nginx answers 413 with HTML, no code
  if (status === 429) return ERROR_WORDS.rate_limited;
  if (status === 0) return 'No connection to the Dugout server.';
  if (status >= 500) return `The server had a problem (${status}${code ? `: ${code}` : ''}). Try again.`;
  return code ? `Refused: ${code}` : `Request failed (${status}).`;
}
