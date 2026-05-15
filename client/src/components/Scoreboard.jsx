import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Radio, Home, Plane, Clock, Trophy, RefreshCw, ExternalLink, Shield, AlertTriangle, ChevronDown, ChevronUp, Sun, Eye } from 'lucide-react';
import { formatDateMMDDYYYY } from '../utils/formatDate';
import { fetchWithBackoff } from '../utils/apiClient';
import { PlayerName } from './StatTooltip';

const POLL_INTERVAL_LIVE = 15000;
const POLL_INTERVAL_IDLE = 60000;

// ─── Helpers ──────────────────────────────────────────────────────────────────

function clamp01(v) { return Math.min(1, Math.max(0, v)); }

function parseRunners(runners) {
  if (!runners) return [false, false, false];
  // Server normalizes to {first, second, third}; array form is a fallback
  if (Array.isArray(runners)) {
    const occupied = new Set(runners.map(r =>
      typeof r === 'object' ? String(r?.base || r?.base_number || '') : String(r)
    ));
    return [
      occupied.has('1') || occupied.has('first') || occupied.has('1b'),
      occupied.has('2') || occupied.has('second') || occupied.has('2b'),
      occupied.has('3') || occupied.has('third') || occupied.has('3b'),
    ];
  }
  return [!!runners.first, !!runners.second, !!runners.third];
}

function computeZonesFromBatting(b) {
  if (!b) return null;
  const h = b.h || b.hits || 0;
  const doubles = b['2b'] || b.doubles || 0;
  const triples = b['3b'] || b.triples || 0;
  const hr = b.hr || b.home_runs || 0;
  const singles = Math.max(0, h - doubles - triples - hr);
  const total = h || 1;
  const s = singles / total;
  const d = doubles / total;
  const hr_pct = hr / total;
  // GC stores pcts as percentages (e.g. 45.2) or decimals (0.452) — normalize like the server does
  const rawGb = b.gb_pct || b.gb || 0;
  const rawFb = b.fb_pct || b.fb || 0;
  const gb = clamp01(rawGb > 1 ? rawGb / 100 : rawGb || 0.4);
  const fb = clamp01(rawFb > 1 ? rawFb / 100 : rawFb || 0.3);
  return {
    lf:  clamp01(0.10 + s * 0.05 + d * 0.15 + fb * 0.08),
    lc:  clamp01(0.12 + d * 0.15 + s * 0.10),
    cf:  clamp01(0.10 + fb * 0.10 + hr_pct * 0.15),
    rc:  clamp01(0.12 + d * 0.15 + s * 0.10),
    rf:  clamp01(0.10 + s * 0.05 + d * 0.15 + fb * 0.08),
    if3: clamp01(0.12 + gb * 0.15 + s * 0.10),
    ifm: clamp01(0.14 + gb * 0.12 + s * 0.08),
    if1: clamp01(0.12 + gb * 0.15 + s * 0.08),
  };
}

function findBatterAndNext(list, currentBatter) {
  if (!list?.length) return [null, null];
  if (!currentBatter) return [list[0] || null, list[1] || null];
  const num = currentBatter.number;
  const name = currentBatter.name?.toLowerCase();
  let idx = list.findIndex(p =>
    (num && p.number === num) ||
    (name && (p.name || p.player || '').toLowerCase() === name)
  );
  if (idx === -1) idx = 0;
  return [list[idx], list[(idx + 1) % list.length] || null];
}

function fmtStat(v) {
  if (v == null || isNaN(v)) return '—';
  if (v < 1) return '.' + v.toFixed(3).split('.')[1];
  return v.toFixed(3);
}

// ─── Base Diagram ─────────────────────────────────────────────────────────────

const BaseDiagram = ({ runners }) => {
  const [first, second, third] = parseRunners(runners);
  const on = '#FFD700';
  const off = 'rgba(255,255,255,0.15)';
  const stroke = 'rgba(255,255,255,0.3)';
  const sz = 11;
  return (
    <svg width="52" height="52" viewBox="0 0 52 52">
      {/* second */}
      <rect x={26 - sz / 2} y={4} width={sz} height={sz}
        fill={second ? on : off} stroke={stroke} strokeWidth="1"
        transform={`rotate(45 26 ${4 + sz / 2})`} />
      {/* third */}
      <rect x={4} y={26 - sz / 2} width={sz} height={sz}
        fill={third ? on : off} stroke={stroke} strokeWidth="1"
        transform={`rotate(45 ${4 + sz / 2} 26)`} />
      {/* first */}
      <rect x={52 - 4 - sz} y={26 - sz / 2} width={sz} height={sz}
        fill={first ? on : off} stroke={stroke} strokeWidth="1"
        transform={`rotate(45 ${52 - 4 - sz / 2} 26)`} />
      {/* home */}
      <circle cx="26" cy="47" r="4" fill="rgba(255,255,255,0.35)" />
    </svg>
  );
};

const LivePulse = ({ outdoor = false }) => (
  <span style={{
    display: 'inline-flex', alignItems: 'center', gap: outdoor ? '0.5rem' : '0.35rem',
    background: outdoor ? '#dc2626' : 'rgba(218, 54, 51, 0.15)',
    color: outdoor ? '#ffffff' : '#ff4444',
    padding: outdoor ? '6px 16px' : '3px 10px',
    borderRadius: '999px',
    fontSize: outdoor ? '0.95rem' : 'var(--text-xs)',
    fontWeight: '900', letterSpacing: outdoor ? '2px' : '1px',
    border: outdoor ? '2px solid #ffffff' : '1px solid rgba(218, 54, 51, 0.3)',
    boxShadow: outdoor ? '0 0 0 3px rgba(220,38,38,0.45)' : 'none',
  }}>
    <span className="live-pulse-dot" />
    LIVE
  </span>
);

