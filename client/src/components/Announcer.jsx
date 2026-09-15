import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { createPortal } from 'react-dom';
import {
  Mic, Play, Square, SkipBack, SkipForward, RefreshCw, UserPlus,
  AlertCircle, Volume2, Zap, X, ChevronDown, ChevronUp, Check, Trash2,
} from 'lucide-react';
import { playIntro, playClip, stop as stopAudio, preload, cleanup, setVolume } from '../utils/audioController';
import { apiRequest } from '../utils/apiClient';

// One screen, Ballpark DJ style: the batting order is a list of big rows, each
// with its own Play. Tap a row to fix how the name is said, pick a voice, or set
// the walk-up song. A sticky bar at the bottom shows who is up and carries the
// game-situation controls and the Halo moments.

const MODAL_SCROLL_STYLE = {
  maxHeight: '85dvh', overflowY: 'auto', overscrollBehavior: 'contain', WebkitOverflowScrolling: 'touch',
};

const ORIGIN_HEADERS = () => ({ 'Content-Type': 'application/json', 'Origin': window.location.origin });

// Must match _HALO_SCRIPTS keys in tools/announcer_engine.py
const HALO_ACHIEVEMENTS = [
  { key: 'grand_slam',    label: 'Grand Slam',     desc: 'Grand. Slam. QUEEN!' },
  { key: 'cycle',         label: 'The Cycle',      desc: 'PERFECTION!' },
  { key: 'triple_rbi',    label: 'Hat Trick',      desc: '3 RBI' },
  { key: 'quad_rbi',      label: 'Grand Slam Hero', desc: '4 RBI' },
  { key: '3_strikeouts',  label: 'Strikeout Artist', desc: '3 K' },
  { key: '4_strikeouts',  label: 'On Fire',        desc: '4 K' },
  { key: '5_strikeouts',  label: 'Untouchable',    desc: '5 K' },
];

const DEFAULT_SITUATION = { bases: [false, false, false], outs: 0 };

const ONES = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten',
  'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen'];
const TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety'];
function numToWord(raw) {
  const s = String(raw ?? '').trim();
  if (!/^\d+$/.test(s)) return s;
  if (s === '00') return 'double-zero';
  const n = parseInt(s, 10);
  if (n >= 100) return s;
  if (n < 20) return ONES[n];
  const t = Math.floor(n / 10), o = n % 10;
  return o ? `${TENS[t]}-${ONES[o]}` : TENS[t];
}

// Mirrors the server's standard walk-up so the sheet can preview while typing.
function previewLine(player, phonetic) {
  const name = (phonetic || `${player.first} ${player.last}`).trim();
  return `Now batting for your Sharks... NUMBEEEER ${numToWord(player.number)}... ${name}!`;
}

function useEscapeToClose(onClose) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' || e.key === 'Esc') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);
}

function StatusLed({ status }) {
  const color = { ready: 'var(--success)', rendering: 'var(--warning)', error: 'var(--danger)' }[status] || 'rgba(255,255,255,0.25)';
  const label = { ready: 'Ready', rendering: 'Rendering', error: 'Error', pending: 'Not rendered' }[status] || status;
  return <span className="announcer-status-led" style={{ background: color }} title={label} aria-label={label} />;
}

