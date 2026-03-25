import React, { useState, useEffect } from 'react';
import { Trophy, Users, ChevronDown, ChevronUp, Shield, AlertTriangle } from 'lucide-react';

const League = ({ isMobile = false }) => {
  const [standings, setStandings] = useState(null);
  const [opponents, setOpponents] = useState([]);
  const [expanded, setExpanded] = useState(null);

  useEffect(() => {
    fetch('/api/standings')
      .then(r => r.ok ? r.json() : null)
      .then(setStandings)
      .catch(() => {});

    fetch('/api/opponents')
      .then(r => r.ok ? r.json() : [])
      .then(setOpponents)
      .catch(() => {});
  }, []);

  const standingRows = standings?.standings || [];
  const formatTeamName = (team) => {
    const slug = String(team?.slug || '').toLowerCase();
    const raw = String(team?.team_name || '').trim();
    if (slug === 'sharks' || raw.toLowerCase() === 'sharks' || raw.toLowerCase() === 'the sharks') {
      return 'The Sharks';
    }
    return raw || 'Unknown Team';
  };

  return (
    <div>
      <h2 className="view-title">
        <Trophy size={isMobile ? 20 : 24} color="var(--primary-color)" /> League
        {standings?.league && (
          <span style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)', fontWeight: 'normal', marginLeft: '0.5rem' }}>
            {standings.league}
          </span>
        )}
      </h2>

      {/* Standings table */}
      <div className="glass-panel" style={{ padding: isMobile ? 'var(--space-lg)' : '1.5rem', marginBottom: '2rem' }}>
        <div className="section-label">Standings</div>

        {standingRows.length === 0 && (
          <div style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)', padding: '0.5rem' }}>Loading standings...</div>
        )}

        {!isMobile && (
          <div style={{
            display: 'grid', gridTemplateColumns: '1fr 60px 60px 70px',
            gap: '0.5rem', padding: '0.3rem 0.5rem',
            fontSize: 'var(--text-xs)', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', fontWeight: '700'
          }}>
            <span>Team</span>
            <span style={{ textAlign: 'center' }}>W-L</span>
            <span style={{ textAlign: 'center' }}>PCT</span>
            <span style={{ textAlign: 'center' }}>Record</span>
          </div>
        )}

        {standingRows.map((team, i) => {
          const isSharks = team.slug === 'sharks';
          if (isMobile) {
            return (
              <div key={team.slug} style={{
                padding: '0.625rem 0.75rem',
                borderRadius: '8px',
                background: isSharks ? 'rgba(4, 101, 104, 0.08)' : 'rgba(255,255,255,0.03)',
                border: isSharks ? '1px solid rgba(4, 101, 104, 0.2)' : '1px solid rgba(255,255,255,0.06)',
                marginBottom: '0.4rem',
                minHeight: 'var(--touch-min)',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'center',
              }}>
                <div style={{ fontWeight: isSharks ? '700' : '600', color: isSharks ? 'var(--primary-color)' : 'var(--text-main)', fontSize: 'var(--text-sm)' }}>
                  {isSharks ? 'SHARKS' : `${i + 1}.`} {formatTeamName(team)}
                </div>
                <div style={{ marginTop: '0.2rem', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
                  {team.w}-{team.l} \u00b7 {team.record} \u00b7 {team.pct != null ? (team.pct === 1 ? '1.000' : team.pct.toFixed(3)) : '\u2014'}
                </div>
              </div>
            );
          }
          return (
            <div key={team.slug} style={{
              display: 'grid', gridTemplateColumns: '1fr 60px 60px 70px',
              gap: '0.5rem', padding: '0.5rem 0.5rem',
              borderRadius: '6px', alignItems: 'center',
              background: isSharks ? 'rgba(4, 101, 104, 0.08)' : i % 2 === 0 ? 'rgba(255,255,255,0.02)' : 'transparent',
              border: isSharks ? '1px solid rgba(4, 101, 104, 0.2)' : '1px solid transparent',
              marginBottom: '0.25rem'
            }}>
              <span style={{ fontWeight: isSharks ? '700' : '500', color: isSharks ? 'var(--primary-color)' : 'var(--text-main)', fontSize: 'var(--text-sm)' }}>
                {isSharks ? 'SHARKS ' : `${i + 1}. `}{formatTeamName(team)}
              </span>
              <span style={{ textAlign: 'center', fontWeight: '600', fontSize: 'var(--text-sm)' }}>{team.w}-{team.l}</span>
              <span style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: 'var(--text-sm)' }}>
                {team.pct != null ? (team.pct === 1 ? '1.000' : team.pct.toFixed(3)) : '\u2014'}
              </span>
              <span style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: 'var(--text-xs)' }}>{team.record}</span>
            </div>
          );
        })}
      </div>

      {/* Opponent cards */}
      {opponents.length > 0 && (
        <>
          <div className="section-label section-label--muted">Opponent Scouting ({opponents.length} teams)</div>
          <div className="card-grid">
            {opponents.map(opp => {
              const isExpanded = expanded === opp.slug;
              const standRow = standingRows.find(s => s.slug === opp.slug);
              return (
                <div
                  key={opp.slug}
                  className="glass-panel"
                  style={{ padding: 'var(--space-lg)', cursor: 'pointer' }}
                  onClick={() => setExpanded(isExpanded ? null : opp.slug)}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                      <h3 style={{ fontSize: 'var(--text-base)', margin: '0 0 0.25rem' }}>{opp.team_name}</h3>
                      <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                        {standRow?.record && (
                          <span style={{
                            fontSize: 'var(--text-xs)', fontWeight: '700', padding: '2px 8px',
                            borderRadius: '10px',
                            background: parseInt(standRow.w) > parseInt(standRow.l) ? 'rgba(35,134,54,0.15)' : parseInt(standRow.w) < parseInt(standRow.l) ? 'rgba(220,70,70,0.15)' : 'rgba(255,255,255,0.1)',
                            color: parseInt(standRow.w) > parseInt(standRow.l) ? 'var(--success)' : parseInt(standRow.w) < parseInt(standRow.l) ? 'var(--danger)' : 'var(--text-muted)'
                          }}>{standRow.record}</span>
                        )}
                        <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
                          <Users size={11} style={{ display: 'inline', marginRight: '3px', verticalAlign: 'middle' }} />
                          {opp.roster_size} players
                        </span>
                      </div>
                    </div>
                    {isExpanded ? <ChevronUp size={16} color="var(--text-muted)" /> : <ChevronDown size={16} color="var(--text-muted)" />}
                  </div>

                  {isExpanded && (
                    <OpponentDetail slug={opp.slug} hasRoster={opp.roster_size > 0} />
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
};

const OpponentDetail = ({ slug, hasRoster }) => {
  const [roster, setRoster] = useState(null);
  const [matchup, setMatchup] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetches = [
      fetch(`/api/matchup/${slug}`).then(r => r.ok ? r.json() : null).catch(() => null),
    ];
    if (hasRoster) {
      fetches.push(fetch(`/api/opponents/${slug}`).then(r => r.ok ? r.json() : null).catch(() => null));
    }
    Promise.all(fetches).then(([m, opp]) => {
      setMatchup(m);
      if (opp) setRoster(opp?.roster || []);
      setLoading(false);
    });
  }, [slug, hasRoster]);

  if (loading) return <div className="loader" style={{ width: '20px', height: '20px', margin: '0.75rem auto' }} />;

  return (
    <div style={{ marginTop: '1rem', paddingTop: '0.75rem', borderTop: '1px solid var(--surface-border)' }}>
      {matchup && !matchup.empty && (
        <div style={{ marginBottom: 'var(--space-sm)' }}>
          {matchup.our_advantages?.length > 0 && (
            <div style={{ marginBottom: '0.5rem' }}>
              <span style={{ fontSize: 'var(--text-xs)', color: 'var(--success)', textTransform: 'uppercase', fontWeight: '700' }}>
                <Shield size={11} style={{ display: 'inline', verticalAlign: 'middle', marginRight: '3px' }} />
                Our Advantages
              </span>
              <ul style={{ margin: '0.2rem 0 0 1rem', fontSize: 'var(--text-xs)', color: 'var(--text-muted)', paddingLeft: '0.5rem' }}>
                {matchup.our_advantages.slice(0, 3).map((a, i) => <li key={i}>{a}</li>)}
              </ul>
            </div>
          )}
          {matchup.their_advantages?.length > 0 && (
            <div>
              <span style={{ fontSize: 'var(--text-xs)', color: 'var(--danger)', textTransform: 'uppercase', fontWeight: '700' }}>
                <AlertTriangle size={11} style={{ display: 'inline', verticalAlign: 'middle', marginRight: '3px' }} />
                Their Strengths
              </span>
              <ul style={{ margin: '0.2rem 0 0 1rem', fontSize: 'var(--text-xs)', color: 'var(--text-muted)', paddingLeft: '0.5rem' }}>
                {matchup.their_advantages.slice(0, 3).map((a, i) => <li key={i}>{a}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}

      {roster && roster.length > 0 && (
        <div>
          <div className="section-label section-label--muted" style={{ fontSize: 'var(--text-xs)' }}>Roster</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem' }}>
            {roster.map((p, i) => (
              <span key={i} style={{
                background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: '6px', padding: '3px 8px', fontSize: 'var(--text-xs)', color: 'var(--text-muted)'
              }}>
                {p.number ? <span style={{ color: 'var(--primary-color)', fontWeight: '700', marginRight: '4px' }}>#{p.number}</span> : null}
                {p.name || `${p.first || ''} ${p.last || ''}`.trim()}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default League;
