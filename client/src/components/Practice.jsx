import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Dumbbell, RefreshCw, Users, Target, AlertTriangle } from 'lucide-react';
import { TipBadge } from './StatTooltip';
import { formatDateMMDDYYYY } from '../utils/formatDate';
import OpponentFieldMap from './OpponentFieldMap';
import { fetchSharedJson, getLocalCachedJson, setLocalCachedJson, isPollingPaused } from '../utils/apiClient';

const formatRelativeAge = (iso) => {
  if (!iso) return 'unknown';
  try {
    const ms = Date.now() - new Date(iso).getTime();
    if (!isFinite(ms) || ms < 0) return 'just now';
    const m = Math.round(ms / 60000);
    if (m < 1) return 'just now';
    if (m < 60) return `${m}m ago`;
    const h = Math.round(m / 60);
    if (h < 24) return `${h}h ago`;
    const d = Math.round(h / 24);
    return `${d}d ago`;
  } catch { return 'unknown'; }
};

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
  // Hydrate from localStorage so the priorities section has SOMETHING to show
  // immediately (and stays populated when /api/practice-insights is down).
  const initialCache = (() => {
    const c = getLocalCachedJson('practice-insights');
    return c ? c : null;
  })();
  const [insights, setInsights] = useState(initialCache?.value || null);
  const [insightsFromCache, setInsightsFromCache] = useState(Boolean(initialCache));
  const [insightsCacheAt, setInsightsCacheAt] = useState(initialCache?.savedAt || null);
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
    fetchSharedJson('/api/opponents', { fallback: [] })
      .then(opponents => {
        const list = Array.isArray(opponents) ? opponents : [];
        const match = list.find(o =>
          o.team_name?.toLowerCase() === opponentName.toLowerCase() ||
          o.slug === opponentName.toLowerCase().replace(/ /g, '_')
        );
        if (!match?.slug) return null;
        return fetchSharedJson(`/api/matchup/${match.slug}`, { fallback: null });
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
    const fromApi = insights?.available_players || [];
    // Fall back to team roster when API returns no players
    const all = fromApi.length > 0
      ? fromApi
      : (team?.roster || []).map(p => `${p.first || ''} ${p.last || ''}`.trim()).filter(Boolean);
    // Only show core Sharks players (no borrowed/subs from other teams)
    if (coreRosterNames.length > 0) {
      const coreSet = new Set(coreRosterNames);
      const filtered = all.filter(n => coreSet.has(n));
      return (filtered.length > 0 ? filtered : all).sort((a, b) => a.localeCompare(b));
    }
    return [...all].sort((a, b) => a.localeCompare(b));
  }, [insights, coreRosterNames, team]);

  const fetchInsights = async () => {
    setLoading(true);
    setError('');
    // When apiClient has globally paused polling (recent 429), skip the
    // live call entirely and fall straight through to the cache chain
    // below. This keeps the rate-limit cascade from flaring back up.
    if (isPollingPaused() && (insights || getLocalCachedJson('practice-insights'))) {
      const lc = getLocalCachedJson('practice-insights');
      if (lc?.value) {
        setInsights(lc.value);
        setInsightsFromCache(true);
        setInsightsCacheAt(lc.savedAt || null);
        setLoading(false);
        return;
      }
    }
    try {
      const url = '/api/practice-insights';
      const res = await fetch(url);
      if (!res.ok) throw new Error(`practice insights status ${res.status}`);
      const data = await res.json();
      setInsights(data);
      setInsightsFromCache(false);
      setInsightsCacheAt(null);
      // Persist to localStorage with never-downgrade semantics — only
      // useful payloads (with `needs` or `recommended_plan`) are written.
      const writable = data && (
        (Array.isArray(data.needs) && data.needs.length > 0) ||
        (Array.isArray(data.recommended_plan) && data.recommended_plan.length > 0)
      );
      if (writable) setLocalCachedJson('practice-insights', data);
      // On initial load, default to all core roster if available; otherwise use API default
      if (!initialLoaded) {
        const allPlayers = data.available_players?.length > 0
          ? data.available_players
          : (team?.roster || []).map(p => `${p.first || ''} ${p.last || ''}`.trim()).filter(Boolean);
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
      // Static-file fallback when API and localStorage both empty.
      // (apiClient already restored from LS into `insights` on mount; if
      // we're here and `insights` is still null, hit the static file.)
      try {
        const sRes = await fetch('/data/sharks/practice_insights.json', { cache: 'no-store' });
        if (sRes.ok) {
          const sData = await sRes.json();
          if (Array.isArray(sData?.needs) && sData.needs.length) {
            setInsights(sData);
            setInsightsFromCache(true);
            setInsightsCacheAt(sData.generated_at || null);
            setError('');
            return;
          }
        }
      } catch { /* truly nothing available */ }
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
    return 'Next game: TBD — generating priorities from full roster';
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
            <span style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)' }}>
              {availablePlayers.length === 0 ? '(loading roster…)' : `(${selected.length}/${availablePlayers.length})`}
            </span>
          </div>
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
            <button onClick={selectAll} disabled={availablePlayers.length === 0} style={{ background: 'rgba(255,255,255,0.06)', color: 'var(--text-main)', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '6px', padding: '0.5rem 0.625rem', cursor: availablePlayers.length === 0 ? 'not-allowed' : 'pointer', fontSize: 'var(--text-xs)', minHeight: 'var(--touch-min)', opacity: availablePlayers.length === 0 ? 0.5 : 1 }}>All</button>
            <button onClick={clearAll} disabled={availablePlayers.length === 0} style={{ background: 'rgba(255,255,255,0.06)', color: 'var(--text-main)', border: '1px solid rgba(255,255,255,0.15)', borderRadius: '6px', padding: '0.5rem 0.625rem', cursor: availablePlayers.length === 0 ? 'not-allowed' : 'pointer', fontSize: 'var(--text-xs)', minHeight: 'var(--touch-min)', opacity: availablePlayers.length === 0 ? 0.5 : 1 }}>None</button>
          </div>
        </div>

        {availablePlayers.length === 0 ? (
          <div style={{ marginTop: '0.75rem', display: 'grid', gridTemplateColumns: isLandscape ? 'repeat(auto-fill, minmax(160px, 1fr))' : isMobile ? '1fr' : 'repeat(auto-fill, minmax(190px, 1fr))', gap: isLandscape ? '0.3rem' : '0.4rem' }}>
            {[0, 1, 2, 3, 4, 5].map(i => (
              <div key={i} style={{ height: 'var(--touch-min)', borderRadius: '7px', background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)', opacity: 0.5 + (i % 2) * 0.2 }} />
            ))}
          </div>
        ) : (
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
        )}
      </div>

      {/* Stale-cache banner — when we're showing cached insights because the
          live fetch is failing. Sits ABOVE the cached content rather than
          replacing it, so coaches still see priorities. */}
      {insights && insightsFromCache && error && (
        <div
          onClick={() => fetchInsights()}
          style={{
            display: 'flex', alignItems: 'center', gap: '0.5rem',
            marginBottom: 'var(--space-sm)', padding: '6px 10px', borderRadius: '6px',
            background: 'rgba(168, 116, 33, 0.15)',
            border: '1px solid rgba(168, 116, 33, 0.30)',
            color: 'var(--warning, #facc15)',
            fontSize: 'var(--text-xs)', fontWeight: '700', cursor: 'pointer',
          }}
        >
          <AlertTriangle size={12} />
          <span>Showing cached practice insights (last updated {formatRelativeAge(insightsCacheAt)}) — tap to retry</span>
        </div>
      )}

      {/* Insights error — recoverable empty state. Shown only when the live
          fetch failed AND there's no cached payload to fall back to. The
          dashed border + "Tap to retry" affordance differentiates this from
          a permanent missing-section. */}
      {error && !insights && (
        <div
          className="glass-panel"
          onClick={() => fetchInsights()}
          role="button"
          tabIndex={0}
          aria-label="Practice insights unavailable. Tap to retry."
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') fetchInsights(); }}
          style={{
            padding: 'var(--space-lg)', marginBottom: 'var(--space-md)', cursor: 'pointer',
            display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.5rem',
            background: 'rgba(179, 74, 57, 0.08)',
            border: '2px dashed rgba(179, 74, 57, 0.45)',
            textAlign: 'center',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <RefreshCw size={18} color="var(--danger)" />
            <span style={{ color: 'var(--danger)', fontSize: 'var(--text-base)', fontWeight: '700' }}>
              Practice insights unavailable
            </span>
          </div>
          <span style={{ color: 'var(--text-muted)', fontSize: 'var(--text-xs)' }}>
            No cached priorities on this device. Tap anywhere on this card to retry.
          </span>
        </div>
      )}

      {/* Insights skeleton while loading and we don't yet have cache. */}
      {!insights && !error && loading && (
        <div className="glass-panel" style={{ padding: 'var(--space-lg)', marginBottom: 'var(--space-md)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', marginBottom: 'var(--space-sm)' }}>
            <Target size={16} color="var(--primary-color)" />
            <span className="section-label" style={{ marginBottom: 0 }}>Most Needed Practice Work</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(auto-fill, minmax(220px, 1fr))', gap: '0.5rem' }}>
            {[0, 1, 2].map(i => (
              <div key={i} className="practice-skeleton-shimmer" style={{
                height: '110px', borderRadius: '8px',
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid rgba(255,255,255,0.06)',
                opacity: 0.4 + (i % 3) * 0.15,
              }} />
            ))}
          </div>
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

    </div>
  );
};

export default Practice;
