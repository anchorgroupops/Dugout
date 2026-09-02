import React, { useState } from 'react';
import { Settings, ShieldCheck, RefreshCw, Clock, Home, Plane } from 'lucide-react';
import { getTodayEST, formatDateMMDDYYYY } from '../utils/formatDate';
import { apiRequest } from '../utils/apiClient';
import { Tip, TipBadge, TipIcon, PlayerName } from './StatTooltip';
import RosterManager from './RosterManager';

// Was an 8x8px colour-only dot whose only label was a `title`: unreadable on a
// phone (no hover) and indistinguishable for a red/green colour-blind coach.
// TipIcon supplies the tap-to-explain popover, the accessible name and a 44px
// hit area on coarse pointers; the ✓ / ✕ glyph carries the meaning without
// depending on hue at all.
const AvailBadge = ({ available }) => (
  <TipIcon
    text={available ? 'Available tonight' : 'Unavailable tonight'}
    style={{
      width: '18px', height: '18px', borderRadius: '50%', flexShrink: 0,
      background: available ? 'rgba(63, 185, 80, 0.16)' : 'rgba(218, 54, 51, 0.16)',
      border: `1px solid ${available ? 'var(--success)' : 'var(--danger)'}`,
      color: available ? 'var(--success)' : 'var(--danger)',
      fontSize: '11px', fontWeight: 800, lineHeight: 1,
    }}
  >
    {available ? '✓' : '✕'}
  </TipIcon>
);

const slotLabel = (slot) => {
  if (slot === 1) return 'Leadoff';
  if (slot === 2) return 'Table Setter';
  if (slot === 3) return 'Power';
  if (slot === 4) return 'Run Producer';
  return null;
};

