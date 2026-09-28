import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { createPortal } from 'react-dom';
import {
  Mic, Play, Square, SkipBack, SkipForward, RefreshCw, UserPlus,
  AlertCircle, Volume2, Zap, X, ChevronDown, ChevronUp, Check, Trash2, Pin, Shuffle, Plus, Music,
} from 'lucide-react';
import { playIntro, playClip, stop as stopAudio, preload, cleanup, setVolume } from '../utils/audioController';
import { apiRequest } from '../utils/apiClient';

// One screen, Ballpark DJ style: the batting order is a list of big rows, each
// with its own Play. Tap a row to fix how the name is said, add calls in any
// voice, or set walk-up songs. Each at-bat plays a random call and song (never
// the pair just played) unless one is pinned. A sticky bar at the bottom shows
// who is up and what will play, and carries the situation controls and Halo.

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

// Mirrors tools/announcer_engine._spoken_name. GameChanger abbreviates some
// surnames to one letter ("Ava W"), and a voice reads that out as a letter,
// so the first name carries the call unless a coach overrides it.
function spokenName(first, last) {
  const f = (first || '').trim();
  const l = (last || '').trim();
  if (!f) return l;
  return l.replace(/\.$/, '').trim().length <= 1 ? f : `${f} ${l}`;
}

// Mirrors the server's standard walk-up so the sheet can preview while typing.
// A player with no jersey number gets no number call at all.
function previewLine(player, phonetic) {
  const name = (phonetic || '').trim() || spokenName(player.first, player.last);
  const num = numToWord(player.number);
  return `Now batting... ${num ? `NUMBEEEER ${num}... ` : ''}${name}!`;
}

// Mirrors MAX_INTROS / MAX_SONGS in tools/announcer_engine.py.
const MAX_ITEMS = 4;

// Rosters cached before multiple calls existed carry one clip and one song.
const introsOf = (p) => p.intros || (p.announcer_audio_url ? [{ id: 'legacy', clip_url: p.announcer_audio_url, voice: p.voice_rendered || '' }] : []);
const songsOf = (p) => p.songs || (p.walkup_song_url ? [{ id: 'legacy', url: p.walkup_song_url, start: p.intro_timestamp ?? 5 }] : []);

function randomOther(items, lastId) {
  const pool = items.length > 1 ? items.filter(x => x.id !== lastId) : items;
  return pool[Math.floor(Math.random() * pool.length)]?.id || '';
}
const rollPair = (p, last = {}) => ({ intro: randomOther(introsOf(p), last.intro), song: randomOther(songsOf(p), last.song) });

// A pin wins, then the queued pick, then the first item.
function pairFor(p, q = {}) {
  const pick = (items, pinnedId, id) => items.find(x => x.id === pinnedId) || items.find(x => x.id === id) || items[0] || null;
  return { intro: pick(introsOf(p), p.intro_pick, q.intro), song: pick(songsOf(p), p.song_pick, q.song) };
}

function songLabel(url) {
  try { return decodeURIComponent(new URL(url).pathname.split('/').pop()).replace(/\.[a-z0-9]+$/i, '') || 'Walk-up song'; }
  catch { return 'Walk-up song'; }
}

const newId = () => Math.random().toString(36).slice(2, 10);

function useEscapeToClose(onClose) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' || e.key === 'Esc') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);
}

function StatusLed({ status }) {
  const color = { ready: 'var(--success)', rendering: 'var(--warning)', error: 'var(--danger)' }[status] || 'rgba(255,255,255,0.25)';
  const label = { ready: 'Ready', rendering: 'Rendering', error: 'Error', pending: 'Needs render' }[status] || status;
  return <span className="announcer-status-led" style={{ background: color }} title={label} aria-label={label} />;
}

