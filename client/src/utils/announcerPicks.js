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

// Batting order: the GameChanger game lineup, else the optimiser lineup, else
// roster order. Anyone on the roster the lineup doesn't name goes after it.
export function orderBattingLineup(active, gcLineup, lineups) {
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
};

export function describeApiError(status, code) {
  if (code && ERROR_WORDS[code]) return ERROR_WORDS[code];
  if (status === 429) return ERROR_WORDS.rate_limited;
  if (status === 0) return 'No connection to the Dugout server.';
  if (status >= 500) return `The server had a problem (${status}${code ? `: ${code}` : ''}). Try again.`;
  return code ? `Refused: ${code}` : `Request failed (${status}).`;
}