// ── Lineup row ─────────────────────────────────────────────────────────────
function LineupRow({ player, slot, isCurrent, isPlaying, onPlay, onOpen }) {
  const hasClip = Boolean(player.announcer_audio_url);
  const hasSong = Boolean(player.walkup_song_url);
  return (
    <div className={`announcer-lineup-row glass-panel${isCurrent ? ' announcer-lineup-row--current' : ''}`}>
      <button type="button" className="announcer-lineup-main" onClick={() => onOpen(player)} aria-label={`Edit ${player.first} ${player.last}`}>
        <span className="announcer-lineup-slot">{slot}</span>
        <span className="announcer-jersey">#{player.number || '–'}</span>
        <span className="announcer-lineup-name">
          <span className="announcer-lineup-first">{player.first} <strong>{player.last}</strong></span>
          <span className="announcer-lineup-sub">
            <StatusLed status={player.status} />
            {player.status === 'rendering' ? 'Rendering…' : player.status === 'error' ? 'Render failed' : hasClip ? 'Announcer ready' : 'Tap to set up'}
            {hasSong && <span> · <Volume2 size={11} style={{ verticalAlign: '-2px' }} /> walk-up</span>}
          </span>
        </span>
      </button>
      <button
        type="button"
        className={`announcer-row-play${isCurrent && isPlaying ? ' announcer-row-play--active' : ''}`}
        onClick={() => onPlay(player)}
        disabled={!hasClip && !hasSong}
        aria-label={isCurrent && isPlaying ? `Stop ${player.first}` : `Play ${player.first}`}
      >
        {isCurrent && isPlaying ? <Square size={20} /> : <Play size={22} style={{ marginLeft: 2 }} />}
      </button>
    </div>
  );
}

// ── Player sheet ───────────────────────────────────────────────────────────
function PlayerSheet({ player, profiles, defaultVoiceId, onClose, onSave, onRender, onRemove }) {
  useEscapeToClose(onClose);
  const [phonetic, setPhonetic] = useState(player.phonetic_hint || '');
  const [voice, setVoice] = useState(player.voice_profile_id || '');
  const [song, setSong] = useState(player.walkup_song_url || '');
  const [introTs, setIntroTs] = useState(player.intro_timestamp ?? 5);
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState('');
  const [confirmRemove, setConfirmRemove] = useState(false);
  const defaultName = profiles.find(p => p.id === defaultVoiceId)?.name || 'Team voice';

  const payload = () => ({
    phonetic_hint: phonetic.trim(),
    voice_profile_id: voice,
    walkup_song_url: song.trim(),
    intro_timestamp: Number(introTs) || 0,
  });

  const save = async () => {
    setBusy('save'); setMsg('');
    try { await onSave(player.id, payload()); setMsg('Saved.'); }
    catch (e) { setMsg(e.message || 'Save failed'); }
    finally { setBusy(''); }
  };

  const saveAndRender = async () => {
    setBusy('render'); setMsg('');
    try {
      await onSave(player.id, payload());
      await onRender(player.id);
      // The parent shows the "Rendering…" notice; this sheet is about to close.
      onClose();
    } catch (e) { setMsg(e.message || 'Render failed'); setBusy(''); }
  };

  const testPlay = () => {
    if (player.announcer_audio_url) playClip(player.announcer_audio_url);
  };

  return createPortal(
    <div className="announcer-modal-overlay" onClick={onClose}>
      <div className="announcer-modal glass-panel" onClick={e => e.stopPropagation()} style={{ maxWidth: 420, ...MODAL_SCROLL_STYLE }}>
        <div className="announcer-modal-header">
          <h3 style={{ margin: 0 }}><span className="announcer-jersey">#{player.number}</span> {player.first} {player.last}</h3>
          <button type="button" className="announcer-modal-close" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>

        <label className="announcer-form-group">
          <span>Say it as</span>
          <input
            value={phonetic}
            onChange={e => setPhonetic(e.target.value)}
            placeholder={`${player.first} ${player.last}`}
            maxLength={200}
            autoCapitalize="off"
            autoCorrect="off"
          />
          <small>Spell it how it sounds. Capitals get stressed: <em>ROO-bee van-DOO-sen</em></small>
        </label>
        <div className="announcer-preview-text">{previewLine(player, phonetic)}</div>

        <label className="announcer-form-group">
          <span>Voice</span>
          <select value={voice} onChange={e => setVoice(e.target.value)}>
            <option value="">Team voice ({defaultName})</option>
            {profiles.map(p => <option key={p.id} value={p.id}>{p.name} — {p.tagline}</option>)}
          </select>
        </label>

        <label className="announcer-form-group">
          <span>Walk-up song (link)</span>
          <input value={song} onChange={e => setSong(e.target.value)} placeholder="https://…mp3" inputMode="url" maxLength={500} />
        </label>
        <label className="announcer-form-group">
          <span>Start the song at (seconds)</span>
          <input type="number" min="0" max="300" step="0.5" value={introTs} onChange={e => setIntroTs(e.target.value)} />
        </label>

        {msg && <div className="announcer-error-msg" role="status">{msg}</div>}

        <div className="announcer-form-actions">
          <button type="button" className="announcer-btn announcer-btn-primary" onClick={saveAndRender} disabled={Boolean(busy)}>
            {busy === 'render' ? <RefreshCw size={14} className="sync-spin" /> : <Mic size={14} />} Save &amp; render
          </button>
          <button type="button" className="announcer-btn announcer-btn-secondary" onClick={save} disabled={Boolean(busy)}>
            {busy === 'save' ? <RefreshCw size={14} className="sync-spin" /> : <Check size={14} />} Save
          </button>
          {player.announcer_audio_url && (
            <button type="button" className="announcer-btn announcer-btn-accent" onClick={testPlay}><Play size={14} /> Hear it</button>
          )}
        </div>

        <button
          type="button"
          className="announcer-btn announcer-btn-secondary announcer-remove-btn"
          onClick={() => { if (confirmRemove) { onRemove(player.id); onClose(); } else setConfirmRemove(true); }}
        >
          <Trash2 size={13} /> {confirmRemove ? 'Tap again to remove from announcer' : 'Remove player'}
        </button>
      </div>
    </div>,
    document.body,
  );
}

