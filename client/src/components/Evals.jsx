import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ClipboardList, RefreshCw, Target, AlertTriangle, Plus, Trash2, Timer } from 'lucide-react';
import { getLocalCachedJson, setLocalCachedJson, isPollingPaused, apiRequest } from '../utils/apiClient';
import { TipIcon } from './StatTooltip';

const CATEGORY_ICONS = {
  Fielding: '🧤',
  Throwing: '💪',
  Catching: '🦺',
  Pitching: '⚾',
  Speed: '🏃',
  Hitting: '🏏',
};

const STAT_LABELS = {
  'fielding.fpct': 'FPCT', 'fielding.a': 'Assists', 'fielding.e': 'Errors',
  'fielding.po': 'Putouts', 'fielding.dp': 'Double Plays', 'fielding.tc': 'Chances',
  'catching.cs_pct': 'CS%', 'catching.pb': 'Passed Balls', 'catching.sb': 'SB Allowed',
  'pitching_advanced.s_pct': 'Strike%', 'pitching.whip': 'WHIP',
  'pitching_advanced.k_bb': 'K/BB', 'pitching.baa': 'BAA',
  'batting.sb': 'Stolen Bases', 'batting.sb_pct': 'SB%', 'batting.avg': 'AVG',
  'batting.sac': 'Sac Bunts', 'batting_advanced.qab_pct': 'QAB%',
  'batting_advanced.ld_pct': 'LD%', 'batting_advanced.c_pct': 'Contact%',
};

const statLabel = (path) => STAT_LABELS[path] || path;

const fitColor = (fit) => {
  if (fit == null) return 'var(--text-muted)';
  if (fit >= 70) return 'var(--primary-color)';
  if (fit >= 45) return 'var(--warning, #facc15)';
  return 'var(--danger)';
};

const Chip = ({ children, tone = 'neutral' }) => (
  <span style={{
    background: tone === 'primary' ? 'rgba(4, 101, 104, 0.18)' : 'rgba(255,255,255,0.06)',
    border: tone === 'primary' ? '1px solid rgba(4, 101, 104, 0.35)' : '1px solid rgba(255,255,255,0.12)',
    color: tone === 'primary' ? 'var(--primary-color)' : 'var(--text-main)',
    borderRadius: '999px', padding: '2px 8px', fontSize: 'var(--text-xs)', fontWeight: 700,
    whiteSpace: 'nowrap',
  }}>{children}</span>
);

