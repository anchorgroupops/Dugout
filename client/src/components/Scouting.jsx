import React, { useState, useEffect } from 'react';
import { Target, Shield, Swords, AlertTriangle, Calendar, MapPin } from 'lucide-react';

const BulletCard = ({ title, items, color, icon, emptyText }) => (
  <div className="glass-panel" style={{ padding: '1rem', marginBottom: '0.75rem' }}>
    <h4 style={{
      color,
      display: 'flex',
      alignItems: 'center',
      gap: '0.5rem',
      fontSize: '0.85rem',
      marginBottom: '0.5rem',
      fontWeight: '700',
      textTransform: 'uppercase',
      letterSpacing: '0.5px',
      margin: '0 0 0.5rem 0',
    }}>
      {icon} {title}
    </h4>
    {items?.length > 0 ? (
      <ul style={{ paddingLeft: '1.2rem', fontSize: '0.88rem', color: 'var(--text-muted)', margin: 0 }}>
        {items.slice(0, 4).map((s, i) => (
          <li key={i} style={{ marginBottom: '3px' }}>{s}</li>
        ))}
      </ul>
    ) : (
      <p style={{ fontSize: '0.83rem', color: 'rgba(255,255,255,0.3)', fontStyle: 'italic', margin: 0 }}>
        {emptyText || 'Insufficient data'}
      </p>
    )}
  </div>
);

export default function Scouting({ isMobile }) {
  const [nextGame, setNextGame] = useState(null);
  const [matchup, setMatchup] = useState(null);
  const [h2h, setH2h] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    setLoading(true);
    fetch('/api/next-game')
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        setNextGame(data);
        if (data?.slug) {
          return Promise.all([
            fetch(`/api/matchup/${data.slug}`).then(r => r.ok ? r.json() : null),
            fetch(`/api/h2h/${data.slug}`).then(r => r.ok ? r.json() : null),
          ]);
        }
        return [null, null];
      })
      .then(([m, h]) => {
        if (m) setMatchup(m);
        if (h) setH2h(h);
        setLoading(false);
      })
      .catch(() => {
        setError('Failed to load scouting data');
        setLoading(false);
      });
  }, []);

  if (loading) return <div className="loader" />;
  if (error) return <p style={{ color: 'var(--danger)', textAlign: 'center' }}>{error}</p>;
  if (!nextGame?.opponent) {
    return (
      <div className="glass-panel animate-fade-in" style={{ padding: '1.5rem', textAlign: 'center' }}>
        <p style={{ color: 'var(--text-muted)' }}>No upcoming games scheduled.</p>
      </div>
    );
  }

  const recommendation = matchup?.recommendation || '';
  const isInsufficient = matchup?.empty;

  return (
    <div className="animate-fade-in">
      {/* Header card */}
      <div className="glass-panel" style={{
        padding: isMobile ? '1rem' : '1.25rem',
        marginBottom: '1rem',
        textAlign: 'center',
      }}>
        <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px', margin: '0 0 0.3rem 0' }}>
          Next Opponent
        </p>
        <h2 style={{
          fontSize: isMobile ? '1.3rem' : '1.6rem',
          fontFamily: 'var(--font-heading)',
          color: 'var(--text-main)',
          margin: '0 0 0.5rem 0',
        }}>
          {nextGame.opponent}
        </h2>
        <div style={{ display: 'flex', justifyContent: 'center', gap: '1rem', fontSize: '0.82rem', color: 'var(--text-muted)', flexWrap: 'wrap' }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}>
            <Calendar size={14} /> {nextGame.date}
          </span>
          {nextGame.time && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}>
              {nextGame.time}
            </span>
          )}
          {nextGame.home_away && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}>
              <MapPin size={14} /> {nextGame.home_away === 'home' ? 'Home' : 'Away'}
            </span>
          )}
        </div>
      </div>

      {isInsufficient ? (
        <div className="glass-panel" style={{ padding: '1.25rem', textAlign: 'center' }}>
          <AlertTriangle size={20} style={{ color: 'var(--warning)', marginBottom: '0.5rem' }} />
          <p style={{ color: 'var(--text-muted)', fontSize: '0.88rem', margin: 0 }}>
            Not enough historical data for this opponent to generate a stat-based scouting report.
          </p>
        </div>
      ) : matchup ? (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: '0.75rem' }}>
            <BulletCard
              title="Their Strengths"
              items={matchup.their_advantages}
              color="var(--danger)"
              icon={<AlertTriangle size={16} />}
              emptyText="No clear advantages detected"
            />
            <BulletCard
              title="Our Advantages"
              items={matchup.our_advantages}
              color="var(--success)"
              icon={<Shield size={16} />}
              emptyText="No clear advantages detected"
            />
          </div>

          {matchup.key_matchups?.length > 0 && (
            <BulletCard
              title="Key Matchups"
              items={matchup.key_matchups}
              color="var(--primary-color)"
              icon={<Swords size={16} />}
            />
          )}

          {recommendation && (
            <div className="glass-panel" style={{ padding: '1rem', marginBottom: '0.75rem' }}>
              <h4 style={{
                color: 'var(--primary-color)',
                fontSize: '0.85rem',
                fontWeight: '700',
                textTransform: 'uppercase',
                letterSpacing: '0.5px',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                margin: '0 0 0.4rem 0',
              }}>
                <Target size={16} /> Strategy
              </h4>
              <p style={{ fontSize: '0.88rem', color: 'var(--text-main)', margin: 0, lineHeight: '1.5' }}>
                {recommendation}
              </p>
            </div>
          )}

          {h2h && h2h.games_played > 0 && (
            <div className="glass-panel" style={{ padding: '1rem', marginBottom: '0.75rem' }}>
              <h4 style={{
                color: 'var(--primary-color)',
                fontSize: '0.85rem',
                fontWeight: '700',
                textTransform: 'uppercase',
                letterSpacing: '0.5px',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                margin: '0 0 0.5rem 0',
              }}>
                <Calendar size={16} /> History vs. {nextGame.opponent}
              </h4>
              <p style={{ fontSize: '0.92rem', color: 'var(--text-main)', fontWeight: '700', margin: '0 0 0.4rem 0' }}>
                {h2h.record} ({h2h.games_played} games) &mdash; Avg {h2h.avg_runs_for}-{h2h.avg_runs_against}
              </p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
                {h2h.games.slice(0, 5).map((g, i) => (
                  <span key={i} style={{
                    fontSize: '0.75rem',
                    padding: '2px 8px',
                    borderRadius: '999px',
                    background: g.result === 'W' ? 'rgba(47,143,98,0.2)' : g.result === 'L' ? 'rgba(179,74,57,0.2)' : 'rgba(255,255,255,0.08)',
                    color: g.result === 'W' ? 'var(--success)' : g.result === 'L' ? 'var(--danger)' : 'var(--text-muted)',
                    border: `1px solid ${g.result === 'W' ? 'rgba(47,143,98,0.3)' : g.result === 'L' ? 'rgba(179,74,57,0.3)' : 'rgba(255,255,255,0.12)'}`,
                  }}>
                    {g.result} {g.runs_for}-{g.runs_against} ({g.date})
                  </span>
                ))}
              </div>
            </div>
          )}
        </>
      ) : (
        <div className="glass-panel" style={{ padding: '1.25rem', textAlign: 'center' }}>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.88rem', margin: 0 }}>
            No scouting data available for this opponent.
          </p>
        </div>
      )}
    </div>
  );
}
