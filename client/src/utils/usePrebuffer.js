import { useEffect, useRef } from 'react';
import { preload } from './audioController';

/**
 * Anticipatory walk-up audio pre-buffering, lineup-aware.
 *
 * Given a lineup array and the current batter index, fetches the next N
 * walk-up tracks via /api/music/next/<player_id>?peek=1 and warms the
 * AudioContext buffer cache (and the Service Worker cache via the network
 * request itself). When the coach taps "Play," the audio is already
 * decoded and ready — no spinner while the kid is walking to the box.
 *
 * Field Wi-Fi resilience: because each peek triggers a real fetch, the
 * walkup-music CacheFirst SW rule (vite.config.js) holds the blob in
 * persistent storage. A 30-second outage doesn't break playback.
 *
 * @param {object}  opts
 * @param {Array}   opts.lineup           — array of {id, ...} (player order)
 * @param {number}  [opts.currentIndex=0] — index of player currently at plate
 * @param {number}  [opts.lookahead=3]    — how many upcoming batters to pre-buffer
 * @param {string}  [opts.session]        — game session id (defaults to today)
 * @param {boolean} [opts.enabled=true]   — set false to pause pre-buffering
 *
 * @returns {{ prebufferedUrls: React.MutableRefObject<Map<string, string>> }}
 *   Map<player_id, audio_url>; useful for diagnostics or fallbacks.
 */
export function usePrebuffer({
  lineup,
  currentIndex = 0,
  lookahead = 3,
  session,
  enabled = true,
} = {}) {
  // Map<player_id, audio_url> of warmed entries — exposed via ref so the
  // caller can introspect or pass entries directly to playIntro().
  const prebufferedUrls = useRef(new Map());
  // Track which (player_id, session) pairs we've already peeked to avoid
  // refetching when only `currentIndex` changes within the same lineup.
  const peekedKey = useRef('');

  useEffect(() => {
    if (!enabled) return;
    if (!Array.isArray(lineup) || lineup.length === 0) return;

    let cancelled = false;
    const upcoming = [];
    for (let i = 1; i <= lookahead; i++) {
      const idx = currentIndex + i;
      if (idx >= lineup.length) break;
      const p = lineup[idx];
      if (p && p.id) upcoming.push(p.id);
    }
    if (upcoming.length === 0) return;

    const key = `${session || ''}::${upcoming.join(',')}`;
    if (peekedKey.current === key) return;
    peekedKey.current = key;

    const qs = session ? `?peek=1&session=${encodeURIComponent(session)}` : '?peek=1';

    (async () => {
      const urls = [];
      for (const pid of upcoming) {
        if (cancelled) return;
        try {
          const res = await fetch(`/api/music/next/${encodeURIComponent(pid)}${qs}`);
          if (!res.ok) continue;
          const data = await res.json();
          const audioUrl = data && data.audio_url;
          if (!audioUrl) continue;
          prebufferedUrls.current.set(pid, audioUrl);
          urls.push(audioUrl);
        } catch {
          /* network/parse error — leave previous entry */
        }
      }
      if (cancelled || urls.length === 0) return;
      try {
        await preload(urls);
      } catch {
        /* AudioContext failures are non-fatal — playback will lazy-load */
      }
    })();

    return () => { cancelled = true; };
  }, [lineup, currentIndex, lookahead, session, enabled]);

  return { prebufferedUrls };
}
