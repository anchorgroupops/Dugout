// Pure helpers for the dugout tablet. No React, no DOM: unit-tested in
// tests/dugoutTablet.test.mjs.

export const DEFAULT_FIELD = { width: 320, height: 320, home: [160, 292] };

// Pull / centre / oppo split from spray points, by angle off the vertical
// line through home. Frame: smaller x = third-base / left-field side, y
// shrinks toward the outfield. A right-handed hitter's pull side is left
// field; handedness is not in the payload, so we report the field thirds
// (Left / Centre / Right) rather than guessing pull vs oppo.
export function zoneSplit(points, home = DEFAULT_FIELD.home) {
  const out = { left: 0, centre: 0, right: 0, total: 0 };
  for (const p of points || []) {
    if (!Number.isFinite(p?.x) || !Number.isFinite(p?.y)) continue;
    const dx = p.x - home[0];
    const dy = home[1] - p.y;
    // Angle from straight-up centre field: -45 (left line) .. +45 (right line).
    const deg = (Math.atan2(dx, Math.max(dy, 0.0001)) * 180) / Math.PI;
    if (deg < -15) out.left += 1;
    else if (deg > 15) out.right += 1;
    else out.centre += 1;
    out.total += 1;
  }
  return out;
}

export function zonePercents(points, home) {
  const z = zoneSplit(points, home);
  if (!z.total) return null;
  const pct = (n) => Math.round((n / z.total) * 100);
  return { left: pct(z.left), centre: pct(z.centre), right: pct(z.right), total: z.total };
}

// Lit/unlit dot arrays for B (max 3), S (max 2), O (max 2).
export function countDots(count, max) {
  const n = Math.max(0, Math.min(max, Number(count) || 0));
  return Array.from({ length: max }, (_, i) => i < n);
}

export function playTypeGroup(playType) {
  const t = String(playType || '').toLowerCase();
  if (t.includes('ground')) return 'ground';
  if (t.includes('line')) return 'line';
  if (t.includes('fly') || t.includes('pop')) return 'fly';
  return 'other';
}

export function historyLine(history) {
  if (!history) return '';
  const { games = 0, pa = 0, hits = 0, in_play: inPlay = 0 } = history;
  return `${pa} PA · ${hits} H · ${inPlay} in play · ${games} ${games === 1 ? 'game' : 'games'}`;
}

// Banner for the payload status; null when nothing needs saying.
// `networkFailed` means our last fetch failed: keep the old payload, go stale.
export function bannerFor(payload, networkFailed, nowMs = Date.now(), lastOkMs = null) {
  if (networkFailed) {
    const secs = lastOkMs ? Math.max(0, Math.round((nowMs - lastOkMs) / 1000)) : null;
    return { tone: 'stale', text: secs == null ? 'Connection lost' : `Connection lost - last update ${secs}s ago` };
  }
  if (!payload) return { tone: 'starting', text: 'Loading…' };
  switch (payload.status) {
    case 'starting': return { tone: 'starting', text: 'Waiting for first pitch data…' };
    case 'stale': return { tone: 'stale', text: `Last update ${payload.age_s ?? '?'}s ago` };
    case 'error': return { tone: 'error', text: `Live feed stopped (${payload.error || 'error'})` };
    default: return null;
  }
}

export function isFinalView(payload) {
  return !!payload && payload.status === 'idle' && !!payload.game;
}
