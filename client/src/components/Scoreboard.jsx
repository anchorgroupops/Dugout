import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Radio, Home, Plane, Clock, Trophy, RefreshCw, ExternalLink, Shield, AlertTriangle, ChevronDown, ChevronUp } from 'lucide-react';
import { formatDateMMDDYYYY } from '../utils/formatDate';
import { PlayerName } from './StatTooltip';

const POLL_INTERVAL_LIVE = 15000;  // 15s when live
const POLL_INTERVAL_IDLE = 60000;  // 60s when not live

const InningDiamond = ({ half }) => {
  const isTop = half === 'top';
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" style={{ verticalAlign: 'middle' }}>
      <polygon
        points="8,1 15,8 8,15 1,8"
        fill="none"
        stroke="var(--text-muted)"
        strokeWidth="1.5"
      />
      <polygon
        points={isTop ? "8,2 14,8 8,8 2,8" : "8,8 14,8 8,14 2,8"}
        fill="var(--primary-color)"
        opacity="0.8"
      />
    </svg>
  );
};

const LivePulse = () => (
  <span style={{
    display: 'inline-flex', alignItems: 'center', gap: '0.35rem',
    background: 'rgba(218, 54, 51, 0.15)', color: '#ff4444',
    padding: '3px 10px', borderRadius: '999px', fontSize: 'var(--text-xs)',
    fontWeight: '800', letterSpacing: '1px', border: '1px solid rgba(218, 54, 51, 0.3)',
  }}>
    <span className="live-pulse-dot" />
    LIVE
  </span>
);

const ScoreBox = ({ label, score, isUs, compact = false }) => (
  <div style={{
    display: 'flex', flexDirection: 'column', alignItems: 'center',
    padding: compact ? '0.4rem 0.75rem' : '0.75rem 1.5rem', borderRadius: compact ? '8px' : '12px',
    background: isUs ? 'rgba(4, 101, 104, 0.12)' : 'rgba(255,255,255,0.04)',
    border: `2px solid ${isUs ? 'rgba(4, 101, 104, 0.4)' : 'rgba(255,255,255,0.08)'}`,
    minWidth: compact ? '70px' : '100px', transition: 'all 0.3s ease',
    flex: compact ? 1 : undefined, maxWidth: compact ? '120px' : undefined,
  }}>
    <span style={{
      fontSize: compact ? '0.6rem' : 'var(--text-xs)', fontWeight: '700', color: 'var(--text-muted)',
      textTransform: 'uppercase', letterSpacing: '1px', marginBottom: compact ? '0.1rem' : '0.25rem',
      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '100%',
    }}>{label}</span>
    <span style={{
      fontSize: compact ? 'clamp(1.5rem, 6vw, 2.5rem)' : 'clamp(2rem, 8vw, 3.5rem)', fontWeight: '900',
      color: isUs ? 'var(--primary-color)' : 'var(--text-main)',
      lineHeight: 1, fontVariantNumeric: 'tabular-nums',
    }}>{score ?? '-'}</span>
  </div>
);

const BatterRow = ({ player, idx, compact = false }) => {
  const b = player.batting || player;
  const name = player.name || player.player || '\u2014';
  const number = player.number;
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: compact ? '0.3rem' : '0.5rem',
      padding: compact ? '0.25rem 0.4rem' : '0.4rem 0.6rem', borderRadius: '6px',
      background: idx % 2 === 0 ? 'rgba(0,0,0,0.15)' : 'rgba(0,0,0,0.08)',
      fontSize: compact ? '0.65rem' : undefined,
    }}>
      <span style={{ width: compact ? '16px' : '20px', fontSize: compact ? '0.6rem' : 'var(--text-xs)', color: 'var(--text-muted)', textAlign: 'right' }}>{idx + 1}</span>
      <div style={{ flex: 1, minWidth: compact ? '60px' : '80px' }}>
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


// ─── Mini Spray Chart (compact SVG for live view) ─────────────────────
const ZONE_POLYS = [
  { id: 'lf',  points: '10,10 55,10 70,80 10,90' },
  { id: 'lc',  points: '55,10 100,5 100,70 70,80' },
  { id: 'cf',  points: '100,5 145,10 130,70 100,70' },
  { id: 'rc',  points: '145,10 190,10 190,80 130,70' },
  { id: 'rf',  points: '190,10 190,90 130,80 145,10' },
  { id: 'if3', points: '10,90 70,80 75,130 40,140' },
  { id: 'ifm', points: '70,80 130,80 120,130 80,130' },
  { id: 'if1', points: '130,80 190,90 160,140 120,130' },
];

