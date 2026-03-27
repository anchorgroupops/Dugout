import React, { useState } from 'react';
import { TipBadge } from './StatTooltip';

/**
 * OpponentFieldMap — inferred hit-zone heatmap for opposing team.
 *
 * Since we don't have XY ball-landing coordinates, we infer zone weights
 * from hit-type distributions (singles/doubles/triples/hr, gb%/fb%/ld%):
 *   - Ground balls → infield zones
 *   - Fly balls    → outfield zones
 *   - Line drives  → gaps (LC, RC)
 *   - Singles      → distributed infield + shallow OF
 *   - Doubles/Trips→ concentrated in gaps / deep OF
 *   - HRs          → deep outfield (all zones)
 *
 * Props:
 *   matchup  — response from /api/matchup/:slug
 *   isMobile — layout hint
 */

// ─── Zone definitions (field SVG coords use 200×185 viewport) ──────────────
const ZONES = [
  // id, label, polygon points, default bias weight
  { id: 'lf',  label: 'LF',  points: '10,10 55,10 70,80 10,90',      base: 0.10 },
  { id: 'lc',  label: 'LC',  points: '55,10 100,5 100,70 70,80',      base: 0.12 },
  { id: 'cf',  label: 'CF',  points: '100,5 145,10 130,70 100,70',    base: 0.10 },
  { id: 'rc',  label: 'RC',  points: '145,10 190,10 190,80 130,70',   base: 0.12 },
  { id: 'rf',  label: 'RF',  points: '190,10 190,90 130,80 145,10',   base: 0.10 },
  { id: 'if3', label: '3B',  points: '10,90 70,80 75,130 40,140',     base: 0.12 },
  { id: 'ifm', label: 'Mid', points: '70,80 130,80 120,130 80,130',   base: 0.14 },
  { id: 'if1', label: '1B',  points: '130,80 190,90 160,140 120,130', base: 0.12 },
  { id: 'home',label: 'Home',points: '40,140 80,130 120,130 160,140 100,180', base: 0.08 },
];

/**
 * Compute zone weight multipliers from team batting stats.
 * Returns an object { zoneId: 0..1 } where higher = more hits expected there.
 */
function computeZoneWeights(stats, advStats) {
  const h       = stats?.h       ?? 0;
  const singles = stats?.singles ?? stats?.h1 ?? (h - (stats?.doubles ?? 0) - (stats?.triples ?? 0) - (stats?.hr ?? 0));
  const doubles = stats?.doubles ?? stats?.h2 ?? 0;
  const triples = stats?.triples ?? stats?.h3 ?? 0;
  const hr      = stats?.hr      ?? 0;
  const total   = Math.max(1, singles + doubles + triples + hr);

  const s_pct = singles / total;
  const d_pct = doubles / total;
  const t_pct = triples / total;
  const hr_pct= hr      / total;

  // Advanced tendencies (stored as 0-100 or 0-1)
  const raw_gb = parseFloat(advStats?.gb_pct ?? 0);
  const raw_fb = parseFloat(advStats?.fb_pct ?? 0);
  const raw_ld = parseFloat(advStats?.ld_pct ?? 0);
  // Normalise to 0-1 if stored as percentage
  const gb = raw_gb > 1 ? raw_gb / 100 : raw_gb;
  const fb = raw_fb > 1 ? raw_fb / 100 : raw_fb;
  const ld = raw_ld > 1 ? raw_ld / 100 : raw_ld;

  // Build weights per zone
  // Each number is a fraction added to the base weight
  const w = {
    lf:   0,
    lc:   0,
    cf:   0,
    rc:   0,
    rf:   0,
    if3:  0,
    ifm:  0,
    if1:  0,
    home: 0,
  };

  // Singles spread: infield (55%) + shallow OF gaps (45%)
  w.if3  += s_pct * 0.20;
  w.ifm  += s_pct * 0.20;
  w.if1  += s_pct * 0.15;
  w.lc   += s_pct * 0.15;
  w.rc   += s_pct * 0.15;
  w.lf   += s_pct * 0.08;
  w.rf   += s_pct * 0.07;

  // Doubles → gaps
  w.lc   += d_pct * 0.35;
  w.rc   += d_pct * 0.35;
  w.lf   += d_pct * 0.12;
  w.rf   += d_pct * 0.12;
  w.cf   += d_pct * 0.06;

  // Triples → deep gaps + CF
  w.lc   += t_pct * 0.30;
  w.rc   += t_pct * 0.30;
  w.cf   += t_pct * 0.40;

  // HRs → all outfield equally
  w.lf   += hr_pct * 0.20;
  w.lc   += hr_pct * 0.20;
  w.cf   += hr_pct * 0.20;
  w.rc   += hr_pct * 0.20;
  w.rf   += hr_pct * 0.20;

  // Ground-ball tendency → infield bias
  w.if3  += gb * 0.20;
  w.ifm  += gb * 0.20;
  w.if1  += gb * 0.20;
  w.home += gb * 0.10;
  // subtract from OF
  w.lf   -= gb * 0.05;
  w.cf   -= gb * 0.05;
  w.rf   -= gb * 0.05;

  // Fly-ball tendency → outfield bias
  w.lf   += fb * 0.15;
  w.lc   += fb * 0.15;
  w.cf   += fb * 0.15;
  w.rc   += fb * 0.15;
  w.rf   += fb * 0.15;
  w.if3  -= fb * 0.05;
  w.ifm  -= fb * 0.05;
  w.if1  -= fb * 0.05;

  // Line-drive tendency → gap bias
  w.lc   += ld * 0.20;
  w.rc   += ld * 0.20;
  w.cf   += ld * 0.10;

  // Blend with base zone weights and clamp 0..1
  const result = {};
  ZONES.forEach(({ id, base }) => {
    result[id] = Math.max(0, Math.min(1, base + (w[id] ?? 0)));
  });

  // Normalise so max = 1
  const maxW = Math.max(...Object.values(result), 0.001);
  ZONES.forEach(({ id }) => { result[id] = result[id] / maxW; });

  return result;
}

