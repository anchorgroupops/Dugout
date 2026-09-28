import React, { useState, useEffect, useCallback, useRef, useMemo, useSyncExternalStore } from 'react';
import { createPortal } from 'react-dom';
import {
  Mic, Play, Square, RefreshCw, UserPlus, AlertCircle, Volume2, Zap, X, Check, Trash2, Pin,
  Shuffle, Plus, Music, Settings, SkipForward, Pencil, WifiOff, Megaphone, RotateCcw,
} from 'lucide-react';
import {
  subscribe as subscribeAudio, getState as getAudioState, play, playClip, stop as stopAudio,
  preload, warm, unlock, dismissError,
} from '../utils/audioController';
import { apiRequest } from '../utils/apiClient';
import {
  MAX_ITEMS, introsOf, songsOf, rollPair, pairFor, isPinned, pickMode, songLabel, rowState,
  needsRender, orderBattingLineup, previewLine, describeApiError,
} from '../utils/announcerPicks';

// The Announcer tab, built like a sports-app game screen:
//   • one list, in batting order; tapping a player announces them
//   • a now-playing bar that always says what is playing, loading, failed,
//     or up next, with one big button (Play / Stop / Retry)
//   • every row says whether its call is ready, being made, or failed
//   • setup (names, calls, songs, voice, subs) lives in sheets that save as
//     you go and close from anywhere — nothing to lose, nothing to trap you
// Playback state comes from audioController's store, never local flags.

// Must match _HALO_SCRIPTS keys in tools/announcer_engine.py
const BIG_MOMENTS = [
  { key: 'grand_slam', label: 'Grand Slam', desc: 'Grand. Slam. QUEEN!' },
  { key: 'cycle', label: 'The Cycle', desc: 'PERFECTION!' },
  { key: 'triple_rbi', label: 'Hat Trick', desc: '3 RBI' },
  { key: 'quad_rbi', label: 'Grand Slam Hero', desc: '4 RBI' },
  { key: '3_strikeouts', label: 'Strikeout Artist', desc: '3 K' },
  { key: '4_strikeouts', label: 'On Fire', desc: '4 K' },
  { key: '5_strikeouts', label: 'Untouchable', desc: '5 K' },
];

const PA_MAX_CHARS = 600; // matches announcer_engine.PA_MAX_CHARS
const POLL_MS = 3000;