const NextGameBanner = ({ schedule }) => {
  if (!schedule) return null;
  const today = getTodayEST();
  const next = schedule.upcoming
    ?.filter(g => g.date >= today)
    ?.sort((a, b) => a.date.localeCompare(b.date))[0];
  if (!next) return null;

  const dateStr = formatDateMMDDYYYY(next.date);
  const isHome = next.home_away === 'home';

  return (
    <div className="glass-panel" style={{
      padding: '0.85rem 1.25rem', marginBottom: '1.25rem',
      borderColor: 'rgba(4, 101, 104, 0.32)', background: 'rgba(4, 101, 104, 0.06)'
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
        <Clock size={16} color="var(--primary-color)" />
        <span className="section-label" style={{ marginBottom: 0 }}>Optimizing For</span>
        <span className={`home-away-pill ${isHome ? 'home-away-pill--home' : 'home-away-pill--away'}`}>
          {isHome ? <Home size={10} /> : <Plane size={10} />}
          {isHome ? 'HOME' : 'AWAY'}
        </span>
        <span style={{ fontWeight: '700', fontSize: 'var(--text-sm)' }}>vs. {next.opponent}</span>
        <span style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)' }}>
          {dateStr}{next.time ? ` \u00b7 ${next.time}` : ''}
        </span>
      </div>
    </div>
  );
};

const Lineup = ({
  team,
  lineupsData,
  availability,
  schedule,
  isMobile = false,
  isLandscape = false,
  onRegenerate,
  onAvailabilityChange,
  onDataRefresh
}) => {
  const [strategy, setStrategy] = useState('balanced');
  const [regenerating, setRegenerating] = useState(false);

  if (!lineupsData) return <p>Loading optimized lineups...</p>;

  const currentStrategy = lineupsData[strategy];
  if (!currentStrategy) return <p>Error loading strategy {strategy}</p>;

  const strategies = [
    { id: 'balanced', label: 'Balanced' },
    { id: 'aggressive', label: 'Aggressive' },
    { id: 'development', label: 'Developmental' }
  ];

  const handleRegenerate = async () => {
    setRegenerating(true);
    try {
      const res = await apiRequest('/api/regenerate-lineups', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ swot: true })
      });
      if (res.ok) {
        const data = await res.json();
        if (data.lineups && onRegenerate) onRegenerate(data.lineups);
        if (onDataRefresh) await onDataRefresh();
      }
    } catch (e) {
      console.error('Regenerate failed', e);
    } finally {
      setRegenerating(false);
    }
  };

  /* Default availability: all core=true Sharks are available */
  const isAvailable = (player) => {
    if (!availability) return player.core !== false;
    const name = `${player.first || ''} ${player.last || ''}`.trim();
    if (availability[name] === undefined) return player.core !== false;
    return availability[name] !== false;
  };

  const fmtStat = (v) => {
    const num = typeof v === 'number' ? v : parseFloat(v) || 0;
    return num > 0 ? num.toFixed(3).replace(/^0/, '') : '\u2014';
  };

  return (
    <div>
      <div style={{ marginBottom: 'var(--space-md)' }}>
        <h2 className="view-title" style={{ margin: 0 }}>
          <Settings size={isMobile ? 20 : 24} color="var(--primary-color)" /> Optimized Lineups
        </h2>
      </div>

      <div
        className="glass-panel"
        data-testid="batting-order-block"
        style={{ padding: isLandscape ? 'var(--space-sm)' : isMobile ? 'var(--space-lg)' : '2rem' }}
      >
        <div style={{ display: 'flex', gap: '0.55rem', alignItems: 'center', flexWrap: 'wrap', width: '100%', marginBottom: isMobile ? '0.85rem' : '1rem' }}>
          {/* Bare `overflowX: auto` gave no hint that "Developmental" was
              off-screen. `.scroll-x` adds momentum scrolling plus a visible
              thin scrollbar, and `--snap` lands a swipe on a whole pill. */}
          <div
            className="scroll-x scroll-x--snap"
            style={{ display: 'flex', gap: '0.4rem', background: 'var(--surface-base)', padding: '0.22rem', borderRadius: '8px', border: '1px solid var(--surface-border)', width: isMobile ? '100%' : 'auto' }}
          >
            {strategies.map(s => (
              <button
                key={s.id}
                onClick={() => setStrategy(s.id)}
                style={{
                  background: strategy === s.id ? 'var(--primary-glow)' : 'transparent',
                  color: strategy === s.id ? 'var(--primary-color)' : 'var(--text-muted)',
                  border: 'none', padding: isMobile ? '0.5rem 0.625rem' : '0.5rem 1rem', borderRadius: '6px',
                  cursor: 'pointer', fontWeight: strategy === s.id ? '600' : '400',
                  transition: 'all var(--transition-fast)', fontSize: isMobile ? 'var(--text-xs)' : 'var(--text-sm)',
                  // Without this the pills compress instead of scrolling, which
                  // is what made the affordance invisible in the first place.
                  whiteSpace: 'nowrap', minHeight: 'var(--touch-min)', flexShrink: 0,
                }}
              >
                {s.label}
              </button>
            ))}
          </div>

          <button
            onClick={handleRegenerate}
            disabled={regenerating}
            style={{
              display: 'flex', alignItems: 'center', gap: '0.4rem',
              background: 'var(--primary-glow)', color: 'var(--primary-color)',
              border: '1px solid rgba(100,200,100,0.3)',
              padding: isMobile ? '0.5rem 0.75rem' : '0.5rem 1rem', borderRadius: '8px',
              cursor: regenerating ? 'not-allowed' : 'pointer',
              fontWeight: '600', fontSize: isMobile ? 'var(--text-xs)' : 'var(--text-sm)',
              opacity: regenerating ? 0.6 : 1,
              transition: 'all var(--transition-fast)',
              minHeight: 'var(--touch-min)',
            }}
          >
            <RefreshCw size={14} className={regenerating ? 'spin-smooth' : ''} />
            {regenerating ? 'Regenerating...' : 'Regenerate'}
          </button>
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: isMobile ? 'flex-start' : 'center', flexDirection: isMobile ? 'column' : 'row', marginBottom: isMobile ? '1rem' : '2rem', paddingBottom: '1rem', borderBottom: '1px solid var(--surface-border)', gap: isMobile ? '0.55rem' : 0 }}>
          <div>
            <h3 style={{ fontSize: isMobile ? 'var(--text-lg)' : '1.5rem', color: 'var(--text-main)' }}>
              Batting Order &middot; {strategy.charAt(0).toUpperCase() + strategy.slice(1)} Strategy
            </h3>
            {!isMobile && (
              <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)', marginTop: '0.25rem' }}>
                Enforces PCLL continuous batting order & mandatory play rules.
              </p>
            )}
          </div>

          {!currentStrategy.compliant && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: '0.5rem',
              background: 'rgba(218, 54, 51, 0.1)',
              color: 'var(--danger)',
              padding: isMobile ? '0.45rem 0.75rem' : '0.5rem 1rem', borderRadius: '20px', fontWeight: '600', fontSize: isMobile ? 'var(--text-xs)' : 'var(--text-sm)',
              border: '1px solid rgba(218, 54, 51, 0.3)'
            }}>
              <ShieldCheck size={isMobile ? 14 : 18} />
              Rule Violation
            </div>
          )}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {(() => {
            // Merge optimizer lineup with any missing core roster players
            const lineupPlayers = [...currentStrategy.lineup];
            if (team?.roster) {
              const lineupNames = new Set(lineupPlayers.map(p =>
                `${p.first || ''} ${p.last || ''}`.trim().toLowerCase()
              ));
              team.roster
                .filter(p => p.core)
                .forEach(p => {
                  const name = `${p.first || ''} ${p.last || ''}`.trim().toLowerCase();
                  if (name && !lineupNames.has(name)) {
                    lineupPlayers.push({ ...p, slot: 999 }); // append at end
                  }
                });
            }
            return lineupPlayers;
          })().sort((a, b) => {
            const aIn = isAvailable(a) ? 0 : 1;
            const bIn = isAvailable(b) ? 0 : 1;
            if (aIn !== bIn) return aIn - bIn;
            // Within each group, borrowed (subs) go after core
            const aSub = a.borrowed ? 1 : 0;
            const bSub = b.borrowed ? 1 : 0;
            if (aSub !== bSub) return aSub - bSub;
            return (a.slot || 99) - (b.slot || 99);
          }).map((player, idx) => {
            const name = `${player.first || ''} ${player.last || ''}`.trim() || player.name || '\u2014';
            const avail = isAvailable(player);
            const hasStats = (player.pa || 0) > 0;
            const roleLabel = slotLabel(idx + 1);
            return (
              <div key={`${player.number}-${idx}`} style={{
                display: 'flex', alignItems: 'center', padding: isLandscape ? '0.4rem 0.6rem' : '0.85rem 1rem',
                background: !avail ? 'rgba(200,50,50,0.08)' : player.borrowed ? 'rgba(63, 143, 136, 0.08)' : 'rgba(0,0,0,0.2)',
                borderRadius: '8px',
                borderLeft: `4px solid ${!avail ? 'var(--danger)' : player.borrowed ? 'rgba(63, 143, 136, 0.42)' : idx < 4 ? 'var(--primary-color)' : 'var(--surface-border)'}`,
                opacity: avail ? 1 : 0.65,
                gap: isMobile ? '0.5rem' : '0.75rem', flexWrap: 'wrap'
              }}>
                <div style={{ width: isMobile ? '20px' : '28px', flexShrink: 0, fontWeight: 'bold', color: 'var(--text-muted)', fontSize: 'var(--text-sm)' }}>{idx + 1}.</div>

                {/* Identity block. The old `minWidth: 100px` floor plus a
                    non-shrinking role pill meant ~236px of hard minimums before
                    the stats even started, so every row broke into 2-3 ragged
                    lines at 360px. `minWidth: 0` lets a long name shrink/wrap
                    inside its own block instead of shoving the row apart. */}
                <div style={{ flex: '1 1 auto', minWidth: isMobile ? 0 : '120px', display: 'flex', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap' }}>
                  <PlayerName name={name} number={player.number} size={isMobile ? 'sm' : 'md'} />
                  <AvailBadge available={avail} />
                  {/* 12px text in 1px of vertical padding is a ~14px chip —
                      unreadable in sunlight. Bumped to 13px with real padding. */}
                  {!player.core && (
                    <span style={{
                      background: 'rgba(63, 143, 136, 0.18)', color: 'var(--accent-sub)',
                      padding: '3px 8px', borderRadius: '5px', fontSize: '13px', lineHeight: 1.2,
                      fontWeight: 'bold', letterSpacing: '1px', border: '1px solid rgba(63, 143, 136, 0.28)'
                    }}>SUB</span>
                  )}
                  {roleLabel && (
                    <span style={{
                      fontSize: '13px', fontWeight: '600', lineHeight: 1.2,
                      color: 'rgba(255,220,120,0.85)',
                      background: 'rgba(255,220,120,0.08)',
                      border: '1px solid rgba(255,220,120,0.18)',
                      padding: '3px 8px', borderRadius: '5px', letterSpacing: '0.3px'
                    }}>{roleLabel}</span>
                  )}
                </div>

                {/* Stats + role pill share one line. The mobile branch used to
                    DROP OBP/SLG/PA rather than show them, so phone users simply
                    lost data; on a phone they now ride a `.scroll-x` line
                    (tap-to-explain TipBadge/Tip intact) that is guaranteed to
                    stay a single row instead of re-wrapping the whole card. */}
                <div
                  className={isMobile ? 'scroll-x' : undefined}
                  style={{
                    display: 'flex', alignItems: 'center', gap: '4px',
                    flexWrap: isMobile ? 'nowrap' : 'wrap',
                    flex: isMobile ? '1 1 100%' : '0 1 auto',
                    minWidth: 0,
                    paddingBottom: isMobile ? '2px' : 0,
                  }}
                >
                  {hasStats ? (
                    <>
                      <TipBadge label="AVG" value={fmtStat(player.avg)} />
                      <TipBadge label="OBP" value={fmtStat(player.obp)} />
                      <TipBadge label="SLG" value={fmtStat(player.slg)} />
                      <Tip label="PA">
                        <span style={{ fontSize: 'var(--text-xs)', color: 'rgba(255,255,255,0.45)', padding: '1px 4px', whiteSpace: 'nowrap' }}>
                          {player.pa} PA
                        </span>
                      </Tip>
                    </>
                  ) : (
                    <span style={{ fontSize: 'var(--text-xs)', color: 'rgba(255,255,255,0.35)', fontStyle: 'italic', whiteSpace: 'nowrap' }}>No stats yet</span>
                  )}

                  {/* The pill was `minWidth: 80px` + `flexShrink: 0`, so it
                      never yielded and pushed the stats onto their own line.
                      On a phone it now shrinks and truncates instead. */}
                  <div style={{
                    background: 'var(--surface-hover)', padding: '0.25rem 0.65rem',
                    borderRadius: '12px', fontSize: 'var(--text-xs)',
                    color: 'var(--text-muted)',
                    minWidth: isMobile ? 0 : '100px', textAlign: 'center',
                    flexShrink: isMobile ? 1 : 0,
                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                  }}>
                    {player.role || 'Depth'}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <NextGameBanner schedule={schedule} />

      <div
        className="glass-panel"
        data-testid="availability-block"
        style={{
          padding: isMobile ? 'var(--space-lg)' : '1.2rem',
          marginTop: '1.75rem',
          borderTop: '3px solid var(--primary-color)',
        }}
      >
        <div style={{ marginBottom: '0.75rem' }}>
          <h3 style={{
            margin: 0,
            fontSize: isMobile ? 'var(--text-lg)' : '1.25rem',
            fontWeight: '700',
            color: 'var(--primary-color)',
            paddingBottom: '0.5rem',
            borderBottom: '2px solid rgba(4, 101, 104, 0.35)',
          }}>
            Game Day Roster
          </h3>
          {!isMobile && (
            <p style={{ margin: '0.5rem 0 0', fontSize: 'var(--text-sm)', color: 'var(--text-muted)' }}>
              Toggle who is in tonight, add subs if needed, and lineups will auto-refresh from live stats.
            </p>
          )}
        </div>
        <RosterManager
          team={team}
          availability={availability}
          onAvailabilityChange={onAvailabilityChange}
          onRosterMutated={onDataRefresh}
          title="Game Day Roster"
          showTitle={false}
          isMobile={isMobile}
        />
      </div>
    </div>
  );
};

export default Lineup;