const ScoreBox = ({ label, score, isUs, compact = false, outdoor = false }) => {
  // Outdoor: solid panel backgrounds and pure-white scores so they're legible
  // in direct sunlight. Indoor: keep the original glass aesthetic.
  const bg = outdoor
    ? (isUs ? '#0e3f43' : '#1a2540')
    : (isUs ? 'rgba(4, 101, 104, 0.12)' : 'rgba(255,255,255,0.04)');
  const border = outdoor
    ? `3px solid ${isUs ? '#82cbc3' : '#cfd9e6'}`
    : `2px solid ${isUs ? 'rgba(4, 101, 104, 0.4)' : 'rgba(255,255,255,0.08)'}`;
  const labelColor = outdoor ? '#ffffff' : 'var(--text-muted)';
  const scoreColor = outdoor
    ? '#ffffff'
    : (isUs ? 'var(--primary-color)' : 'var(--text-main)');
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      padding: compact ? '0.4rem 0.75rem' : '0.75rem 1.5rem', borderRadius: compact ? '8px' : '12px',
      background: bg, border,
      minWidth: compact ? '70px' : '100px', transition: 'all 0.3s ease',
      flex: compact ? 1 : undefined, maxWidth: compact ? '120px' : undefined,
      boxShadow: outdoor ? '0 4px 12px rgba(0,0,0,0.45)' : 'none',
    }}>
      <span style={{
        fontSize: compact ? '0.6rem' : 'var(--text-xs)', fontWeight: '800',
        color: labelColor,
        textTransform: 'uppercase', letterSpacing: '1px', marginBottom: compact ? '0.1rem' : '0.25rem',
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '100%',
      }}>{label}</span>
      <span style={{
        fontSize: compact ? 'clamp(1.5rem, 6vw, 2.5rem)' : 'clamp(2.2rem, 9vw, 4rem)', fontWeight: '900',
        color: scoreColor,
        lineHeight: 1, fontVariantNumeric: 'tabular-nums',
        textShadow: outdoor ? '0 2px 4px rgba(0,0,0,0.55)' : 'none',
      }}>{score ?? '-'}</span>
    </div>
  );
};

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
        <button type="button" onClick={() => setBalls(b => (b + 1) % 4)} style={cell('#4CAF50', balls > 0)} aria-label="Add ball">
          <span style={lbl}>Balls</span>
          <span style={num('#4CAF50')}>{balls}</span>
          <Dots filled={balls} max={4} color="#4CAF50" />
        </button>
        <button type="button" onClick={() => setStrikes(s => (s + 1) % 3)} style={cell('#FFD700', strikes > 0)} aria-label="Add strike">
          <span style={lbl}>Strikes</span>
          <span style={num('#FFD700')}>{strikes}</span>
          <Dots filled={strikes} max={3} color="#FFD700" />
        </button>
        <div style={{ ...cell('#ff4444', outsCount > 0), cursor: 'default' }}>
          <span style={lbl}>Outs</span>
          <span style={num('#ff4444')}>{outsCount}</span>
          <Dots filled={outsCount} max={3} color="#ff4444" />
        </div>
      </div>
      <button
        type="button"
        onClick={() => { setBalls(0); setStrikes(0); }}
        style={{
          width: '100%', padding: '9px', background: 'rgba(255,255,255,0.05)',
          border: '1px solid rgba(255,255,255,0.12)', borderRadius: 8,
          color: 'rgba(255,255,255,0.55)', fontSize: '0.65rem', fontWeight: 800,
          letterSpacing: '1px', cursor: 'pointer', fontFamily: 'inherit',
          textTransform: 'uppercase',
        }}
      >▶ Next Batter — Reset Count</button>
    </div>
  );
};

// ─── Spray Chart ──────────────────────────────────────────────────────────────

// ─── Spray Charts (compact + outdoor-readable) ─────────────────────
const ZONE_POLYS = [
  { id: 'lf',  label: 'LF',  points: '10,10 55,10 70,80 10,90',      cx: 38,  cy: 50 },
  { id: 'lc',  label: 'LC',  points: '55,10 100,5 100,70 70,80',     cx: 80,  cy: 42 },
  { id: 'cf',  label: 'CF',  points: '100,5 145,10 130,70 100,70',   cx: 120, cy: 40 },
  { id: 'rc',  label: 'RC',  points: '145,10 190,10 190,80 130,70',  cx: 162, cy: 42 },
  { id: 'rf',  label: 'RF',  points: '190,10 190,90 130,80 145,10',  cx: 165, cy: 50 },
  { id: 'if3', label: '3B',  points: '10,90 70,80 75,130 40,140',    cx: 45,  cy: 110 },
  { id: 'ifm', label: 'SS',  points: '70,80 130,80 120,130 80,130',  cx: 100, cy: 105 },
  { id: 'if1', label: '1B',  points: '130,80 190,90 160,140 120,130', cx: 153, cy: 110 },
];

const MiniSprayChart = ({ zones, size = 100, outdoor = false }) => {
  if (!zones) return null;
  // Field background: solid dark green outdoors; subtle indoors.
  // Zone fill: heat ramp (cool → hot) with much higher floor opacity outdoors
  // so weak zones are still visible against bright sunlight.
  const fieldBg = outdoor ? '#0f2d18' : 'rgba(15,45,24,0.55)';
  const diamondStroke = outdoor ? 'rgba(255,255,255,0.95)' : 'rgba(255,255,255,0.55)';
  const zoneStroke = outdoor ? 'rgba(255,255,255,0.85)' : 'rgba(255,255,255,0.30)';
  const labelFill = outdoor ? '#ffffff' : 'rgba(255,255,255,0.75)';
  const minFill = outdoor ? 0.42 : 0.20;
  const maxBoost = outdoor ? 0.55 : 0.70;
  const showLabels = size >= 140;
  return (
    <svg width={size} height={size * 0.85} viewBox="0 0 200 170" style={{ display: 'block' }}>
      <rect width="200" height="170" fill={fieldBg} rx="8" />
      {ZONE_POLYS.map(z => {
        const weight = Math.max(0, Math.min(1, zones[z.id] || 0));
        // Heat ramp: green (#2e8a4d) → yellow (#facc15) → red (#dc2626)
        let r, g, b;
        if (weight < 0.5) {
          const t = weight * 2;
          r = Math.round(46 + (250 - 46) * t);
          g = Math.round(138 + (204 - 138) * t);
          b = Math.round(77 + (21 - 77) * t);
        } else {
          const t = (weight - 0.5) * 2;
          r = Math.round(250 + (220 - 250) * t);
          g = Math.round(204 + (38 - 204) * t);
          b = Math.round(21 + (38 - 21) * t);
        }
        const opacity = minFill + weight * maxBoost;
        return (
          <g key={z.id}>
            <polygon
              points={z.points}
              fill={`rgba(${r}, ${g}, ${b}, ${opacity.toFixed(2)})`}
              stroke={zoneStroke}
              strokeWidth={outdoor ? 1.5 : 1}
            />
            {showLabels && (
              <text
                x={z.cx} y={z.cy} fill={labelFill}
                fontSize="11" fontWeight="800" textAnchor="middle"
                style={{ paintOrder: 'stroke', stroke: 'rgba(0,0,0,0.6)', strokeWidth: 2 }}
              >
                {z.label}
              </text>
            )}
          </g>
        );
      })}
      {/* Diamond */}
      <polygon points="100,155 115,140 100,125 85,140"
               fill={outdoor ? 'rgba(0,0,0,0.45)' : 'none'}
               stroke={diamondStroke} strokeWidth={outdoor ? 2.2 : 1.5} />
      <circle cx="100" cy="155" r={outdoor ? 4 : 3}
              fill={outdoor ? '#82cbc3' : 'var(--primary-color)'} />
    </svg>
  );
};

// ─── LivePulse ───────────────────────────────────────────────────────────────

const LivePulse = () => (
  <span style={{
    display: 'inline-flex', alignItems: 'center', gap: '0.35rem',
    background: 'rgba(218,54,51,0.15)', color: '#ff4444',
    padding: '3px 10px', borderRadius: 999, fontSize: 'var(--text-xs)',
    fontWeight: 800, letterSpacing: '1px', border: '1px solid rgba(218,54,51,0.3)',
  }}>
    <span className="live-pulse-dot" />
    LIVE
  </span>
);

// ─── DangerBadge ─────────────────────────────────────────────────────────────

const DangerBadge = ({ danger }) => {
  const color = danger >= 70 ? 'var(--danger)' : danger >= 40 ? 'var(--warning)' : 'var(--success)';
  const label = danger >= 70 ? 'HIGH' : danger >= 40 ? 'MED' : 'LOW';
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: '0.2rem',
      background: `${color}22`, color, padding: '2px 8px', borderRadius: 4,
      fontSize: '0.6rem', fontWeight: 800, letterSpacing: '0.5px',
      border: `1px solid ${color}44`,
    }}>
      {danger >= 70 && <AlertTriangle size={9} />}
      {label} {danger}
    </span>
  );
};