/** One drill card: what it is, how to run it, quick score logger. */
const DrillCard = ({ drill, players, onLog, saving }) => {
  const [open, setOpen] = useState(false);
  const [player, setPlayer] = useState('');
  const [made, setMade] = useState('');
  const [attempts, setAttempts] = useState(drill.default_attempts || 10);
  const [seconds, setSeconds] = useState('');

  const timed = drill.unit === 'seconds';
  const canSave = player && (timed
    ? Number(seconds) > 0
    : Number(attempts) > 0 && made !== '' && Number(made) >= 0 && Number(made) <= Number(attempts));

  const save = () => {
    if (!canSave) return;
    onLog({
      player,
      drill_id: drill.id,
      made: timed ? null : Number(made),
      attempts: timed ? null : Number(attempts),
      value: timed ? Number(seconds) : null,
      date: new Date().toISOString().slice(0, 10),
      notes: '',
    });
    setMade('');
    setSeconds('');
    setOpen(false);
  };

  const inputStyle = {
    background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.15)',
    borderRadius: '6px', color: 'var(--text-main)', padding: '0.45rem 0.5rem',
    fontSize: 'var(--text-sm)', minHeight: 'var(--touch-min)', width: '100%',
  };

  return (
    <div className="glass-panel" style={{ padding: 'var(--space-lg)', display: 'flex', flexDirection: 'column', gap: '0.45rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
        <span>{CATEGORY_ICONS[drill.category] || '🎯'}</span>
        <h3 style={{ margin: 0, fontSize: 'var(--text-sm)', fontWeight: 700, flex: 1 }}>{drill.name}</h3>
        {timed && <Timer size={14} color="var(--text-muted)" />}
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.25rem' }}>
        {(drill.positions?.length ? drill.positions : ['Lineup']).map(p => <Chip key={p} tone="primary">{p}</Chip>)}
        {(drill.stat_keys || []).map(s => <Chip key={s}>{statLabel(s)}</Chip>)}
      </div>

      <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', margin: 0, lineHeight: 1.45 }}>{drill.how_to}</p>
      <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-main)', margin: 0, fontWeight: 600 }}>
        {'📋'} {drill.scoring}
      </p>

      {!open ? (
        <button
          onClick={() => setOpen(true)}
          style={{
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '0.35rem',
            background: 'var(--primary-glow)', color: 'var(--primary-color)',
            border: '1px solid rgba(4, 101, 104, 0.27)', borderRadius: '8px',
            padding: '0.45rem 0.75rem', cursor: 'pointer', fontWeight: 700,
            fontSize: 'var(--text-xs)', minHeight: 'var(--touch-min)', marginTop: 'auto',
          }}
        >
          <Plus size={14} /> Log result
        </button>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', marginTop: '0.2rem' }}>
          <select value={player} onChange={e => setPlayer(e.target.value)} style={inputStyle}>
            <option value="">Select player…</option>
            {players.map(name => <option key={name} value={name}>{name}</option>)}
          </select>
          {timed ? (
            <input
              type="number" inputMode="decimal" step="0.1" min="0.1" placeholder="Time (seconds)"
              value={seconds} onChange={e => setSeconds(e.target.value)} style={inputStyle}
            />
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <input
                type="number" inputMode="numeric" min="0" max={attempts} placeholder="Made"
                value={made} onChange={e => setMade(e.target.value)} style={{ ...inputStyle, flex: 1 }}
              />
              <span style={{ color: 'var(--text-muted)', fontWeight: 800 }}>/</span>
              <input
                type="number" inputMode="numeric" min="1" max="500"
                value={attempts} onChange={e => setAttempts(e.target.value)} style={{ ...inputStyle, flex: 1 }}
              />
            </div>
          )}
          <div style={{ display: 'flex', gap: '0.4rem' }}>
            <button
              onClick={save} disabled={!canSave || saving}
              style={{
                flex: 1, background: canSave ? 'var(--primary-color)' : 'rgba(255,255,255,0.08)',
                color: canSave ? '#03283a' : 'var(--text-muted)', border: 'none', borderRadius: '8px',
                padding: '0.45rem', fontWeight: 800, fontSize: 'var(--text-xs)',
                cursor: canSave && !saving ? 'pointer' : 'not-allowed', minHeight: 'var(--touch-min)',
              }}
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button
              onClick={() => setOpen(false)}
              style={{
                background: 'rgba(255,255,255,0.06)', color: 'var(--text-main)',
                border: '1px solid rgba(255,255,255,0.15)', borderRadius: '8px',
                padding: '0.45rem 0.7rem', fontSize: 'var(--text-xs)', cursor: 'pointer',
                minHeight: 'var(--touch-min)',
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

const recordSummary = (rec, drillsById) => {
  const drill = drillsById[rec.drill_id];
  const name = drill?.name || rec.drill_id;
  if (rec.value != null) return `${name}: ${rec.value}s`;
  return `${name}: ${rec.made}/${rec.attempts}`;
};

const PositionCard = ({ pos, entries, statSpecs, isMobile }) => (
  <div className="glass-panel" style={{ padding: 'var(--space-lg)' }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem' }}>
      <span style={{
        background: 'var(--primary-color)', color: '#03283a', borderRadius: '8px',
        padding: '2px 9px', fontWeight: 800, fontSize: 'var(--text-sm)',
      }}>{pos}</span>
      {/* 10px on a ~200px line was effectively decorative. */}
      <span style={{ fontSize: '12px', color: 'var(--text-muted)', lineHeight: 1.35 }}>
        Key stats: {(statSpecs || []).map(s => statLabel(s.stat) + (s.lower_is_better ? ' ↓' : '')).join(', ')}
      </span>
    </div>
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
      {(entries || []).slice(0, isMobile ? 3 : 5).map((e, i) => (
        <div key={e.name} style={{
          display: 'flex', alignItems: 'center', gap: '0.5rem',
          background: 'rgba(0,0,0,0.2)', border: '1px solid rgba(255,255,255,0.08)',
          borderRadius: '6px', padding: '0.35rem 0.55rem',
        }}>
          {/* The fixed rank column and the fit% column squeezed the name into a
              few characters at 360px; `minWidth: 0` + `overflowWrap` let the
              name take the slack and wrap instead of being clipped. */}
          <span style={{ color: 'var(--text-muted)', fontSize: 'var(--text-xs)', fontWeight: 800, width: '1rem', flexShrink: 0 }}>{i + 1}</span>
          <span style={{ flex: '1 1 auto', minWidth: 0, overflowWrap: 'anywhere', fontSize: 'var(--text-xs)', fontWeight: 700 }}>
            {e.name}
            {/* `title`-only glyphs a phone can never surface: the R had no
                legend at all and the drill count was a 10px whisper. */}
            {e.returning && (
              <TipIcon
                text="Returning player — last season's stats are blended into this fit score"
                style={{ marginLeft: '0.3rem', color: 'var(--primary-color)', fontWeight: 800 }}
              >R</TipIcon>
            )}
          </span>
          {e.drills_logged > 0 && (
            <TipIcon
              text={`${e.drills_logged} eval drill${e.drills_logged > 1 ? 's' : ''} logged for this player`}
              style={{ fontSize: '12px', color: 'var(--text-muted)', flexShrink: 0, whiteSpace: 'nowrap' }}
            >
              {e.drills_logged} drill{e.drills_logged > 1 ? 's' : ''}
            </TipIcon>
          )}
          <span style={{ fontWeight: 800, fontSize: 'var(--text-sm)', color: fitColor(e.fit), minWidth: '2.6rem', flexShrink: 0, textAlign: 'right' }}>
            {e.fit == null ? '—' : `${Math.round(e.fit)}%`}
          </span>
        </div>
      ))}
    </div>
  </div>
);

const Evals = ({ team, isMobile = false, isLandscape = false }) => {
  const initialCache = getLocalCachedJson('evals');
  const [payload, setPayload] = useState(initialCache?.value || null);
  const [fromCache, setFromCache] = useState(Boolean(initialCache));
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [view, setView] = useState('fits'); // 'fits' | 'drills' | 'log'
  // Deleting an eval record is destructive and irreversible, and the button sat
  // flush against the record text. Arm-then-confirm in place (no window.confirm,
  // which is easy to dismiss blind on a phone); the arm lapses after 4s so a
  // stray tap can never sit waiting to fire.
  const [pendingDelete, setPendingDelete] = useState(null);
  const pendingDeleteTimer = useRef(null);
  useEffect(() => () => { if (pendingDeleteTimer.current) clearTimeout(pendingDeleteTimer.current); }, []);

  const drillsById = useMemo(() => {
    const map = {};
    (payload?.drills || []).forEach(d => { map[d.id] = d; });
    return map;
  }, [payload]);

  const playerNames = useMemo(() => {
    const fromPayload = (payload?.roster || []).filter(p => p.core !== false).map(p => p.name);
    if (fromPayload.length) return [...fromPayload].sort((a, b) => a.localeCompare(b));
    return (team?.roster || [])
      .filter(p => p.core !== false && !p.borrowed)
      .map(p => `${p.first || ''} ${p.last || ''}`.trim())
      .filter(Boolean)
      .sort((a, b) => a.localeCompare(b));
  }, [payload, team]);

  const applyPayload = (data) => {
    setPayload(data);
    setFromCache(false);
    if (data && Array.isArray(data.drills) && data.drills.length) {
      setLocalCachedJson('evals', data);
    }
  };

  const fetchEvals = async () => {
    setLoading(true);
    setError('');
    if (isPollingPaused() && payload) { setLoading(false); return; }
    try {
      const res = await fetch('/api/evals');
      if (!res.ok) throw new Error(`evals status ${res.status}`);
      applyPayload(await res.json());
    } catch (e) {
      console.error('Failed to load evals', e);
      try {
        const sRes = await fetch('/data/sharks/evals.json', { cache: 'no-store' });
        if (sRes.ok) {
          const sData = await sRes.json();
          if (Array.isArray(sData?.drills) && sData.drills.length) {
            setPayload(sData);
            setFromCache(true);
            setLoading(false);
            return;
          }
        }
      } catch { /* nothing available */ }
      setError('Failed to load evals');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchEvals();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const postRecords = async (records) => {
    setSaving(true);
    setError('');
    try {
      const res = await apiRequest('/api/evals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ records }),
      });
      if (!res.ok) throw new Error(`save status ${res.status}`);
      applyPayload(await res.json());
      return true;
    } catch (e) {
      console.error('Failed to save eval record', e);
      setError('Failed to save — check connection and retry');
      return false;
    } finally {
      setSaving(false);
    }
  };

  const logRecord = (rec) => postRecords([...(payload?.records || []), rec]);

  const deleteRecord = (index) => {
    const records = [...(payload?.records || [])];
    records.splice(index, 1);
    postRecords(records);
  };

  const requestDelete = (index) => {
    if (pendingDeleteTimer.current) clearTimeout(pendingDeleteTimer.current);
    if (pendingDelete === index) {
      setPendingDelete(null);
      deleteRecord(index);
      return;
    }
    setPendingDelete(index);
    pendingDeleteTimer.current = setTimeout(() => setPendingDelete(null), 4000);
  };

  const records = payload?.records || [];
  const groupedDrills = useMemo(() => {
    const groups = {};
    (payload?.drills || []).forEach(d => {
      (groups[d.category] = groups[d.category] || []).push(d);
    });
    return groups;
  }, [payload]);

  const tabBtn = (id, label) => (
    <button
      key={id}
      onClick={() => setView(id)}
      style={{
        background: view === id ? 'rgba(4, 101, 104, 0.18)' : 'rgba(255,255,255,0.05)',
        border: view === id ? '1px solid rgba(4, 101, 104, 0.4)' : '1px solid rgba(255,255,255,0.12)',
        color: view === id ? 'var(--primary-color)' : 'var(--text-main)',
        borderRadius: '8px', padding: '0.45rem 0.8rem', fontWeight: 700,
        fontSize: 'var(--text-xs)', cursor: 'pointer', minHeight: 'var(--touch-min)',
        // Inside the scroller the pills must hold their size, not squash.
        flexShrink: 0, whiteSpace: 'nowrap',
      }}
    >
      {label}
    </button>
  );

  return (
    <div>
      <h2 className="view-title">
        <ClipboardList size={isMobile ? 20 : 24} color="var(--primary-color)" /> Player Evals
      </h2>

      <div className="glass-panel" style={{ padding: isMobile ? 'var(--space-lg)' : '1rem 1.25rem', marginBottom: 'var(--space-md)' }}>
        {/* The segment bar wrapped to two rows at 360px and Refresh changed
            line position as `Log (N)` grew. `flexWrap: nowrap` on the outer row
            pins Refresh; the pills get their own snapping scroller instead. */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.75rem', flexWrap: 'nowrap' }}>
          <div
            className="scroll-x scroll-x--snap"
            style={{ display: 'flex', gap: '0.4rem', flexWrap: 'nowrap', flex: '1 1 auto', minWidth: 0, paddingBottom: '2px' }}
          >
            {tabBtn('fits', 'Position Fit')}
            {tabBtn('drills', 'Drills')}
            {tabBtn('log', `Log (${records.length})`)}
          </div>
          <button
            onClick={fetchEvals}
            disabled={loading}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: '0.4rem', flexShrink: 0,
              background: 'var(--primary-glow)', color: 'var(--primary-color)', border: '1px solid rgba(4, 101, 104, 0.27)',
              padding: '0.5rem 0.85rem', borderRadius: '8px', cursor: loading ? 'not-allowed' : 'pointer', fontWeight: 600,
              minHeight: 'var(--touch-min)',
            }}
          >
            <RefreshCw size={14} className={loading ? 'spin-smooth' : ''} /> Refresh
          </button>
        </div>
        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: '0.4rem', lineHeight: 1.4 }}>
          Run drills, log results (e.g. pop flies 7/10), and rankings blend fresh evals (60%) with last
          season&apos;s stats (40%) for returning players. New players rank on drills alone.
        </div>
      </div>

      {fromCache && payload && (
        // The banner invites a tap, so it has to be a real button: a bare
        // `div onClick` at ~30px tall was neither reachable by keyboard nor
        // reliably hittable with a thumb.
        <button
          type="button"
          onClick={fetchEvals}
          aria-label="Showing cached evaluations. Retry live data."
          style={{
            display: 'flex', alignItems: 'center', gap: '0.5rem', width: '100%',
            marginBottom: 'var(--space-sm)', textAlign: 'left',
            padding: '6px 10px', minHeight: 'var(--touch-min)', borderRadius: '6px',
            background: 'rgba(168, 116, 33, 0.15)',
            border: '1px solid rgba(168, 116, 33, 0.30)', color: 'var(--warning, #facc15)',
            fontFamily: 'var(--font-base)', fontSize: 'var(--text-sm)', fontWeight: 700,
            cursor: 'pointer',
          }}
        >
          <AlertTriangle size={14} style={{ flexShrink: 0 }} />
          <span>Showing cached evals — tap to retry live data</span>
        </button>
      )}

      {error && (
        <div style={{
          marginBottom: 'var(--space-sm)', padding: '6px 10px', borderRadius: '6px',
          background: 'rgba(179, 74, 57, 0.12)', border: '1px solid rgba(179, 74, 57, 0.35)',
          color: 'var(--danger)', fontSize: 'var(--text-xs)', fontWeight: 700,
        }}>
          {error}
        </div>
      )}

      {!payload && !error && (
        <div className="glass-panel" style={{ padding: 'var(--space-lg)' }}>
          <div className="loader"></div>
        </div>
      )}

      {payload && view === 'fits' && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', marginBottom: 'var(--space-sm)' }}>
            <Target size={16} color="var(--primary-color)" />
            <span className="section-label" style={{ marginBottom: 0 }}>
              Best Fit By Position <span style={{ fontWeight: 500, color: 'var(--text-muted)' }}>(R = returning)</span>
            </span>
          </div>
          <div style={{
            display: 'grid', gap: '0.5rem',
            gridTemplateColumns: isLandscape ? 'repeat(auto-fill, minmax(230px, 1fr))' : isMobile ? '1fr' : 'repeat(auto-fill, minmax(270px, 1fr))',
          }}>
            {(payload.positions || []).map(pos => (
              <PositionCard
                key={pos}
                pos={pos}
                entries={payload.fits?.positions?.[pos]}
                statSpecs={payload.position_stats?.[pos]}
                isMobile={isMobile}
              />
            ))}
          </div>
        </>
      )}

      {payload && view === 'drills' && (
        <>
          {Object.entries(groupedDrills).map(([category, drills]) => (
            <div key={category} style={{ marginBottom: 'var(--space-md)' }}>
              <div className="section-label" style={{ marginBottom: 'var(--space-sm)' }}>
                {CATEGORY_ICONS[category] || ''} {category}
              </div>
              <div style={{
                display: 'grid', gap: '0.5rem',
                gridTemplateColumns: isLandscape ? 'repeat(auto-fill, minmax(240px, 1fr))' : isMobile ? '1fr' : 'repeat(auto-fill, minmax(290px, 1fr))',
              }}>
                {drills.map(d => (
                  <DrillCard key={d.id} drill={d} players={playerNames} onLog={logRecord} saving={saving} />
                ))}
              </div>
            </div>
          ))}
        </>
      )}

      {payload && view === 'log' && (
        <div className="glass-panel" style={{ padding: 'var(--space-lg)' }}>
          <div className="section-label">Logged Results</div>
          {records.length === 0 ? (
            <div style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)' }}>
              No results yet — open the Drills tab and tap “Log result” on any drill.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
              {records.map((rec, i) => ({ rec, i })).reverse().map(({ rec, i }) => (
                <div key={`${rec.player}-${rec.drill_id}-${i}`} style={{
                  display: 'flex', alignItems: 'center', gap: '0.5rem',
                  background: 'rgba(0,0,0,0.2)', border: '1px solid rgba(255,255,255,0.08)',
                  borderRadius: '6px', padding: '0.4rem 0.55rem',
                }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 'var(--text-xs)', fontWeight: 700 }}>{rec.player}</div>
                    {/* 10px alongside a 44px delete target was the smallest text
                        on the tab; 12px is the readable floor. */}
                    <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                      {recordSummary(rec, drillsById)}{rec.date ? ` — ${rec.date}` : ''}
                    </div>
                  </div>
                  {/* minHeight without minWidth left a ~28px-wide destructive
                      control sitting flush against a `flex: 1` text block. Now a
                      full 44x44 target that arms on the first tap. */}
                  <button
                    onClick={() => requestDelete(i)}
                    disabled={saving}
                    title={pendingDelete === i ? 'Tap again to confirm delete' : 'Delete record'}
                    aria-label={pendingDelete === i
                      ? `Confirm deleting ${rec.player} ${rec.drill_id} record`
                      : `Delete ${rec.player} ${rec.drill_id} record`}
                    style={{
                      background: pendingDelete === i ? 'rgba(179, 74, 57, 0.22)' : 'transparent',
                      border: pendingDelete === i ? '1px solid rgba(179, 74, 57, 0.55)' : '1px solid transparent',
                      borderRadius: '8px', color: 'var(--danger)',
                      cursor: saving ? 'not-allowed' : 'pointer', padding: '0.4rem',
                      minHeight: 'var(--touch-min)', minWidth: 'var(--touch-min)', flexShrink: 0,
                      display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '0.25rem',
                      fontSize: 'var(--text-xs)', fontWeight: 800,
                    }}
                  >
                    <Trash2 size={15} />
                    {pendingDelete === i && <span>Sure?</span>}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default Evals;