/** Interpolate from teal (cold) to red (hot) */
function heatColor(t) {
  // t: 0..1
  if (t < 0.33) {
    const r = Math.round(4 + t * 3 * (63 - 4));
    const g = Math.round(101 + t * 3 * (143 - 101));
    const b = Math.round(104 + t * 3 * (136 - 104));
    return `rgba(${r},${g},${b},${0.25 + t * 0.35})`;
  }
  if (t < 0.66) {
    const p = (t - 0.33) * 3;
    const r = Math.round(63 + p * (220 - 63));
    const g = Math.round(143 + p * (180 - 143));
    const b = Math.round(136 + p * (50 - 136));
    return `rgba(${r},${g},${b},${0.45 + p * 0.25})`;
  }
  const p = (t - 0.66) * 3;
  const r = Math.round(220 + p * (230 - 220));
  const g = Math.round(180 + p * (80 - 180));
  const b = Math.round(50 + p * (30 - 50));
  return `rgba(${r},${g},${b},${0.65 + p * 0.25})`;
}

const fmt3 = (v) => {
  if (v == null || v === '') return '—';
  const n = parseFloat(v);
  if (isNaN(n)) return '—';
  const s = n.toFixed(3);
  return (n >= 0 && n < 1) ? s.replace(/^0/, '') : s;
};