// ── Voice picker ───────────────────────────────────────────────────────────
function VoicePicker({ profiles, defaultVoiceId, onChoose, onClose }) {
  useEscapeToClose(onClose);
  const [playingId, setPlayingId] = useState('');
  const [choosing, setChoosing] = useState('');

  const sample = (id) => {
    if (playingId === id) { stopAudio(); setPlayingId(''); return; }
    setPlayingId(id);
    playClip(`/api/announcer/voice-sample/${id}`, () => setPlayingId('')).catch(() => setPlayingId(''));
  };

  const choose = async (id) => {
    setChoosing(id);
    try { await onChoose(id); onClose(); } finally { setChoosing(''); }
  };

  useEffect(() => () => stopAudio(), []);

  return createPortal(
    <div className="announcer-modal-overlay" onClick={onClose}>
      <div className="announcer-modal glass-panel" onClick={e => e.stopPropagation()} style={{ maxWidth: 420, ...MODAL_SCROLL_STYLE }}>
        <div className="announcer-modal-header">
          <h3 style={{ margin: 0 }}>Announcer voice</h3>
          <button type="button" className="announcer-modal-close" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        <p className="announcer-hint">Tap ▶ to hear a sample. Choosing a voice re-renders the whole team.</p>
        {profiles.map(p => {
          const active = p.id === defaultVoiceId;
          return (
            <div key={p.id} className={`announcer-voice-row${active ? ' announcer-voice-row--active' : ''}`}>
              <button type="button" className="announcer-btn-round" onClick={() => sample(p.id)} aria-label={`Sample ${p.name}`}>
                {playingId === p.id ? <Square size={16} /> : <Play size={16} style={{ marginLeft: 2 }} />}
              </button>
              <div className="announcer-voice-text">
                <strong>{p.name}</strong>
                <span>{p.tagline}</span>
              </div>
              {active
                ? <span className="announcer-voice-current"><Check size={14} /> In use</span>
                : (
                  <button type="button" className="announcer-btn announcer-btn-accent" onClick={() => choose(p.id)} disabled={Boolean(choosing)}>
                    {choosing === p.id ? <RefreshCw size={14} className="sync-spin" /> : 'Use'}
                  </button>
                )}
            </div>
          );
        })}
      </div>
    </div>,
    document.body,
  );
}

