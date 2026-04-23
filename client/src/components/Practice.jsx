import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Dumbbell, RefreshCw, Users, Target } from 'lucide-react';
import { TipBadge } from './StatTooltip';
import { formatDateMMDDYYYY } from '../utils/formatDate';
import OpponentFieldMap from './OpponentFieldMap';

const sourceLabel = (src) => {
  if (src === 'practice_rsvp') return 'Current/next practice RSVP';
  if (src === 'availability') return 'Availability defaults';
  return 'Full roster default';
};

/** Pick a simple emoji icon based on drill name keywords */
const drillIcon = (name = '') => {
  const n = name.toLowerCase();
  if (/bat|hit|swing|slug|contact|tee/.test(n)) return '\u26be';
  if (/run|base.*run|sprint|steal|lead/.test(n)) return '\ud83c\udfc3';
  if (/field|glove|catch|ground|fly|throw|backup/.test(n)) return '\ud83e\udde4';
  return '\ud83c\udfaf';
};

const NeedCard = ({ need }) => (
  <div className="glass-panel" style={{ padding: 'var(--space-lg)' }}>
    {/* Header: priority + title on one line */}
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem', flexWrap: 'wrap' }}>
      <span style={{
        background: 'rgba(4, 101, 104, 0.18)', border: '1px solid rgba(4, 101, 104, 0.35)',
        color: 'var(--primary-color)', borderRadius: '999px', padding: '2px 10px',
        fontSize: 'var(--text-xs)', fontWeight: '800',
      }}>
        P{need.priority}
      </span>
      <h3 style={{ margin: 0, fontSize: 'var(--text-sm)', fontWeight: '700', flex: 1 }}>{need.title}</h3>
    </div>

    <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', margin: '0 0 0.5rem', lineHeight: '1.4' }}>{need.why}</p>

    {need.focus_players?.length > 0 && (
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.25rem', marginBottom: '0.5rem' }}>
        {need.focus_players.map((p, i) => (
          <span key={`${p}-${i}`} style={{
            background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.12)',
            borderRadius: '6px', padding: '2px 7px', fontSize: 'var(--text-xs)', color: 'var(--text-main)',
          }}>{p}</span>
        ))}
      </div>
    )}

    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
      {(need.drills || []).map((drill, idx) => (
        <div key={`${drill.name}-${idx}`} style={{
          background: 'rgba(0,0,0,0.2)', border: '1px solid rgba(255,255,255,0.08)',
          borderRadius: '6px', padding: '0.4rem 0.55rem',
        }}>
          <div style={{ fontSize: 'var(--text-xs)', fontWeight: '700' }}>
            <span style={{ marginRight: '0.25rem' }}>{drillIcon(drill.name)}</span>
            {drill.name}
            <span style={{ fontWeight: '500', color: 'var(--text-muted)', marginLeft: '0.3rem' }}>({drill.duration_min}m)</span>
          </div>
          {drill.goal && <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '0.15rem' }}>{drill.goal}</div>}
        </div>
      ))}
    </div>
  </div>
);

/** Numbered circle for session build items */
const NumberCircle = ({ n }) => (
  <span style={{
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
    width: '1.6rem', height: '1.6rem', borderRadius: '50%', flexShrink: 0,
    background: 'var(--primary-color)', color: '#03283a',
    fontSize: 'var(--text-xs)', fontWeight: '800', lineHeight: 1,
  }}>
    {n}
  </span>
);

const SessionItem = ({ item, index }) => (
  <div style={{
    background: 'rgba(0,0,0,0.2)', border: '1px solid rgba(255,255,255,0.08)',
    borderRadius: '7px', padding: '0.55rem 0.65rem',
    display: 'flex', alignItems: 'flex-start', gap: '0.6rem',
  }}>
    <NumberCircle n={index + 1} />
    <div style={{ flex: 1 }}>
      <div style={{ fontWeight: '700', fontSize: 'var(--text-sm)' }}>
        <span style={{ marginRight: '0.3rem' }}>{drillIcon(item.drill)}</span>
        {item.drill}
        <span style={{ color: 'var(--text-muted)', fontWeight: '500', marginLeft: '0.4rem' }}>({item.duration_min} min)</span>
      </div>
      <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{item.need} — {item.goal}</div>
    </div>
  </div>
);

