import React, { useEffect, useMemo, useState } from 'react';
import { Dumbbell, RefreshCw, Users, Target } from 'lucide-react';

const sourceLabel = (src) => {
  if (src === 'practice_rsvp') return 'Current/next practice RSVP';
  if (src === 'availability') return 'Availability defaults';
  return 'Full roster default';
};

const NeedCard = ({ need }) => (
  <div className="glass-panel" style={{ padding: '1rem' }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', marginBottom: '0.6rem', alignItems: 'center' }}>
      <div>
        <div style={{ fontSize: '0.68rem', color: 'var(--primary-color)', textTransform: 'uppercase', letterSpacing: '0.8px', fontWeight: '700' }}>
          Priority {need.priority}
        </div>
        <h3 style={{ margin: '0.2rem 0 0', fontSize: '1.02rem' }}>{need.title}</h3>
      </div>
      <span style={{
        background: 'rgba(0,210,255,0.09)', border: '1px solid rgba(0,210,255,0.25)',
        color: 'var(--primary-color)', borderRadius: '999px', padding: '2px 10px', fontSize: '0.8rem', fontWeight: '700'
      }}>
        Score {need.score}
      </span>
    </div>

    <p style={{ fontSize: '0.86rem', color: 'var(--text-muted)', margin: '0 0 0.65rem' }}>{need.why}</p>

    {need.focus_players?.length > 0 && (
      <div style={{ marginBottom: '0.65rem' }}>
        <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '0.35rem' }}>
          Focus Players
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem' }}>
          {need.focus_players.map((p, i) => (
            <span key={`${p}-${i}`} style={{
              background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.12)',
              borderRadius: '6px', padding: '2px 8px', fontSize: '0.78rem', color: 'var(--text-main)'
            }}>{p}</span>
          ))}
        </div>
      </div>
    )}

    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
      {(need.drills || []).map((drill, idx) => (
        <div key={`${drill.name}-${idx}`} style={{
          background: 'rgba(0,0,0,0.2)', border: '1px solid rgba(255,255,255,0.08)',
          borderRadius: '8px', padding: '0.55rem 0.65rem'
        }}>
          <div style={{ fontSize: '0.88rem', fontWeight: '700' }}>{drill.name}</div>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{drill.duration_min} min · {drill.goal}</div>
        </div>
      ))}
    </div>
  </div>
);