// ── Add sub ────────────────────────────────────────────────────────────────
function AddSubModal({ onClose, onAdd }) {
  useEscapeToClose(onClose);
  const [first, setFirst] = useState('');
  const [last, setLast] = useState('');
  const [number, setNumber] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const submit = async (e) => {
    e.preventDefault();
    if (!first.trim()) { setErr('First name is required'); return; }
    setBusy(true); setErr('');
    try { await onAdd({ first: first.trim(), last: last.trim(), number: number.trim() }); onClose(); }
    catch (ex) { setErr(ex.message || 'Could not add player'); setBusy(false); }
  };
  return createPortal(
    <div className="announcer-modal-overlay" onClick={onClose}>
      <form className="announcer-modal glass-panel" onClick={e => e.stopPropagation()} onSubmit={submit} style={{ maxWidth: 380, ...MODAL_SCROLL_STYLE }}>
        <div className="announcer-modal-header">
          <h3 style={{ margin: 0 }}>Add a sub</h3>
          <button type="button" className="announcer-modal-close" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        <label className="announcer-form-group"><span>First name</span><input value={first} onChange={e => setFirst(e.target.value)} autoFocus maxLength={64} /></label>
        <label className="announcer-form-group"><span>Last name</span><input value={last} onChange={e => setLast(e.target.value)} maxLength={64} /></label>
        <label className="announcer-form-group"><span>Number</span><input value={number} onChange={e => setNumber(e.target.value)} inputMode="numeric" maxLength={4} /></label>
        {err && <div className="announcer-error-msg">{err}</div>}
        <div className="announcer-form-actions">
          <button type="submit" className="announcer-btn announcer-btn-primary" disabled={busy}>{busy ? 'Adding…' : 'Add & render'}</button>
          <button type="button" className="announcer-btn announcer-btn-secondary" onClick={onClose}>Cancel</button>
        </div>
      </form>
    </div>,
    document.body,
  );
}

// ── Halo moments ───────────────────────────────────────────────────────────
function HaloOverlay({ player, onSelect, onClose }) {
  useEscapeToClose(onClose);
  return createPortal(
    <div className="announcer-modal-overlay" onClick={onClose}>
      <div className="announcer-modal glass-panel" onClick={e => e.stopPropagation()} style={{ maxWidth: 360, ...MODAL_SCROLL_STYLE }}>
        <div className="announcer-modal-header">
          <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}><Zap size={18} style={{ color: 'var(--warning)' }} /> Halo moment</h3>
          <button type="button" className="announcer-modal-close" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        <p className="announcer-hint">Renders a special call for <strong>{player.first} {player.last}</strong> and plays it.</p>
        <div className="announcer-halo-grid">
          {HALO_ACHIEVEMENTS.map(a => (
            <button type="button" key={a.key} className="announcer-btn announcer-btn-accent announcer-halo-btn" onClick={() => { onSelect(a.key); onClose(); }}>
              <span>{a.label}</span><small>{a.desc}</small>
            </button>
          ))}
        </div>
      </div>
    </div>,
    document.body,
  );
}

