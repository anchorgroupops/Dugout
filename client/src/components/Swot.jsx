import React, { useState } from 'react';
import { AlertTriangle, TrendingUp, ShieldAlert, Target, ChevronDown, ChevronUp } from 'lucide-react';

const SwotQuadrant = ({ title, items, color, icon }) => (
  <div>
    <h4 style={{ color, display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem', marginBottom: '0.4rem', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
      {icon} {title}
    </h4>
    {items?.length > 0 ? (
      <ul style={{ paddingLeft: '1.2rem', fontSize: '0.88rem', color: 'var(--text-muted)', margin: 0 }}>
        {items.map((s, i) => <li key={i} style={{ marginBottom: '2px' }}>{s}</li>)}
      </ul>
    ) : (
      <p style={{ fontSize: '0.83rem', color: 'rgba(255,255,255,0.3)', fontStyle: 'italic', margin: 0 }}>Need more data</p>
    )}
  </div>
);

const Swot = ({ swotData, roster }) => {
  const [expandedPlayer, setExpandedPlayer] = useState(null);
  if (!swotData) return <p>Loading SWOT Analysis...</p>;

  // Combine player objects with their SWOT evaluations
  const evaluations = swotData.player_analyses || swotData.player_evaluations || [];
  const playersWithSwot = (roster || []).map(player => {
    const evaluation = evaluations.find(e =>
      (e.number && String(e.number) === String(player.number)) ||
      (e.name && e.name.toLowerCase() === `${player.first} ${player.last}`.trim().toLowerCase()) ||
      (e.name && e.name.toLowerCase() === String(player.first || '').toLowerCase())
    );
    return { ...player, swot: evaluation?.swot || evaluation };
  }).filter(p => p.swot);

  const teamSwot = swotData.team_swot;

  return (
    <div>
      <h2 style={{ marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <Target size={24} color="var(--primary-color)" /> SWOT Analysis
        <span style={{ fontSize: '0.9rem', color: 'var(--text-muted)', fontWeight: 'normal', marginLeft: '0.5rem' }}>
          ({playersWithSwot.length} players)
        </span>
      </h2>

      {/* Team-level SWOT */}
      {teamSwot && (
        <div className="glass-panel" style={{ marginBottom: '2rem', padding: '1.5rem', borderColor: 'var(--primary-glow)' }}>
          <h3 style={{ marginBottom: '1.25rem', color: 'var(--primary-color)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <ShieldAlert size={20} /> Team Analysis
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: '1.25rem' }}>
            <SwotQuadrant title="Strengths" items={teamSwot.strengths} color="var(--success)" icon={<TrendingUp size={14} />} />
            <SwotQuadrant title="Areas for Growth" items={teamSwot.weaknesses} color="var(--danger)" icon={<AlertTriangle size={14} />} />
            <SwotQuadrant title="Opportunities" items={teamSwot.opportunities} color="#3b9ede" icon={<Target size={14} />} />
            <SwotQuadrant title="Threats" items={teamSwot.threats} color="#e8a838" icon={<ShieldAlert size={14} />} />
          </div>
        </div>
      )}

      {/* Player cards */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(350px, 1fr))',
        gap: '1.5rem'
      }}>
        {playersWithSwot.map(player => {
          const key = `${player.number}-${player.last}`;
          const isExpanded = expandedPlayer === key;
          return (
            <div
              key={key}
              className="glass-panel"
              style={{ padding: '1.5rem', cursor: 'pointer' }}
              onClick={() => setExpandedPlayer(isExpanded ? null : key)}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', paddingBottom: '0.5rem', borderBottom: '1px solid var(--surface-border)' }}>
                <h3 style={{ fontSize: '1.1rem', margin: 0 }}>
                  {player.number ? `#${player.number} ` : ''}{player.first} {player.last}
                </h3>
                {isExpanded ? <ChevronUp size={18} color="var(--text-muted)" /> : <ChevronDown size={18} color="var(--text-muted)" />}
              </div>

              {/* Always show strengths/weaknesses summary */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                <SwotQuadrant title="Strengths" items={player.swot?.strengths} color="var(--success)" icon={<TrendingUp size={13} />} />
                <SwotQuadrant title="Areas for Growth" items={player.swot?.weaknesses} color="var(--danger)" icon={<AlertTriangle size={13} />} />
                {isExpanded && (
                  <>
                    <SwotQuadrant title="Opportunities" items={player.swot?.opportunities} color="#3b9ede" icon={<Target size={13} />} />
                    <SwotQuadrant title="Threats" items={player.swot?.threats} color="#e8a838" icon={<ShieldAlert size={13} />} />
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {playersWithSwot.length === 0 && (
        <div className="glass-panel" style={{ padding: '2rem', textAlign: 'center' }}>
          <p style={{ color: 'var(--text-muted)' }}>No SWOT data available. Run the scraper to populate player stats.</p>
        </div>
      )}
    </div>
  );
};

export default Swot;
