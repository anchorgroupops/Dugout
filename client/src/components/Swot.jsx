import React, { useState, useEffect } from 'react';
import { AlertTriangle, TrendingUp, ShieldAlert, Target, ChevronDown, ChevronUp, Swords, Clock, Home, Plane } from 'lucide-react';
import { getTodayEST } from '../utils/formatDate';

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

const PlayerStatChip = ({ label, value }) => (
  <span style={{
    display: 'inline-flex',
    gap: '0.3rem',
    alignItems: 'center',
    fontSize: '0.72rem',
    color: 'var(--text-muted)',
    border: '1px solid rgba(255,255,255,0.12)',
    borderRadius: '999px',
    padding: '2px 8px',
    background: 'rgba(255,255,255,0.04)'
  }}>
    <span style={{ color: 'rgba(255,255,255,0.55)', textTransform: 'uppercase', letterSpacing: '0.35px' }}>{label}</span>
    <span style={{ color: 'var(--text-main)', fontWeight: '700' }}>{value}</span>
  </span>
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

const MatchupPanel = ({ defaultOpponent }) => {
  const [opponents, setOpponents] = useState([]);
  const [selected, setSelected] = useState('');
  const [matchup, setMatchup] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch('/api/opponents')
      .then(r => r.ok ? r.json() : [])
      .then(data => {
        setOpponents(data);
        if (defaultOpponent) {
          const matched = data.find(o => o.team_name.toLowerCase() === defaultOpponent.toLowerCase() || o.slug === defaultOpponent.toLowerCase().replace(/ /g, '_'));
          if (matched && selected !== matched.slug) {
            handleSelect(matched.slug);
          }
        }
      })
      .catch(() => setOpponents([]));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaultOpponent]);

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
    <div className="glass-panel" style={{ padding: '1.5rem', marginBottom: '0' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.75rem' }}>
        <h3 style={{ margin: 0, color: 'var(--primary-color)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Swords size={20} /> {defaultOpponent && selected === opponents.find(o => o.team_name.toLowerCase() === defaultOpponent.toLowerCase() || o.slug === defaultOpponent.toLowerCase().replace(/ /g, '_'))?.slug ? `Next Game Matchup vs ${defaultOpponent}` : 'Matchup Analysis'}
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
            padding: '0.75rem 1rem', borderRadius: '8px', marginBottom: matchup.empty ? '0' : '1rem',
            background: matchup.empty ? 'rgba(4,101,104,0.18)' : 'rgba(4, 101, 104, 0.08)',
            border: `1px solid ${matchup.empty ? 'rgba(130,203,195,0.5)' : 'rgba(4, 101, 104, 0.2)'}`,
            fontSize: '0.9rem', fontWeight: '600',
            color: matchup.empty ? '#82CBC3' : 'var(--primary-color)',
            display: 'flex', alignItems: 'center', gap: '0.6rem'
          }}>
            {matchup.empty && <AlertTriangle size={16} color="#82CBC3" style={{ flexShrink: 0 }} />}
            {matchup.recommendation}
          </div>
          <div style={{ marginTop: '0.45rem', marginBottom: matchup.empty ? '0.85rem' : '1rem', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            Data source: {matchup.data_source === 'opponent_game_history'
              ? 'scorebook game history'
              : matchup.data_source === 'opponent_team_json'
                ? 'opponent team feed'
                : matchup.data_source === 'opponent_public_games'
                  ? 'opponent public game feed'
                : 'none'}
            {matchup.empty && matchup.reason ? ` · reason: ${matchup.reason}` : ''}
          </div>

          {!matchup.empty && (
            <>
              {/* Side-by-side stat comparison */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem', marginBottom: '1rem' }}>
            <div>
              <div style={{ fontSize: '0.7rem', color: 'var(--primary-color)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '0.5rem', fontWeight: '700' }}>
                Batting
              </div>
              <StatCompare label="AVG" ours={matchup.our_stats.batting.avg} theirs={matchup.their_stats.batting.avg} />
              <StatCompare label="OBP" ours={matchup.our_stats.batting.obp} theirs={matchup.their_stats.batting.obp} />
              <StatCompare label="OPS" ours={matchup.our_stats.batting.ops} theirs={matchup.their_stats.batting.ops} />
              <StatCompare label="QAB%" ours={matchup.our_stats.batting_advanced?.qab_pct ?? 0} theirs={matchup.their_stats.batting_advanced?.qab_pct ?? 0} />
              <StatCompare label="C%" ours={matchup.our_stats.batting_advanced?.c_pct ?? 0} theirs={matchup.their_stats.batting_advanced?.c_pct ?? 0} />
              <StatCompare label="LD%" ours={matchup.our_stats.batting_advanced?.ld_pct ?? 0} theirs={matchup.their_stats.batting_advanced?.ld_pct ?? 0} />
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
              <div style={{ fontSize: '0.7rem', color: 'var(--warning)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '0.4rem', fontWeight: '700' }}>
                Key Matchups
              </div>
              <ul style={{ paddingLeft: '1.2rem', fontSize: '0.85rem', color: 'var(--text-muted)', margin: 0 }}>
                {matchup.key_matchups.map((m, i) => <li key={i} style={{ marginBottom: '2px' }}>{m}</li>)}
              </ul>
            </div>
          )}

              {/* Opponent roster */}
              {matchup.their_roster?.length > 0 && (
                <div style={{ marginTop: '1rem', paddingTop: '0.75rem', borderTop: '1px solid var(--surface-border)' }}>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '0.5rem', fontWeight: '700' }}>
                    {matchup.opponent} Roster ({matchup.their_roster.length})
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
                    {[...matchup.their_roster].sort((a,b) => {
                      const sortKey = (p) => {
                        if (p.last) return `${p.last} ${p.first || ''}`.trim();
                        const n = (p.name || '').trim();
                        const parts = n.split(' ');
                        return parts.length > 1
                          ? `${parts[parts.length - 1]} ${parts.slice(0, -1).join(' ')}`
                          : n;
                      };
                      return sortKey(a).toLowerCase().localeCompare(sortKey(b).toLowerCase());
                    }).map((p, i) => (
                      <span key={i} style={{
                        background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)',
                        borderRadius: '6px', padding: '3px 8px', fontSize: '0.8rem', color: 'var(--text-muted)'
                      }}>
                        {p.number ? <span style={{ color: 'var(--primary-color)', fontWeight: '700', marginRight: '4px' }}>#{p.number}</span> : null}
                        {p.name || `${p.first || ''} ${p.last || ''}`.trim()}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
};

const UpcomingGameBanner = ({ next }) => {
  if (!next) return null;

  const dateStr = new Date(next.date + 'T12:00:00').toLocaleDateString('en-US', {
    timeZone: 'America/New_York', weekday: 'short', month: 'short', day: 'numeric'
  });
  const isHome = next.home_away === 'home';

  return (
    <div className="glass-panel" style={{
      padding: '1rem 1.5rem', marginBottom: '0.75rem',
      borderColor: 'rgba(4, 101, 104, 0.32)', background: 'rgba(4, 101, 104, 0.06)'
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
        <Clock size={18} color="var(--primary-color)" />
        <span style={{ fontSize: '0.7rem', color: 'var(--primary-color)', textTransform: 'uppercase', letterSpacing: '1px', fontWeight: '700' }}>
          Next Game
        </span>
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: '0.25rem',
          background: isHome ? 'rgba(35,134,54,0.15)' : 'rgba(42, 143, 147, 0.16)',
          color: isHome ? 'var(--success)' : 'var(--accent-away)',
          padding: '2px 8px', borderRadius: '12px', fontSize: '0.7rem', fontWeight: '700'
        }}>
          {isHome ? <Home size={10} /> : <Plane size={10} />}
          {isHome ? 'HOME' : 'AWAY'}
        </span>
        <span style={{ fontWeight: '700', fontSize: '1rem' }}>vs. {next.opponent}</span>
        <span style={{ color: 'var(--text-muted)', fontSize: '0.88rem' }}>
          {dateStr}{next.time ? ` · ${next.time}` : ''}
        </span>
        {next.location && next.location !== 'TBD' && (
          <span style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>@ {next.location}</span>
        )}
      </div>
    </div>
  );
};

const Swot = ({ swotData, roster, schedule, isMobile = false }) => {
  const [expandedPlayer, setExpandedPlayer] = useState(null);
  const [showMatchup, setShowMatchup] = useState(!isMobile);
  if (!swotData) return <p>Loading SWOT Analysis...</p>;

  // Combine player objects with their SWOT evaluations
  const evaluations = swotData.player_analyses || swotData.player_evaluations || [];
  const playersWithSwot = (roster || []).filter(p => p.core !== false).map(player => {
    const evaluation = evaluations.find(e =>
      (e.number && String(e.number) === String(player.number)) ||
      (e.name && e.name.toLowerCase() === `${player.first} ${player.last}`.trim().toLowerCase()) ||
      (e.name && e.name.toLowerCase() === String(player.first || '').toLowerCase())
    );
    return {
      ...player,
      swot: evaluation?.swot || evaluation,
      derivedStats: evaluation?.derived_stats || null
    };
  }).filter(p => p.swot)
    .sort((a, b) => {
      const textA = `${a.last || ''} ${a.first || ''}`.trim().toLowerCase();
      const textB = `${b.last || ''} ${b.first || ''}`.trim().toLowerCase();
      return textA.localeCompare(textB);
    });

  const teamSwot = swotData.team_swot;

  const today = getTodayEST();
  const nextGame = schedule?.upcoming
    ?.filter(g => g.date >= today)
    ?.sort((a, b) => a.date.localeCompare(b.date))[0];

  return (
    <div>
      <h2 style={{ marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
        <Target size={isMobile ? 20 : 24} color="var(--primary-color)" /> SWOT Analysis
        <span style={{ fontSize: isMobile ? '0.78rem' : '0.9rem', color: 'var(--text-muted)', fontWeight: 'normal', marginLeft: '0.5rem' }}>
          ({playersWithSwot.length} players)
        </span>
      </h2>

      {/* 1. Next Game & Matchups Combined Group */}
      <div style={{ marginBottom: isMobile ? '1rem' : '2rem' }}>
        <UpcomingGameBanner next={nextGame} />
        {isMobile ? (
          <div className="glass-panel" style={{ padding: '0.85rem 1rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.75rem' }}>
              <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                Matchup details are optional on mobile.
              </span>
              <button
                onClick={() => setShowMatchup(prev => !prev)}
                style={{
                  background: 'var(--primary-glow)',
                  color: 'var(--primary-color)',
                  border: '1px solid rgba(4, 101, 104, 0.24)',
                  borderRadius: '8px',
                  padding: '0.32rem 0.65rem',
                  fontSize: '0.76rem',
                  fontWeight: '700',
                  cursor: 'pointer'
                }}
              >
                {showMatchup ? 'Hide Matchup' : 'Show Matchup'}
              </button>
            </div>
            {showMatchup && <div style={{ marginTop: '0.75rem' }}><MatchupPanel defaultOpponent={nextGame?.opponent} /></div>}
          </div>
        ) : (
          <MatchupPanel defaultOpponent={nextGame?.opponent} />
        )}
      </div>

      {/* 2. Team-level SWOT */}
      {teamSwot && (
        isMobile ? (
          <details className="glass-panel" style={{ marginBottom: '1rem', padding: '0.9rem 1rem', borderColor: 'var(--primary-glow)' }}>
            <summary style={{ cursor: 'pointer', color: 'var(--primary-color)', fontWeight: 700 }}>Team Analysis</summary>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '0.85rem', marginTop: '0.75rem' }}>
              <SwotQuadrant title="Strengths" items={(teamSwot.strengths || []).slice(0, 4)} color="var(--success)" icon={<TrendingUp size={14} />} />
              <SwotQuadrant title="Areas for Growth" items={(teamSwot.weaknesses || []).slice(0, 4)} color="var(--danger)" icon={<AlertTriangle size={14} />} />
              <SwotQuadrant title="Opportunities" items={(teamSwot.opportunities || []).slice(0, 4)} color="#3b9ede" icon={<Target size={14} />} />
              <SwotQuadrant title="Threats" items={(teamSwot.threats || []).slice(0, 4)} color="var(--warning)" icon={<ShieldAlert size={14} />} />
            </div>
          </details>
        ) : (
          <div className="glass-panel" style={{ marginBottom: '2rem', padding: '1.5rem', borderColor: 'var(--primary-glow)' }}>
            <h3 style={{ marginBottom: '1.25rem', color: 'var(--primary-color)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <ShieldAlert size={20} /> Team Analysis
            </h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: '1.25rem' }}>
              <SwotQuadrant title="Strengths" items={teamSwot.strengths} color="var(--success)" icon={<TrendingUp size={14} />} />
              <SwotQuadrant title="Areas for Growth" items={teamSwot.weaknesses} color="var(--danger)" icon={<AlertTriangle size={14} />} />
              <SwotQuadrant title="Opportunities" items={teamSwot.opportunities} color="#3b9ede" icon={<Target size={14} />} />
              <SwotQuadrant title="Threats" items={teamSwot.threats} color="var(--warning)" icon={<ShieldAlert size={14} />} />
            </div>
          </div>
        )
      )}

      {/* Player cards */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: isMobile ? '1fr' : 'repeat(auto-fill, minmax(260px, 1fr))',
        gap: isMobile ? '0.85rem' : '1.5rem'
      }}>
        {playersWithSwot.map(player => {
          const key = `${player.number}-${player.last}`;
          const isExpanded = expandedPlayer === key;
          const hitting = player.derivedStats?.hitting || {};
          const pa = Number(hitting.pa || 0);
          const avg = Number(hitting.ba || 0).toFixed(3).replace(/^0/, '');
          const obp = Number(hitting.obp || 0).toFixed(3).replace(/^0/, '');
          const ops = Number(hitting.ops || 0).toFixed(3).replace(/^0/, '');
          const kRate = `${Math.round(Number(hitting.k_rate || 0) * 100)}%`;
          const bbRate = `${Math.round(Number(hitting.bb_rate || 0) * 100)}%`;
          return (
            <div
              key={key}
              className="glass-panel"
              style={{ padding: isMobile ? '0.95rem' : '1.5rem', cursor: 'pointer' }}
              onClick={() => setExpandedPlayer(isExpanded ? null : key)}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', paddingBottom: '0.5rem', borderBottom: '1px solid var(--surface-border)' }}>
                <h3 style={{ fontSize: isMobile ? '1rem' : '1.1rem', margin: 0 }}>
                  {player.number ? `#${player.number} ` : ''}{player.first} {player.last}
                </h3>
                {isExpanded ? <ChevronUp size={18} color="var(--text-muted)" /> : <ChevronDown size={18} color="var(--text-muted)" />}
              </div>

              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem', marginBottom: '0.9rem' }}>
                {pa > 0 ? (
                  <>
                    <PlayerStatChip label="PA" value={pa} />
                    <PlayerStatChip label="AVG" value={avg} />
                    <PlayerStatChip label="OBP" value={obp} />
                    <PlayerStatChip label="OPS" value={ops} />
                    {!isMobile && <PlayerStatChip label="K%" value={kRate} />}
                    {!isMobile && <PlayerStatChip label="BB%" value={bbRate} />}
                  </>
                ) : (
                  <PlayerStatChip label="Stats" value="No plate appearances yet" />
                )}
              </div>

              {/* Always show strengths/weaknesses summary */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                <SwotQuadrant title="Strengths" items={isMobile ? (player.swot?.strengths || []).slice(0, 2) : player.swot?.strengths} color="var(--success)" icon={<TrendingUp size={13} />} />
                <SwotQuadrant title="Areas for Growth" items={isMobile ? (player.swot?.weaknesses || []).slice(0, 2) : player.swot?.weaknesses} color="var(--danger)" icon={<AlertTriangle size={13} />} />
                {isExpanded && (
                  <>
                    <SwotQuadrant title="Opportunities" items={player.swot?.opportunities} color="#3b9ede" icon={<Target size={13} />} />
                    <SwotQuadrant title="Threats" items={player.swot?.threats} color="var(--warning)" icon={<ShieldAlert size={13} />} />
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