// Every write goes through here: JSON body (the API refuses anything else,
// including DELETE), write-token handling from apiRequest, and the server's
// error code turned into words instead of "Could not save".
async function api(path, method = 'POST', body = {}) {
  let res;
  try {
    res = await apiRequest(path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  } catch {
    throw new Error(describeApiError(0));
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(describeApiError(res.status, data.error));
  return data;
}

const fullName = (p) => `${p.first || ''} ${p.last || ''}`.trim();
const jersey = (p) => (p.number ? `#${p.number}` : '#–');

function useEscape(onClose) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' || e.key === 'Esc') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);
}

// A sheet closes on ✕, Escape or a tap outside. It never holds unsaved work.
function Sheet({ title, onClose, children }) {
  useEscape(onClose);
  return createPortal(
    <div className="announcer-modal-overlay" onClick={onClose}>
      <div className="announcer-modal announcer-sheet glass-panel" role="dialog" aria-modal="true" aria-label={title}
        onClick={e => e.stopPropagation()}>
        <div className="announcer-modal-header">
          <h3>{title}</h3>
          <button type="button" className="announcer-modal-close" onClick={onClose} aria-label="Close"><X size={20} /></button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}

function Spinner({ size = 14 }) {
  return <RefreshCw size={size} className="sync-spin" aria-hidden="true" />;
}

function SheetMessage({ msg }) {
  if (!msg?.text) return null;
  return <div className={`announcer-msg announcer-msg--${msg.kind || 'info'}`} role="status">{msg.text}</div>;
}

// Small round preview button used in every sheet; state comes from the store.
function HearButton({ hearKey, audio, onHear, label, disabled }) {
  const active = audio.key === hearKey && (audio.status === 'playing' || audio.status === 'loading');
  return (
    <button type="button" className="announcer-btn-round" onClick={onHear} disabled={disabled}
      aria-label={active ? `Stop ${label}` : `Hear ${label}`}>
      {active ? (audio.status === 'loading' ? <Spinner size={16} /> : <Square size={16} />) : <Play size={16} style={{ marginLeft: 2 }} />}
    </button>
  );
}

// ── Roster row ─────────────────────────────────────────────────────────────
function PlayerRow({ player, slot, audio, isNext, voiceName, onAnnounce, onEdit }) {
  const st = rowState(player);
  const intros = introsOf(player);
  const songs = songsOf(player);
  const isThis = audio.key === player.id;
  const busy = isThis && (audio.status === 'playing' || audio.status === 'loading');
  const callMode = pickMode(intros, player.intro_pick, 'call', i => voiceName(i.voice));
  const songMode = pickMode(songs, player.song_pick, 'song', s => songLabel(s.url));
  const mainLabel = !st.canPlay ? `Set up ${fullName(player)}` : busy ? `Stop ${fullName(player)}` : `Announce ${fullName(player)}`;
  return (
    <div className={`announcer-row glass-panel${busy ? ' announcer-row--playing' : ''}${isNext && !busy ? ' announcer-row--next' : ''}`}>
      <button type="button" className="announcer-row-main" aria-label={mainLabel}
        onClick={() => (st.canPlay ? onAnnounce(player) : onEdit(player))}>
        <span className="announcer-row-slot">{slot}</span>
        <span className="announcer-jersey">{jersey(player)}</span>
        <span className="announcer-row-text">
          <span className="announcer-row-name">{player.first} <strong>{player.last}</strong></span>
          <span className="announcer-row-sub">
            {busy && <span className="announcer-tag announcer-tag--live">{audio.status === 'loading' ? 'Loading' : 'Playing'}</span>}
            {isNext && !busy && <span className="announcer-tag">Up next</span>}
            <span className={`announcer-badge announcer-badge--${st.kind}`}>
              {st.kind === 'rendering' && <Spinner size={11} />}{st.label}
            </span>
            {callMode && <span><Mic size={11} /> {callMode}</span>}
            {songMode && <span><Music size={11} /> {songMode}</span>}
          </span>
        </span>
        <span className={`announcer-row-go${busy ? ' announcer-row-go--stop' : ''}${!st.canPlay ? ' announcer-row-go--setup' : ''}`} aria-hidden="true">
          {!st.canPlay ? <Plus size={22} /> : busy ? <Square size={20} /> : <Play size={22} style={{ marginLeft: 3 }} />}
        </span>
      </button>
      <button type="button" className="announcer-row-edit" onClick={() => onEdit(player)} aria-label={`Set up ${fullName(player)}`}>
        <Pencil size={18} />
      </button>
    </div>
  );
}

// ── Player setup sheet ─────────────────────────────────────────────────────
function PlayerSheet({ player, profiles, defaultVoiceId, audio, voiceName, onHear, onClose, onSave, onRender, onRemove, onMoment }) {
  const [phonetic, setPhonetic] = useState(player.phonetic_hint || '');
  const [voice, setVoice] = useState(player.voice_profile_id || defaultVoiceId);
  const [newSong, setNewSong] = useState({ url: '', start: '5' });
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState(null);
  const [confirm, setConfirm] = useState('');
  const intros = introsOf(player);
  const songs = songsOf(player);
  const st = rowState(player);
  const nameDirty = phonetic.trim() !== (player.phonetic_hint || '').trim();

  const run = async (tag, fn, okText) => {
    setBusy(tag); setMsg(null); setConfirm('');
    try { await fn(); if (okText) setMsg({ text: okText, kind: 'ok' }); return true; }
    catch (e) { setMsg({ text: e.message, kind: 'error' }); return false; }
    finally { setBusy(''); }
  };
  const save = (tag, data, okText) => run(tag, () => onSave(player.id, data), okText);

  // Closing saves a typed-but-unsaved name rather than dropping it or asking.
  const close = () => {
    if (!nameDirty) { onClose(); return; }
    onClose(onSave(player.id, { phonetic_hint: phonetic.trim() })
      .then(() => `Saved how to say ${player.first}. Make a call to hear it.`)
      .catch(e => `Name not saved: ${e.message}`));
  };

  const makeCall = () => run('call', async () => {
    if (nameDirty) await onSave(player.id, { phonetic_hint: phonetic.trim() });
    await onRender(player.id, voice);
  });

  const twoTap = (id, action) => { if (confirm === id) { setConfirm(''); action(); } else setConfirm(id); };

  const addSong = (e) => {
    e.preventDefault();
    const url = newSong.url.trim();
    if (!/^https?:\/\//i.test(url)) { setMsg({ text: 'Paste a link that starts with http:// or https://', kind: 'error' }); return; }
    const kept = songs.map(s => ({ id: s.id, url: s.url, start: s.start }));
    save('song', { songs: [...kept, { url, start: Number(newSong.start) || 0 }] }, 'Song added.')
      .then(ok => { if (ok) setNewSong({ url: '', start: '5' }); });
  };

  return (
    <Sheet title={`${jersey(player)} ${fullName(player)}`} onClose={close}>
      <section className="announcer-section">
        <label className="announcer-form-group">
          <span>Say the name as</span>
          <input value={phonetic} onChange={e => setPhonetic(e.target.value)} placeholder={fullName(player)}
            maxLength={200} autoCapitalize="off" autoCorrect="off" enterKeyHint="done"
            onKeyDown={e => { if (e.key === 'Enter' && nameDirty) save('name', { phonetic_hint: phonetic.trim() }, 'Saved. Make a call to hear it.'); }} />
          <small>Spell it how it sounds. Capitals get stressed: <em>ROO-bee van-DOO-sen</em></small>
        </label>
        <div className="announcer-preview-text">{previewLine(player, phonetic)}</div>
        {nameDirty && (
          <button type="button" className="announcer-btn announcer-btn-secondary" disabled={Boolean(busy)}
            onClick={() => save('name', { phonetic_hint: phonetic.trim() }, 'Saved. Make a call to hear it.')}>
            {busy === 'name' ? <Spinner /> : <Check size={14} />} Save name
          </button>
        )}
      </section>

      <section className="announcer-section">
        <div className="announcer-section-head">
          <span>Calls</span>
          <small>{pickMode(intros, player.intro_pick, 'call', i => voiceName(i.voice)) || 'None yet'}</small>
        </div>
        {st.kind === 'rendering' && <div className="announcer-msg announcer-msg--info"><Spinner /> Making a new call…</div>}
        {st.kind === 'failed' && (
          <div className="announcer-msg announcer-msg--error">
            <span>Last call failed: {st.error || 'unknown error'}</span>
            <button type="button" className="announcer-btn announcer-btn-secondary" onClick={makeCall} disabled={Boolean(busy)}>
              <RotateCcw size={14} /> Retry
            </button>
          </div>
        )}
        {intros.map((i, n) => {
          const pinned = i.id === player.intro_pick;
          return (
            <div key={i.id} className="announcer-item-row">
              <HearButton hearKey={`hear:${i.id}`} audio={audio} label={`call ${n + 1}`}
                onHear={() => onHear(`hear:${i.id}`, { clipUrl: i.clip_url, label: `${fullName(player)} · ${voiceName(i.voice)}` })} />
              <div className="announcer-item-text">
                <strong>{voiceName(i.voice)}</strong>
                <span>{i.draft ? 'Quick draft' : 'Studio'}{pinned ? ' · always plays' : ''}</span>
              </div>
              <button type="button" className={`announcer-icon-btn${pinned ? ' announcer-icon-btn--on' : ''}`} aria-pressed={pinned}
                aria-label={pinned ? `Stop always playing call ${n + 1}` : `Always play call ${n + 1}`}
                onClick={() => save('pin', { intro_pick: pinned ? '' : i.id }, pinned ? 'Calls shuffle again.' : 'This call plays every time.')}>
                <Pin size={16} />
              </button>
              <button type="button" className={`announcer-icon-btn${confirm === i.id ? ' announcer-icon-btn--danger' : ''}`}
                aria-label={confirm === i.id ? `Tap again to delete call ${n + 1}` : `Delete call ${n + 1}`}
                onClick={() => twoTap(i.id, () => save('del', { remove_intro: i.id }, 'Call deleted.'))}>
                {confirm === i.id ? <Check size={16} /> : <Trash2 size={16} />}
              </button>
            </div>
          );
        })}
        <div className="announcer-add-row">
          <select value={voice} onChange={e => setVoice(e.target.value)} aria-label="Voice for the new call">
            {profiles.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <button type="button" className="announcer-btn announcer-btn-primary" onClick={makeCall}
            disabled={Boolean(busy) || st.kind === 'rendering'}>
            {busy === 'call' ? <Spinner /> : <Plus size={14} />} Make call
          </button>
        </div>
        {intros.length >= MAX_ITEMS && <small className="announcer-hint">A new call replaces the oldest one that isn't pinned.</small>}
      </section>

      <section className="announcer-section">
        <div className="announcer-section-head">
          <span>Walk-up songs</span>
          <small>{pickMode(songs, player.song_pick, 'song', s => songLabel(s.url)) || 'None'}</small>
        </div>
        {songs.map((s, n) => {
          const pinned = s.id === player.song_pick;
          const delKey = `song:${s.id}`;
          return (
            <div key={s.id} className="announcer-item-row">
              <HearButton hearKey={`hear:${s.id}`} audio={audio} label={`song ${n + 1}`}
                onHear={() => onHear(`hear:${s.id}`, { songUrl: s.url, songStart: s.start, label: songLabel(s.url) })} />
              <div className="announcer-item-text">
                <strong>{songLabel(s.url)}</strong>
                <span>{Number(s.start) ? `Call at ${s.start}s` : 'Call on the beat'}{pinned ? ' · always plays' : ''}</span>
              </div>
              <button type="button" className={`announcer-icon-btn${pinned ? ' announcer-icon-btn--on' : ''}`} aria-pressed={pinned}
                aria-label={pinned ? `Stop always playing song ${n + 1}` : `Always play song ${n + 1}`}
                onClick={() => save('pin', { song_pick: pinned ? '' : s.id }, pinned ? 'Songs shuffle again.' : 'This song plays every time.')}>
                <Pin size={16} />
              </button>
              <button type="button" className={`announcer-icon-btn${confirm === delKey ? ' announcer-icon-btn--danger' : ''}`}
                aria-label={confirm === delKey ? `Tap again to remove song ${n + 1}` : `Remove song ${n + 1}`}
                onClick={() => twoTap(delKey, () => save('song', {
                  songs: songs.filter(x => x.id !== s.id).map(x => ({ id: x.id, url: x.url, start: x.start })),
                  ...(pinned ? { song_pick: '' } : {}),
                }, 'Song removed.'))}>
                {confirm === delKey ? <Check size={16} /> : <Trash2 size={16} />}
              </button>
            </div>
          );
        })}
        {songs.length < MAX_ITEMS && (
          <form className="announcer-add-row" onSubmit={addSong}>
            <input value={newSong.url} onChange={e => setNewSong(v => ({ ...v, url: e.target.value }))}
              placeholder="Song link (https://…mp3)" inputMode="url" maxLength={500} aria-label="New song link" />
            <input type="number" min="0" max="300" step="0.5" value={newSong.start} className="announcer-song-start"
              onChange={e => setNewSong(v => ({ ...v, start: e.target.value }))} aria-label="Seconds into the song for the call" />
            <button type="submit" className="announcer-btn announcer-btn-secondary" disabled={Boolean(busy) || !newSong.url.trim()}>
              {busy === 'song' ? <Spinner /> : <Plus size={14} />} Add
            </button>
          </form>
        )}
        <small className="announcer-hint">The number is when the call starts, in seconds into the song. 0 finds the beat.</small>
      </section>

      <SheetMessage msg={msg} />

      <section className="announcer-section">
        <div className="announcer-section-head"><span><Zap size={14} /> Big moment</span><small>Makes a one-off call and plays it</small></div>
        <div className="announcer-halo-grid">
          {BIG_MOMENTS.map(a => (
            <button type="button" key={a.key} className="announcer-btn announcer-btn-accent announcer-halo-btn" onClick={() => onMoment(player, a)}>
              <span>{a.label}</span><small>{a.desc}</small>
            </button>
          ))}
        </div>
      </section>

      {/* Only subs and former players can be removed: anyone GameChanger
          still lists comes straight back, so the server refuses (409). */}
      {(player.is_sub || player.is_ghost || player.is_active === false) ? (
        <button type="button" className={`announcer-btn announcer-btn-secondary announcer-remove-btn${confirm === 'remove' ? ' announcer-remove-btn--armed' : ''}`}
          onClick={() => twoTap('remove', () => run('remove', () => onRemove(player.id)).then(ok => { if (ok) onClose(`Removed ${player.first} from the announcer.`); }))}>
          <Trash2 size={14} /> {confirm === 'remove' ? 'Tap again to remove from the announcer' : 'Remove player'}
        </button>
      ) : (
        <small className="announcer-hint announcer-remove-note">{player.first} is on the GameChanger roster, so she stays here. Subs and former players can be removed.</small>
      )}
    </Sheet>
  );
}

// ── Settings sheet: team voice, subs, former players ───────────────────────
function SettingsSheet({ profiles, defaultVoiceId, audio, former, onHear, onChooseVoice, onAddSub, onEdit, onClose }) {
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState(null);
  const [sub, setSub] = useState({ first: '', last: '', number: '' });

  const choose = async (id) => {
    setBusy(id); setMsg(null);
    try { setMsg({ text: await onChooseVoice(id), kind: 'ok' }); }
    catch (e) { setMsg({ text: e.message, kind: 'error' }); }
    finally { setBusy(''); }
  };
  const addSub = async (e) => {
    e.preventDefault();
    if (!sub.first.trim()) { setMsg({ text: 'First name is required.', kind: 'error' }); return; }
    setBusy('sub'); setMsg(null);
    try {
      await onAddSub({ first: sub.first.trim(), last: sub.last.trim(), number: sub.number.trim() });
      setMsg({ text: `Added ${sub.first.trim()}. Making the call now.`, kind: 'ok' });
      setSub({ first: '', last: '', number: '' });
    } catch (ex) { setMsg({ text: ex.message, kind: 'error' }); }
    finally { setBusy(''); }
  };

  return (
    <Sheet title="Announcer settings" onClose={onClose}>
      <section className="announcer-section">
        <div className="announcer-section-head"><span>Team voice</span><small>Changing it remakes every team-voice call</small></div>
        {profiles.map(p => (
          <div key={p.id} className={`announcer-item-row${p.id === defaultVoiceId ? ' announcer-item-row--active' : ''}`}>
            <HearButton hearKey={`sample:${p.id}`} audio={audio} label={`${p.name} sample`}
              onHear={() => onHear(`sample:${p.id}`, { clipUrl: `/api/announcer/voice-sample/${p.id}`, label: `${p.name} sample` })} />
            <div className="announcer-item-text"><strong>{p.name}</strong><span>{p.tagline}</span></div>
            {p.id === defaultVoiceId
              ? <span className="announcer-voice-current"><Check size={14} /> In use</span>
              : (
                <button type="button" className="announcer-btn announcer-btn-accent" onClick={() => choose(p.id)} disabled={Boolean(busy)}>
                  {busy === p.id ? <Spinner /> : 'Use'}
                </button>
              )}
          </div>
        ))}
      </section>

      <form className="announcer-section" onSubmit={addSub}>
        <div className="announcer-section-head"><span><UserPlus size={14} /> Add a sub</span></div>
        <div className="announcer-sub-grid">
          <input value={sub.first} onChange={e => setSub(v => ({ ...v, first: e.target.value }))} placeholder="First name" maxLength={64} aria-label="First name" />
          <input value={sub.last} onChange={e => setSub(v => ({ ...v, last: e.target.value }))} placeholder="Last name" maxLength={64} aria-label="Last name" />
          <input value={sub.number} onChange={e => setSub(v => ({ ...v, number: e.target.value }))} placeholder="#" inputMode="numeric" maxLength={4} aria-label="Jersey number" />
        </div>
        <button type="submit" className="announcer-btn announcer-btn-primary" disabled={Boolean(busy)}>
          {busy === 'sub' ? <Spinner /> : <Plus size={14} />} Add &amp; make call
        </button>
      </form>

      <SheetMessage msg={msg} />

      {former.length > 0 && (
        <section className="announcer-section">
          <div className="announcer-section-head"><span>Former players</span><small>Not on the current roster</small></div>
          {former.map(p => (
            <div key={p.id} className="announcer-item-row">
              <div className="announcer-item-text"><strong>{jersey(p)} {fullName(p)}</strong><span>{rowState(p).label}</span></div>
              <button type="button" className="announcer-icon-btn" onClick={() => onEdit(p)} aria-label={`Set up ${fullName(p)}`}><Pencil size={16} /></button>
            </div>
          ))}
        </section>
      )}
    </Sheet>
  );
}

// ── PA announcements ───────────────────────────────────────────────────────
function PASheet({ audio, onClose }) {
  const [text, setText] = useState('');
  const [style, setStyle] = useState('halo');
  const [styles, setStyles] = useState([]);
  const [items, setItems] = useState([]);
  const [waitingId, setWaitingId] = useState('');
  const [msg, setMsg] = useState(null);
  const [loadErr, setLoadErr] = useState('');

  const load = useCallback(async () => {
    const res = await fetch('/api/announcer/pa');
    if (!res.ok) throw new Error(describeApiError(res.status));
    const data = await res.json();
    setStyles(data.styles || []);
    setItems(data.announcements || []);
    setLoadErr('');
    return data.announcements || [];
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch
    load().catch(e => setLoadErr(`Couldn't load recent announcements: ${e.message}`));
  }, [load]);

  const hear = (item) => {
    const key = `pa:${item.id}`;
    if (audio.key === key && audio.status !== 'idle' && audio.status !== 'error') { stopAudio(); return; }
    playClip(item.clip_url, { key, label: 'PA announcement', detail: item.text });
  };

  // Poll until the new clip lands, then play it. A job that never finishes
  // stops the wait after 3 minutes and says so.
  useEffect(() => {
    if (!waitingId) return undefined;
    const deadline = Date.now() + 180000;
    const timer = setInterval(async () => {
      const list = await load().catch(() => null);
      const job = list?.find(i => i.id === waitingId);
      if (job?.status === 'COMPLETED' && job.clip_url) {
        setWaitingId('');
        playClip(job.clip_url, { key: `pa:${job.id}`, label: 'PA announcement', detail: job.text });
      } else if (job?.status === 'FAILED') {
        setWaitingId(''); setMsg({ text: `That announcement failed: ${job.error || 'unknown error'}`, kind: 'error' });
      } else if (Date.now() > deadline) {
        setWaitingId(''); setMsg({ text: 'Still being made. It will appear in Recent when it is ready.', kind: 'info' });
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [waitingId, load]);

  const submit = async (e) => {
    e.preventDefault();
    if (!text.trim()) { setMsg({ text: 'Type what the announcer should say.', kind: 'error' }); return; }
    setMsg(null);
    try {
      const data = await api('/api/announcer/pa', 'POST', { text, style });
      setWaitingId(data.job.id);
      await load().catch(() => {});
    } catch (ex) { setMsg({ text: ex.message, kind: 'error' }); }
  };

  const statusWord = (item) => (item.status === 'COMPLETED'
    ? (item.quality === 'best' ? 'Studio voice' : 'Quick voice')
    : item.status === 'FAILED' ? `Failed${item.error ? `: ${item.error}` : ''}` : 'Being made…');

  return (
    <Sheet title="PA announcement" onClose={onClose}>
      <form className="announcer-section" onSubmit={submit}>
        <label className="announcer-form-group">
          <span>What should the announcer say?</span>
          <textarea value={text} onChange={e => setText(e.target.value)} rows={3} maxLength={PA_MAX_CHARS}
            placeholder="Ladies and gentlemen, please rise for the national anthem." />
          <small>{text.length}/{PA_MAX_CHARS}</small>
        </label>
        <div className="announcer-add-row">
          <select value={style} onChange={e => setStyle(e.target.value)} aria-label="Announcement style">
            {(styles.length ? styles : [{ id: 'halo', name: 'Arena legend' }]).map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <button type="submit" className="announcer-btn announcer-btn-primary" disabled={Boolean(waitingId)}>
            {waitingId ? <><Spinner /> Making…</> : <><Megaphone size={14} /> Make &amp; play</>}
          </button>
        </div>
      </form>
      <SheetMessage msg={msg} />
      {loadErr && <div className="announcer-msg announcer-msg--error">{loadErr}</div>}
      {items.length > 0 && (
        <section className="announcer-section">
          <div className="announcer-section-head"><span>Recent</span></div>
          {items.map(item => (
            <div key={item.id} className="announcer-item-row">
              <HearButton hearKey={`pa:${item.id}`} audio={audio} label="announcement" disabled={!item.clip_url} onHear={() => hear(item)} />
              <div className="announcer-item-text">
                <strong className="announcer-pa-text">{item.text}</strong>
                <span className={item.status === 'FAILED' ? 'announcer-text-danger' : ''}>{statusWord(item)}</span>
              </div>
            </div>
          ))}
        </section>
      )}
    </Sheet>
  );
}

// ── Now-playing bar ────────────────────────────────────────────────────────
function NowPlayingBar({ audio, upNext, upNextDetail, moment, canShuffle, onAnnounce, onRetry, onShuffle, onSkip }) {
  const pct = audio.duration > 0 ? Math.min(100, (audio.elapsed / audio.duration) * 100) : 0;
  let head, name, detail, action;
  if (audio.status === 'playing' || audio.status === 'loading') {
    head = audio.status === 'loading' ? 'Loading…' : 'Now playing';
    name = audio.label;
    detail = audio.detail;
    action = (
      <button type="button" className="announcer-bar-btn announcer-bar-btn--stop" onClick={stopAudio} aria-label="Stop">
        {audio.status === 'loading' ? <Spinner size={24} /> : <Square size={24} />}
      </button>
    );
  } else if (audio.status === 'error') {
    head = "Couldn't play";
    name = audio.label;
    detail = audio.error;
    action = (
      <button type="button" className="announcer-bar-btn" onClick={onRetry} aria-label="Try again">
        <RotateCcw size={24} />
      </button>
    );
  } else if (moment) {
    head = 'Big moment';
    name = moment.text;
    detail = 'It plays as soon as it is ready.';
    action = <span className="announcer-bar-btn announcer-bar-btn--wait" aria-hidden="true"><Spinner size={24} /></span>;
  } else if (upNext) {
    head = 'Up next';
    name = `${jersey(upNext)} ${fullName(upNext)}`;
    detail = upNextDetail;
    action = (
      <button type="button" className="announcer-bar-btn" onClick={() => onAnnounce(upNext)} aria-label={`Announce ${fullName(upNext)}`}
        disabled={!rowState(upNext).canPlay}>
        <Play size={26} style={{ marginLeft: 3 }} />
      </button>
    );
  } else {
    return null;
  }
  const idle = audio.status === 'idle' && !moment;
  return (
    <div className={`announcer-bar glass-panel announcer-bar--${audio.status}`} role="region" aria-label="Now playing">
      {(audio.status === 'playing') && <div className="announcer-progress-track"><div className="announcer-progress-fill" style={{ width: `${pct}%` }} /></div>}
      <div className="announcer-bar-row">
        <div className="announcer-bar-text" aria-live="polite">
          <span className="announcer-bar-head">{head}</span>
          <span className="announcer-bar-name">{name}</span>
          {detail && <span className={`announcer-bar-detail${audio.status === 'error' ? ' announcer-text-danger' : ''}`}>{detail}</span>}
          {audio.warning && <span className="announcer-bar-detail announcer-text-warning"><AlertCircle size={12} /> {audio.warning}</span>}
        </div>
        {idle && canShuffle && (
          <button type="button" className="announcer-bar-mini" onClick={onShuffle} aria-label="Pick a different call and song"><Shuffle size={18} /></button>
        )}
        {idle && (
          <button type="button" className="announcer-bar-mini" onClick={onSkip} aria-label="Skip to the next batter"><SkipForward size={18} /></button>
        )}
        {audio.status === 'error' && (
          <button type="button" className="announcer-bar-mini" onClick={dismissError} aria-label="Dismiss"><X size={18} /></button>
        )}
        {action}
      </div>
    </div>
  );
}

// ── Main ───────────────────────────────────────────────────────────────────
export default function Announcer({ lineups }) {
  const audio = useSyncExternalStore(subscribeAudio, getAudioState);
  const [roster, setRoster] = useState([]);
  const [profiles, setProfiles] = useState([]);
  const [defaultVoiceId, setDefaultVoiceId] = useState('halo');
  const [gcLineup, setGcLineup] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [cached, setCached] = useState(false);
  const [toast, setToast] = useState(null);
  const [sheet, setSheet] = useState(null); // { kind: 'player', id } | { kind: 'settings' } | { kind: 'pa' }
  const [upNextId, setUpNextId] = useState(null);
  const [queued, setQueued] = useState({}); // player id → { intro, song } for the next at-bat
  const [moment, setMoment] = useState(null); // { playerId, since, text }
  const [batchBusy, setBatchBusy] = useState(false);
  const lastPlayed = useRef({});
  const lastRequest = useRef(null);
  const warmed = useRef(new Set());

  const say = useCallback((text, kind = 'info') => setToast(text ? { text, kind } : null), []);

  // ── data ──
  const fetchRoster = useCallback(async () => {
    try {
      const res = await fetch('/api/announcer/roster', { cache: 'no-store' });
      if (!res.ok) throw new Error(`server said ${res.status}`);
      const data = await res.json();
      const list = data.roster || [];
      if (!list.length) throw new Error('no players');
      setRoster(list);
      setCached(false);
      setLoadError('');
      // Queue a random call + song for anyone who has none yet, so the bar
      // shows exactly what the next tap will play.
      setQueued(q => {
        const missing = list.filter(p => !q[p.id]);
        return missing.length ? { ...q, ...Object.fromEntries(missing.map(p => [p.id, rollPair(p)])) } : q;
      });
      return list;
    } catch (apiErr) {
      // Last-good copy nginx serves when the API is down — playback still works.
      try {
        const sRes = await fetch('/data/sharks/announcer_roster.json', { cache: 'no-store' });
        const sData = sRes.ok ? await sRes.json() : null;
        if (sData?.roster?.length) {
          setRoster(sData.roster);
          setCached(true);
          setLoadError('');
          return sData.roster;
        }
      } catch { /* fall through */ }
      setLoadError(`Couldn't load the announcer roster (${apiErr.message}).`);
      return null;
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
    } catch { /* voice names fall back to "Announcer" */ }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch
    fetchRoster();
    fetchProfiles();
    fetch('/api/announcer/game-lineup')
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (d) setGcLineup(d); })
      .catch(() => {});
    return () => stopAudio();
  }, [fetchRoster, fetchProfiles]);

  // iOS: sound must be started inside a tap. The first tap anywhere unlocks it.
  useEffect(() => {
    const opts = { capture: true, passive: true };
    const once = () => { unlock(); remove(); };
    function remove() {
      document.removeEventListener('pointerdown', once, opts);
      document.removeEventListener('touchend', once, opts);
    }
    document.addEventListener('pointerdown', once, opts);
    document.addEventListener('touchend', once, opts);
    return remove;
  }, []);

  // Poll for as long as anything is being made. The server turns a render
  // that stops responding into an error after 10 minutes, so this ends.
  const inFlight = roster.some(p => p.status === 'rendering') || Boolean(moment) || batchBusy;
  useEffect(() => {
    if (!inFlight) return undefined;
    const t = setInterval(() => { if (document.visibilityState !== 'hidden') fetchRoster(); }, POLL_MS);
    return () => clearInterval(t);
  }, [inFlight, fetchRoster]);
  useEffect(() => {
    const onVis = () => { if (document.visibilityState === 'visible') fetchRoster(); };
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  }, [fetchRoster]);

  // ── batting order ──
  const active = useMemo(() => roster.filter(p => p.is_active !== false && !p.is_ghost), [roster]);
  const former = useMemo(() => roster.filter(p => p.is_ghost || p.is_active === false), [roster]);
  const { battingOrder, lineupSource } = useMemo(() => orderBattingLineup(active, gcLineup, lineups), [active, gcLineup, lineups]);
  const upNext = battingOrder.find(p => p.id === upNextId) || battingOrder[0] || null;

  const profileName = useCallback((id) => profiles.find(v => v.id === id)?.name || (id ? 'Announcer' : 'Big-moment call'), [profiles]);
  const describePair = useCallback((pair) => [
    pair.intro && `${profileName(pair.intro.voice)} call`,
    pair.song && songLabel(pair.song.url),
  ].filter(Boolean).join(' + '), [profileName]);

  const upNextPair = upNext ? pairFor(upNext, queued[upNext.id]) : null;
  const upNextDetail = upNext ? (describePair(upNextPair) || rowState(upNext).label) : '';

  // Decode the up-next batter's audio now so the tap starts instantly and
  // still works if the signal drops. Fetch every call file once so the
  // service worker has them all for offline use.
  const deckSong = upNextPair?.song?.url || '';
  const deckClip = upNextPair?.intro?.clip_url || '';
  useEffect(() => { preload([deckSong, deckClip]); }, [deckSong, deckClip]);
  useEffect(() => {
    const urls = active.flatMap(p => introsOf(p).map(i => i.clip_url)).filter(u => u && !warmed.current.has(u));
    urls.forEach(u => warmed.current.add(u));
    if (urls.length) warm(urls);
  }, [active]);

  // A big-moment call plays itself as soon as the server has it.
  useEffect(() => {
    if (!moment) return;
    const p = roster.find(r => r.id === moment.playerId);
    if (!p) return;
    if (p.status === 'ready' && p.rendered_at && p.rendered_at !== moment.since && p.announcer_audio_url) {
      setMoment(null); // eslint-disable-line react-hooks/set-state-in-effect -- reacting to polled server state
      play({ key: p.id, label: `${jersey(p)} ${fullName(p)}`, detail: moment.text, clipUrl: p.announcer_audio_url });
    } else if (p.status === 'error') {
      setMoment(null);
      say(`${moment.text} failed: ${p.error_message || 'unknown error'}`, 'error');
    }
  }, [roster, moment, say]);

  // ── playback ──
  const announce = useCallback((p) => {
    if (audio.key === p.id && (audio.status === 'playing' || audio.status === 'loading')) { stopAudio(); return; }
    const pair = pairFor(p, queued[p.id]);
    lastPlayed.current[p.id] = { intro: pair.intro?.id, song: pair.song?.id };
    setQueued(q => ({ ...q, [p.id]: rollPair(p, lastPlayed.current[p.id]) }));
    const idx = battingOrder.findIndex(x => x.id === p.id);
    if (idx >= 0 && battingOrder.length) setUpNextId(battingOrder[(idx + 1) % battingOrder.length].id);
    const req = {
      key: p.id, label: `${jersey(p)} ${fullName(p)}`, detail: describePair(pair),
      songUrl: pair.song?.url || '', clipUrl: pair.intro?.clip_url || '', songStart: pair.song?.start ?? 5,
    };
    lastRequest.current = req;
    play(req);
  }, [audio.key, audio.status, queued, battingOrder, describePair]);

  const hear = useCallback((key, { clipUrl = '', songUrl = '', songStart = 5, label = '' }) => {
    const s = getAudioState();
    if (s.key === key && (s.status === 'playing' || s.status === 'loading')) { stopAudio(); return; }
    const req = { key, label: `Preview: ${label}`, clipUrl, songUrl, songStart };
    lastRequest.current = req;
    play(req);
  }, []);

  const retry = () => { if (lastRequest.current) play(lastRequest.current); };
  const shuffle = () => {
    if (upNext) setQueued(q => ({ ...q, [upNext.id]: rollPair(upNext, { intro: upNextPair?.intro?.id, song: upNextPair?.song?.id }) }));
  };
  const skip = () => {
    const idx = battingOrder.findIndex(x => x.id === upNext?.id);
    if (battingOrder.length) setUpNextId(battingOrder[(idx + 1) % battingOrder.length].id);
  };
  const canShuffle = Boolean(upNext) && (
    (introsOf(upNext).length > 1 && !isPinned(introsOf(upNext), upNext.intro_pick))
    || (songsOf(upNext).length > 1 && !isPinned(songsOf(upNext), upNext.song_pick)));

  // ── writes ──
  const savePlayer = async (playerId, data) => {
    await api(`/api/announcer/phonetics/${playerId}`, 'POST', data);
    await fetchRoster();
  };
  const renderPlayer = async (playerId, voiceId) => {
    await api(`/api/announcer/render/${playerId}`, 'POST', { quality: 'best', ...(voiceId ? { voice_id: voiceId } : {}) });
    await fetchRoster();
  };
  const removePlayer = async (playerId) => {
    await api(`/api/announcer/player/${playerId}`, 'DELETE');
    await fetchRoster();
  };
  const renderAll = async () => {
    setBatchBusy(true);
    try {
      const data = await api('/api/announcer/render-all', 'POST');
      await fetchRoster();
      return data.count ?? 0;
    } finally { setBatchBusy(false); }
  };
  const makeMissing = async () => {
    try {
      const n = await renderAll();
      say(n ? `Making ${n} call${n === 1 ? '' : 's'}. Each takes about 10 seconds.` : 'Nothing needed making.', 'ok');
    } catch (e) { say(e.message, 'error'); }
  };
  const chooseVoice = async (profileId) => {
    await api('/api/announcer/voice-profiles/default', 'POST', { profile_id: profileId });
    setDefaultVoiceId(profileId);
    await fetchProfiles();
    const n = await renderAll();
    return `Team voice is now ${profiles.find(p => p.id === profileId)?.name || profileId}. Remaking ${n} call${n === 1 ? '' : 's'}; the old ones play until the new ones land.`;
  };
  const addSub = async (data) => {
    await api('/api/announcer/add-sub', 'POST', data);
    await fetchRoster();
  };
  const fireMoment = async (p, m) => {
    setSheet(null);
    const text = `${m.label} for ${p.first}`;
    try {
      await api(`/api/announcer/render/${p.id}`, 'POST', { quality: 'best', game_context: { achievement: m.key } });
      // Refresh first so the row already says "rendering" when the moment
      // starts watching it; an old error on the row can't end it early.
      await fetchRoster();
      setMoment({ playerId: p.id, since: p.rendered_at || '', text });
    } catch (e) { say(`${text} failed: ${e.message}`, 'error'); }
  };

  const closeSheet = useCallback((result) => {
    setSheet(null);
    if (result && typeof result.then === 'function') result.then(t => say(t, /not saved/i.test(t) ? 'error' : 'ok'));
    else if (typeof result === 'string') say(result, 'ok');
  }, [say]);

  // ── summary ──
  const counts = useMemo(() => ({
    rendering: active.filter(p => p.status === 'rendering').length,
    failed: active.filter(p => p.status === 'error').length,
    todo: active.filter(needsRender).length,
    ready: active.filter(p => rowState(p).kind === 'ready').length,
  }), [active]);

  const sheetPlayer = sheet?.kind === 'player' ? roster.find(p => p.id === sheet.id) : null;

  if (loading) return <div className="loader" />;

  return (
    <div className="announcer-container announcer-page">
      <div className="announcer-header">
        <h2><Mic size={22} /> Announcer</h2>
        <div className="announcer-header-actions">
          <button type="button" className="announcer-btn announcer-btn-secondary announcer-header-btn" onClick={() => setSheet({ kind: 'pa' })}>
            <Megaphone size={16} /> PA
          </button>
          <button type="button" className="announcer-btn announcer-btn-secondary announcer-header-btn" onClick={() => setSheet({ kind: 'settings' })} aria-label="Announcer settings">
            <Settings size={16} /> <Volume2 size={14} />
          </button>
        </div>
      </div>

      {cached && (
        <div className="announcer-msg announcer-msg--warn" role="status">
          <WifiOff size={14} /> Can't reach the server. Showing the saved roster: calls you've played before still work, but nothing new can be made.
        </div>
      )}
      {loadError && (
        <div className="announcer-msg announcer-msg--error" role="alert">
          <span>{loadError}</span>
          <button type="button" className="announcer-btn announcer-btn-secondary" onClick={fetchRoster}><RotateCcw size={14} /> Try again</button>
        </div>
      )}
      {toast && (
        <div className={`announcer-msg announcer-msg--${toast.kind}`} role="status">
          <span>{toast.text}</span>
          <button type="button" className="announcer-icon-btn" onClick={() => say(null)} aria-label="Dismiss"><X size={16} /></button>
        </div>
      )}

      <div className="announcer-summary">
        <span className="announcer-lineup-source">{lineupSource}</span>
        <span>{counts.ready}/{active.length} ready</span>
        {counts.rendering > 0 && <span className="announcer-summary-busy"><Spinner size={12} /> Making {counts.rendering}</span>}
        {counts.failed > 0 && <span className="announcer-text-danger">{counts.failed} failed</span>}
        {counts.todo > 0 && !cached && (
          <button type="button" className="announcer-btn announcer-btn-primary announcer-summary-btn" onClick={makeMissing} disabled={batchBusy}>
            {batchBusy ? <Spinner /> : <Mic size={14} />} {counts.failed ? 'Make / retry' : 'Make'} {counts.todo} call{counts.todo === 1 ? '' : 's'}
          </button>
        )}
      </div>

      <div className="announcer-roster-list">
        {battingOrder.map((p, i) => (
          <PlayerRow key={p.id} player={p} slot={i + 1} audio={audio} isNext={upNext?.id === p.id}
            voiceName={profileName} onAnnounce={announce} onEdit={(x) => setSheet({ kind: 'player', id: x.id })} />
        ))}
        {battingOrder.length === 0 && !loadError && (
          <div className="glass-panel announcer-empty">No players yet. Sync the team, or add a sub in settings.</div>
        )}
      </div>

      <NowPlayingBar audio={audio} upNext={upNext} upNextDetail={upNextDetail} moment={moment} canShuffle={canShuffle}
        onAnnounce={announce} onRetry={retry} onShuffle={shuffle} onSkip={skip} />

      {sheetPlayer && (
        <PlayerSheet key={sheetPlayer.id} player={sheetPlayer} profiles={profiles} defaultVoiceId={defaultVoiceId} audio={audio}
          voiceName={profileName} onHear={hear} onClose={closeSheet} onSave={savePlayer} onRender={renderPlayer}
          onRemove={removePlayer} onMoment={fireMoment} />
      )}
      {sheet?.kind === 'settings' && (
        <SettingsSheet profiles={profiles} defaultVoiceId={defaultVoiceId} audio={audio} former={former} onHear={hear}
          onChooseVoice={chooseVoice} onAddSub={addSub} onEdit={(x) => setSheet({ kind: 'player', id: x.id })} onClose={closeSheet} />
      )}
      {sheet?.kind === 'pa' && <PASheet audio={audio} onClose={closeSheet} />}
    </div>
  );
}
