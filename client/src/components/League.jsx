import React, { useState, useEffect } from 'react';
import { Trophy, Users, ChevronDown, ChevronUp } from 'lucide-react';

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

  const rosterMap = {};
  opponents.forEach(o => { rosterMap[o.slug] = o; });

  const standingRows = standings?.standings || [];
  const formatTeamName = (team) => {
    const slug = String(team?.slug || '').toLowerCase();
    const raw = String(team?.team_name || '').trim();
    if (slug === 'sharks' || raw.toLowerCase() === 'sharks' || raw.toLowerCase() === 'the sharks') {
      return 'The Sharks';
    }
    return raw || 'Unknown Team';
  };
  const sharksRow = standingRows.find(s => s.slug === 'sharks');
  const others = standingRows.filter(s => s.slug !== 'sharks');

  return (
    <div>
      <h2 style={{ marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <Trophy size={isMobile ? 20 : 24} color="var(--primary-color)" /> League
        {standings?.league && (
          <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontWeight: 'normal', marginLeft: '0.5rem' }}>
            {standings.league}
          </span>
        )}
      </h2>

      {/* Standings table */}
      <div className="glass-panel" style={{ padding: '1.5rem', marginBottom: '2rem' }}>
        <div style={{ fontSize: '0.7rem', color: 'var(--primary-color)', textTransform: 'uppercase', letterSpacing: '1px', fontWeight: '700', marginBottom: '1rem' }}>
          Standings
        </div>

        {standingRows.length === 0 && (
          <div style={{ color: 'var(--text-muted)', fontSize: '0.88rem', padding: '0.5rem' }}>Loading standings...</div>
        )}

        {!isMobile && (
          <div style={{
            display: 'grid', gridTemplateColumns: '1fr 60px 60px 70px',
            gap: '0.5rem', padding: '0.3rem 0.5rem',
            fontSize: '0.68rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', fontWeight: '700'
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
                padding: '0.6rem 0.7rem',
                borderRadius: '8px',
                background: isSharks ? 'rgba(4, 101, 104, 0.08)' : 'rgba(255,255,255,0.03)',
                border: isSharks ? '1px solid rgba(4, 101, 104, 0.2)' : '1px solid rgba(255,255,255,0.06)',
                marginBottom: '0.4rem'
              }}>
                <div style={{ fontWeight: isSharks ? '700' : '600', color: isSharks ? 'var(--primary-color)' : 'var(--text-main)', fontSize: '0.92rem' }}>
                  {isSharks ? 'SHARKS' : `${i + 1}.`} {formatTeamName(team)}
                </div>
                <div style={{ marginTop: '0.2rem', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                  {team.w}-{team.l} · {team.record} · {team.pct != null ? (team.pct === 1 ? '1.000' : team.pct.toFixed(3)) : '—'}
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
              <span style={{ fontWeight: isSharks ? '700' : '500', color: isSharks ? 'var(--primary-color)' : 'var(--text-main)', fontSize: '0.9rem' }}>
                {isSharks ? 'SHARKS ' : `${i + 1}. `}{formatTeamName(team)}
              </span>
              <span style={{ textAlign: 'center', fontWeight: '600', fontSize: '0.9rem' }}>{team.w}-{team.l}</span>
              <span style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                {team.pct != null ? (team.pct === 1 ? '1.000' : team.pct.toFixed(3)) : '—'}
              </span>
              <span style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.8rem' }}>{team.record}</span>
            </div>
          );
        })}
      </div>

      {/* Opponent cards */}
      {opponents.length > 0 && (
        <>
          <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px', fontWeight: '700', marginBottom: '0.75rem' }}>
            Opponent Scouting ({opponents.length} teams)
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(auto-fill, minmax(260px, 1fr))', gap: '1rem' }}>
            {opponents.map(opp => {
              const isExpanded = expanded === opp.slug;
              const standRow = standingRows.find(s => s.slug === opp.slug);
              return (
                <div
                  key={opp.slug}
                  className="glass-panel"
                  style={{ padding: '1.25rem', cursor: 'pointer' }}
                  onClick={() => setExpanded(isExpanded ? null : opp.slug)}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                      <h3 style={{ fontSize: '1rem', margin: '0 0 0.25rem' }}>{opp.team_name}</h3>
                      <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                        {standRow?.record && (
                          <span style={{
                            fontSize: '0.75rem', fontWeight: '700', padding: '2px 8px',
                            borderRadius: '10px',
                            background: parseInt(standRow.w) > parseInt(standRow.l) ? 'rgba(35,134,54,0.15)' : parseInt(standRow.w) < parseInt(standRow.l) ? 'rgba(220,70,70,0.15)' : 'rgba(255,255,255,0.1)',
                            color: parseInt(standRow.w) > parseInt(standRow.l) ? 'var(--success)' : parseInt(standRow.w) < parseInt(standRow.l) ? 'var(--danger)' : 'var(--text-muted)'
                          }}>{standRow.record}</span>
                        )}
                        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                          <Users size={11} style={{ display: 'inline', marginRight: '3px', verticalAlign: 'middle' }} />
                          {opp.roster_size} players
                        </span>
                      </div>
                    </div>
                    {isExpanded ? <ChevronUp size={16} color="var(--text-muted)" /> : <ChevronDown size={16} color="var(--text-muted)" />}
                  </div>

                  {isExpanded && opp.roster_size > 0 && (
                    <OpponentRoster slug={opp.slug} />
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

const OpponentRoster = ({ slug }) => {
  const [roster, setRoster] = useState(null);

  useEffect(() => {
    fetch(`/api/opponents/${slug}`)
      .then(r => r.ok ? r.json() : null)
      .then(data => setRoster(data?.roster || []))
      .catch(() => setRoster([]));
  }, [slug]);

  if (roster === null) return <div className="loader" style={{ width: '20px', height: '20px', margin: '0.75rem auto' }}></div>;

  return (
    <div style={{ marginTop: '1rem', paddingTop: '0.75rem', borderTop: '1px solid var(--surface-border)' }}>
      <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', fontWeight: '700', marginBottom: '0.5rem' }}>
        Roster
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem' }}>
        {roster.map((p, i) => (
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
  );
};

export default League;