const Practice = ({ team, schedule }) => {
  const [insights, setInsights] = useState(null);
  const [selected, setSelected] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const availablePlayers = useMemo(() => insights?.available_players || [], [insights]);

  const fetchInsights = async (players = null) => {
    setLoading(true);
    setError('');
    try {
      const opts = players
        ? {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ players })
          }
        : undefined;
      const res = await fetch('/api/practice-insights', opts);
      if (!res.ok) throw new Error(`practice insights status ${res.status}`);
      const data = await res.json();
      setInsights(data);
      if (!players) setSelected(data.selected_players || []);
    } catch (e) {
      console.error(e);
      setError('Failed to load practice insights');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchInsights();
  }, []);

  const toggle = (name) => {
    setSelected(prev => prev.includes(name) ? prev.filter(x => x !== name) : [...prev, name]);
  };

  const selectAll = () => setSelected(availablePlayers);
  const clearAll = () => setSelected([]);

  const applySelection = async () => {
    await fetchInsights(selected);
  };

  const nextPracticeText = (() => {
    const meta = insights?.practice_meta || {};
    if (meta?.date) {
      const d = new Date(meta.date + 'T12:00:00');
      const ds = d.toLocaleDateString('en-US', { timeZone: 'America/New_York', weekday: 'short', month: 'short', day: 'numeric' });
      return `${meta.title ? `${meta.title} · ` : ''}${ds}`;
    }
    const nextGame = (schedule?.upcoming || [])[0];
    if (nextGame) return `No practice RSVP found; planning from roster/availability before next event (${nextGame.opponent})`;
    return 'No practice date metadata found';
  })();

  return (
    <div>
      <h2 style={{ marginBottom: '1.25rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <Dumbbell size={24} color="var(--primary-color)" /> Practice Priorities
      </h2>

      <div className="glass-panel" style={{ padding: '1rem 1.25rem', marginBottom: '1rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem' }}>
          <div>
            <div style={{ fontSize: '0.7rem', color: 'var(--primary-color)', textTransform: 'uppercase', letterSpacing: '0.8px', fontWeight: '700' }}>
              Tailored Session Target
            </div>
            <div style={{ fontSize: '0.92rem', color: 'var(--text-main)', marginTop: '0.15rem' }}>{nextPracticeText}</div>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
              Default selection source: {sourceLabel(insights?.default_player_source)}
            </div>
          </div>

          <button
            onClick={() => fetchInsights()}
            disabled={loading}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
              background: 'var(--primary-glow)', color: 'var(--primary-color)', border: '1px solid rgba(0,210,255,0.25)',
              padding: '0.45rem 0.85rem', borderRadius: '8px', cursor: loading ? 'not-allowed' : 'pointer', fontWeight: '600'
            }}
          >
            <RefreshCw size={14} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
            Refresh
          </button>
        </div>
      </div>

      <div className="glass-panel" style={{ padding: '1rem 1.25rem', marginBottom: '1rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <Users size={16} color="var(--primary-color)" />
            <span style={{ fontWeight: '700' }}>Players At Practice</span>
            <span style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>({selected.length}/{availablePlayers.length})</span>
          </div>
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
            <button onClick={selectAll} style={{ background: 'rgba(255,255,255,0.06)', color: 'var(--text-main)', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '6px', padding: '0.3rem 0.55rem', cursor: 'pointer', fontSize: '0.78rem' }}>All</button>
            <button onClick={clearAll} style={{ background: 'rgba(255,255,255,0.06)', color: 'var(--text-main)', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '6px', padding: '0.3rem 0.55rem', cursor: 'pointer', fontSize: '0.78rem' }}>None</button>
            <button onClick={applySelection} disabled={loading || selected.length === 0} style={{ background: 'var(--primary-color)', color: '#03283a', border: 'none', borderRadius: '6px', padding: '0.3rem 0.7rem', cursor: loading ? 'not-allowed' : 'pointer', fontSize: '0.78rem', fontWeight: '700' }}>Tailor Plan</button>
          </div>
        </div>

        <div style={{ marginTop: '0.75rem', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(190px, 1fr))', gap: '0.4rem' }}>
          {availablePlayers.map(name => (
            <label key={name} style={{
              display: 'flex', alignItems: 'center', gap: '0.5rem', background: selected.includes(name) ? 'rgba(0,210,255,0.08)' : 'rgba(255,255,255,0.03)',
              border: selected.includes(name) ? '1px solid rgba(0,210,255,0.3)' : '1px solid rgba(255,255,255,0.08)', borderRadius: '7px', padding: '0.35rem 0.5rem', cursor: 'pointer'
            }}>
              <input type="checkbox" checked={selected.includes(name)} onChange={() => toggle(name)} />
              <span style={{ fontSize: '0.84rem' }}>{name}</span>
            </label>
          ))}
        </div>
      </div>

      {error && <p style={{ color: 'var(--danger)' }}>{error}</p>}

      {insights && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', marginBottom: '0.75rem' }}>
            <Target size={16} color="var(--primary-color)" />
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.7px', fontWeight: '700' }}>
              Most Needed Practice Work
            </span>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(330px, 1fr))', gap: '0.85rem', marginBottom: '1rem' }}>
            {(insights.needs || []).map(need => <NeedCard key={need.key} need={need} />)}
          </div>

          <div className="glass-panel" style={{ padding: '1rem 1.25rem' }}>
            <div style={{ fontSize: '0.7rem', color: 'var(--primary-color)', textTransform: 'uppercase', letterSpacing: '0.8px', fontWeight: '700', marginBottom: '0.6rem' }}>
              Session Build (Top 3 Needs)
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem' }}>
              {(insights.recommended_plan || []).map((item, i) => (
                <div key={`${item.drill}-${i}`} style={{ background: 'rgba(0,0,0,0.2)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '7px', padding: '0.55rem 0.65rem' }}>
                  <div style={{ fontWeight: '700', fontSize: '0.9rem' }}>{i + 1}. {item.drill} <span style={{ color: 'var(--text-muted)', fontWeight: '500' }}>({item.duration_min} min)</span></div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{item.need} · {item.goal}</div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      {!insights && !loading && <p style={{ color: 'var(--text-muted)' }}>Loading practice insights...</p>}
      {!team && <p style={{ color: 'var(--text-muted)' }}>Team data is still loading.</p>}
    </div>
  );
};

export default Practice;