const MiniSprayChart = ({ zones, size = 100 }) => {
  if (!zones) return null;
  return (
    <svg width={size} height={size * 0.85} viewBox="0 0 200 170" style={{ display: 'block' }}>
      <rect width="200" height="170" fill="rgba(0,80,0,0.15)" rx="8" />
      {ZONE_POLYS.map(z => {
        const weight = zones[z.id] || 0;
        const r = Math.round(255 * weight);
        const g = Math.round(60 * (1 - weight));
        const opacity = 0.15 + weight * 0.65;
        return (
          <polygon
            key={z.id}
            points={z.points}
            fill={`rgba(${r}, ${g}, 30, ${opacity})`}
            stroke="rgba(255,255,255,0.15)"
            strokeWidth="1"
          />
        );
      })}
      {/* Diamond */}
      <polygon points="100,155 115,140 100,125 85,140" fill="none" stroke="rgba(255,255,255,0.3)" strokeWidth="1.5" />
      <circle cx="100" cy="155" r="3" fill="var(--primary-color)" opacity="0.8" />
    </svg>
  );
};

const DangerBadge = ({ danger }) => {
  const color = danger >= 70 ? 'var(--danger)' : danger >= 40 ? 'var(--warning)' : 'var(--success)';
  const label = danger >= 70 ? 'HIGH' : danger >= 40 ? 'MED' : 'LOW';
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: '0.2rem',
      background: `${color}22`, color, padding: '2px 8px', borderRadius: '4px',
      fontSize: '0.6rem', fontWeight: '800', letterSpacing: '0.5px',
      border: `1px solid ${color}44`,
    }}>
      {danger >= 70 && <AlertTriangle size={9} />}
      {label} {danger}
    </span>
  );
};