// ─── ScoutingCard ─────────────────────────────────────────────────────────────

const ScoutingCard = ({ player, expanded, onToggle, compact = false }) => {
  if (!player) return null;
  return (
    <div style={{
      background: 'rgba(0,0,0,0.2)', borderRadius: 8, overflow: 'hidden',
      border: `1px solid ${player.danger >= 70 ? 'rgba(179,74,57,0.3)' : 'rgba(255,255,255,0.06)'}`,
    }}>
      <button
        type="button"
        onClick={onToggle}
        style={{
          display: 'flex', alignItems: 'center', gap: '0.5rem', width: '100%',
          padding: compact ? '0.35rem 0.5rem' : '0.5rem 0.75rem',
          background: 'none', border: 'none',
          color: 'var(--text-main)', cursor: 'pointer', fontFamily: 'var(--font-base)',
          fontSize: compact ? '0.7rem' : '0.8rem', textAlign: 'left',
        }}
      >
        <span style={{ fontWeight: '800', color: 'var(--text-muted)', minWidth: '28px' }}>
          #{player.number || '—'}
        </span>
        <span style={{ flex: 1, fontWeight: '600' }}>{player.name}</span>
        <DangerBadge danger={player.danger} />
        {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>
      {expanded && (
        <div style={{ padding: '0.5rem 0.75rem', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'flex-start', flexWrap: 'wrap' }}>
            <SprayChart zones={player.zones} size={compact ? 80 : 110} />
            <div style={{ flex: 1, minWidth: 120 }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem', marginBottom: '0.4rem' }}>
                {(player.tags || []).map(t => (
                  <span key={t} style={{ background: 'rgba(130,203,195,0.12)', color: 'var(--primary-color)', padding: '1px 6px', borderRadius: 3, fontSize: '0.6rem', fontWeight: 700 }}>{t}</span>
                ))}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: '0.2rem', fontSize: '0.65rem' }}>
                {[['AVG', fmtStat(player.avg)], ['SLG', fmtStat(player.slg)], ['OBP', fmtStat(player.obp)],
                  ['H', player.h ?? '—'], ['HR', player.hr ?? '—'], ['BB', player.bb ?? '—'],
                  ['SO', player.so ?? '—'], ['SB', player.sb ?? '—'], ['PA', player.pa ?? '—']].map(([k, v]) => (
                  <span key={k} style={{ color: 'var(--text-muted)' }}>{k} <strong style={{ color: 'var(--text-main)' }}>{v}</strong></span>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// ─── At-Bat Panel — current + on-deck batters with high-contrast spray charts ──
//
// This is the PRIMARY in-game artifact: large enough to read from the dugout
// fence in direct sun. Shows side-by-side cards for the current batter and
// the on-deck batter, each with a 200px spray chart, danger badge, key
// slash-line stats, and threat tags. Renders during live play OR pre-game
// once we have an opponent batting order — so coaches can scout warm-ups too.
const BatterScoutCard = ({ player, role, outdoor, isMobile }) => {
  if (!player) return null;
  const fmtAvg = (v) => v != null ? (v < 1 ? `.${String(v).split('.')[1] || '000'}` : v.toFixed(3)) : '—';
  const danger = player.danger ?? 0;
  const dangerColor = danger >= 70 ? '#ff4444' : danger >= 40 ? '#facc15' : '#2ecc71';
  const isAtBat = role === 'AT BAT';

  // Outdoor mode: solid backgrounds, white text, thicker borders, larger fonts.
  const cardBg = outdoor ? '#0a1628' : 'rgba(0,0,0,0.35)';
  const cardBorder = outdoor
    ? (isAtBat ? '3px solid #ff4444' : '3px solid #82cbc3')
    : (isAtBat ? '2px solid rgba(255,68,68,0.55)' : '2px solid rgba(130,203,195,0.45)');
  const roleBg = outdoor
    ? (isAtBat ? '#ff4444' : '#82cbc3')
    : (isAtBat ? 'rgba(255,68,68,0.20)' : 'rgba(130,203,195,0.18)');
  const roleColor = outdoor ? '#000000' : (isAtBat ? '#ff4444' : '#82cbc3');
  const nameColor = outdoor ? '#ffffff' : 'var(--text-main)';
  const labelColor = outdoor ? '#cfd9e6' : 'var(--text-muted)';
  const statValueColor = outdoor ? '#ffffff' : 'var(--text-main)';

  return (
    <div style={{
      background: cardBg, border: cardBorder, borderRadius: '12px',
      padding: isMobile ? '0.6rem' : '0.85rem',
      display: 'flex', flexDirection: 'column', gap: '0.5rem',
      boxShadow: outdoor ? '0 4px 14px rgba(0,0,0,0.55)' : 'none',
    }}>
      {/* Role chip */}
      <div style={{
        display: 'inline-flex', alignSelf: 'flex-start',
        background: roleBg, color: roleColor,
        padding: outdoor ? '4px 12px' : '3px 10px',
        borderRadius: '999px',
        fontSize: outdoor ? '0.85rem' : '0.7rem',
        fontWeight: '900', letterSpacing: '1.5px',
      }}>
        {role}
      </div>

      {/* Name + jersey */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.4rem', flexWrap: 'wrap' }}>
        <span style={{
          fontSize: outdoor ? 'clamp(1.4rem, 5vw, 2rem)' : 'clamp(1.05rem, 4vw, 1.4rem)',
          fontWeight: '900', color: nameColor, lineHeight: 1.1,
        }}>
          {player.name || 'Unknown'}
        </span>
        {player.number && (
          <span style={{
            fontSize: outdoor ? '1.5rem' : '1.05rem', fontWeight: '900',
            color: outdoor ? '#82cbc3' : 'var(--primary-color)',
          }}>
            #{player.number}
          </span>
        )}
      </div>

      {/* Spray chart + stats column */}
      <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'flex-start' }}>
        <div>
          <MiniSprayChart
            zones={player.zones}
            size={isMobile ? 160 : 200}
            outdoor={outdoor}
          />
        </div>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '0.4rem', minWidth: 0 }}>
          {/* Danger pill */}
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: '0.3rem', alignSelf: 'flex-start',
            background: outdoor ? dangerColor : `${dangerColor}22`,
            color: outdoor ? '#000000' : dangerColor,
            padding: outdoor ? '4px 12px' : '3px 10px',
            borderRadius: '6px',
            fontSize: outdoor ? '0.85rem' : '0.7rem',
            fontWeight: '900', letterSpacing: '0.5px',
            border: outdoor ? 'none' : `1px solid ${dangerColor}55`,
          }}>
            {danger >= 70 && <AlertTriangle size={outdoor ? 14 : 10} />}
            {danger >= 70 ? 'HIGH' : danger >= 40 ? 'MED' : 'LOW'} {danger}
          </div>

          {/* Slash line */}
          <div style={{
            display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.25rem',
            fontSize: outdoor ? '0.95rem' : '0.7rem',
          }}>
            {[
              ['AVG', fmtAvg(player.avg)],
              ['SLG', fmtAvg(player.slg)],
              ['OBP', fmtAvg(player.obp)],
              ['HR',  player.hr ?? '—'],
              ['SB',  player.sb ?? '—'],
              ['SO',  player.so ?? '—'],
            ].map(([k, v]) => (
              <div key={k} style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center',
                background: outdoor ? 'rgba(255,255,255,0.06)' : 'transparent',
                padding: outdoor ? '4px 6px' : '0',
                borderRadius: '4px',
              }}>
                <span style={{ color: labelColor, fontSize: outdoor ? '0.65rem' : '0.55rem', fontWeight: '700', letterSpacing: '0.5px' }}>{k}</span>
                <span style={{ color: statValueColor, fontWeight: '900', fontVariantNumeric: 'tabular-nums' }}>{v}</span>
              </div>
            ))}
          </div>

          {/* Threat tags */}
          {player.tags?.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.25rem', marginTop: '0.1rem' }}>
              {player.tags.slice(0, 3).map(t => (
                <span key={t} style={{
                  background: outdoor ? '#82cbc3' : 'rgba(130,203,195,0.15)',
                  color: outdoor ? '#000000' : '#82cbc3',
                  padding: outdoor ? '2px 8px' : '1px 6px',
                  borderRadius: '3px',
                  fontSize: outdoor ? '0.7rem' : '0.6rem',
                  fontWeight: '800',
                }}>{t}</span>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

const AtBatPanel = ({ scouting, livePlay, outdoor, isMobile }) => {
  if (!scouting?.has_data) return null;
  const players = scouting.players || [];
  if (players.length === 0) return null;

  // Identify current batter — match by jersey number first, then name.
  const cb = livePlay?.current_batter || {};
  const cbNum = String(cb.number || '').trim();
  const cbName = (cb.name || '').trim().toLowerCase();
  let currentIdx = -1;
  if (cbNum || cbName) {
    currentIdx = players.findIndex(p =>
      (cbNum && String(p.number) === cbNum) ||
      (cbName && (p.name || '').toLowerCase() === cbName)
    );
  }

  // Identify next batter — prefer GC's `live_play.next_batter`, else use the
  // scouting players array (which mirrors box-score order).
  const nb = livePlay?.next_batter || null;
  let nextIdx = -1;
  if (nb && (nb.number || nb.name)) {
    const nbNum = String(nb.number || '').trim();
    const nbName = (nb.name || '').trim().toLowerCase();
    nextIdx = players.findIndex(p =>
      (nbNum && String(p.number) === nbNum) ||
      (nbName && (p.name || '').toLowerCase() === nbName)
    );
  }
  if (nextIdx < 0 && currentIdx >= 0) {
    nextIdx = (currentIdx + 1) < players.length ? currentIdx + 1 : -1;
  }
  // If we still don't know the current batter, use the top of the order so
  // the panel is never empty when scouting data exists.
  if (currentIdx < 0) currentIdx = 0;
  if (nextIdx < 0) nextIdx = currentIdx + 1 < players.length ? currentIdx + 1 : -1;

  const current = players[currentIdx] || null;
  const onDeck = nextIdx >= 0 ? players[nextIdx] : null;

  return (
    <div style={{ marginTop: '0.75rem', marginBottom: '0.5rem' }}>
      <div style={{
        display: 'grid',
        gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr',
        gap: '0.6rem',
      }}>
        <BatterScoutCard player={current} role="AT BAT"  outdoor={outdoor} isMobile={isMobile} />
        <BatterScoutCard player={onDeck}  role="ON DECK" outdoor={outdoor} isMobile={isMobile} />
      </div>
    </div>
  );
};

const LivePlayPanel = ({ livePlay }) => {
  if (!livePlay) return null;
  const batter = livePlay.current_batter;
  return (
    <div className="glass-panel" style={{
      padding: '0.75rem 1rem', marginTop: '0.75rem',
      borderLeft: '3px solid #ff4444',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.4rem' }}>
        <Shield size={14} color="var(--primary-color)" />
        <span style={{ fontSize: '0.7rem', fontWeight: '800', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
          Live Situation
        </span>
        <span style={{ fontSize: '0.65rem', color: 'rgba(255,255,255,0.3)', marginLeft: 'auto' }}>
          {livePlay.outs} out{livePlay.outs !== 1 ? 's' : ''}
        </span>
      </div>
      {batter && (
        <div style={{ fontSize: '0.85rem', fontWeight: '700', marginBottom: '0.3rem' }}>
          At Bat: <span style={{ color: 'var(--primary-color)' }}>#{batter.number}</span> {batter.name}
        </div>
      )}
      {livePlay.last_play && (
        <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>
          {livePlay.last_play}
        </div>
      )}
    </div>
  );
};

const OpponentScoutPanel = React.memo(({ scouting, livePlay, isLandscape, hideHeader = false }) => {
  const [expandedPlayer, setExpandedPlayer] = useState(null);
  const [showAll, setShowAll] = useState(false);

  if (!scouting?.has_data) return null;

  const players = scouting.players || [];
  const currentBatterNum = livePlay?.current_batter?.number;
  const currentBatterName = livePlay?.current_batter?.name?.toLowerCase();

  const highlightIdx = players.findIndex(p =>
    (currentBatterNum && p.number === currentBatterNum) ||
    (currentBatterName && p.name?.toLowerCase() === currentBatterName)
  );

  const displayPlayers = showAll ? players : players.slice(0, 5);

  return (
    <div style={hideHeader ? {} : { marginTop: '1rem' }}>
      {!hideHeader && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem', paddingBottom: '0.35rem', borderBottom: '1px solid rgba(179,74,57,0.3)' }}>
          <Shield size={14} color="var(--danger)" />
          <h3 style={{ fontSize: 'var(--text-sm)', fontWeight: 700, color: 'var(--danger)', margin: 0 }}>Opponent Scouting</h3>
          <span style={{ fontSize: '0.6rem', color: 'var(--text-muted)', marginLeft: 'auto' }}>{players.length} batter{players.length !== 1 ? 's' : ''}</span>
        </div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {displayPlayers.map((p, i) => {
          const isCurrent = i === highlightIdx;
          return (
            <div key={p.number || i} style={isCurrent ? { border: '1px solid rgba(255,68,68,0.4)', borderRadius: 8 } : {}}>
              {isCurrent && (
                <div style={{ fontSize: '0.55rem', fontWeight: 800, color: '#ff4444', textTransform: 'uppercase', letterSpacing: '1px', padding: '3px 8px', background: 'rgba(255,68,68,0.1)', borderRadius: '8px 8px 0 0' }}>AT BAT</div>
              )}
              <ScoutingCard
                player={p}
                expanded={expandedPlayer === i || isCurrent}
                onToggle={() => setExpandedPlayer(expandedPlayer === i ? null : i)}
                compact={isLandscape}
              />
            </div>
          );
        })}
      </div>
      {players.length > 5 && (
        <button
          type="button"
          onClick={() => setShowAll(s => !s)}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.3rem',
            width: '100%', marginTop: '0.4rem', padding: '0.4rem',
            background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: 6, color: 'var(--text-muted)', fontSize: '0.7rem',
            fontWeight: 600, cursor: 'pointer', fontFamily: 'var(--font-base)',
          }}
        >
          {showAll ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          {showAll ? 'Show top 5' : `Show all ${players.length}`}
        </button>
      )}
    </div>
  );
});

// ─── ScoreBox (for final view) ────────────────────────────────────────────────

const ScoreBox = ({ label, score, isUs }) => (
  <div style={{
    display: 'flex', flexDirection: 'column', alignItems: 'center',
    padding: '0.75rem 1.5rem', borderRadius: 12,
    background: isUs ? 'rgba(4,101,104,0.12)' : 'rgba(255,255,255,0.04)',
    border: `2px solid ${isUs ? 'rgba(4,101,104,0.4)' : 'rgba(255,255,255,0.08)'}`,
    minWidth: 100,
  }}>
    <span style={{ fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '0.25rem' }}>{label}</span>
    <span style={{ fontSize: 'clamp(2rem,8vw,3.5rem)', fontWeight: 900, color: isUs ? 'var(--primary-color)' : 'var(--text-main)', lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>{score ?? '-'}</span>
  </div>
);

// ─── BatterRow (box score rows) ───────────────────────────────────────────────

const BatterRow = ({ player, idx, compact = false }) => {
  const b = player.batting || player;
  const name = player.name || player.player || '—';
  const number = player.number;
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: compact ? '0.3rem' : '0.5rem',
      padding: compact ? '0.25rem 0.4rem' : '0.4rem 0.6rem', borderRadius: 6,
      background: idx % 2 === 0 ? 'rgba(0,0,0,0.15)' : 'rgba(0,0,0,0.08)',
      fontSize: compact ? '0.65rem' : undefined,
    }}>
      <span style={{ width: compact ? 16 : 20, fontSize: compact ? '0.6rem' : 'var(--text-xs)', color: 'var(--text-muted)', textAlign: 'right' }}>{idx + 1}</span>
      <div style={{ flex: 1, minWidth: compact ? 60 : 80 }}>
        <PlayerName name={name} number={number} size="sm" />
      </div>
      <div style={{ display: 'flex', gap: compact ? '0.35rem' : '0.75rem', fontSize: compact ? '0.6rem' : 'var(--text-xs)', color: 'var(--text-muted)' }}>
        <span>{b.ab ?? b.pa ?? '-'} AB</span>
        <span>{b.h ?? '-'} H</span>
        <span>{b.r ?? '-'} R</span>
        {!compact && <span>{b.rbi ?? '-'} RBI</span>}
        {!compact && <span>{b.bb ?? '-'} BB</span>}
      </div>
    </div>
  );
};

// ─── Live Scoreboard Panel ────────────────────────────────────────────────────

const LiveScoreboardPanel = ({ data, isMobile, isLandscape, fetchScoreboard, lastUpdated, team }) => {
  const isHome = (data.home_away || '').toLowerCase() === 'home';
  const livePlay = data.live_play;
  const outs = livePlay?.outs ?? 0;
  const runners = livePlay?.runners;

  const sharksBatting = (isHome && data.inning_half === 'bottom') || (!isHome && data.inning_half === 'top');

  let atBatPlayer = null;
  let onDeckPlayer = null;
  let atBatIsShark = false;

  if (sharksBatting && data.sharks_batting?.length) {
    [atBatPlayer, onDeckPlayer] = findBatterAndNext(data.sharks_batting, livePlay?.current_batter);
    atBatIsShark = true;
  } else if (!sharksBatting && data.opponent_scouting?.has_data) {
    [atBatPlayer, onDeckPlayer] = findBatterAndNext(data.opponent_scouting.players || [], livePlay?.current_batter);
  }

  const batterKey = `${livePlay?.current_batter?.name || ''}-${livePlay?.current_batter?.number || ''}`;

  return (
    <div style={{
      background: '#080808',
      borderRadius: 16,
      border: '2px solid rgba(255,68,68,0.35)',
      padding: isMobile ? 16 : 20,
      display: 'flex', flexDirection: 'column', gap: 14,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <LivePulse />
        <span className={`home-away-pill ${isHome ? 'home-away-pill--home' : 'home-away-pill--away'}`} style={{ fontSize: '0.55rem' }}>
          {isHome ? <Home size={9} /> : <Plane size={9} />}
          {isHome ? 'HOME' : 'AWAY'}
        </span>
        <span style={{ fontSize: '0.8rem', color: 'rgba(255,255,255,0.5)' }}>
          vs. <strong style={{ color: '#fff' }}>{data.opponent || 'Opponent'}</strong>
        </span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          {data.gc_game_id && (
            <a
              href={`https://web.gc.com/teams/${team?.gc_team_id || 'NuGgx6WvP7TO'}/${team?.gc_season_slug || '2026-spring-sharks'}/schedule/${data.gc_game_id}/plays`}
              target="_blank" rel="noopener noreferrer"
              style={{ display: 'flex', alignItems: 'center', gap: 3, background: 'rgba(4,101,104,0.2)', color: '#82CBC3', border: '1px solid rgba(4,101,104,0.3)', padding: '4px 10px', borderRadius: 6, fontSize: '0.65rem', fontWeight: 600, textDecoration: 'none' }}
            ><ExternalLink size={10} /> GC</a>
          )}
          <button
            type="button" onClick={fetchScoreboard}
            style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.12)', borderRadius: 6, color: 'rgba(255,255,255,0.4)', cursor: 'pointer', padding: '4px 8px', display: 'flex', alignItems: 'center' }}
            title="Refresh"
          ><RefreshCw size={13} /></button>
        </div>
      </div>

      {/* Score row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flex: 1 }}>
          <span style={{ fontSize: '0.58rem', fontWeight: 900, color: 'rgba(130,203,195,0.7)', letterSpacing: '2px', textTransform: 'uppercase', marginBottom: 2 }}>Sharks</span>
          <span style={{ fontSize: 'clamp(3.5rem,16vw,6rem)', fontWeight: 900, color: '#82CBC3', lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>
            {data.sharks_score ?? '-'}
          </span>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, minWidth: 64 }}>
          {data.inning != null && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              <InningDiamond half={data.inning_half} />
              <span style={{ fontSize: '0.7rem', fontWeight: 800, color: 'rgba(255,255,255,0.55)', marginTop: 2 }}>
                {data.inning_half === 'top' ? 'Top' : data.inning_half === 'bottom' ? 'Bot' : ''} {data.inning}
              </span>
            </div>
          )}
          <BaseDiagram runners={runners} />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flex: 1 }}>
          <span style={{ fontSize: '0.58rem', fontWeight: 900, color: 'rgba(255,255,255,0.35)', letterSpacing: '2px', textTransform: 'uppercase', marginBottom: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 100 }}>
            {data.opponent || 'Opp'}
          </span>
          <span style={{ fontSize: 'clamp(3.5rem,16vw,6rem)', fontWeight: 900, color: 'rgba(255,255,255,0.8)', lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>
            {data.opponent_score ?? '-'}
          </span>
        </div>
      </div>

      {/* Count Widget */}
      <CountWidget outs={outs} batterKey={batterKey} />

      {/* AT BAT / ON DECK */}
      {(atBatPlayer || onDeckPlayer) && (
        <div style={{ display: 'flex', gap: 8 }}>
          {atBatPlayer && (
            <BatterCard player={atBatPlayer} label="At Bat" isOnDeck={false} isSharksBatting={atBatIsShark} />
          )}
          {onDeckPlayer && (
            <BatterCard player={onDeckPlayer} label="On Deck" isOnDeck={true} isSharksBatting={atBatIsShark} />
          )}
        </div>
      )}

      {/* Last Play */}
      {livePlay?.last_play && (
        <CollapsibleSection label="Last Play" defaultOpen={true}>
          <p style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.65)', margin: 0, fontStyle: 'italic' }}>
            {livePlay.last_play}
          </p>
        </CollapsibleSection>
      )}

      {/* Linescore */}
      {data.linescore?.length > 0 && (
        <CollapsibleSection label="Linescore">
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.62rem', textAlign: 'center' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
                  <th style={{ padding: '3px 6px', textAlign: 'left', color: 'rgba(255,255,255,0.35)' }}>Team</th>
                  {data.linescore[0]?.innings?.map((_, i) => (
                    <th key={i} style={{ padding: '3px', color: 'rgba(255,255,255,0.35)', minWidth: 20 }}>{i + 1}</th>
                  ))}
                  <th style={{ padding: '3px 5px', color: 'rgba(255,255,255,0.35)', fontWeight: 800 }}>R</th>
                  <th style={{ padding: '3px 5px', color: 'rgba(255,255,255,0.35)' }}>H</th>
                  <th style={{ padding: '3px 5px', color: 'rgba(255,255,255,0.35)' }}>E</th>
                </tr>
              </thead>
              <tbody>
                {data.linescore.map((teamRow, idx) => (
                  <tr key={idx} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', color: idx === 0 ? '#82CBC3' : '#fff' }}>
                    <td style={{ padding: '3px 6px', textAlign: 'left', fontWeight: 700 }}>
                      {teamRow.name || (idx === 0 ? 'Sharks' : data.opponent)}
                    </td>
                    {teamRow.innings?.map((runs, i) => <td key={i} style={{ padding: 3, fontVariantNumeric: 'tabular-nums' }}>{runs ?? '-'}</td>)}
                    <td style={{ padding: '3px 5px', fontWeight: 800, fontVariantNumeric: 'tabular-nums' }}>{teamRow.runs ?? '-'}</td>
                    <td style={{ padding: '3px 5px', fontVariantNumeric: 'tabular-nums' }}>{teamRow.hits ?? '-'}</td>
                    <td style={{ padding: '3px 5px', fontVariantNumeric: 'tabular-nums' }}>{teamRow.errors ?? '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CollapsibleSection>
      )}

      {/* Opponent Scouting */}
      {data.opponent_scouting?.has_data && (
        <CollapsibleSection label="Opponent Scouting">
          <OpponentScoutPanel scouting={data.opponent_scouting} livePlay={livePlay} isLandscape={isLandscape} hideHeader={true} />
        </CollapsibleSection>
      )}

      {/* Box Score */}
      {(data.sharks_batting?.length > 0 || data.opponent_batting?.length > 0) && (
        <CollapsibleSection label="Box Score">
          <div style={isLandscape ? { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 } : {}}>
            {data.sharks_batting?.length > 0 && (
              <div>
                <div style={{ fontSize: '0.58rem', fontWeight: 800, color: '#82CBC3', marginBottom: 4, letterSpacing: '1px', textTransform: 'uppercase' }}>Sharks Batting</div>
                {data.sharks_batting.map((p, i) => <BatterRow key={`s-${i}`} player={p} idx={i} compact={true} />)}
              </div>
            )}
            {data.opponent_batting?.length > 0 && (
              <div style={isLandscape ? {} : { marginTop: 8 }}>
                <div style={{ fontSize: '0.58rem', fontWeight: 800, color: 'rgba(255,255,255,0.35)', marginBottom: 4, letterSpacing: '1px', textTransform: 'uppercase' }}>{data.opponent || 'Opponent'} Batting</div>
                {data.opponent_batting.map((p, i) => <BatterRow key={`o-${i}`} player={p} idx={i} compact={true} />)}
              </div>
            )}
          </div>
        </CollapsibleSection>
      )}

      {lastUpdated && (
        <div style={{ fontSize: '0.52rem', color: 'rgba(255,255,255,0.18)', textAlign: 'center' }}>
          <RefreshCw size={9} style={{ verticalAlign: 'middle', marginRight: 4 }} />
          Updated {lastUpdated.toLocaleTimeString()} · Auto-refreshing every 15s
        </div>
      )}
    </div>
  );
};

// ─── Main Scoreboard ──────────────────────────────────────────────────────────

const Scoreboard = ({ isMobile = false, isLandscape = false, team, schedule }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [lastUpdated, setLastUpdated] = useState(null);
  // Outdoor mode: solid bright backgrounds, white text, larger fonts so the
  // dugout coach can read this at noon in direct sun.
  const [outdoor, setOutdoor] = useState(() => {
    try { return window.localStorage.getItem('sharks_scoreboard_outdoor') === '1'; }
    catch { return false; }
  });
  const toggleOutdoor = useCallback(() => {
    setOutdoor(prev => {
      const next = !prev;
      try { window.localStorage.setItem('sharks_scoreboard_outdoor', next ? '1' : '0'); } catch { /* ignore */ }
      return next;
    });
  }, []);
  const timerRef = useRef(null);
  const mountedRef = useRef(true);

  const fetchScoreboard = useCallback(async () => {
    try {
      const res = await fetchWithBackoff('/api/scoreboard');
      if (!res.ok) throw new Error('Scoreboard unavailable');
      const json = await res.json();
      if (mountedRef.current) { setData(json); setError(''); setLastUpdated(new Date()); }
    } catch (e) {
      if (mountedRef.current) setError(e.message || 'Failed to load scoreboard');
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    fetchScoreboard();
    return () => { mountedRef.current = false; };
  }, [fetchScoreboard]);

  useEffect(() => {
    const interval = data?.status === 'live' ? POLL_INTERVAL_LIVE : POLL_INTERVAL_IDLE;
    timerRef.current = setInterval(fetchScoreboard, interval);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [data?.status, fetchScoreboard]);

  if (loading) return <div className="loader"></div>;

  if (error && !data) {
    return (
      <div className="glass-panel" style={{ padding: '2rem', textAlign: 'center' }}>
        <p style={{ color: 'var(--danger)' }}>{error}</p>
        <button
          type="button" onClick={fetchScoreboard}
          style={{ marginTop: '1rem', background: 'var(--primary-glow)', color: 'var(--primary-color)', border: '1px solid rgba(4,101,104,0.27)', padding: '0.5rem 1rem', borderRadius: 8, cursor: 'pointer', fontWeight: 600 }}
        >Retry</button>
      </div>
    );
  }

  const status = data?.status || 'no_game';
  const isLive = status === 'live';
  const isFinal = status === 'final';
  const isUpcoming = status === 'upcoming' || status === 'pregame';
  const isNoGame = status === 'no_game';

  // ── No Game ──
  if (isNoGame) {
    const record = team?.record || '';
    const today = new Date().toISOString().slice(0, 10);
    const nextGame = (schedule?.upcoming || []).filter(g => g.date >= today).sort((a, b) => a.date.localeCompare(b.date))[0];
    const lastGame = (schedule?.past || []).sort((a, b) => (b.date || '').localeCompare(a.date || ''))[0];
    return (
      <div>
        <h2 className="view-title" style={{ margin: '0 0 var(--space-md)' }}>
          <Radio size={isMobile ? 20 : 24} color="var(--primary-color)" /> Scoreboard
        </h2>
        <div className="glass-panel" style={{ padding: '2rem', textAlign: 'center' }}>
          <Clock size={40} color="var(--text-muted)" style={{ marginBottom: '1rem', opacity: 0.5 }} />
          <p style={{ fontSize: 'var(--text-lg)', color: 'var(--text-muted)', marginBottom: '0.75rem' }}>No game scheduled today</p>
          {record && <p style={{ fontSize: 'var(--text-base)', fontWeight: 700, marginBottom: '0.5rem' }}>Season Record: {record}</p>}
          {nextGame?.opponent && <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)', marginBottom: '0.25rem' }}>Next: {nextGame.opponent}{nextGame.date ? ` · ${nextGame.date}` : ''}</p>}
          {lastGame?.opponent && <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)', marginBottom: '0.25rem' }}>Last: {lastGame.opponent}{lastGame.result ? ` · ${lastGame.result}` : ''}{lastGame.score ? ` (${lastGame.score})` : ''}</p>}
          <p style={{ fontSize: 'var(--text-sm)', color: 'rgba(255,255,255,0.25)', marginTop: '0.75rem' }}>Scoreboard activates automatically on game day.</p>
        </div>
      </div>
    );
  }

  // ── Upcoming ──
  if (isUpcoming) {
    const dateStr = data.date ? formatDateMMDDYYYY(data.date) : '';
    const isHome = data.home_away === 'home';
    const record = team?.record || '';
    const recentGames = (schedule?.past || []).slice(0, 5);
    return (
      <div>
        <h2 className="view-title" style={{ margin: '0 0 var(--space-md)' }}>
          <Radio size={isMobile ? 20 : 24} color="var(--primary-color)" /> Scoreboard
        </h2>
        <div className="glass-panel" style={{ padding: '2rem', textAlign: 'center' }}>
          <Clock size={40} color="var(--primary-color)" style={{ marginBottom: '1rem' }} />
          <p style={{ fontSize: 'var(--text-lg)', fontWeight: 700, marginBottom: '0.5rem' }}>Game Day</p>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '0.75rem' }}>
            <span className={`home-away-pill ${isHome ? 'home-away-pill--home' : 'home-away-pill--away'}`}>
              {isHome ? <Home size={10} /> : <Plane size={10} />}
              {isHome ? 'HOME' : 'AWAY'}
            </span>
            <span style={{ fontWeight: 700 }}>vs. {data.opponent || 'TBD'}</span>
          </div>
          <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)' }}>{dateStr}{data.time ? ` · ${data.time}` : ''}</p>
          {record && <p style={{ fontSize: 'var(--text-sm)', color: 'var(--primary-color)', fontWeight: 700, marginTop: '0.75rem' }}>Season Record: {record}</p>}
          {recentGames.length > 0 && (
            <div style={{ marginTop: '1rem', display: 'flex', justifyContent: 'center', gap: '0.35rem', flexWrap: 'wrap' }}>
              <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginRight: '0.25rem' }}>Recent:</span>
              {recentGames.map((g, i) => {
                const r = (g.result || '').toUpperCase();
                const bgColor = r === 'W' ? 'rgba(46,160,67,0.2)' : r === 'L' ? 'rgba(218,54,51,0.2)' : r === 'T' ? 'rgba(255,220,120,0.15)' : 'rgba(255,255,255,0.06)';
                const textColor = r === 'W' ? 'var(--success)' : r === 'L' ? 'var(--danger)' : r === 'T' ? 'rgba(255,220,120,0.85)' : 'var(--text-muted)';
                return <span key={i} style={{ background: bgColor, color: textColor, padding: '2px 8px', borderRadius: 4, fontSize: 'var(--text-xs)', fontWeight: 700 }}>{r || '?'} {g.score || ''}</span>;
              })}
            </div>
          )}
          <p style={{ fontSize: 'var(--text-xs)', color: 'rgba(255,255,255,0.3)', marginTop: '1rem' }}>Live scores will appear here once the game starts in GameChanger.</p>
        </div>
      </div>
    );
  }

  // ── Live ──
  if (isLive) {
    return (
      <div>
        <h2 className="view-title" style={{ margin: '0 0 var(--space-md)' }}>
          <Radio size={isMobile ? 20 : 24} color="#ff4444" /> Scoreboard
        </h2>
        <LiveScoreboardPanel
          data={data}
          isMobile={isMobile}
          isLandscape={isLandscape}
          fetchScoreboard={fetchScoreboard}
          lastUpdated={lastUpdated}
          team={team}
        />
      </div>
    );
  }

  // ── Final ──
  const isHome = (data.home_away || '').toLowerCase() === 'home';
  const sharksWinning = (data.sharks_score ?? 0) > (data.opponent_score ?? 0);
  const tied = (data.sharks_score ?? 0) === (data.opponent_score ?? 0);

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: 'var(--space-md)', flexWrap: 'wrap' }}>
        <h2 className="view-title" style={{ margin: 0 }}>
          <Radio size={isMobile ? 20 : 24} color="var(--primary-color)" /> Scoreboard
        </h2>
        {isLive && <LivePulse outdoor={outdoor} />}
        {isFinal && (
          <span style={{
            background: 'rgba(255,255,255,0.08)', color: 'var(--text-muted)',
            padding: '3px 10px', borderRadius: '999px', fontSize: 'var(--text-xs)',
            fontWeight: '800', letterSpacing: '1px',
          }}>FINAL</span>
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          {/* Outdoor / bright-light mode toggle. Persists in localStorage so
              the coach doesn't have to re-enable it every time the app reopens. */}
          <button
            onClick={toggleOutdoor}
            title={outdoor ? 'Disable bright-light mode' : 'Enable bright-light mode (high contrast for outdoor use)'}
            aria-pressed={outdoor}
            aria-label="Toggle bright-light mode"
            style={{
              display: 'flex', alignItems: 'center', gap: '0.3rem',
              background: outdoor ? '#facc15' : 'var(--primary-glow)',
              color: outdoor ? '#000000' : 'var(--primary-color)',
              border: outdoor ? '2px solid #facc15' : '1px solid rgba(4, 101, 104, 0.27)',
              padding: '0.35rem 0.65rem', borderRadius: '6px',
              fontSize: 'var(--text-xs)', fontWeight: '700',
              cursor: 'pointer', minHeight: 'var(--touch-min)', fontFamily: 'inherit',
            }}
          >
            {outdoor ? <Sun size={14} /> : <Eye size={14} />}
            {outdoor ? 'Bright' : 'Dim'}
          </button>
          {data.gc_game_id && (
            <a
              href={`https://web.gc.com/teams/${team?.gc_team_id || 'NuGgx6WvP7TO'}/${team?.gc_season_slug || '2026-spring-sharks'}/schedule/${data.gc_game_id}/plays`}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'flex', alignItems: 'center', gap: '0.3rem',
                background: 'var(--primary-glow)', color: 'var(--primary-color)',
                border: '1px solid rgba(4, 101, 104, 0.27)',
                padding: '0.35rem 0.65rem', borderRadius: '6px',
                fontSize: 'var(--text-xs)', fontWeight: '600',
                textDecoration: 'none', minHeight: 'var(--touch-min)',
              }}
              title="Open in GameChanger"
            >
              <ExternalLink size={12} />
              GC
            </a>
          )}
          <button
            onClick={fetchScoreboard}
            style={{
              display: 'flex', alignItems: 'center', gap: '0.3rem',
              background: 'transparent', border: 'none', color: 'var(--text-muted)',
              cursor: 'pointer', fontSize: 'var(--text-xs)', padding: '0.25rem',
            }}
            title="Refresh scoreboard"
          >
            <RefreshCw size={14} />
          </button>
        </div>
      </div>
      <div className="glass-panel" style={{ padding: isMobile ? 'var(--space-lg)' : '2rem', borderTop: '3px solid var(--primary-color)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
          <span className={`home-away-pill ${isHome ? 'home-away-pill--home' : 'home-away-pill--away'}`}>
            {isHome ? <Home size={10} /> : <Plane size={10} />}
            {isHome ? 'HOME' : 'AWAY'}
          </span>
          <span style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)' }}>
            vs. <strong style={{ color: 'var(--text-main)' }}>{data.opponent || 'Opponent'}</strong>
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '2rem', marginBottom: '1.5rem' }}>
          <ScoreBox label="Sharks" score={data.sharks_score} isUs={true} />
          <Trophy size={24} color="var(--primary-color)" />
          <ScoreBox label={data.opponent || 'Opponent'} score={data.opponent_score} isUs={false} />
        </div>
        <div style={{
          textAlign: 'center', padding: '0.75rem', borderRadius: 8, marginBottom: '1rem',
          background: sharksWinning ? 'rgba(46,160,67,0.1)' : tied ? 'rgba(255,220,120,0.1)' : 'rgba(218,54,51,0.1)',
          border: `1px solid ${sharksWinning ? 'rgba(46,160,67,0.3)' : tied ? 'rgba(255,220,120,0.3)' : 'rgba(218,54,51,0.3)'}`,
        }}>
          <ScoreBox
            label="Sharks"
            score={data.sharks_score}
            isUs={true}
            compact={isLandscape}
            outdoor={outdoor}
          />
          <div style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center',
            color: 'var(--text-muted)', fontSize: 'var(--text-xs)',
          }}>
            {data.inning != null && (
              <>
                {data.inning_half && <InningDiamond half={data.inning_half} />}
                <span style={{ fontWeight: '700', fontSize: 'var(--text-sm)', marginTop: '0.25rem' }}>
                  {data.inning_half === 'top' ? 'Top' : data.inning_half === 'bottom' ? 'Bot' : ''} {data.inning}
                </span>
              </>
            )}
            {!data.inning && isLive && (
              <span style={{ fontWeight: '600' }}>In Progress</span>
            )}
            {isFinal && !data.inning && (
              <Trophy size={20} color="var(--primary-color)" />
            )}
          </div>
          <ScoreBox
            label={data.opponent || 'Opponent'}
            score={data.opponent_score}
            isUs={false}
            compact={isLandscape}
            outdoor={outdoor}
          />
        </div>
        {data.linescore?.length > 0 && (
          <div style={{ overflowX: 'auto', marginBottom: '1rem' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-xs)', textAlign: 'center' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--surface-border)' }}>
                  <th style={{ padding: '0.4rem 0.6rem', textAlign: 'left', color: 'var(--text-muted)' }}>Team</th>
                  {data.linescore[0]?.innings?.map((_, i) => <th key={i} style={{ padding: '0.4rem 0.3rem', color: 'var(--text-muted)', minWidth: 24 }}>{i + 1}</th>)}
                  <th style={{ padding: '0.4rem 0.5rem', color: 'var(--text-muted)', fontWeight: 800 }}>R</th>
                  <th style={{ padding: '0.4rem 0.5rem', color: 'var(--text-muted)' }}>H</th>
                  <th style={{ padding: '0.4rem 0.5rem', color: 'var(--text-muted)' }}>E</th>
                </tr>
              </thead>
              <tbody>
                {data.linescore.map((teamRow, idx) => (
                  <tr key={idx} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', fontWeight: idx === 0 ? 700 : 400 }}>
                    <td style={{ padding: '0.4rem 0.6rem', textAlign: 'left', color: idx === 0 ? 'var(--primary-color)' : 'var(--text-main)' }}>
                      {teamRow.name || (idx === 0 ? 'Sharks' : data.opponent)}
                    </td>
                    {teamRow.innings?.map((runs, i) => <td key={i} style={{ padding: '0.4rem 0.3rem', fontVariantNumeric: 'tabular-nums' }}>{runs ?? '-'}</td>)}
                    <td style={{ padding: '0.4rem 0.5rem', fontWeight: 800, fontVariantNumeric: 'tabular-nums' }}>{teamRow.runs ?? '-'}</td>
                    <td style={{ padding: '0.4rem 0.5rem', fontVariantNumeric: 'tabular-nums' }}>{teamRow.hits ?? '-'}</td>
                    <td style={{ padding: '0.4rem 0.5rem', fontVariantNumeric: 'tabular-nums' }}>{teamRow.errors ?? '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* AT BAT / ON DECK — large high-contrast spray-chart cards.
            Renders for both live games (with current batter from GC events)
            and pre-game scouting (with default top-of-order batters). */}
        <AtBatPanel
          scouting={data.opponent_scouting}
          livePlay={data.live_play}
          outdoor={outdoor}
          isMobile={isMobile}
        />

        {/* Live Play + Opponent Scouting */}
        {isLive && <LivePlayPanel livePlay={data.live_play} />}
        <OpponentScoutPanel
          scouting={data.opponent_scouting}
          livePlay={data.live_play}
          isLandscape={isLandscape}
        />

        {/* Batting Stats */}
        <div style={isLandscape && data.sharks_batting?.length > 0 ? {
          display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', marginTop: '0.5rem',
        } : { marginTop: isLandscape ? '0.5rem' : undefined }}>
          {data.sharks_batting?.length > 0 && (
            <div>
              <h3 style={{ fontSize: 'var(--text-sm)', fontWeight: 700, color: 'var(--primary-color)', marginBottom: '0.5rem', paddingBottom: '0.35rem', borderBottom: '1px solid rgba(4,101,104,0.3)' }}>Sharks Batting</h3>
              {data.sharks_batting.map((p, i) => <BatterRow key={`s-${i}`} player={p} idx={i} compact={isLandscape} />)}
            </div>
          )}
          {data.opponent_batting?.length > 0 && (
            <div style={{ marginTop: isLandscape ? 0 : '1rem' }}>
              <h3 style={{ fontSize: 'var(--text-sm)', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '0.5rem', paddingBottom: '0.35rem', borderBottom: '1px solid rgba(255,255,255,0.1)' }}>{data.opponent || 'Opponent'} Batting</h3>
              {data.opponent_batting.map((p, i) => <BatterRow key={`o-${i}`} player={p} idx={i} compact={isLandscape} />)}
            </div>
          )}
        </div>
        {lastUpdated && (
          <div style={{ marginTop: '1rem', paddingTop: '0.75rem', borderTop: '1px solid rgba(255,255,255,0.05)', fontSize: 'var(--text-xs)', color: 'rgba(255,255,255,0.2)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <RefreshCw size={10} />
            Last updated: {lastUpdated.toLocaleTimeString()}
          </div>
        )}
      </div>
    </div>
  );
};

export default Scoreboard;
