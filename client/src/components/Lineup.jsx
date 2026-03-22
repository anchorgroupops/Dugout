import React, { useState } from 'react';
import { Settings, ShieldCheck, RefreshCw } from 'lucide-react';

const AvailBadge = ({ available }) => (
  <span style={{
    width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0,
    background: available ? 'var(--success)' : 'var(--danger)',
    boxShadow: available ? '0 0 4px var(--success)' : '0 0 4px var(--danger)',
    display: 'inline-block'
  }} title={available ? 'Available' : 'Unavailable'} />
);

const Lineup = ({ lineupsData, availability, onRegenerate }) => {
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
        body: JSON.stringify({})
      });
      if (res.ok) {
        const data = await res.json();
        if (data.lineups && onRegenerate) onRegenerate(data.lineups);
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
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: '1.5rem', flexWrap: 'wrap', gap: '0.75rem' }}>
        <h2 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', margin: 0 }}>
          <Settings size={24} color="var(--primary-color)" /> Optimized Lineups
        </h2>

        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', gap: '0.5rem', background: 'var(--surface-base)', padding: '0.25rem', borderRadius: '8px', border: '1px solid var(--surface-border)' }}>
            {strategies.map(s => (
              <button
                key={s.id}
                onClick={() => setStrategy(s.id)}
                style={{
                  background: strategy === s.id ? 'var(--primary-glow)' : 'transparent',
                  color: strategy === s.id ? 'var(--primary-color)' : 'var(--text-muted)',
                  border: 'none',
                  padding: '0.5rem 1rem',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontWeight: strategy === s.id ? '600' : '400',
                  transition: 'all var(--transition-fast)'
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
              padding: '0.5rem 1rem', borderRadius: '8px',
              cursor: regenerating ? 'not-allowed' : 'pointer',
              fontWeight: '600', fontSize: '0.85rem',
              opacity: regenerating ? 0.6 : 1,
              transition: 'all var(--transition-fast)'
            }}
          >
            <RefreshCw size={14} style={{ animation: regenerating ? 'spin 1s linear infinite' : 'none' }} />
            {regenerating ? 'Regenerating...' : 'Regenerate'}
          </button>
        </div>
      </div>

      <div className="glass-panel" style={{ padding: '2rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem', paddingBottom: '1rem', borderBottom: '1px solid var(--surface-border)' }}>
          <div>
            <h3 style={{ fontSize: '1.5rem', color: 'var(--text-main)', textTransform: 'capitalize' }}>
              {strategy} Strategy
            </h3>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', marginTop: '0.25rem' }}>
              Enforces PCLL continuous batting order & mandatory play rules.
            </p>
          </div>

          <div style={{
            display: 'flex', alignItems: 'center', gap: '0.5rem',
            background: currentStrategy.compliant ? 'rgba(35, 134, 54, 0.1)' : 'rgba(218, 54, 51, 0.1)',
            color: currentStrategy.compliant ? 'var(--success)' : 'var(--danger)',
            padding: '0.5rem 1rem', borderRadius: '20px', fontWeight: '600', fontSize: '0.9rem',
            border: `1px solid ${currentStrategy.compliant ? 'rgba(35, 134, 54, 0.3)' : 'rgba(218, 54, 51, 0.3)'}`
          }}>
            <ShieldCheck size={18} />
            {currentStrategy.compliant ? 'PCLL Compliant' : 'Rule Violation Detected'}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {currentStrategy.lineup.map((player, idx) => {
            const name = `${player.first || ''} ${player.last || ''}`.trim() || player.name || '—';
            const avail = isAvailable(player);
            return (
              <div key={`${player.number}-${idx}`} style={{
                display: 'flex', alignItems: 'center', padding: '1rem',
                background: !avail ? 'rgba(200,50,50,0.08)' : player.borrowed ? 'rgba(255,165,0,0.04)' : 'rgba(0,0,0,0.2)',
                borderRadius: '8px',
                borderLeft: `4px solid ${!avail ? 'var(--danger)' : player.borrowed ? 'rgba(255,165,0,0.5)' : idx < 4 ? 'var(--primary-color)' : 'var(--surface-border)'}`,
                opacity: avail ? 1 : 0.65
              }}>
                <div style={{ width: '40px', fontWeight: 'bold', color: 'var(--text-muted)' }}>{player.slot}.</div>
                <div style={{ width: '60px', fontFamily: 'var(--font-heading)', fontSize: '1.2rem', color: '#fff' }}>#{player.number}</div>
                <div style={{ flex: 1, fontWeight: '600', fontSize: '1.1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  {name}
                  <AvailBadge available={avail} />
                  {player.borrowed && (
                    <span style={{
                      background: 'rgba(255, 165, 0, 0.2)', color: '#ffa500',
                      padding: '1px 6px', borderRadius: '4px', fontSize: '0.65rem',
                      fontWeight: 'bold', letterSpacing: '1px', border: '1px solid rgba(255,165,0,0.3)'
                    }}>SUB</span>
                  )}
                </div>
                <div style={{
                  background: 'var(--surface-hover)', padding: '0.25rem 0.75rem',
                  borderRadius: '12px', fontSize: '0.85rem', color: 'var(--text-muted)',
                  minWidth: '120px', textAlign: 'center'
                }}>
                  {player.role || 'Depth'}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

export default Lineup;