const ScoutingCard = ({ player, expanded, onToggle, compact = false }) => {
  if (!player) return null;
  const fmtAvg = (v) => v != null ? (v < 1 ? `.${String(v).split('.')[1] || '000'}` : v.toFixed(3)) : '—';
  return (
    <div style={{
      background: 'rgba(0,0,0,0.2)', borderRadius: '8px', overflow: 'hidden',
      border: `1px solid ${player.danger >= 70 ? 'rgba(179,74,57,0.3)' : 'rgba(255,255,255,0.06)'}`,
    }}>
      <button
        onClick={onToggle}
        style={{
          display: 'flex', alignItems: 'center', gap: '0.5rem', width: '100%',
          padding: compact ? '0.35rem 0.5rem' : '0.5rem 0.75rem', background: 'none', border: 'none',
          color: 'var(--text-main)', cursor: 'pointer', fontFamily: 'var(--font-base)',
          fontSize: compact ? '0.7rem' : '0.8rem', textAlign: 'left',
        }}
      >
        <span style={{ fontWeight: '800', color: 'var(--text-muted)', minWidth: '28px' }}>
          #{player.number || '?'}
        </span>
        <span style={{ flex: 1, fontWeight: '600' }}>{player.name}</span>
        <DangerBadge danger={player.danger} />
        {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>
      {expanded && (
        <div style={{ padding: '0.5rem 0.75rem', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'flex-start', flexWrap: 'wrap' }}>
            <MiniSprayChart zones={player.zones} size={compact ? 80 : 110} />
            <div style={{ flex: 1, minWidth: '120px' }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem', marginBottom: '0.4rem' }}>
                {(player.tags || []).map(t => (
                  <span key={t} style={{
                    background: 'rgba(130,203,195,0.12)', color: 'var(--primary-color)',
                    padding: '1px 6px', borderRadius: '3px', fontSize: '0.6rem', fontWeight: '700',
                  }}>{t}</span>
                ))}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.2rem', fontSize: '0.65rem' }}>
                <span style={{ color: 'var(--text-muted)' }}>AVG <strong style={{ color: 'var(--text-main)' }}>{fmtAvg(player.avg)}</strong></span>
                <span style={{ color: 'var(--text-muted)' }}>SLG <strong style={{ color: 'var(--text-main)' }}>{fmtAvg(player.slg)}</strong></span>
                <span style={{ color: 'var(--text-muted)' }}>OBP <strong style={{ color: 'var(--text-main)' }}>{fmtAvg(player.obp)}</strong></span>
                <span style={{ color: 'var(--text-muted)' }}>H <strong style={{ color: 'var(--text-main)' }}>{player.h ?? '—'}</strong></span>
                <span style={{ color: 'var(--text-muted)' }}>HR <strong style={{ color: 'var(--text-main)' }}>{player.hr ?? '—'}</strong></span>
                <span style={{ color: 'var(--text-muted)' }}>BB <strong style={{ color: 'var(--text-main)' }}>{player.bb ?? '—'}</strong></span>
                <span style={{ color: 'var(--text-muted)' }}>SO <strong style={{ color: 'var(--text-main)' }}>{player.so ?? '—'}</strong></span>
                <span style={{ color: 'var(--text-muted)' }}>SB <strong style={{ color: 'var(--text-main)' }}>{player.sb ?? '—'}</strong></span>
                <span style={{ color: 'var(--text-muted)' }}>PA <strong style={{ color: 'var(--text-main)' }}>{player.pa ?? '—'}</strong></span>
              </div>
            </div>
          </div>
        </div>
      )}
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

const OpponentScoutPanel = React.memo(({ scouting, livePlay, isLandscape }) => {
  const [expandedPlayer, setExpandedPlayer] = useState(null);
  const [showAll, setShowAll] = useState(false);

  if (!scouting?.has_data) return null;

  const players = scouting.players || [];
  // If we know the current batter, highlight them
  const currentBatterNum = livePlay?.current_batter?.number;
  const currentBatterName = livePlay?.current_batter?.name?.toLowerCase();

  // Auto-expand current batter
  const highlightIdx = players.findIndex(p =>
    (currentBatterNum && p.number === currentBatterNum) ||
    (currentBatterName && p.name.toLowerCase() === currentBatterName)
  );

  const displayPlayers = showAll ? players : players.slice(0, 5);

  return (
    <div style={{ marginTop: '1rem' }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: '0.5rem',
        marginBottom: '0.5rem', paddingBottom: '0.35rem',
        borderBottom: '1px solid rgba(179, 74, 57, 0.3)',
      }}>
        <Shield size={14} color="var(--danger)" />
        <h3 style={{ fontSize: 'var(--text-sm)', fontWeight: '700', color: 'var(--danger)', margin: 0 }}>
          Opponent Scouting
        </h3>
        <span style={{ fontSize: '0.6rem', color: 'var(--text-muted)', marginLeft: 'auto' }}>
          {players.length} batter{players.length !== 1 ? 's' : ''}
        </span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
        {displayPlayers.map((p, i) => {
          const isCurrentBatter = i === highlightIdx;
          return (
            <div key={p.number || i} style={isCurrentBatter ? { border: '1px solid rgba(255,68,68,0.4)', borderRadius: '8px' } : {}}>
              {isCurrentBatter && (
                <div style={{
                  fontSize: '0.55rem', fontWeight: '800', color: '#ff4444',
                  textTransform: 'uppercase', letterSpacing: '1px', padding: '3px 8px',
                  background: 'rgba(255,68,68,0.1)',
                  borderRadius: '8px 8px 0 0',
                }}>
                  AT BAT
                </div>
              )}
              <ScoutingCard
                player={p}
                expanded={expandedPlayer === i || isCurrentBatter}
                onToggle={() => setExpandedPlayer(expandedPlayer === i ? null : i)}
                compact={isLandscape}
              />
            </div>
          );
        })}
      </div>
      {players.length > 5 && (
        <button
          onClick={() => setShowAll(!showAll)}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.3rem',
            width: '100%', marginTop: '0.4rem', padding: '0.4rem',
            background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: '6px', color: 'var(--text-muted)', fontSize: '0.7rem',
            fontWeight: '600', cursor: 'pointer', fontFamily: 'var(--font-base)',
          }}
        >
          {showAll ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          {showAll ? 'Show top 5' : `Show all ${players.length}`}
        </button>
      )}
    </div>
  );
});

const Scoreboard = ({ isMobile = false, isLandscape = false, team, schedule }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [lastUpdated, setLastUpdated] = useState(null);
  const timerRef = useRef(null);
  const mountedRef = useRef(true);

  const fetchScoreboard = useCallback(async () => {
    try {
      const res = await fetch('/api/scoreboard');
      if (!res.ok) throw new Error('Scoreboard unavailable');
      const json = await res.json();
      if (mountedRef.current) {
        setData(json);
        setError('');
        setLastUpdated(new Date());
      }
    } catch (e) {
      if (mountedRef.current) {
        setError(e.message || 'Failed to load scoreboard');
      }
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    fetchScoreboard();
    return () => { mountedRef.current = false; };
  }, [fetchScoreboard]);

  // Adaptive polling: faster when live
  useEffect(() => {
    const interval = data?.status === 'live' ? POLL_INTERVAL_LIVE : POLL_INTERVAL_IDLE;
    timerRef.current = setInterval(fetchScoreboard, interval);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [data?.status, fetchScoreboard]);

  if (loading) return <div className="loader"></div>;

  if (error && !data) {
    return (
      <div className="glass-panel" style={{ padding: '2rem', textAlign: 'center' }}>
        <p style={{ color: 'var(--danger)' }}>{error}</p>
        <button
          onClick={fetchScoreboard}
          style={{
            marginTop: '1rem', background: 'var(--primary-glow)', color: 'var(--primary-color)',
            border: '1px solid rgba(4, 101, 104, 0.27)', padding: '0.5rem 1rem',
            borderRadius: '8px', cursor: 'pointer', fontWeight: '600',
          }}
        >Retry</button>
      </div>
    );
  }

  const status = data?.status || 'no_game';
  const isLive = status === 'live';
  const isFinal = status === 'final';
  const isUpcoming = status === 'upcoming' || status === 'pregame';
  const isNoGame = status === 'no_game';

  // Upcoming / no game state
  if (isNoGame) {
    const record = team?.record || '';
    const today = new Date().toISOString().slice(0, 10);
    const nextGame = (schedule?.upcoming || [])
      .filter(g => g.date >= today)
      .sort((a, b) => a.date.localeCompare(b.date))[0];
    const lastGame = (schedule?.past || [])
      .sort((a, b) => (b.date || '').localeCompare(a.date || ''))[0];
    return (
      <div>
        <h2 className="view-title" style={{ margin: '0 0 var(--space-md)' }}>
          <Radio size={isMobile ? 20 : 24} color="var(--primary-color)" /> Scoreboard
        </h2>
        <div className="glass-panel" style={{ padding: '2rem', textAlign: 'center' }}>
          <Clock size={40} color="var(--text-muted)" style={{ marginBottom: '1rem', opacity: 0.5 }} />
          <p style={{ fontSize: 'var(--text-lg)', color: 'var(--text-muted)', marginBottom: '0.75rem' }}>
            No game scheduled today
          </p>
          {record && (
            <p style={{ fontSize: 'var(--text-base)', fontWeight: '700', marginBottom: '0.5rem' }}>
              Season Record: {record}
            </p>
          )}
          {nextGame?.opponent && (
            <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)', marginBottom: '0.25rem' }}>
              Next: {nextGame.opponent}{nextGame.date ? ` · ${nextGame.date}` : ''}
            </p>
          )}
          {lastGame?.opponent && (
            <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)', marginBottom: '0.25rem' }}>
              Last: {lastGame.opponent}{lastGame.result ? ` · ${lastGame.result}` : ''}{lastGame.score ? ` (${lastGame.score})` : ''}
            </p>
          )}
          <p style={{ fontSize: 'var(--text-sm)', color: 'rgba(255,255,255,0.25)', marginTop: '0.75rem' }}>
            Scoreboard activates automatically on game day.
          </p>
        </div>
      </div>
    );
  }

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
          <p style={{ fontSize: 'var(--text-lg)', fontWeight: '700', marginBottom: '0.5rem' }}>
            Game Day
          </p>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '0.75rem' }}>
            <span className={`home-away-pill ${isHome ? 'home-away-pill--home' : 'home-away-pill--away'}`}>
              {isHome ? <Home size={10} /> : <Plane size={10} />}
              {isHome ? 'HOME' : 'AWAY'}
            </span>
            <span style={{ fontWeight: '700' }}>vs. {data.opponent || 'TBD'}</span>
          </div>
          <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)' }}>
            {dateStr}{data.time ? ` \u00b7 ${data.time}` : ''}
          </p>
          {record && (
            <p style={{ fontSize: 'var(--text-sm)', color: 'var(--primary-color)', fontWeight: '700', marginTop: '0.75rem' }}>
              Season Record: {record}
            </p>
          )}
          {recentGames.length > 0 && (
            <div style={{ marginTop: '1rem', display: 'flex', justifyContent: 'center', gap: '0.35rem', flexWrap: 'wrap' }}>
              <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginRight: '0.25rem' }}>Recent:</span>
              {recentGames.map((g, i) => {
                const r = (g.result || '').toUpperCase();
                const bgColor = r === 'W' ? 'rgba(46, 160, 67, 0.2)' : r === 'L' ? 'rgba(218, 54, 51, 0.2)' : r === 'T' ? 'rgba(255,220,120,0.15)' : 'rgba(255,255,255,0.06)';
                const textColor = r === 'W' ? 'var(--success)' : r === 'L' ? 'var(--danger)' : r === 'T' ? 'rgba(255,220,120,0.85)' : 'var(--text-muted)';
                return (
                  <span key={i} style={{
                    background: bgColor, color: textColor,
                    padding: '2px 8px', borderRadius: '4px',
                    fontSize: 'var(--text-xs)', fontWeight: '700',
                  }}>{r || '?'} {g.score || ''}</span>
                );
              })}
            </div>
          )}
          <p style={{ fontSize: 'var(--text-xs)', color: 'rgba(255,255,255,0.3)', marginTop: '1rem' }}>
            Live scores will appear here once the game starts in GameChanger.
          </p>
        </div>
      </div>
    );
  }

  // Live or Final game
  const isHome = (data.home_away || '').toLowerCase() === 'home';
  const sharksWinning = (data.sharks_score ?? 0) > (data.opponent_score ?? 0);
  const tied = (data.sharks_score ?? 0) === (data.opponent_score ?? 0);

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: 'var(--space-md)', flexWrap: 'wrap' }}>
        <h2 className="view-title" style={{ margin: 0 }}>
          <Radio size={isMobile ? 20 : 24} color={isLive ? '#ff4444' : 'var(--primary-color)'} /> Scoreboard
        </h2>
        {isLive && <LivePulse />}
        {isFinal && (
          <span style={{
            background: 'rgba(255,255,255,0.08)', color: 'var(--text-muted)',
            padding: '3px 10px', borderRadius: '999px', fontSize: 'var(--text-xs)',
            fontWeight: '800', letterSpacing: '1px',
          }}>FINAL</span>
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
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

      {/* Main Scoreboard Card */}
      <div className="glass-panel" style={{
        padding: isLandscape ? 'var(--space-sm)' : isMobile ? 'var(--space-lg)' : '2rem',
        borderTop: isLive ? '3px solid #ff4444' : isFinal ? '3px solid var(--primary-color)' : 'none',
      }}>
        {/* Matchup Header */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          gap: '0.5rem', marginBottom: isLandscape ? '0.5rem' : '1.5rem', flexWrap: 'wrap',
        }}>
          <span className={`home-away-pill ${isHome ? 'home-away-pill--home' : 'home-away-pill--away'}`}>
            {isHome ? <Home size={10} /> : <Plane size={10} />}
            {isHome ? 'HOME' : 'AWAY'}
          </span>
          <span style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)' }}>
            vs. <strong style={{ color: 'var(--text-main)' }}>{data.opponent || 'Opponent'}</strong>
          </span>
          {data.scheduled_time && (
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
              \u00b7 {data.scheduled_time}
            </span>
          )}
        </div>

        {/* Score Display */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          gap: isLandscape ? '0.75rem' : isMobile ? '1rem' : '2rem',
          marginBottom: isLandscape ? '0.75rem' : '1.5rem',
        }}>
          <ScoreBox
            label="Sharks"
            score={data.sharks_score}
            isUs={true}
            compact={isLandscape}
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
          />
        </div>

        {/* Game Result Banner */}
        {isFinal && (
          <div style={{
            textAlign: 'center', padding: '0.75rem',
            borderRadius: '8px', marginBottom: '1rem',
            background: sharksWinning ? 'rgba(46, 160, 67, 0.1)' : tied ? 'rgba(255,220,120,0.1)' : 'rgba(218, 54, 51, 0.1)',
            border: `1px solid ${sharksWinning ? 'rgba(46, 160, 67, 0.3)' : tied ? 'rgba(255,220,120,0.3)' : 'rgba(218, 54, 51, 0.3)'}`,
          }}>
            <span style={{
              fontWeight: '800', fontSize: 'var(--text-lg)',
              color: sharksWinning ? 'var(--success)' : tied ? 'rgba(255,220,120,0.85)' : 'var(--danger)',
            }}>
              {sharksWinning ? 'VICTORY!' : tied ? 'TIE GAME' : 'DEFEAT'}
            </span>
          </div>
        )}

        {/* Linescore Table (if available) */}
        {data.linescore && Array.isArray(data.linescore) && data.linescore.length > 0 && (
          <div style={{ overflowX: 'auto', marginBottom: '1rem' }}>
            <table style={{
              width: '100%', borderCollapse: 'collapse', fontSize: 'var(--text-xs)',
              textAlign: 'center',
            }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--surface-border)' }}>
                  <th style={{ padding: '0.4rem 0.6rem', textAlign: 'left', color: 'var(--text-muted)' }}>Team</th>
                  {data.linescore[0]?.innings?.map((_, i) => (
                    <th key={i} style={{ padding: '0.4rem 0.3rem', color: 'var(--text-muted)', minWidth: '24px' }}>{i + 1}</th>
                  ))}
                  <th style={{ padding: '0.4rem 0.5rem', color: 'var(--text-muted)', fontWeight: '800' }}>R</th>
                  <th style={{ padding: '0.4rem 0.5rem', color: 'var(--text-muted)' }}>H</th>
                  <th style={{ padding: '0.4rem 0.5rem', color: 'var(--text-muted)' }}>E</th>
                </tr>
              </thead>
              <tbody>
                {data.linescore.map((team, idx) => (
                  <tr key={idx} style={{
                    borderBottom: '1px solid rgba(255,255,255,0.05)',
                    fontWeight: idx === 0 ? '700' : '400',
                  }}>
                    <td style={{
                      padding: '0.4rem 0.6rem', textAlign: 'left',
                      color: idx === 0 ? 'var(--primary-color)' : 'var(--text-main)',
                    }}>
                      {team.name || (idx === 0 ? 'Sharks' : data.opponent)}
                    </td>
                    {team.innings?.map((runs, i) => (
                      <td key={i} style={{ padding: '0.4rem 0.3rem', fontVariantNumeric: 'tabular-nums' }}>
                        {runs ?? '-'}
                      </td>
                    ))}
                    <td style={{ padding: '0.4rem 0.5rem', fontWeight: '800', fontVariantNumeric: 'tabular-nums' }}>{team.runs ?? '-'}</td>
                    <td style={{ padding: '0.4rem 0.5rem', fontVariantNumeric: 'tabular-nums' }}>{team.hits ?? '-'}</td>
                    <td style={{ padding: '0.4rem 0.5rem', fontVariantNumeric: 'tabular-nums' }}>{team.errors ?? '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

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
            <div style={{ marginTop: isLandscape ? 0 : '1rem' }}>
              <h3 style={{
                fontSize: isLandscape ? '0.7rem' : 'var(--text-sm)', fontWeight: '700', color: 'var(--primary-color)',
                marginBottom: isLandscape ? '0.25rem' : '0.5rem', paddingBottom: '0.35rem',
                borderBottom: '1px solid rgba(4, 101, 104, 0.3)',
              }}>Sharks Batting</h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: isLandscape ? '1px' : '2px' }}>
                {data.sharks_batting.map((p, i) => (
                  <BatterRow key={`s-${i}`} player={p} idx={i} compact={isLandscape} />
                ))}
              </div>
            </div>
          )}

          {data.opponent_batting?.length > 0 && (
            <div style={{ marginTop: isLandscape ? 0 : '1rem' }}>
              <h3 style={{
                fontSize: isLandscape ? '0.7rem' : 'var(--text-sm)', fontWeight: '700', color: 'var(--text-muted)',
                marginBottom: isLandscape ? '0.25rem' : '0.5rem', paddingBottom: '0.35rem',
                borderBottom: '1px solid rgba(255,255,255,0.1)',
              }}>{data.opponent || 'Opponent'} Batting</h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: isLandscape ? '1px' : '2px' }}>
                {data.opponent_batting.map((p, i) => (
                  <BatterRow key={`o-${i}`} player={p} idx={i} compact={isLandscape} />
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Last Updated */}
        {lastUpdated && (
          <div style={{
            marginTop: '1rem', paddingTop: '0.75rem',
            borderTop: '1px solid rgba(255,255,255,0.05)',
            fontSize: 'var(--text-xs)', color: 'rgba(255,255,255,0.2)',
            display: 'flex', alignItems: 'center', gap: '0.5rem',
          }}>
            <RefreshCw size={10} />
            Last updated: {lastUpdated.toLocaleTimeString()}
            {isLive && <span> \u00b7 Auto-refreshing every 15s</span>}
          </div>
        )}
      </div>
    </div>
  );
};

export default Scoreboard;