// ─── Field SVG ──────────────────────────────────────────────────────────────
const FieldSVG = ({ zoneWeights, onHover, hoveredZone }) => (
  <svg viewBox="0 0 200 185" style={{ width: '100%', maxWidth: 300, display: 'block', margin: '0 auto' }}>
    {/* Sky / warning track */}
    <rect x="0" y="0" width="200" height="185" fill="rgba(0,0,0,0.3)" rx="4" />

    {/* Warning track arc */}
    <path d="M 5,5 A 140,140 0 0 1 195,5 L 195,95 A 110,110 0 0 0 5,95 Z"
      fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="4" />

    {/* Zone overlays */}
    {ZONES.map(({ id, label, points }) => {
      const t = zoneWeights[id] ?? 0;
      const isHovered = hoveredZone === id;
      return (
        <polygon
          key={id}
          points={points}
          fill={heatColor(t)}
          stroke={isHovered ? 'rgba(255,255,255,0.8)' : 'rgba(255,255,255,0.12)'}
          strokeWidth={isHovered ? 1.5 : 0.5}
          style={{ cursor: 'default', transition: 'fill 0.3s' }}
          onMouseEnter={() => onHover && onHover(id)}
          onMouseLeave={() => onHover && onHover(null)}
        />
      );
    })}

    {/* Zone labels */}
    {ZONES.map(({ id, label, points }) => {
      const pts = points.split(' ').map(p => p.split(',').map(Number));
      const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length;
      const cy = pts.reduce((s, p) => s + p[1], 0) / pts.length;
      return (
        <text key={id} x={cx} y={cy + 3} textAnchor="middle"
          fontSize="7" fill="rgba(255,255,255,0.55)" fontWeight="600"
          style={{ pointerEvents: 'none', userSelect: 'none' }}>
          {label}
        </text>
      );
    })}

    {/* Infield diamond (orientation guide) */}
    <polygon points="100,95 75,120 100,145 125,120"
      fill="none" stroke="rgba(255,255,255,0.2)" strokeWidth="0.8" />

    {/* Pitcher circle */}
    <circle cx="100" cy="118" r="6"
      fill="rgba(255,255,255,0.06)" stroke="rgba(255,255,255,0.18)" strokeWidth="0.7" />

    {/* Home plate */}
    <polygon points="100,165 94,170 94,176 106,176 106,170"
      fill="rgba(255,255,255,0.3)" />
  </svg>
);

// ─── Threat badge for a single player ─────────────────────────────────────
const PlayerThreatRow = ({ player }) => {
  const b = player.batting || {};
  const avg = parseFloat(b.avg ?? player.avg);
  const obp = parseFloat(b.obp ?? player.obp);
  const ops = parseFloat(b.ops ?? player.ops);
  const h   = parseInt(b.h   ?? player.h   ?? 0);
  const sb  = parseInt(b.sb  ?? player.sb  ?? 0);
  const name = player.name || `${player.first || ''} ${player.last || ''}`.trim() || '—';
  const num  = player.number || '';
  const pos  = player.pos || b.pos || '';

  // Threat level
  const isHot = !isNaN(avg) && (avg >= 0.350 || (!isNaN(ops) && ops >= 0.800));
  const isCaution = !isNaN(avg) && avg >= 0.250 && !isHot;

  const threatColor = isHot ? '#f87171' : isCaution ? '#fbbf24' : 'rgba(255,255,255,0.35)';
  const threatLabel = isHot ? '🔥' : isCaution ? '⚠️' : '•';

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '0.5rem',
      padding: '0.4rem 0.5rem', borderRadius: '5px',
      background: isHot ? 'rgba(248,113,113,0.08)' : 'rgba(255,255,255,0.02)',
      borderLeft: `3px solid ${threatColor}`,
    }}>
      <span style={{ fontSize: '11px', width: 16, textAlign: 'center' }}>{threatLabel}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <span style={{ fontWeight: 600, fontSize: 'var(--text-sm)' }}>
          {num ? `#${num} ` : ''}{name}
        </span>
        {pos && <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginLeft: '0.3rem' }}>{pos}</span>}
      </div>
      <div style={{ display: 'flex', gap: '0.3rem', flexShrink: 0 }}>
        {!isNaN(avg) && <TipBadge label="AVG" value={fmt3(avg)} />}
        {!isNaN(obp) && <TipBadge label="OBP" value={fmt3(obp)} />}
        {h > 0    && <TipBadge label="H"   value={h} />}
        {sb > 0   && <TipBadge label="SB"  value={sb} />}
      </div>
    </div>
  );
};