// ── Lineup row ─────────────────────────────────────────────────────────────
function LineupRow({ player, slot, isCurrent, isPlaying, onPlay, onOpen }) {
  const calls = introsOf(player).length;
  const songs = songsOf(player).length;
  const hasClip = calls > 0;
  const hasSong = songs > 0;
  return (
    <div className={`announcer-lineup-row glass-panel${isCurrent ? ' announcer-lineup-row--current' : ''}`}>
      <button type="button" className="announcer-lineup-main" onClick={() => onOpen(player)} aria-label={`Edit ${player.first} ${player.last}`}>
        <span className="announcer-lineup-slot">{slot}</span>
        <span className="announcer-jersey">#{player.number || '–'}</span>
        <span className="announcer-lineup-name">
          <span className="announcer-lineup-first">{player.first} <strong>{player.last}</strong></span>
          <span className="announcer-lineup-sub">
            <StatusLed status={player.status} />
            {player.status === 'rendering' ? 'Rendering…'
              : player.status === 'error' ? 'Render failed'
              : hasClip && player.status === 'pending' ? 'Ready · new voice available'
              : hasClip ? `${calls} call${calls === 1 ? '' : 's'}` : 'Tap to set up'}
            {hasSong && <span> · <Music size={11} style={{ verticalAlign: '-2px' }} /> {songs} song{songs === 1 ? '' : 's'}</span>}
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
  const [voice, setVoice] = useState(player.voice_profile_id || defaultVoiceId);
  const [songs, setSongs] = useState(() => songsOf(player).map(s => ({ ...s })));
  const [songPick, setSongPick] = useState(player.song_pick || '');
  const [hearing, setHearing] = useState('');
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState('');
  const [confirmDelete, setConfirmDelete] = useState('');
  const [confirmRemove, setConfirmRemove] = useState(false);
  const intros = introsOf(player);
  const voiceName = (id) => profiles.find(p => p.id === id)?.name || 'Announcer';

  useEffect(() => () => stopAudio(), []);

  const payload = () => {
    const kept = songs.filter(s => s.url.trim()).map(s => ({ id: s.id, url: s.url.trim(), start: Number(s.start) || 0 }));
    return {
      phonetic_hint: phonetic.trim(),
      songs: kept,
      song_pick: kept.some(s => s.id === songPick) ? songPick : '',
    };
  };

  const save = async () => {
    setBusy('save'); setMsg('');
    try { await onSave(player.id, payload()); setMsg('Saved.'); }
    catch (e) { setMsg(e.message || 'Save failed'); }
    finally { setBusy(''); }
  };

  const addCall = async () => {
    setBusy('render'); setMsg('');
    try {
      await onSave(player.id, payload());
      await onRender(player.id, null, voice);
      // The parent shows the "Rendering…" notice; this sheet is about to close.
      onClose();
    } catch (e) { setMsg(e.message || 'Render failed'); setBusy(''); }
  };

  // Pins and deletes on calls save straight away; songs wait for Save.
  const saveNow = async (data) => {
    setMsg('');
    try { await onSave(player.id, data); } catch (e) { setMsg(e.message || 'Save failed'); }
  };

  const hear = (id, { clipUrl, songUrl, at }) => {
    if (hearing === id) { stopAudio(); setHearing(''); return; }
    setHearing(id);
    const done = () => setHearing('');
    if (clipUrl) playClip(clipUrl, done).catch(done);
    else playIntro({ walkupUrl: songUrl, clipUrl: '', introTimestamp: at, onEnd: done }).catch(done);
  };

  const editSong = (i, patch) => setSongs(list => list.map((s, j) => (j === i ? { ...s, ...patch } : s)));

  return createPortal(
    <div className="announcer-modal-overlay" onClick={onClose}>
      <div className="announcer-modal glass-panel" onClick={e => e.stopPropagation()} style={{ maxWidth: 440, ...MODAL_SCROLL_STYLE }}>
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

        <div className="announcer-section-head">
          <span>Calls</span>
          <small>{intros.some(i => i.id === player.intro_pick) ? 'Pinned call plays every time' : 'Random each at-bat'}</small>
        </div>
        {intros.length === 0 && <p className="announcer-hint">No calls yet. Pick a voice and add one.</p>}
        {intros.map((i, n) => {
          const pinned = i.id === player.intro_pick;
          return (
            <div key={i.id} className="announcer-voice-row">
              <button type="button" className="announcer-btn-round" onClick={() => hear(i.id, { clipUrl: i.clip_url })} aria-label={`Hear call ${n + 1}`}>
                {hearing === i.id ? <Square size={16} /> : <Play size={16} style={{ marginLeft: 2 }} />}
              </button>
              <div className="announcer-voice-text">
                <strong>{voiceName(i.voice)}</strong>
                <span>{i.draft ? 'Quick draft' : 'Studio'}{pinned ? ' · pinned' : ''}</span>
              </div>
              <button type="button" className={`announcer-icon-btn${pinned ? ' announcer-icon-btn--on' : ''}`} aria-pressed={pinned}
                onClick={() => saveNow({ intro_pick: pinned ? '' : i.id })} aria-label={pinned ? `Unpin call ${n + 1}` : `Always play call ${n + 1}`}>
                <Pin size={16} />
              </button>
              <button type="button" className="announcer-icon-btn" aria-label={confirmDelete === i.id ? `Confirm delete call ${n + 1}` : `Delete call ${n + 1}`}
                onClick={() => { if (confirmDelete === i.id) { setConfirmDelete(''); saveNow({ remove_intro: i.id }); } else setConfirmDelete(i.id); }}>
                {confirmDelete === i.id ? <Check size={16} /> : <Trash2 size={16} />}
              </button>
            </div>
          );
        })}
        <div className="announcer-add-row">
          <select value={voice} onChange={e => setVoice(e.target.value)} aria-label="Voice for the new call">
            {profiles.map(p => <option key={p.id} value={p.id}>{p.name} — {p.tagline}</option>)}
          </select>
          <button type="button" className="announcer-btn announcer-btn-primary" onClick={addCall} disabled={Boolean(busy)}>
            {busy === 'render' ? <RefreshCw size={14} className="sync-spin" /> : <Plus size={14} />} Add call
          </button>
        </div>
        {intros.length >= MAX_ITEMS && <small className="announcer-hint">A new call replaces the oldest one that isn't pinned.</small>}

        <div className="announcer-section-head">
          <span>Walk-up songs</span>
          <small>{songs.some(s => s.id === songPick) ? 'Pinned song plays every time' : 'Random each at-bat'}</small>
        </div>
        {songs.map((s, n) => {
          const pinned = s.id === songPick;
          return (
            <div key={s.id} className="announcer-song-row">
              <input value={s.url} onChange={e => editSong(n, { url: e.target.value })} placeholder="https://…mp3" inputMode="url" maxLength={500} aria-label={`Song ${n + 1} link`} />
              <input type="number" min="0" max="300" step="0.5" value={s.start} onChange={e => editSong(n, { start: e.target.value })}
                className="announcer-song-start" aria-label={`Song ${n + 1} start, in seconds`} title="Start at (seconds)" />
              <button type="button" className="announcer-icon-btn" disabled={!s.url.trim()} aria-label={`Hear song ${n + 1}`}
                onClick={() => hear(s.id, { songUrl: s.url.trim(), at: Number(s.start) || 0 })}>
                {hearing === s.id ? <Square size={16} /> : <Play size={16} />}
              </button>
              <button type="button" className={`announcer-icon-btn${pinned ? ' announcer-icon-btn--on' : ''}`} aria-pressed={pinned}
                onClick={() => setSongPick(pinned ? '' : s.id)} aria-label={pinned ? `Unpin song ${n + 1}` : `Always play song ${n + 1}`}>
                <Pin size={16} />
              </button>
              <button type="button" className="announcer-icon-btn" onClick={() => setSongs(list => list.filter((_, j) => j !== n))} aria-label={`Remove song ${n + 1}`}>
                <X size={16} />
              </button>
            </div>
          );
        })}
        {songs.length < MAX_ITEMS && (
          <button type="button" className="announcer-btn announcer-btn-secondary" onClick={() => setSongs(list => [...list, { id: newId(), url: '', start: 5 }])}>
            <Plus size={14} /> Add song
          </button>
        )}
        <small className="announcer-hint">The number is where the song starts, in seconds. 0 finds the beat for you.</small>

        {msg && <div className="announcer-error-msg" role="status">{msg}</div>}

        <div className="announcer-form-actions">
          <button type="button" className="announcer-btn announcer-btn-primary" onClick={save} disabled={Boolean(busy)}>
            {busy === 'save' ? <RefreshCw size={14} className="sync-spin" /> : <Check size={14} />} Save
          </button>
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

// ── PA announcements ───────────────────────────────────────────────────────
// Free-text lines ("Please welcome the Blue Jays…"). A render worker voices them
// with Qwen3-TTS when one is online; otherwise the Pi's quick voice does.
const PA_MAX_CHARS = 600; // matches announcer_engine.PA_MAX_CHARS

function PAModal({ onClose }) {
  useEscapeToClose(onClose);
  const [text, setText] = useState('');
  const [style, setStyle] = useState('halo');
  const [styles, setStyles] = useState([]);
  const [items, setItems] = useState([]);
  const [waitingId, setWaitingId] = useState('');
  const [playingId, setPlayingId] = useState('');
  const [err, setErr] = useState('');

  const load = useCallback(async () => {
    const res = await fetch('/api/announcer/pa');
    if (!res.ok) return [];
    const data = await res.json();
    setStyles(data.styles || []);
    setItems(data.announcements || []);
    return data.announcements || [];
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load().catch(() => {});
    return () => stopAudio();
  }, [load]);

  const play = (item) => {
    if (playingId === item.id) { stopAudio(); setPlayingId(''); return; }
    setPlayingId(item.id);
    playClip(item.clip_url, () => setPlayingId('')).catch(() => setPlayingId(''));
  };

  // Poll until the new clip lands, then play it straight away.
  useEffect(() => {
    if (!waitingId) return undefined;
    const deadline = Date.now() + 120000;
    const timer = setInterval(async () => {
      const list = await load().catch(() => []);
      const job = list.find(i => i.id === waitingId);
      if (job?.status === 'COMPLETED' && job.clip_url) { setWaitingId(''); play(job); }
      else if (job?.status === 'FAILED') { setWaitingId(''); setErr(`Render failed: ${job.error || 'unknown'}`); }
      else if (Date.now() > deadline) { setWaitingId(''); setErr('Still rendering — it will appear in the list when done.'); }
    }, 2000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [waitingId, load]);

  const submit = async (e) => {
    e.preventDefault();
    if (!text.trim()) { setErr('Type what the announcer should say'); return; }
    setErr('');
    try {
      const res = await apiRequest('/api/announcer/pa', { method: 'POST', headers: ORIGIN_HEADERS(), body: JSON.stringify({ text, style }) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `${res.status}`);
      setWaitingId(data.job.id);
      await load();
    } catch (ex) { setErr(`Could not render: ${ex.message}`); }
  };

  return createPortal(
    <div className="announcer-modal-overlay" onClick={onClose}>
      <form className="announcer-modal glass-panel" onClick={e => e.stopPropagation()} onSubmit={submit} style={{ maxWidth: 460, ...MODAL_SCROLL_STYLE }}>
        <div className="announcer-modal-header">
          <h3 style={{ margin: 0 }}>PA announcement</h3>
          <button type="button" className="announcer-modal-close" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        <label className="announcer-form-group">
          <span>What should the announcer say?</span>
          <textarea value={text} onChange={e => setText(e.target.value)} rows={4} maxLength={PA_MAX_CHARS} autoFocus
            placeholder="Ladies and gentlemen, please rise for the national anthem." />
          <small>{text.length}/{PA_MAX_CHARS}</small>
        </label>
        <label className="announcer-form-group">
          <span>Style</span>
          <select value={style} onChange={e => setStyle(e.target.value)}>
            {styles.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </label>
        {err && <div className="announcer-error-msg">{err}</div>}
        <div className="announcer-form-actions">
          <button type="submit" className="announcer-btn announcer-btn-primary" disabled={Boolean(waitingId)}>
            {waitingId ? <><RefreshCw size={14} className="sync-spin" /> Rendering…</> : <><Mic size={14} /> Render &amp; play</>}
          </button>
        </div>
        {items.length > 0 && <p className="announcer-hint" style={{ marginTop: 'var(--space-md)' }}>Recent</p>}
        {items.map(item => (
          <div key={item.id} className="announcer-voice-row">
            <button type="button" className="announcer-btn-round" onClick={() => play(item)} disabled={!item.clip_url} aria-label="Play announcement">
              {playingId === item.id ? <Square size={16} /> : <Play size={16} style={{ marginLeft: 2 }} />}
            </button>
            <div className="announcer-voice-text">
              <strong>{item.text}</strong>
              <span>{item.status === 'COMPLETED' ? (item.quality === 'best' ? 'Qwen3 voice' : 'Quick voice') : item.status.toLowerCase()}</span>
            </div>
          </div>
        ))}
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
  const [showPA, setShowPA] = useState(false);
  const [showHalo, setShowHalo] = useState(false);
  const [showFormer, setShowFormer] = useState(false);
  const [renderAllBusy, setRenderAllBusy] = useState(false);
  // Next call/song queued per player, and what each played last, so the DJ bar
  // can show what's coming and a replay never repeats the same pair.
  const [queued, setQueued] = useState({});
  const [nowPair, setNowPair] = useState(null);
  const lastPlayed = useRef({});
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
    const need = [current, onDeck].filter(p => p && !queued[p.id]);
    if (need.length) setQueued(q => ({ ...q, ...Object.fromEntries(need.map(p => [p.id, rollPair(p, lastPlayed.current[p.id])])) }));
  }, [current, onDeck, queued]);

  const nextPair = current ? pairFor(current, queued[current.id]) : null;
  const deckPair = onDeck ? pairFor(onDeck, queued[onDeck.id]) : null;
  const deckSong = deckPair?.song?.url || '';
  const deckClip = deckPair?.intro?.clip_url || '';
  useEffect(() => {
    preload([deckSong, deckClip].filter(Boolean));
  }, [deckSong, deckClip]);

  // ── playback ──
  const stop = useCallback(() => { stopAudio(); setPlaying(false); setProgress({ elapsed: 0, duration: 0 }); }, []);

  // `override` plays a specific call (Halo) instead of this at-bat's pick.
  const playPlayer = useCallback(async (p, override) => {
    if (currentId === p.id && playing) { stop(); return; }
    const pair = override || pairFor(p, queued[p.id] || rollPair(p, lastPlayed.current[p.id]));
    if (!override) {
      lastPlayed.current[p.id] = { intro: pair.intro?.id, song: pair.song?.id };
      setQueued(q => ({ ...q, [p.id]: rollPair(p, lastPlayed.current[p.id]) }));
    }
    setNowPair(pair);
    setCurrentId(p.id);
    setPlaying(true);
    const start = pair.song?.start ?? 5;
    try {
      await playIntro({
        walkupUrl: pair.song?.url || '',
        clipUrl: pair.intro?.clip_url || '',
        introTimestamp: start,
        autoBPM: start === 0,
        onEnd: () => setPlaying(false),
        onProgress: setProgress,
      });
    } catch { setPlaying(false); }
  }, [currentId, playing, stop, queued]);

  const reshuffle = () => {
    if (current) setQueued(q => ({ ...q, [current.id]: rollPair(current, { intro: nextPair.intro?.id, song: nextPair.song?.id }) }));
  };

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

  const renderPlayer = async (playerId, gameContext, voiceId) => {
    const body = gameContext ? { quality: 'best', game_context: gameContext } : { quality: 'best' };
    if (voiceId) body.voice_id = voiceId;
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
        playPlayer(fresh, { intro: { clip_url: fresh.announcer_audio_url, voice: '' }, song: null });
        return;
      }
      if (fresh?.status === 'error') { setNotice(`Render failed: ${fresh.error_message || 'unknown'}`); return; }
    }
    setNotice('Render is taking longer than usual — it will appear on the row when done.');
  };

  const shown = playing ? nowPair : nextPair;
  const canShuffle = current && (
    (introsOf(current).length > 1 && !introsOf(current).some(i => i.id === current.intro_pick)) ||
    (songsOf(current).length > 1 && !songsOf(current).some(s => s.id === current.song_pick)));
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
          <button type="button" className="announcer-btn announcer-btn-secondary" onClick={() => setShowPA(true)} aria-label="PA announcement">
            <Mic size={14} /> PA
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
              {shown && (shown.intro || shown.song) && (
                <span className="announcer-dj-pair">
                  {shown.intro && <span><Mic size={11} /> {shown.intro.voice ? (profiles.find(v => v.id === shown.intro.voice)?.name || 'Announcer') : 'Halo call'}</span>}
                  {shown.song && <span><Music size={11} /> {songLabel(shown.song.url)}</span>}
                  {!playing && canShuffle && (
                    <button type="button" className="announcer-icon-btn announcer-dj-shuffle" onClick={reshuffle} aria-label="Pick a different call and song">
                      <Shuffle size={13} />
                    </button>
                  )}
                </span>
              )}
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
      {showPA && <PAModal onClose={() => setShowPA(false)} />}
      {showHalo && current && <HaloOverlay player={current} onSelect={fireHalo} onClose={() => setShowHalo(false)} />}
    </div>
  );
}