// ── Main ───────────────────────────────────────────────────────────────────
export default function Announcer({ lineups }) {
  const [roster, setRoster] = useState([]);
  const [stats, setStats] = useState({ total: 0, ready: 0, pending: 0, error: 0 });
  const [profiles, setProfiles] = useState([]);
  const [defaultVoiceId, setDefaultVoiceId] = useState('halo');
  const [gcLineup, setGcLineup] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [currentId, setCurrentId] = useState(null);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState({ elapsed: 0, duration: 0 });
  const [situation, setSituation] = useState(DEFAULT_SITUATION);
  const [sheetPlayer, setSheetPlayer] = useState(null);
  const [showVoices, setShowVoices] = useState(false);
  const [showAddSub, setShowAddSub] = useState(false);
  const [showHalo, setShowHalo] = useState(false);
  const [showFormer, setShowFormer] = useState(false);
  const [renderAllBusy, setRenderAllBusy] = useState(false);
  const pollRef = useRef(null);
  const pollStopRef = useRef(null);

  // ── data ──
  const fetchRoster = useCallback(async () => {
    try {
      const res = await fetch('/api/announcer/roster');
      if (!res.ok) throw new Error(`${res.status}`);
      const data = await res.json();
      const list = data.roster || [];
      if (!list.length) throw new Error('empty roster');
      setRoster(list);
      setStats(data.stats || { total: 0, ready: 0, pending: 0, error: 0 });
      setError('');
      // Clear our own "Rendering…" notice once nothing is in flight. Halo
      // failure notices use different wording and are left alone.
      if (!list.some(p => p.status === 'rendering')) {
        setNotice(n => (n.startsWith('Rendering ') ? '' : n));
      }
      return list;
    } catch (apiErr) {
      // Last-good cache nginx serves when the API is down — playback still works.
      try {
        const sRes = await fetch('/data/sharks/announcer_roster.json', { cache: 'no-store' });
        const sData = sRes.ok ? await sRes.json() : null;
        if (sData?.roster?.length) {
          setRoster(sData.roster);
          setStats(sData.stats || { total: sData.roster.length, ready: 0, pending: 0, error: 0 });
          setError(`Using cached roster — live rendering unavailable (${apiErr.message})`);
          return sData.roster;
        }
      } catch { /* fall through */ }
      setError(`Failed to load roster: ${apiErr.message}`);
      return [];
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchProfiles = useCallback(async () => {
    try {
      const res = await fetch('/api/announcer/voice-profiles');
      if (!res.ok) return;
      const data = await res.json();
      setProfiles(data.profiles || []);
      if (data.default_id) setDefaultVoiceId(data.default_id);
    } catch { /* picker just stays empty */ }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchRoster();
    fetchProfiles();
    fetch('/api/announcer/game-lineup')
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (d) setGcLineup(d); })
      .catch(() => {});
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (pollStopRef.current) clearTimeout(pollStopRef.current);
      cleanup();
    };
  }, [fetchRoster, fetchProfiles]);

  // iOS: an AudioContext created outside a user gesture is born suspended, so
  // the first Play would be silent. Touch the controller on the first gesture.
  useEffect(() => {
    let done = false;
    const opts = { capture: true, passive: true };
    const unlock = () => {
      if (done) return;
      done = true;
      try { setVolume(1); } catch { /* no Web Audio */ }
      remove();
    };
    function remove() {
      document.removeEventListener('pointerdown', unlock, opts);
      document.removeEventListener('touchend', unlock, opts);
      document.removeEventListener('click', unlock, opts);
    }
    document.addEventListener('pointerdown', unlock, opts);
    document.addEventListener('touchend', unlock, opts);
    document.addEventListener('click', unlock, opts);
    return remove;
  }, []);

  // Poll while renders are in flight; stop on our own once things settle.
  const startPolling = useCallback((maxMs = 120000) => {
    if (!pollRef.current) pollRef.current = setInterval(fetchRoster, 3000);
    if (pollStopRef.current) clearTimeout(pollStopRef.current);
    pollStopRef.current = setTimeout(() => {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    }, maxMs);
  }, [fetchRoster]);

  useEffect(() => {
    const inFlight = roster.some(p => p.status === 'rendering');
    if (!inFlight && pollRef.current && !renderAllBusy) {
      clearInterval(pollRef.current); pollRef.current = null;
    }
  }, [roster, renderAllBusy]);

  // ── batting order: GC game → optimiser lineup → active roster ──
  const active = useMemo(() => roster.filter(p => p.is_active && !p.is_ghost), [roster]);
  const former = useMemo(() => roster.filter(p => p.is_ghost || p.is_active === false), [roster]);
  const { battingOrder, lineupSource } = useMemo(() => {
    const byRef = (p) => active.find(r =>
      (p.id && r.id === p.id) ||
      (p.number && String(r.number) === String(p.number)) ||
      `${r.first} ${r.last}`.toLowerCase() === `${p.first || ''} ${p.last || ''}`.toLowerCase().trim(),
    ) || null;
    const withRest = (ordered) => {
      const seen = new Set(ordered.map(p => p.id));
      return [...ordered, ...active.filter(p => !seen.has(p.id))];
    };
    if (gcLineup?.players?.length) {
      const ordered = gcLineup.players.map(byRef).filter(Boolean);
      if (ordered.length) return { battingOrder: withRest(ordered), lineupSource: gcLineup.source_label || 'GameChanger lineup' };
    }
    if (lineups) {
      // lineups.json: { balanced: { lineup: [...] }, ... } — the array is under
      // `lineup`, not the strategy key itself.
      const strategy = lineups[lineups.recommended_strategy || 'balanced'] || lineups.balanced;
      const lineup = Array.isArray(strategy) ? strategy : strategy?.lineup;
      if (Array.isArray(lineup) && lineup.length) {
        const ordered = [...lineup].sort((a, b) => (a.slot || 0) - (b.slot || 0)).map(byRef).filter(Boolean);
        if (ordered.length) return { battingOrder: withRest(ordered), lineupSource: 'Optimiser lineup' };
      }
    }
    return { battingOrder: active, lineupSource: 'Roster order' };
  }, [active, gcLineup, lineups]);

  const currentIdx = Math.max(0, battingOrder.findIndex(p => p.id === currentId));
  const current = battingOrder[currentIdx] || null;
  const onDeck = battingOrder[currentIdx + 1] || null;

  useEffect(() => {
    if (onDeck) preload([onDeck.walkup_song_url, onDeck.announcer_audio_url].filter(Boolean));
  }, [onDeck]);

  // ── playback ──
  const stop = useCallback(() => { stopAudio(); setPlaying(false); setProgress({ elapsed: 0, duration: 0 }); }, []);

  const playPlayer = useCallback(async (p) => {
    if (currentId === p.id && playing) { stop(); return; }
    setCurrentId(p.id);
    setPlaying(true);
    try {
      await playIntro({
        walkupUrl: p.walkup_song_url || '',
        clipUrl: p.announcer_audio_url || '',
        introTimestamp: p.intro_timestamp ?? 5,
        autoBPM: (p.intro_timestamp ?? 5) === 0,
        onEnd: () => setPlaying(false),
        onProgress: setProgress,
      });
    } catch { setPlaying(false); }
  }, [currentId, playing, stop]);

  const step = (delta) => {
    stop();
    const next = battingOrder[Math.min(battingOrder.length - 1, Math.max(0, currentIdx + delta))];
    if (next) setCurrentId(next.id);
  };

  // ── mutations ──
  const savePlayer = async (playerId, data) => {
    const res = await apiRequest(`/api/announcer/phonetics/${playerId}`, { method: 'POST', headers: ORIGIN_HEADERS(), body: JSON.stringify(data) });
    if (!res.ok) throw new Error('Could not save');
    await fetchRoster();
  };

  const renderPlayer = async (playerId, gameContext) => {
    const body = gameContext ? { quality: 'best', game_context: gameContext } : { quality: 'best' };
    const res = await apiRequest(`/api/announcer/render/${playerId}`, { method: 'POST', headers: ORIGIN_HEADERS(), body: JSON.stringify(body) });
    if (!res.ok) throw new Error('Could not start render');
    if (!gameContext) {
      const p = roster.find(r => r.id === playerId);
      setNotice(`Rendering ${p ? p.first : 'player'} — takes about 10 seconds.`);
    }
    startPolling(60000);
  };

  const renderAll = async () => {
    setRenderAllBusy(true);
    setNotice('');
    try {
      const res = await apiRequest('/api/announcer/render-all', { method: 'POST', headers: ORIGIN_HEADERS(), body: '{}' });
      if (!res.ok) throw new Error(`${res.status}`);
      startPolling(180000);
      setTimeout(() => setRenderAllBusy(false), 8000);
    } catch (e) { setNotice(`Render all failed: ${e.message}`); setRenderAllBusy(false); }
  };

  const chooseVoice = async (profileId) => {
    const res = await apiRequest('/api/announcer/voice-profiles/default', { method: 'POST', headers: ORIGIN_HEADERS(), body: JSON.stringify({ profile_id: profileId }) });
    if (!res.ok) throw new Error('Could not set voice');
    setDefaultVoiceId(profileId);
    await fetchProfiles();
    await renderAll();
    setNotice(`Voice changed to ${profiles.find(p => p.id === profileId)?.name || profileId} — re-rendering the team.`);
  };

  const addSub = async (data) => {
    const res = await apiRequest('/api/announcer/add-sub', { method: 'POST', headers: ORIGIN_HEADERS(), body: JSON.stringify(data) });
    if (!res.ok) throw new Error('Could not add player');
    await fetchRoster();
    startPolling(60000);
  };

  const removePlayer = async (playerId) => {
    try {
      const res = await apiRequest(`/api/announcer/player/${playerId}`, { method: 'DELETE', headers: { 'Origin': window.location.origin } });
      if (res.ok) await fetchRoster();
    } catch { /* roster unchanged */ }
  };

  // Situation → server, so situational renders know the bases/outs.
  const pushSituation = useCallback(async (next) => {
    setSituation(next);
    try {
      await apiRequest('/api/announcer/game-state', { method: 'POST', headers: ORIGIN_HEADERS(), body: JSON.stringify(next) });
    } catch { /* non-critical */ }
  }, []);

  // Halo moment: render a one-off call with the achievement, then play it.
  const fireHalo = async (achievementKey) => {
    if (!current) return;
    const ctx = { ...situation, achievement: achievementKey };
    const since = current.rendered_at || '';
    setNotice(`Rendering "${HALO_ACHIEVEMENTS.find(a => a.key === achievementKey)?.label}" for ${current.first}…`);
    try {
      await renderPlayer(current.id, ctx);
    } catch (e) { setNotice(e.message); return; }
    const deadline = Date.now() + 40000;
    while (Date.now() < deadline) {
      await new Promise(r => setTimeout(r, 1500));
      const list = await fetchRoster();
      const fresh = list.find(p => p.id === current.id);
      if (fresh && fresh.status === 'ready' && fresh.rendered_at && fresh.rendered_at !== since) {
        setNotice('');
        playPlayer({ ...fresh, walkup_song_url: '' });
        return;
      }
      if (fresh?.status === 'error') { setNotice(`Render failed: ${fresh.error_message || 'unknown'}`); return; }
    }
    setNotice('Render is taking longer than usual — it will appear on the row when done.');
  };

  const pct = progress.duration > 0 ? Math.min(100, (progress.elapsed / progress.duration) * 100) : 0;
  const defaultVoice = profiles.find(p => p.id === defaultVoiceId);
  const pendingCount = active.filter(p => p.status !== 'ready').length;

  if (loading) return <div className="loader" />;

  return (
    <div className="announcer-container announcer-page">
      <div className="announcer-header">
        <h2 style={{ margin: 0 }}><Mic size={22} /> Sharks Announcer</h2>
        <div className="announcer-header-actions">
          <button type="button" className="announcer-btn announcer-btn-accent" onClick={() => setShowVoices(true)}>
            <Volume2 size={14} /> {defaultVoice ? defaultVoice.name : 'Voice'} <ChevronDown size={12} />
          </button>
          <button type="button" className="announcer-btn announcer-btn-secondary" onClick={() => setShowAddSub(true)} aria-label="Add sub">
            <UserPlus size={14} /> Sub
          </button>
        </div>
      </div>

      {error && <div className="voice-error"><AlertCircle size={14} /> {error}</div>}
      {notice && <div className="voice-error announcer-notice" role="status"><AlertCircle size={14} /> {notice}</div>}

      <div className="announcer-summary">
        <span>{active.length} players · {stats.ready || active.filter(p => p.status === 'ready').length} ready</span>
        <span className={`announcer-lineup-source${gcLineup?.players?.length ? ' announcer-lineup-source--gc' : ''}`}>{lineupSource}</span>
        {pendingCount > 0 && (
          <button type="button" className="announcer-btn announcer-btn-primary" onClick={renderAll} disabled={renderAllBusy}>
            {renderAllBusy ? <RefreshCw size={14} className="sync-spin" /> : <Mic size={14} />}
            {renderAllBusy ? 'Rendering…' : `Render ${pendingCount === active.length ? 'all' : pendingCount}`}
          </button>
        )}
      </div>

      <div className="announcer-roster-list">
        {battingOrder.map((p, i) => (
          <LineupRow
            key={p.id}
            player={p}
            slot={i + 1}
            isCurrent={current?.id === p.id}
            isPlaying={playing}
            onPlay={playPlayer}
            onOpen={setSheetPlayer}
          />
        ))}
        {battingOrder.length === 0 && (
          <div className="glass-panel" style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
            No players yet — sync the team or add a sub.
          </div>
        )}
        {former.length > 0 && (
          <div className="announcer-former-section">
            <button type="button" className="announcer-btn announcer-btn-secondary announcer-former-toggle" aria-expanded={showFormer} onClick={() => setShowFormer(v => !v)}>
              <span>Former players ({former.length})</span>{showFormer ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
            {showFormer && former.map(p => (
              <LineupRow key={p.id} player={p} slot="–" isCurrent={false} isPlaying={false} onPlay={playPlayer} onOpen={setSheetPlayer} />
            ))}
          </div>
        )}
      </div>

      {current && (
        <div className="announcer-dj-bar glass-panel">
          <div className="announcer-dj-top">
            <div className="announcer-dj-title">
              <span className="announcer-dj-label">{playing ? 'Now batting' : 'Up next'}</span>
              <span className="announcer-dj-name"><span className="announcer-jersey">#{current.number}</span> {current.first} {current.last}</span>
              {onDeck && <span className="announcer-dj-ondeck">On deck: #{onDeck.number} {onDeck.first}</span>}
            </div>
            <div className="announcer-dj-controls">
              <button type="button" className="announcer-btn-round" onClick={() => step(-1)} disabled={currentIdx === 0} aria-label="Previous batter"><SkipBack size={18} /></button>
              <button type="button" className="announcer-btn-play" onClick={() => playPlayer(current)} aria-label={playing ? 'Stop' : 'Play'}>
                {playing ? <Square size={26} /> : <Play size={28} style={{ marginLeft: 3 }} />}
              </button>
              <button type="button" className="announcer-btn-round" onClick={() => step(1)} disabled={currentIdx >= battingOrder.length - 1} aria-label="Next batter"><SkipForward size={18} /></button>
            </div>
          </div>
          <div className="announcer-progress-track"><div className="announcer-progress-fill" style={{ width: `${pct}%` }} /></div>
          <div className="announcer-dj-situation">
            {['1B', '2B', '3B'].map((b, i) => (
              <button
                type="button"
                key={b}
                className={`announcer-base-btn${situation.bases[i] ? ' announcer-base-btn--on' : ''}`}
                aria-pressed={situation.bases[i]}
                onClick={() => pushSituation({ ...situation, bases: situation.bases.map((v, j) => (j === i ? !v : v)) })}
              >{b}</button>
            ))}
            <button type="button" className="announcer-base-btn" onClick={() => pushSituation({ ...situation, outs: (situation.outs + 1) % 3 })}>
              {situation.outs} out{situation.outs === 1 ? '' : 's'}
            </button>
            <button type="button" className="announcer-btn announcer-btn-accent announcer-halo-trigger" onClick={() => setShowHalo(true)}>
              <Zap size={14} /> Halo
            </button>
          </div>
        </div>
      )}

      {sheetPlayer && (
        <PlayerSheet
          player={roster.find(p => p.id === sheetPlayer.id) || sheetPlayer}
          profiles={profiles}
          defaultVoiceId={defaultVoiceId}
          onClose={() => setSheetPlayer(null)}
          onSave={savePlayer}
          onRender={renderPlayer}
          onRemove={removePlayer}
        />
      )}
      {showVoices && <VoicePicker profiles={profiles} defaultVoiceId={defaultVoiceId} onChoose={chooseVoice} onClose={() => setShowVoices(false)} />}
      {showAddSub && <AddSubModal onClose={() => setShowAddSub(false)} onAdd={addSub} />}
      {showHalo && current && <HaloOverlay player={current} onSelect={fireHalo} onClose={() => setShowHalo(false)} />}
    </div>
  );
}