const Practice = ({ team, schedule, isMobile = false, isLandscape = false }) => {
  const [insights, setInsights] = useState(null);
  const [selected, setSelected] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [initialLoaded, setInitialLoaded] = useState(false);
  const debounceRef = useRef(null);

  // ── Opponent field map: fetch matchup for the next scheduled game ──
  const [nextMatchup, setNextMatchup] = useState(null);
  useEffect(() => {
    const nextGame = (schedule?.upcoming || [])[0];
    if (!nextGame?.opponent) return;
    const opponentName = nextGame.opponent;
    // Fetch opponents list to resolve slug, then fetch matchup
    fetch('/api/opponents')
      .then(r => r.ok ? r.json() : [])
      .then(opponents => {
        const match = opponents.find(o =>
          o.team_name.toLowerCase() === opponentName.toLowerCase() ||
          o.slug === opponentName.toLowerCase().replace(/ /g, '_')
        );
        if (!match?.slug) return;
        return fetch(`/api/matchup/${match.slug}`).then(r => r.ok ? r.json() : null);
      })
      .then(data => { if (data) setNextMatchup(data); })
      .catch(() => {/* silent — non-critical */});
  }, [schedule]);

  // Core roster names from team prop (used to default-select ALL Sharks players)
  const coreRosterNames = useMemo(() => {
    if (!team?.roster) return [];
    return team.roster.filter(p => p.core !== false).map(p => `${p.first || ''} ${p.last || ''}`.trim()).filter(Boolean);
  }, [team]);

  const availablePlayers = useMemo(() => {
    const all = insights?.available_players || [];
    // Only show core Sharks players (no borrowed/subs from other teams)
    if (coreRosterNames.length > 0) {
      const coreSet = new Set(coreRosterNames);
      return all.filter(n => coreSet.has(n)).sort((a, b) => a.localeCompare(b));
    }
    return [...all].sort((a, b) => a.localeCompare(b));
  }, [insights, coreRosterNames]);

  const fetchInsights = async () => {
    setLoading(true);
    setError('');
    try {
      // Dynamic endpoint — nothing writes practice_insights.json to disk.
      const url = '/api/practice-insights';
      const res = await fetch(url);
      if (!res.ok) throw new Error(`practice insights status ${res.status}`);
      const data = await res.json();
      setInsights(data);
      // On initial load, default to all core roster if available; otherwise use API default
      if (!initialLoaded) {
        const allPlayers = data.available_players || [];
        if (coreRosterNames.length > 0) {
          const coreSet = new Set(coreRosterNames);
          const defaultSelected = allPlayers.filter(n => coreSet.has(n));
          setSelected(defaultSelected.length > 0 ? defaultSelected : allPlayers);
        } else {
          setSelected(allPlayers);
        }
        setInitialLoaded(true);
      }
      // If preserveSelection is true (user toggled checkboxes), keep current selection
    } catch (e) {
      console.error('Failed to load practice insights', e);
      setError('Failed to load practice insights');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchInsights();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-fetch selecting all core roster once team data arrives (if initial fetch already ran)
  useEffect(() => {
    if (initialLoaded && coreRosterNames.length > 0 && availablePlayers.length > 0) {
      const coreSet = new Set(coreRosterNames);
      const shouldSelect = availablePlayers.filter(n => coreSet.has(n));
      if (shouldSelect.length > 0 && shouldSelect.length !== selected.length) {
        setSelected(shouldSelect);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [coreRosterNames]);

  const toggle = (name) => {
    setSelected(prev => prev.includes(name) ? prev.filter(x => x !== name) : [...prev, name]);
  };

  const selectAll = () => setSelected(availablePlayers);
  const clearAll = () => setSelected([]);

  // Auto-tailor: debounce 500ms after selected players change
  const isFirstRender = useRef(true);
  useEffect(() => {
    // Skip the very first render and skip while initial data is loading
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    if (!initialLoaded) return;

    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      fetchInsights();
    }, 500);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  const nextPracticeText = (() => {
    const meta = insights?.practice_meta || {};
    if (meta?.date) {
      const formatted = formatDateMMDDYYYY(meta.date);
      return `${meta.title ? `${meta.title} — ` : ''}${formatted}`;
    }
    const nextGame = (schedule?.upcoming || [])[0];
    if (nextGame) {
      const dateStr = nextGame.date ? ` on ${formatDateMMDDYYYY(nextGame.date)}` : '';
      return `No practice RSVP found; planning from roster/availability before next event (${nextGame.opponent}${dateStr})`;
    }
    return 'No practice date metadata found';
  })();

  return (
    <div>
      <h2 className="view-title">
        <Dumbbell size={isMobile ? 20 : 24} color="var(--primary-color)" /> Practice Priorities
      </h2>

      <div className="glass-panel" style={{ padding: isMobile ? 'var(--space-lg)' : '1rem 1.25rem', marginBottom: 'var(--space-md)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem' }}>
          <div>
            <div className="section-label" style={{ marginBottom: '0.15rem' }}>Tailored Session Target</div>
            <div style={{ fontSize: 'var(--text-sm)', color: 'var(--text-main)', marginTop: '0.15rem' }}>{nextPracticeText}</div>
            <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
              Default selection source: {sourceLabel(insights?.default_player_source)}
            </div>
          </div>

          <button
            onClick={() => fetchInsights()}
            disabled={loading}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
              background: 'var(--primary-glow)', color: 'var(--primary-color)', border: '1px solid rgba(4, 101, 104, 0.27)',
              padding: '0.5rem 0.85rem', borderRadius: '8px', cursor: loading ? 'not-allowed' : 'pointer', fontWeight: '600',
              minHeight: 'var(--touch-min)',
            }}
          >
            <RefreshCw size={14} className={loading ? 'spin-smooth' : ''} />
            Refresh
          </button>
        </div>
      </div>

      <div className="glass-panel" style={{ padding: isMobile ? 'var(--space-lg)' : '1rem 1.25rem', marginBottom: 'var(--space-md)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <Users size={16} color="var(--primary-color)" />
            <span style={{ fontWeight: '700' }}>Players At Practice</span>
            <span style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)' }}>({selected.length}/{availablePlayers.length})</span>
          </div>
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
            <button onClick={selectAll} style={{ background: 'rgba(255,255,255,0.06)', color: 'var(--text-main)', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '6px', padding: '0.5rem 0.625rem', cursor: 'pointer', fontSize: 'var(--text-xs)', minHeight: 'var(--touch-min)' }}>All</button>
            <button onClick={clearAll} style={{ background: 'rgba(255,255,255,0.06)', color: 'var(--text-main)', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '6px', padding: '0.5rem 0.625rem', cursor: 'pointer', fontSize: 'var(--text-xs)', minHeight: 'var(--touch-min)' }}>None</button>
          </div>
        </div>

        <div style={{ marginTop: '0.75rem', display: 'grid', gridTemplateColumns: isLandscape ? 'repeat(auto-fill, minmax(160px, 1fr))' : isMobile ? '1fr' : 'repeat(auto-fill, minmax(190px, 1fr))', gap: isLandscape ? '0.3rem' : '0.4rem' }}>
          {availablePlayers.map(name => (
            <label key={name} style={{
              display: 'flex', alignItems: 'center', gap: '0.5rem', background: selected.includes(name) ? 'rgba(4, 101, 104, 0.11)' : 'rgba(255,255,255,0.03)',
              border: selected.includes(name) ? '1px solid rgba(4, 101, 104, 0.32)' : '1px solid rgba(255,255,255,0.08)', borderRadius: '7px',
              padding: '0.625rem 0.75rem', cursor: 'pointer', minHeight: 'var(--touch-min)',
            }}>
              <input type="checkbox" checked={selected.includes(name)} onChange={() => toggle(name)} />
              <span style={{ fontSize: 'var(--text-sm)' }}>{name}</span>
            </label>
          ))}
        </div>
      </div>

      {error && (
        <div
          className="glass-panel"
          onClick={() => fetchInsights()}
          style={{
            padding: 'var(--space-lg)', marginBottom: 'var(--space-md)', cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: '0.75rem',
            background: 'rgba(179, 74, 57, 0.12)', border: '1px solid rgba(179, 74, 57, 0.3)',
          }}
        >
          <RefreshCw size={16} color="var(--danger)" />
          <span style={{ color: 'var(--danger)', fontSize: 'var(--text-sm)', fontWeight: '600' }}>
            Could not load practice data. Tap to retry.
          </span>
        </div>
      )}

      {insights && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', marginBottom: 'var(--space-sm)' }}>
            <Target size={16} color="var(--primary-color)" />
            <span className="section-label" style={{ marginBottom: 0 }}>Most Needed Practice Work</span>
          </div>

          <div className="card-grid" style={{ marginBottom: 'var(--space-md)' }}>
            {(insights.needs || []).slice(0, isMobile ? 3 : undefined).map(need => <NeedCard key={need.key} need={need} />)}
          </div>

          {/* ── Defensive Prep: opponent hit-zone heatmap for next game ── */}
          {nextMatchup && !nextMatchup.empty && (
            <div className="glass-panel" style={{ padding: isMobile ? 'var(--space-lg)' : '1rem 1.25rem', marginBottom: 'var(--space-md)' }}>
              <OpponentFieldMap matchup={nextMatchup} isMobile={isMobile} />
            </div>
          )}

          {!isMobile && (
            <div className="glass-panel" style={{ padding: '1rem 1.25rem' }}>
              <div className="section-label">Session Build (Top 3 Needs)</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem' }}>
                {(insights.recommended_plan || []).map((item, i) => (
                  <SessionItem key={`${item.drill}-${i}`} item={item} index={i} />
                ))}
              </div>
            </div>
          )}

          {isMobile && (
            <details className="glass-panel" style={{ padding: 'var(--space-lg)' }}>
              <summary style={{ cursor: 'pointer', color: 'var(--primary-color)', fontWeight: 700, fontSize: 'var(--text-sm)' }}>
                Session Build (Top 3 Needs)
              </summary>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.45rem', marginTop: '0.55rem' }}>
                {(insights.recommended_plan || []).map((item, i) => (
                  <SessionItem key={`${item.drill}-${i}`} item={item} index={i} />
                ))}
              </div>
            </details>
          )}
        </>
      )}

      {!insights && !loading && <p style={{ color: 'var(--text-muted)' }}>Loading practice insights...</p>}
      {!team && <p style={{ color: 'var(--text-muted)' }}>Team data is still loading.</p>}
    </div>
  );
};

export default Practice;
