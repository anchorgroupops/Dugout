import React, { useState, useEffect } from 'react';
import { Target, Shield, Swords, AlertTriangle, Calendar, MapPin } from 'lucide-react';
import { formatDateMMDDYYYY } from '../utils/formatDate';
import { fetchSharedJson } from '../utils/apiClient';

const BulletCard = ({ title, items, color, icon, emptyText }) => (
  <div className="glass-panel" style={{ padding: 'var(--space-lg)', marginBottom: 'var(--space-sm)' }}>
    <h4 className="swot-label" style={{ color, margin: '0 0 0.5rem 0' }}>
      {icon} {title}
    </h4>
    {items?.length > 0 ? (
      <ul style={{ paddingLeft: '1.2rem', fontSize: 'var(--text-sm)', color: 'var(--text-muted)', margin: 0 }}>
        {items.slice(0, 4).map((s, i) => (
          <li key={i} style={{ marginBottom: '3px' }}>{s}</li>
        ))}
      </ul>
    ) : (
      <p style={{ fontSize: 'var(--text-sm)', color: 'rgba(255,255,255,0.3)', fontStyle: 'italic', margin: 0 }}>
        {emptyText || 'Insufficient data'}
      </p>
    )}
  </div>
);

export default function Scouting({ isMobile, isLandscape = false }) {
  const [nextGame, setNextGame] = useState(null);
  const [matchup, setMatchup] = useState(null);
  const [h2h, setH2h] = useState(null);
  const [opponents, setOpponents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    Promise.all([
      fetchSharedJson('/api/next-game', { fallback: null }),
      fetchSharedJson('/api/opponents', { fallback: [] }),
    ]).then(([nextData, opps]) => {
      setNextGame(nextData);
      setOpponents(Array.isArray(opps) ? opps : []);
      if (nextData?.slug) {
        return Promise.all([
          fetchSharedJson(`/api/matchup/${nextData.slug}`, { fallback: null }),
          fetchSharedJson(`/api/h2h/${nextData.slug}`, { fallback: null }),
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

  const recommendation = matchup?.recommendation || '';
  const isInsufficient = matchup?.empty;

  return (
    <div className="animate-fade-in">
      {/* No upcoming game banner */}
      {!nextGame?.opponent && (
        <div className="glass-panel" style={{ padding: 'var(--space-lg)', textAlign: 'center', marginBottom: 'var(--space-md)' }}>
          <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)' }}>
            No upcoming games scheduled — scouting reports available below.
          </p>
        </div>
      )}

      {/* Header card — only when there is an upcoming game */}
      {nextGame?.opponent && (
      <div className="glass-panel" style={{
        padding: isMobile ? 'var(--space-lg)' : '1.5rem 1.25rem',
        marginBottom: 'var(--space-md)',
        textAlign: 'center',
      }}>
        <p className="section-label" style={{
          marginBottom: '0.5rem',
          fontSize: 'var(--text-sm)',
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
        }}>
          Next Opponent
        </p>

        {/* Team logo placeholder + opponent name */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '0.75rem',
          marginBottom: '0.6rem',
        }}>
          <div style={{
            width: isMobile ? 44 : 56,
            height: isMobile ? 44 : 56,
            borderRadius: '50%',
            background: 'linear-gradient(135deg, rgba(179, 74, 57, 0.25), rgba(220, 70, 70, 0.12))',
            border: '2px solid rgba(179, 74, 57, 0.35)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: isMobile ? '1.2rem' : '1.5rem',
            fontWeight: '800',
            color: 'var(--danger)',
            fontFamily: 'var(--font-heading)',
            flexShrink: 0,
            letterSpacing: '-0.02em',
          }}>
            {nextGame.opponent?.charAt(0) || '?'}
          </div>
          <h2 style={{
            fontSize: isMobile ? '1.6rem' : '2rem',
            fontFamily: 'var(--font-heading)',
            color: 'var(--text-main)',
            margin: 0,
            letterSpacing: '-0.01em',
            lineHeight: 1.1,
          }}>
            {nextGame.opponent}
          </h2>
        </div>

        <div style={{ display: 'flex', justifyContent: 'center', gap: '1rem', fontSize: 'var(--text-sm)', color: 'var(--text-muted)', flexWrap: 'wrap' }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}>
            <Calendar size={14} /> {formatDateMMDDYYYY(nextGame.date)}
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

        {/* Data source indicator */}
        {matchup?.data_source && (
          <p style={{
            marginTop: '0.5rem',
            marginBottom: 0,
            fontSize: 'var(--text-xs)',
            color: 'rgba(255,255,255,0.35)',
            fontStyle: 'italic',
          }}>
            Source: {matchup.data_source}
          </p>
        )}
      </div>
      )}

      {isInsufficient ? (
        <div className="glass-panel" style={{ padding: 'var(--space-lg)', textAlign: 'center' }}>
          <AlertTriangle size={20} style={{ color: 'var(--warning)', marginBottom: '0.5rem' }} />
          <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)', margin: 0 }}>
            Not enough historical data for this opponent to generate a stat-based scouting report.
          </p>
        </div>
      ) : matchup ? (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: (isMobile && !isLandscape) ? '1fr' : '1fr 1fr', gap: 'var(--space-sm)' }}>
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
            <div className="glass-panel" style={{ padding: 'var(--space-lg)', marginBottom: 'var(--space-sm)' }}>
              <h4 className="swot-label" style={{ color: 'var(--primary-color)', margin: '0 0 0.4rem 0' }}>
                <Target size={16} /> Strategy
              </h4>
              <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-main)', margin: 0, lineHeight: '1.5' }}>
                {recommendation}
              </p>
            </div>
          )}

          {h2h && h2h.games_played > 0 && (
            <div className="glass-panel" style={{ padding: 'var(--space-lg)', marginBottom: 'var(--space-sm)' }}>
              <h4 className="swot-label" style={{ color: 'var(--primary-color)', margin: '0 0 0.5rem 0' }}>
                <Calendar size={16} /> History vs. {nextGame.opponent}
              </h4>
              <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-main)', fontWeight: '700', margin: '0 0 0.4rem 0' }}>
                {h2h.record} ({h2h.games_played} games) &mdash; Avg {h2h.avg_runs_for}-{h2h.avg_runs_against}
              </p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
                {h2h.games.slice(0, 5).map((g, i) => (
                  <span key={i} style={{
                    fontSize: 'var(--text-xs)',
                    padding: '4px 10px',
                    borderRadius: '999px',
                    background: g.result === 'W' ? 'rgba(47,143,98,0.2)' : g.result === 'L' ? 'rgba(179,74,57,0.2)' : 'rgba(255,255,255,0.08)',
                    color: g.result === 'W' ? 'var(--success)' : g.result === 'L' ? 'var(--danger)' : 'var(--text-muted)',
                    border: `1px solid ${g.result === 'W' ? 'rgba(47,143,98,0.3)' : g.result === 'L' ? 'rgba(179,74,57,0.3)' : 'rgba(255,255,255,0.12)'}`,
                  }}>
                    {g.result} {g.runs_for}-{g.runs_against} ({formatDateMMDDYYYY(g.date)})
                  </span>
                ))}
              </div>
            </div>
          )}
        </>
      ) : (
        nextGame?.opponent && (
          <div className="glass-panel" style={{ padding: 'var(--space-lg)', textAlign: 'center' }}>
            <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)', margin: 0 }}>
              No scouting data available for this opponent.
            </p>
          </div>
        )
      )}

      {/* All-opponents grid — always visible */}
      {opponents.length > 0 && (
        <div style={{ marginTop: 'var(--space-lg)' }}>
          <div className="section-label" style={{ marginBottom: 'var(--space-sm)' }}>
            {nextGame?.opponent ? 'All Division Opponents' : 'Division Opponents'}
          </div>
          <div className="card-grid">
            {opponents.map(opp => {
              const m = opp.public_game_metrics || {};
              const rec = typeof opp.record === 'string' ? opp.record
                : opp.record ? `${opp.record.w || 0}-${opp.record.l || 0}` : null;
              const isNext = nextGame?.slug && (nextGame.slug === opp.slug || nextGame.opponent?.toLowerCase().includes(opp.slug));
              return (
                <div key={opp.slug} className="glass-panel" style={{
                  padding: 'var(--space-lg)',
                  borderLeft: isNext ? '3px solid var(--danger)' : undefined,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.5rem' }}>
                    <div>
                      <div style={{ fontWeight: '700', fontSize: 'var(--text-base)' }}>{opp.team_name}</div>
                      {isNext && <span style={{ fontSize: 'var(--text-xs)', color: 'var(--danger)', fontWeight: '600' }}>NEXT OPPONENT</span>}
                    </div>
                    {rec && (
                      <span style={{
                        fontSize: 'var(--text-sm)', fontWeight: '700',
                        color: 'var(--text-muted)', background: 'rgba(255,255,255,0.06)',
                        borderRadius: '6px', padding: '2px 8px', border: '1px solid rgba(255,255,255,0.1)',
                      }}>{rec}</span>
                    )}
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem' }}>
                    {m.avg_runs_scored != null && (
                      <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '4px', padding: '2px 7px' }}>
                        R/G: {typeof m.avg_runs_scored === 'number' ? m.avg_runs_scored.toFixed(1) : m.avg_runs_scored}
                      </span>
                    )}
                    {m.avg_runs_allowed != null && (
                      <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '4px', padding: '2px 7px' }}>
                        RA/G: {typeof m.avg_runs_allowed === 'number' ? m.avg_runs_allowed.toFixed(1) : m.avg_runs_allowed}
                      </span>
                    )}
                    {m.errors_per_game != null && (
                      <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '4px', padding: '2px 7px' }}>
                        Err/G: {typeof m.errors_per_game === 'number' ? m.errors_per_game.toFixed(1) : m.errors_per_game}
                      </span>
                    )}
                    {m.big_inning_rate != null && (
                      <span style={{ fontSize: 'var(--text-xs)', color: 'rgba(251,191,36,0.8)', background: 'rgba(251,191,36,0.06)', border: '1px solid rgba(251,191,36,0.15)', borderRadius: '4px', padding: '2px 7px' }}>
                        Big Inn: {typeof m.big_inning_rate === 'number' ? `${(m.big_inning_rate * 100).toFixed(0)}%` : m.big_inning_rate}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
