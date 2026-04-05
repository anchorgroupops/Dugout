import React, { useState } from 'react';
import { Settings, ShieldCheck, RefreshCw, Clock, Home, Plane } from 'lucide-react';
import { getTodayEST, formatDateMMDDYYYY } from '../utils/formatDate';
import { TipBadge, PlayerName } from './StatTooltip';
import RosterManager from './RosterManager';

const AvailBadge = ({ available }) => (
  <span style={{
    width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0,
    background: available ? 'var(--success)' : 'var(--danger)',
    boxShadow: available ? '0 0 4px var(--success)' : '0 0 4px var(--danger)',
    display: 'inline-block'
  }} title={available ? 'Available' : 'Unavailable'} />
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
      const res = await fetch('/api/regenerate-lineups', {
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
          <div style={{ display: 'flex', gap: '0.4rem', background: 'var(--surface-base)', padding: '0.22rem', borderRadius: '8px', border: '1px solid var(--surface-border)', width: isMobile ? '100%' : 'auto', overflowX: 'auto' }}>
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
                  whiteSpace: 'nowrap', minHeight: 'var(--touch-min)',
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
                .filter(p => p.core !== false && !p.borrowed)
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
                <div style={{ width: isMobile ? '22px' : '28px', fontWeight: 'bold', color: 'var(--text-muted)', fontSize: 'var(--text-sm)' }}>{idx + 1}.</div>

                {/* Name first, then number */}
                <div style={{ flex: 1, minWidth: isMobile ? '100px' : '120px', display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                  <PlayerName name={name} number={player.number} size={isMobile ? 'sm' : 'md'} />
                  <AvailBadge available={avail} />
                  {player.borrowed && (
                    <span style={{
                      background: 'rgba(63, 143, 136, 0.18)', color: 'var(--accent-sub)',
                      padding: '1px 6px', borderRadius: '4px', fontSize: 'var(--text-xs)',
                      fontWeight: 'bold', letterSpacing: '1px', border: '1px solid rgba(63, 143, 136, 0.28)'
                    }}>SUB</span>
                  )}
                  {roleLabel && (
                    <span style={{
                      fontSize: 'var(--text-xs)', fontWeight: '600',
                      color: 'rgba(255,220,120,0.85)',
                      background: 'rgba(255,220,120,0.08)',
                      border: '1px solid rgba(255,220,120,0.18)',
                      padding: '1px 6px', borderRadius: '4px', letterSpacing: '0.3px'
                    }}>{roleLabel}</span>
                  )}
                </div>

                {hasStats ? (
                  isMobile ? (
                    <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
                      AVG {fmtStat(player.avg)} &middot; OPS {fmtStat(player.ops)}
                    </span>
                  ) : (
                    <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                      <TipBadge label="AVG" value={fmtStat(player.avg)} />
                      <TipBadge label="OBP" value={fmtStat(player.obp)} />
                      <TipBadge label="SLG" value={fmtStat(player.slg)} />
                      <span style={{ fontSize: 'var(--text-xs)', color: 'rgba(255,255,255,0.25)', padding: '1px 4px' }}>
                        {player.pa} PA
                      </span>
                    </div>
                  )
                ) : (
                  <span style={{ fontSize: 'var(--text-xs)', color: 'rgba(255,255,255,0.2)', fontStyle: 'italic' }}>No stats yet</span>
                )}

                <div style={{
                  background: 'var(--surface-hover)', padding: '0.25rem 0.65rem',
                  borderRadius: '12px', fontSize: 'var(--text-xs)',
                  color: 'var(--text-muted)',
                  minWidth: isMobile ? '80px' : '100px', textAlign: 'center', flexShrink: 0
                }}>
                  {player.role || 'Depth'}
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
