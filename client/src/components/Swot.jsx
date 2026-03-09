import React from 'react';
import { AlertTriangle, TrendingUp, ShieldAlert, Target } from 'lucide-react';

const Swot = ({ swotData, roster }) => {
  if (!swotData) return <p>Loading SWOT Analysis...</p>;

  // Combine player objects with their SWOT evaluations
  const playersWithSwot = (roster || []).map(player => {
    const evaluation = swotData.player_evaluations?.find(e => e.recent_game?.number === player.number || e.name === player.first);
    return { ...player, swot: evaluation };
  }).filter(p => p.swot);

  return (
    <div>
      <h2 style={{ marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <Target size={24} color="var(--primary-color)" /> SWOT Analysis
      </h2>
      
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(350px, 1fr))',
        gap: '1.5rem'
      }}>
        {playersWithSwot.map(player => (
          <div key={`${player.number}-${player.last}`} className="glass-panel" style={{ padding: '1.5rem' }}>
            <h3 style={{ fontSize: '1.2rem', marginBottom: '1rem', borderBottom: '1px solid var(--surface-border)', paddingBottom: '0.5rem' }}>
              #{player.number} {player.first} {player.last}
            </h3>
            
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              {/* Strengths */}
              <div>
                <h4 style={{ color: 'var(--success)', display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.9rem', marginBottom: '0.25rem' }}>
                  <TrendingUp size={16} /> Strengths
                </h4>
                {player.swot?.strengths?.length > 0 ? (
                  <ul style={{ paddingLeft: '1.5rem', fontSize: '0.9rem', color: 'var(--text-muted)' }}>
                    {player.swot.strengths.map((s, i) => <li key={i}>{s}</li>)}
                  </ul>
                ) : (
                  <p style={{ fontSize: '0.85rem', color: 'rgba(255,255,255,0.3)', fontStyle: 'italic' }}>Need more data</p>
                )}
              </div>

              {/* Weaknesses */}
              <div>
                <h4 style={{ color: 'var(--danger)', display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.9rem', marginBottom: '0.25rem' }}>
                  <AlertTriangle size={16} /> Areas for Growth
                </h4>
                {player.swot?.weaknesses?.length > 0 ? (
                  <ul style={{ paddingLeft: '1.5rem', fontSize: '0.9rem', color: 'var(--text-muted)' }}>
                    {player.swot.weaknesses.map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                ) : (
                  <p style={{ fontSize: '0.85rem', color: 'rgba(255,255,255,0.3)', fontStyle: 'italic' }}>Need more data</p>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
      
      {/* Team Level SWOT (stubbed out for now) */}
      <div className="glass-panel" style={{ marginTop: '2rem', padding: '1.5rem', borderColor: 'var(--primary-glow)' }}>
        <h3 style={{ marginBottom: '1rem', color: 'var(--primary-color)' }}>Team Outlook</h3>
        <p style={{ color: 'var(--text-muted)' }}>
          With only 2 games in the books, individual sample sizes are currently small. As the season progresses, team aggregations for offensive trends and defensive liabilities will appear here.
        </p>
      </div>
    </div>
  );
};

export default Swot;