// ─── Main component ──────────────────────────────────────────────────────────
export default function OpponentFieldMap({ matchup, isMobile = false }) {
  const [hoveredZone, setHoveredZone] = useState(null);

  if (!matchup || matchup.empty) return null;

  const opponent  = matchup.opponent || 'Opponent';
  const theirStats = matchup.their_stats || {};
  const batting    = theirStats.batting  || {};
  const advBatting = theirStats.batting_advanced || {};
  const roster     = matchup.their_roster || [];

  // Only render players that have batting data
  const playersWithStats = roster.filter(p => {
    const b = p.batting || {};
    return b.h != null || b.avg != null || b.pa != null;
  });

  const zoneWeights = computeZoneWeights(batting, advBatting);

  // Zone legend
  const topZones = ZONES
    .map(z => ({ ...z, w: zoneWeights[z.id] }))
    .sort((a, b) => b.w - a.w)
    .slice(0, 3);

  const totalHits = batting.h ?? 0;
  const hasData = totalHits > 0;

  return (
    <div style={{ marginTop: '1rem' }}>
      {/* Section header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
        <span style={{ fontSize: '1rem' }}>🎯</span>
        <span className="section-label" style={{ marginBottom: 0 }}>Opponent Field Tendencies</span>
        <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginLeft: 'auto' }}>{opponent}</span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: '1rem' }}>

        {/* Left: Field map */}
        <div>
          {hasData ? (
            <>
              <FieldSVG
                zoneWeights={zoneWeights}
                onHover={!isMobile ? setHoveredZone : undefined}
                hoveredZone={hoveredZone}
              />
              {/* Hot zone legend */}
              <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap', justifyContent: 'center' }}>
                {topZones.map(z => (
                  <span key={z.id} style={{
                    fontSize: 'var(--text-xs)', color: 'var(--text-muted)',
                    background: heatColor(z.w), padding: '2px 8px', borderRadius: '4px',
                  }}>
                    ▲ {z.label}
                  </span>
                ))}
              </div>
            </>
          ) : (
            <div style={{
              height: 180, display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: 'rgba(255,255,255,0.03)', borderRadius: '8px',
              color: 'var(--text-muted)', fontSize: 'var(--text-sm)', fontStyle: 'italic', textAlign: 'center',
            }}>
              No batting data yet.<br />Chart will populate after first game.
            </div>
          )}
        </div>

        {/* Right: Player threat list */}
        <div>
          <div className="section-label" style={{ marginBottom: '0.5rem', fontSize: 'var(--text-xs)' }}>
            Player Threat Profile
          </div>
          {playersWithStats.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
              {playersWithStats
                .sort((a, b) => {
                  const avgA = parseFloat((a.batting || {}).avg ?? a.avg ?? 0);
                  const avgB = parseFloat((b.batting || {}).avg ?? b.avg ?? 0);
                  return avgB - avgA;
                })
                .slice(0, 3)
                .map((p, i) => <PlayerThreatRow key={i} player={p} />)
              }
            </div>
          ) : (
            <div style={{
              padding: '1rem', color: 'var(--text-muted)', fontSize: 'var(--text-sm)',
              fontStyle: 'italic', textAlign: 'center',
              background: 'rgba(255,255,255,0.03)', borderRadius: '8px',
            }}>
              Roster visible — no per-player batting stats yet.<br />
              Stats populate from GameChanger scraper.
            </div>
          )}
          {/* Defensive tip */}
          {hasData && (
            <div style={{
              marginTop: '0.75rem', padding: '0.5rem 0.75rem', borderRadius: '6px',
              background: 'rgba(4,101,104,0.12)', border: '1px solid rgba(4,101,104,0.25)',
              fontSize: 'var(--text-xs)', color: 'var(--text-muted)',
            }}>
              💡 {buildDefensiveTip(batting, advBatting, topZones)}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/** Generate a one-liner defensive positioning tip */
function buildDefensiveTip(batting, advBatting, topZones) {
  const tips = [];
  const hr = batting.hr ?? 0;
  const doubles = batting.doubles ?? 0;
  const sb = batting.sb ?? 0;
  const gbPct = parseFloat(advBatting.gb_pct ?? 0);
  const fbPct = parseFloat(advBatting.fb_pct ?? 0);

  if (hr > 0 || doubles > 1) tips.push('play deep in outfield gaps');
  if (gbPct > 50 || (gbPct > 1 && gbPct > 50)) tips.push('infield in for ground ball tendency');
  if (fbPct > 50 || (fbPct > 1 && fbPct > 50)) tips.push('outfield back for fly ball tendency');
  if (sb > 1) tips.push('hold runners, quick release to 2B');
  if (topZones[0]) tips.push(`shade toward ${topZones[0].label}`);

  return tips.length > 0
    ? tips[0].charAt(0).toUpperCase() + tips[0].slice(1) + (tips.length > 1 ? `. Also: ${tips.slice(1).join('; ')}.` : '.')
    : 'Observe tendencies as game progresses.';
}
