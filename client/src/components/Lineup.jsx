import React, { useState } from 'react';
import { Settings, ShieldCheck } from 'lucide-react';

const Lineup = ({ lineupsData }) => {
  const [strategy, setStrategy] = useState('balanced');
  
  if (!lineupsData) return <p>Loading optimized lineups...</p>;

  const currentStrategy = lineupsData[strategy];
  if (!currentStrategy) return <p>Error loading strategy {strategy}</p>;

  const strategies = [
    { id: 'balanced', label: 'Balanced (Standard)' },
    { id: 'aggressive', label: 'Aggressive (Power)' },
    { id: 'development', label: 'Developmental' }
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: '1.5rem' }}>
        <h2 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', margin: 0 }}>
          <Settings size={24} color="var(--primary-color)" /> Optimized Lineups
        </h2>
        
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
            display: 'flex', 
            alignItems: 'center', 
            gap: '0.5rem',
            background: currentStrategy.compliant ? 'rgba(35, 134, 54, 0.1)' : 'rgba(218, 54, 51, 0.1)',
            color: currentStrategy.compliant ? 'var(--success)' : 'var(--danger)',
            padding: '0.5rem 1rem',
            borderRadius: '20px',
            fontWeight: '600',
            fontSize: '0.9rem',
            border: `1px solid ${currentStrategy.compliant ? 'rgba(35, 134, 54, 0.3)' : 'rgba(218, 54, 51, 0.3)'}`
          }}>
            <ShieldCheck size={18} />
            {currentStrategy.compliant ? 'PCLL Compliant' : 'Rule Violation Detected'}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {currentStrategy.lineup.map((player, idx) => (
            <div key={`${player.number}-${idx}`} style={{
              display: 'flex',
              alignItems: 'center',
              padding: '1rem',
              background: 'rgba(0,0,0,0.2)',
              borderRadius: '8px',
              borderLeft: `4px solid ${idx < 4 ? 'var(--primary-color)' : 'var(--surface-border)'}`
            }}>
              <div style={{ width: '40px', fontWeight: 'bold', color: 'var(--text-muted)' }}>{player.slot}.</div>
              <div style={{ width: '60px', fontFamily: 'var(--font-heading)', fontSize: '1.2rem', color: '#fff' }}>#{player.number}</div>
              <div style={{ flex: 1, fontWeight: '600', fontSize: '1.1rem' }}>
                {player.first} {player.last}
              </div>
              <div style={{ 
                background: 'var(--surface-hover)', 
                padding: '0.25rem 0.75rem', 
                borderRadius: '12px', 
                fontSize: '0.85rem',
                color: 'var(--text-muted)',
                minWidth: '120px',
                textAlign: 'center'
              }}>
                {player.role || 'Depth'}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default Lineup;
