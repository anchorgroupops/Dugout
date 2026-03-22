import React, { useState, useEffect } from 'react';
import { AlertTriangle, TrendingUp, ShieldAlert, Target, ChevronDown, ChevronUp, Swords } from 'lucide-react';

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

const StatCompare = ({ label, ours, theirs, lowerIsBetter }) => {
  const diff = lowerIsBetter ? theirs - ours : ours - theirs;
  const color = diff > 0 ? 'var(--success)' : diff < 0 ? 'var(--danger)' : 'var(--text-muted)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.4rem 0', fontSize: '0.88rem' }}>
      <span style={{ width: '70px', color: 'var(--text-muted)', fontSize: '0.8rem', textTransform: 'uppercase' }}>{label}</span>
      <span style={{ width: '60px', textAlign: 'right', fontWeight: '600', color }}>{ours}</span>
      <span style={{ color: 'rgba(255,255,255,0.2)', fontSize: '0.75rem' }}>vs</span>
      <span style={{ width: '60px', fontWeight: '600', color: 'var(--text-muted)' }}>{theirs}</span>
    </div>
  );
};

const MatchupPanel = () => {
  const [opponents, setOpponents] = useState([]);
  const [selected, setSelected] = useState('');
  const [matchup, setMatchup] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch('/api/opponents')
      .then(r => r.ok ? r.json() : [])
      .then(setOpponents)
      .catch(() => setOpponents([]));
  }, []);

  const handleSelect = async (slug) => {
    setSelected(slug);
    if (!slug) { setMatchup(null); return; }
    setLoading(true);
    try {
      const res = await fetch(`/api/matchup/${slug}`);
      if (res.ok) setMatchup(await res.json());
    } catch (e) {
      console.error('Matchup fetch failed', e);
    } finally {
      setLoading(false);
    }
  };

  if (opponents.length === 0) {
    return (
      <div className="glass-panel" style={{ padding: '1.5rem', marginBottom: '2rem', opacity: 0.7 }}>
        <h3 style={{ color: 'var(--primary-color)', display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
          <Swords size={20} /> Matchup Analysis
        </h3>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.88rem' }}>
          No opponent data available yet. Run the league scraper to populate opponent stats.
        </p>
      </div>
    );
  }

  return (
    <div className="glass-panel" style={{ padding: '1.5rem', marginBottom: '2rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.75rem' }}>
        <h3 style={{ margin: 0, color: 'var(--primary-color)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Swords size={20} /> Matchup Analysis
        </h3>
        <select
          value={selected}
          onChange={e => handleSelect(e.target.value)}
          style={{
            padding: '0.4rem 0.75rem', borderRadius: '6px',
            background: 'rgba(0,0,0,0.3)', border: '1px solid var(--surface-border)',
            color: 'var(--text-main)', fontSize: '0.88rem', fontFamily: 'inherit', cursor: 'pointer'
          }}
        >
          <option value="">Select opponent...</option>
          {opponents.map(o => (
            <option key={o.slug} value={o.slug}>{o.team_name} ({o.roster_size} players)</option>
          ))}
        </select>
      </div>

      {loading && <div className="loader" style={{ margin: '1rem auto' }}></div>}

      {matchup && !loading && (
        <div>
          {/* Recommendation banner */}
          <div style={{
            padding: '0.75rem 1rem', borderRadius: '8px', marginBottom: '1rem',
            background: 'rgba(0,210,255,0.06)', border: '1px solid rgba(0,210,255,0.15)',
            fontSize: '0.9rem', fontWeight: '600', color: 'var(--primary-color)'
          }}>
            {matchup.recommendation}
          </div>

          {/* Side-by-side stat comparison */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem', marginBottom: '1rem' }}>
            <div>
              <div style={{ fontSize: '0.7rem', color: 'var(--primary-color)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '0.5rem', fontWeight: '700' }}>
                Batting
              </div>
              <StatCompare label="AVG" ours={matchup.our_stats.batting.avg} theirs={matchup.their_stats.batting.avg} />
              <StatCompare label="OBP" ours={matchup.our_stats.batting.obp} theirs={matchup.their_stats.batting.obp} />
              <StatCompare label="OPS" ours={matchup.our_stats.batting.ops} theirs={matchup.their_stats.batting.ops} />
              <StatCompare label="K%" ours={matchup.our_stats.batting.k_rate} theirs={matchup.their_stats.batting.k_rate} lowerIsBetter />
              <StatCompare label="BB%" ours={matchup.our_stats.batting.bb_rate} theirs={matchup.their_stats.batting.bb_rate} />
            </div>
            <div>
              <div style={{ fontSize: '0.7rem', color: 'var(--primary-color)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '0.5rem', fontWeight: '700' }}>
                Pitching
              </div>
              <StatCompare label="ERA" ours={matchup.our_stats.pitching.era} theirs={matchup.their_stats.pitching.era} lowerIsBetter />
              <StatCompare label="WHIP" ours={matchup.our_stats.pitching.whip} theirs={matchup.their_stats.pitching.whip} lowerIsBetter />
              <StatCompare label="K/IP" ours={matchup.our_stats.pitching.k_per_ip} theirs={matchup.their_stats.pitching.k_per_ip} />
              <StatCompare label="FPCT" ours={matchup.our_stats.fielding.fpct} theirs={matchup.their_stats.fielding.fpct} />
            </div>
          </div>

          {/* Advantages */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
            <div>
              <div style={{ fontSize: '0.7rem', color: 'var(--success)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '0.4rem', fontWeight: '700' }}>
                Our Advantages
              </div>
              <ul style={{ paddingLeft: '1.2rem', fontSize: '0.85rem', color: 'var(--text-muted)', margin: 0 }}>
                {matchup.our_advantages.map((a, i) => <li key={i} style={{ marginBottom: '2px' }}>{a}</li>)}
              </ul>
            </div>
            <div>
              <div style={{ fontSize: '0.7rem', color: 'var(--danger)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '0.4rem', fontWeight: '700' }}>
                Their Advantages
              </div>
              <ul style={{ paddingLeft: '1.2rem', fontSize: '0.85rem', color: 'var(--text-muted)', margin: 0 }}>
                {matchup.their_advantages.map((a, i) => <li key={i} style={{ marginBottom: '2px' }}>{a}</li>)}
              </ul>
            </div>
          </div>

          {/* Key matchups */}
          {matchup.key_matchups.length > 0 && (
            <div style={{ marginTop: '1rem', paddingTop: '0.75rem', borderTop: '1px solid var(--surface-border)' }}>
              <div style={{ fontSize: '0.7rem', color: '#e8a838', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '0.4rem', fontWeight: '700' }}>
                Key Matchups
              </div>
              <ul style={{ paddingLeft: '1.2rem', fontSize: '0.85rem', color: 'var(--text-muted)', margin: 0 }}>
                {matchup.key_matchups.map((m, i) => <li key={i} style={{ marginBottom: '2px' }}>{m}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

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

      {/* Matchup Analysis */}
      <MatchupPanel />

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
