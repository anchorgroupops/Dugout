import React, { useState } from 'react';
import { Settings, ShieldCheck, RefreshCw, Clock, Home, Plane } from 'lucide-react';
import { getTodayEST } from '../utils/formatDate';
import RosterManager from './RosterManager';

const StatBadge = ({ label, value, good, warn }) => {
  const num = typeof value === 'number' ? value : parseFloat(value) || 0;
  const color = num >= good ? 'var(--success)' : num >= warn ? 'var(--warning)' : 'var(--text-muted)';
  const display = num > 0 ? num.toFixed(3).replace(/^0/, '') : '—';
  return (
    <span style={{
      fontSize: '0.72rem', fontWeight: '600', color,
      background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
      borderRadius: '4px', padding: '1px 5px', letterSpacing: '0.3px'
    }}>
      {label} {display}
    </span>
  );
};

const AvailBadge = ({ available }) => (
  <span style={{
    width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0,
    background: available ? 'var(--success)' : 'var(--danger)',
    boxShadow: available ? '0 0 4px var(--success)' : '0 0 4px var(--danger)',
    display: 'inline-block'
  }} title={available ? 'Available' : 'Unavailable'} />
);

const NextGameBanner = ({ schedule }) => {
  if (!schedule) return null;
  const today = getTodayEST();
  const next = schedule.upcoming
    ?.filter(g => g.date >= today)
    ?.sort((a, b) => a.date.localeCompare(b.date))[0];
  if (!next) return null;

  const dateStr = new Date(next.date + 'T12:00:00').toLocaleDateString('en-US', {
    timeZone: 'America/New_York', weekday: 'short', month: 'short', day: 'numeric'
  });
  const isHome = next.home_away === 'home';

  return (
    <div className="glass-panel" style={{
      padding: '0.85rem 1.25rem', marginBottom: '1.25rem',
      borderColor: 'rgba(4, 101, 104, 0.32)', background: 'rgba(4, 101, 104, 0.06)'
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
        <Clock size={16} color="var(--primary-color)" />
        <span style={{ fontSize: '0.68rem', color: 'var(--primary-color)', textTransform: 'uppercase', letterSpacing: '1px', fontWeight: '700' }}>
          Optimizing For
        </span>
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: '0.25rem',
          background: isHome ? 'rgba(35,134,54,0.15)' : 'rgba(42, 143, 147, 0.16)',
          color: isHome ? 'var(--success)' : 'var(--accent-away)',
          padding: '2px 8px', borderRadius: '12px', fontSize: '0.68rem', fontWeight: '700'
        }}>
          {isHome ? <Home size={10} /> : <Plane size={10} />}
          {isHome ? 'HOME' : 'AWAY'}
        </span>
        <span style={{ fontWeight: '700', fontSize: '0.95rem' }}>vs. {next.opponent}</span>
        <span style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
          {dateStr}{next.time ? ` · ${next.time}` : ''}
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

  const isAvailable = (player) => {
    if (!availability) return true;
    const name = `${player.first || ''} ${player.last || ''}`.trim();
    return availability[name] !== false;
  };

  return (
    <div>
      <div style={{ marginBottom: '1rem' }}>
        <h2 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', margin: 0 }}>
          <Settings size={isMobile ? 20 : 24} color="var(--primary-color)" /> Optimized Lineups
        </h2>
      </div>

      <div
        className="glass-panel"
        data-testid="batting-order-block"
        style={{ padding: isMobile ? '1rem' : '2rem' }}
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
                  border: 'none', padding: isMobile ? '0.45rem 0.58rem' : '0.5rem 1rem', borderRadius: '6px',
                  cursor: 'pointer', fontWeight: strategy === s.id ? '600' : '400',
                  transition: 'all var(--transition-fast)', fontSize: isMobile ? '0.8rem' : '0.9rem',
                  whiteSpace: 'nowrap'
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
              padding: isMobile ? '0.46rem 0.75rem' : '0.5rem 1rem', borderRadius: '8px',
              cursor: regenerating ? 'not-allowed' : 'pointer',
              fontWeight: '600', fontSize: isMobile ? '0.78rem' : '0.85rem',
              opacity: regenerating ? 0.6 : 1,
              transition: 'all var(--transition-fast)'
            }}
          >
            <RefreshCw size={14} style={{ animation: regenerating ? 'spin 1s linear infinite' : 'none' }} />
            {regenerating ? 'Regenerating...' : 'Regenerate'}
          </button>
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: isMobile ? 'flex-start' : 'center', flexDirection: isMobile ? 'column' : 'row', marginBottom: isMobile ? '1rem' : '2rem', paddingBottom: '1rem', borderBottom: '1px solid var(--surface-border)', gap: isMobile ? '0.55rem' : 0 }}>
          <div>
            <h3 style={{ fontSize: isMobile ? '1.08rem' : '1.5rem', color: 'var(--text-main)', textTransform: 'capitalize' }}>
              Batting Order · {strategy} Strategy
            </h3>
            {!isMobile && (
              <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', marginTop: '0.25rem' }}>
                Enforces PCLL continuous batting order & mandatory play rules.
              </p>
            )}
          </div>

          <div style={{
            display: 'flex', alignItems: 'center', gap: '0.5rem',
            background: currentStrategy.compliant ? 'rgba(35, 134, 54, 0.1)' : 'rgba(218, 54, 51, 0.1)',
            color: currentStrategy.compliant ? 'var(--success)' : 'var(--danger)',
            padding: isMobile ? '0.36rem 0.72rem' : '0.5rem 1rem', borderRadius: '20px', fontWeight: '600', fontSize: isMobile ? '0.78rem' : '0.9rem',
            border: `1px solid ${currentStrategy.compliant ? 'rgba(35, 134, 54, 0.3)' : 'rgba(218, 54, 51, 0.3)'}`
          }}>
            <ShieldCheck size={isMobile ? 14 : 18} />
            {currentStrategy.compliant ? 'PCLL Compliant' : 'Rule Violation'}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {currentStrategy.lineup.map((player, idx) => {
            const name = `${player.first || ''} ${player.last || ''}`.trim() || player.name || '—';
            const avail = isAvailable(player);
            const hasStats = (player.pa || 0) > 0;
            return (
              <div key={`${player.number}-${idx}`} style={{
                display: 'flex', alignItems: 'center', padding: '0.85rem 1rem',
                background: !avail ? 'rgba(200,50,50,0.08)' : player.borrowed ? 'rgba(63, 143, 136, 0.08)' : 'rgba(0,0,0,0.2)',
                borderRadius: '8px',
                borderLeft: `4px solid ${!avail ? 'var(--danger)' : player.borrowed ? 'rgba(63, 143, 136, 0.42)' : idx < 4 ? 'var(--primary-color)' : 'var(--surface-border)'}`,
                opacity: avail ? 1 : 0.65,
                gap: isMobile ? '0.45rem' : '0.75rem', flexWrap: 'wrap'
              }}>
                <div style={{ width: isMobile ? '22px' : '28px', fontWeight: 'bold', color: 'var(--text-muted)', fontSize: isMobile ? '0.82rem' : '0.9rem' }}>{player.slot}.</div>
                <div style={{ width: isMobile ? '42px' : '52px', fontFamily: 'var(--font-heading)', fontSize: isMobile ? '0.98rem' : '1.1rem', color: '#fff' }}>#{player.number}</div>
                <div style={{ flex: 1, minWidth: isMobile ? '100px' : '120px', fontWeight: '600', fontSize: isMobile ? '0.9rem' : '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  {name}
                  <AvailBadge available={avail} />
                  {player.borrowed && (
                    <span style={{
                      background: 'rgba(63, 143, 136, 0.18)', color: 'var(--accent-sub)',
                      padding: '1px 6px', borderRadius: '4px', fontSize: '0.65rem',
                      fontWeight: 'bold', letterSpacing: '1px', border: '1px solid rgba(63, 143, 136, 0.28)'
                    }}>SUB</span>
                  )}
                </div>

                {/* Per-player stat badges */}
                {hasStats ? (
                  isMobile ? (
                    <span style={{ fontSize: '0.74rem', color: 'var(--text-muted)' }}>
                      AVG {typeof player.avg === 'number' ? player.avg.toFixed(3).replace(/^0/, '') : '—'} · OPS {typeof player.ops === 'number' ? player.ops.toFixed(3).replace(/^0/, '') : '—'}
                    </span>
                  ) : (
                    <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                      <StatBadge label="AVG" value={player.avg} good={0.350} warn={0.200} />
                      <StatBadge label="OBP" value={player.obp} good={0.420} warn={0.280} />
                      <StatBadge label="SLG" value={player.slg} good={0.450} warn={0.250} />
                      <span style={{ fontSize: '0.72rem', color: 'rgba(255,255,255,0.25)', padding: '1px 4px' }}>
                        {player.pa} PA
                      </span>
                    </div>
                  )
                ) : (
                  <span style={{ fontSize: '0.72rem', color: 'rgba(255,255,255,0.2)', fontStyle: 'italic' }}>No stats yet</span>
                )}

                <div style={{
                  background: 'var(--surface-hover)', padding: '0.2rem 0.65rem',
                  borderRadius: '12px', fontSize: isMobile ? '0.72rem' : '0.8rem', color: 'var(--text-muted)',
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
        style={{ padding: isMobile ? '0.9rem' : '1.2rem', marginTop: '1.25rem' }}
      >
        <div style={{ marginBottom: '0.75rem' }}>
          <h3 style={{ margin: 0, fontSize: '1rem', color: 'var(--primary-color)' }}>
            Game-Day Availability & Borrowed Players
          </h3>
          {!isMobile && (
            <p style={{ margin: '0.35rem 0 0', fontSize: '0.84rem', color: 'var(--text-muted)' }}>
              Toggle who is in tonight, add subs if needed, and lineups will auto-refresh from live stats.
            </p>
          )}
        </div>
        <RosterManager
          team={team}
          availability={availability}
          onAvailabilityChange={onAvailabilityChange}
          onRosterMutated={onDataRefresh}
          title="Game-Day Availability"
          showTitle={false}
          isMobile={isMobile}
        />
      </div>
    </div>
  );
};

export default Lineup;
