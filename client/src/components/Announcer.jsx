import React, { useState, useEffect, useCallback, useRef, useMemo, useSyncExternalStore } from 'react';
import { createPortal } from 'react-dom';
import {
  Mic, Play, Square, RefreshCw, UserPlus, AlertCircle, Volume2, Zap, X, Check, Trash2, Pin,
  Shuffle, Plus, Music, SkipForward, Pencil, WifiOff, Megaphone, RotateCcw, MoreHorizontal, ChevronRight,
  Upload, GripVertical, ListOrdered, ArrowUp, ArrowDown, Drum, Bell, Wind, Users, Flag, AudioLines, Lock, Volume1,
} from 'lucide-react';
import {
  subscribe as subscribeAudio, getState as getAudioState, play, playClip, stop as stopAudio, fadeOut, mainAction,
  preload, warm, unlock, dismissError, playEffect, preloadEffects, clampGap, DEFAULT_GAP, GAP_MIN, GAP_MAX,
} from '../utils/audioController';
import { apiRequest } from '../utils/apiClient';
import {
  MAX_ITEMS, introsOf, songsOf, rollPair, pairFor, isPinned, pickMode, songTitle, songStartLabel, rowState,
  needsRender, orderBattingLineup, previewLine, describeApiError, moveItem, dropIndex, uploadProblem, UPLOAD_VOICE,
  undoTarget, songGapLabel,
} from '../utils/announcerPicks';

// The Announcer tab, built like a sports-app game screen:
//   • one list, in batting order; tapping a player announces them
//   • a now-playing bar that always says what is playing, loading, failed,
//     or up next, with ONE big button: Play the up-next batter; while it
//     plays, Fade (1.5 s); during the fade, Stop dead; after a failure, Retry
//   • announcing a batter moves "up next" to the one after her
//   • every row says whether its call is ready, being made, or failed
//   • setup (calls, songs, gap) is one sheet per player; everything else the
//     coach rarely touches (PA, sounds, team voice, subs, big moments) is
//     behind More. Sheets save as you go and close from anywhere
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

// Multipart upload (songs, calls, soundboard). No Content-Type header: the
// browser writes the multipart boundary. apiRequest adds the write token.
async function upload(path, file, fields = {}) {
  const form = new FormData();
  form.append('file', file);
  Object.entries(fields).forEach(([k, v]) => form.append(k, v));
  let res;
  try {
    res = await apiRequest(path, { method: 'POST', body: form });
  } catch {
    throw new Error(describeApiError(0));
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(describeApiError(res.status, data.error));
  return data;
}

const AUDIO_ACCEPT = 'audio/mpeg,audio/mp3,audio/wav,audio/x-wav,audio/mp4,audio/x-m4a,.mp3,.wav,.m4a';

// A visible button that opens the file picker. One tap, one file.
function FileButton({ label, busy, disabled, onFile, className = 'announcer-btn announcer-btn-secondary', accept = AUDIO_ACCEPT }) {
  const ref = useRef(null);
  return (
    <>
      <button type="button" className={className} disabled={disabled} onClick={() => ref.current?.click()}>
        {busy ? <Spinner /> : <Upload size={14} />} {label}
      </button>
      <input ref={ref} type="file" accept={accept} hidden tabIndex={-1} aria-hidden="true"
        onChange={e => { const f = e.target.files?.[0]; e.target.value = ''; if (f) onFile(f); }} />
    </>
  );
}

const hasFiles = (e) => Array.from(e.dataTransfer?.types || []).includes('Files');

const fullName = (p) => `${p.first || ''} ${p.last || ''}`.trim();
const jersey = (p) => (p.number ? `#${p.number}` : '#–');
const ordinal = (n) => {
  const s = ['th', 'st', 'nd', 'rd'];
  const v = n % 100;
  return `${n}${s[(v - 20) % 10] || s[v] || s[0]}`;
};

function useEscape(onClose) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' || e.key === 'Esc') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);
}

// A sheet closes on ✕, Escape or a tap outside. It never holds unsaved work.
function Sheet({ title, onClose, children, dialogProps = {} }) {
  useEscape(onClose);
  return createPortal(
    <div className="announcer-modal-overlay" onClick={onClose}>
      <div {...dialogProps} className={`announcer-modal announcer-sheet glass-panel ${dialogProps.className || ''}`}
        role="dialog" aria-modal="true" aria-label={title}
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
  const busy = isThis && (audio.status === 'playing' || audio.status === 'loading' || audio.status === 'fading');
  const fading = isThis && audio.status === 'fading';
  const callMode = pickMode(intros, player.intro_pick, 'call', i => voiceName(i.voice));
  const songMode = pickMode(songs, player.song_pick, 'song', songTitle);
  const mainLabel = !st.canPlay ? `Set up ${fullName(player)}` : fading ? `Stop ${fullName(player)} now`
    : busy ? `Fade out ${fullName(player)}` : `Announce ${fullName(player)}`;
  return (
    <div className={`announcer-row glass-panel${busy ? ' announcer-row--playing' : ''}${isNext && !busy ? ' announcer-row--next' : ''}`}>
      <button type="button" className="announcer-row-main" aria-label={mainLabel}
        onClick={() => (st.canPlay ? onAnnounce(player) : onEdit(player))}>
        <span className="announcer-row-slot">{slot}</span>
        <span className="announcer-jersey">{jersey(player)}</span>
        <span className="announcer-row-text">
          <span className="announcer-row-name">{player.first} <strong>{player.last}</strong></span>
          <span className="announcer-row-sub">
            {busy && <span className="announcer-tag announcer-tag--live">{audio.status === 'loading' ? 'Loading' : fading ? 'Fading' : 'Playing'}</span>}
            {isNext && !busy && <span className="announcer-tag">Up next</span>}
            <span className={`announcer-badge announcer-badge--${st.kind}`}>
              {st.kind === 'rendering' && <Spinner size={11} />}{st.label}
            </span>
            {callMode && <span><Mic size={11} /> {callMode}</span>}
            {songMode && <span><Music size={11} /> {songMode}</span>}
          </span>
        </span>
        <span className={`announcer-row-go${fading ? ' announcer-row-go--fading' : busy ? ' announcer-row-go--stop' : ''}${!st.canPlay ? ' announcer-row-go--setup' : ''}`} aria-hidden="true">
          {!st.canPlay ? <Plus size={22} /> : fading ? <Square size={20} /> : busy ? <Volume1 size={22} /> : <Play size={22} style={{ marginLeft: 3 }} />}
        </span>
      </button>
      <button type="button" className="announcer-row-edit" onClick={() => onEdit(player)} aria-label={`Set up ${fullName(player)}`}>
        <Pencil size={18} />
      </button>
    </div>
  );
}

// ── Player setup sheet ─────────────────────────────────────────────────────
function PlayerSheet({ player, slot, total, profiles, defaultVoiceId, audio, voiceName, onHear, onClose, onSave, onRender,
  onRemove, onMoment, onMove, onUploadSong, onUploadCall }) {
  const [phonetic, setPhonetic] = useState(player.phonetic_hint || '');
  const [voice, setVoice] = useState(player.voice_profile_id || defaultVoiceId);
  const [newSong, setNewSong] = useState({ url: '', start: '0' });
  const [gap, setGap] = useState(clampGap(player.song_gap));
  const gapTimer = useRef(null);
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState(null);
  const [confirm, setConfirm] = useState('');
  const [dropKind, setDropKind] = useState(''); // '' | 'song' | 'call' while a file is dragged over the sheet
  const intros = introsOf(player);
  const songs = songsOf(player);
  const st = rowState(player);
  const nameDirty = phonetic.trim() !== (player.phonetic_hint || '').trim();

  // The gap slider saves 0.6 s after the last nudge, so dragging it is one
  // write, not thirty (the API allows 12 writes a minute).
  const nudgeGap = (value) => {
    const g = clampGap(value);
    setGap(g);
    clearTimeout(gapTimer.current);
    gapTimer.current = setTimeout(() => onSave(player.id, { song_gap: g }).catch(e => setMsg({ text: `Gap not saved: ${e.message}`, kind: 'error' })), 600);
  };
  useEffect(() => () => clearTimeout(gapTimer.current), []);

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

  // Songs are saved as a whole list; an uploaded one keeps its name.
  const keep = (list) => list.map(s => ({ id: s.id, url: s.url, start: s.start, label: s.label }));
  const addSong = (e) => {
    e.preventDefault();
    const url = newSong.url.trim();
    if (!/^https?:\/\//i.test(url)) { setMsg({ text: 'Paste a link that starts with http:// or https://', kind: 'error' }); return; }
    save('song', { songs: [...keep(songs), { url, start: Number(newSong.start) || 0 }] }, 'Song added.')
      .then(ok => { if (ok) setNewSong({ url: '', start: '0' }); });
  };

  const uploadFile = (kind, file) => {
    const problem = uploadProblem(file);
    if (problem) { setMsg({ text: problem, kind: 'error' }); return; }
    if (kind === 'song' && songs.length >= MAX_ITEMS) {
      setMsg({ text: `${player.first} has ${MAX_ITEMS} songs. Remove one to add another.`, kind: 'error' });
      return;
    }
    if (kind === 'song') run('upload-song', () => onUploadSong(player.id, file), `Added ${file.name}. It plays from the top.`);
    else run('upload-call', () => onUploadCall(player.id, file), `Added ${file.name} as a call.`);
  };

  // Desktop: drop a file anywhere on the sheet for a song, on Calls for a call.
  const dropHandlers = (kind) => ({
    onDragOver: (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      e.stopPropagation();
      e.dataTransfer.dropEffect = 'copy';
      if (dropKind !== kind) setDropKind(kind);
    },
    onDrop: (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      e.stopPropagation();
      setDropKind('');
      const file = e.dataTransfer.files?.[0];
      if (file) uploadFile(kind, file);
    },
  });
  const sheetDrop = {
    ...dropHandlers('song'),
    onDragLeave: (e) => { if (!e.currentTarget.contains(e.relatedTarget)) setDropKind(''); },
    className: dropKind ? `announcer-sheet--drop announcer-sheet--drop-${dropKind}` : '',
  };
  const uploading = busy === 'upload-song' || busy === 'upload-call';

  return (
    <Sheet title={`${jersey(player)} ${fullName(player)}`} onClose={close} dialogProps={sheetDrop}>
      {dropKind && (
        <div className="announcer-drop-hint" aria-hidden="true">
          <Upload size={18} /> Drop to add as {dropKind === 'call' ? 'a call' : 'a walk-up song'}
        </div>
      )}
      {uploading && <div className="announcer-msg announcer-msg--info" role="status"><Spinner /> Uploading and levelling the volume…</div>}

      <section className={`announcer-section${dropKind === 'call' ? ' announcer-section--drop' : ''}`} {...dropHandlers('call')}>
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
                <span>{i.voice === UPLOAD_VOICE ? 'Your recording' : i.draft ? 'Quick draft' : 'Studio'}{pinned ? ' · always plays' : ''}</span>
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
            {profiles.map(p => <option key={p.id} value={p.id} disabled={p.available === false}>{p.name}{p.available === false ? ' (not set up)' : ''}</option>)}
          </select>
          <button type="button" className="announcer-btn announcer-btn-primary" onClick={makeCall}
            disabled={Boolean(busy) || st.kind === 'rendering'}>
            {busy === 'call' ? <Spinner /> : <Plus size={14} />} Make call
          </button>
        </div>
        <FileButton label="Upload a recorded call" busy={busy === 'upload-call'} disabled={Boolean(busy)}
          onFile={f => uploadFile('call', f)} />
        {intros.length >= MAX_ITEMS && <small className="announcer-hint">A new call replaces the oldest one that isn't pinned.</small>}
      </section>

      <section className="announcer-section">
        <div className="announcer-section-head">
          <span>Walk-up songs</span>
          <small>{pickMode(songs, player.song_pick, 'song', songTitle) || 'None'}</small>
        </div>
        {songs.map((s, n) => {
          const pinned = s.id === player.song_pick;
          const delKey = `song:${s.id}`;
          return (
            <div key={s.id} className="announcer-item-row">
              <HearButton hearKey={`hear:${s.id}`} audio={audio} label={`song ${n + 1}`}
                onHear={() => onHear(`hear:${s.id}`, { songUrl: s.url, songStart: s.start, label: songTitle(s) })} />
              <div className="announcer-item-text">
                <strong>{songTitle(s)}</strong>
                <span>{songStartLabel(s.start)}{pinned ? ' · always plays' : ''}</span>
              </div>
              <button type="button" className={`announcer-icon-btn${pinned ? ' announcer-icon-btn--on' : ''}`} aria-pressed={pinned}
                aria-label={pinned ? `Stop always playing song ${n + 1}` : `Always play song ${n + 1}`}
                onClick={() => save('pin', { song_pick: pinned ? '' : s.id }, pinned ? 'Songs shuffle again.' : 'This song plays every time.')}>
                <Pin size={16} />
              </button>
              <button type="button" className={`announcer-icon-btn${confirm === delKey ? ' announcer-icon-btn--danger' : ''}`}
                aria-label={confirm === delKey ? `Tap again to remove song ${n + 1}` : `Remove song ${n + 1}`}
                onClick={() => twoTap(delKey, () => save('song', {
                  songs: keep(songs.filter(x => x.id !== s.id)),
                  ...(pinned ? { song_pick: '' } : {}),
                }, 'Song removed.'))}>
                {confirm === delKey ? <Check size={16} /> : <Trash2 size={16} />}
              </button>
            </div>
          );
        })}
        {songs.length < MAX_ITEMS && (
          <FileButton label="Upload MP3/WAV" busy={busy === 'upload-song'} disabled={Boolean(busy)}
            className="announcer-btn announcer-btn-primary announcer-upload-btn" onFile={f => uploadFile('song', f)} />
        )}
        {songs.length < MAX_ITEMS && (
          <form className="announcer-add-row" onSubmit={addSong}>
            <input value={newSong.url} onChange={e => setNewSong(v => ({ ...v, url: e.target.value }))}
              placeholder="Song link (https://…mp3)" inputMode="url" maxLength={500} aria-label="New song link" />
            <input type="number" min="0" max="300" step="0.5" value={newSong.start} className="announcer-song-start"
              onChange={e => setNewSong(v => ({ ...v, start: e.target.value }))} aria-label="Seconds into the song where it starts" />
            <button type="submit" className="announcer-btn announcer-btn-secondary" disabled={Boolean(busy) || !newSong.url.trim()}>
              {busy === 'song' ? <Spinner /> : <Plus size={14} />} Add
            </button>
          </form>
        )}
        {songs.length >= MAX_ITEMS && <small className="announcer-hint">{MAX_ITEMS} songs is the most. Remove one to add another.</small>}
        <small className="announcer-hint">Uploads (MP3, WAV or M4A, up to 25 MB) play from the top; on a computer you can also drop the file on this sheet. For a link, the number is where the song starts, in seconds into the track (12 = 0:12; 0 = from the top).</small>
      </section>

      <section className="announcer-section">
        <div className="announcer-section-head">
          <span><Volume1 size={14} /> Call to song</span>
          <small className="announcer-gap-value">{songGapLabel(gap)}</small>
        </div>
        <div className="announcer-gap">
          <input type="range" min={GAP_MIN} max={GAP_MAX} step="0.25" value={gap}
            onChange={e => nudgeGap(e.target.value)} aria-label="Seconds between the call ending and the song starting"
            aria-valuetext={songGapLabel(gap)} />
          <div className="announcer-gap-scale"><span>Overlap {Math.abs(GAP_MIN)}s</span><span>Together</span><span>Silence {GAP_MAX}s</span></div>
        </div>
        <small className="announcer-hint">Left brings the song in under the end of the call; right leaves a pause. Saves as you slide.</small>
      </section>

      <SheetMessage msg={msg} />

      <details className="announcer-advanced">
        <summary><ChevronRight size={16} /> Advanced: how the name is said, batting slot, big moments, remove</summary>

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

        {slot > 0 && (
          <section className="announcer-section">
            <div className="announcer-section-head">
              <span><ListOrdered size={14} /> Batting order</span>
              <small>Bats {ordinal(slot)} of {total}</small>
            </div>
            <div className="announcer-move-row">
              <button type="button" className="announcer-btn announcer-btn-secondary" disabled={slot <= 1}
                onClick={() => onMove(player.id, -1)}>
                <ArrowUp size={16} /> Move up
              </button>
              <button type="button" className="announcer-btn announcer-btn-secondary" disabled={slot >= total}
                onClick={() => onMove(player.id, 1)}>
                <ArrowDown size={16} /> Move down
              </button>
            </div>
          </section>
        )}

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
      </details>
    </Sheet>
  );
}

// ── Settings sheet: team voice, subs, former players ───────────────────────
const VOICE_GROUPS = [
  { key: 'fish_audio', label: 'fish.audio' },
  { key: 'elevenlabs', label: 'ElevenLabs' },
  { key: '', label: 'Worker' },
];
const groupOf = (p) => (VOICE_GROUPS.some(g => g.key === p.provider) ? p.provider : '');

// One voice: hear it, make it the team voice, or make every player a call in it.
function VoiceRow({ p, isDefault, audio, busy, makingHere, rendering, confirm, onHear, onChoose, onMakeAll, onDelete }) {
  const off = p.available === false;
  return (
    <div className={`announcer-item-row announcer-voice-row${isDefault ? ' announcer-item-row--active' : ''}${off ? ' announcer-item-row--off' : ''}`}>
      <HearButton hearKey={`sample:${p.id}`} audio={audio} label={`${p.name} sample`} disabled={off}
        onHear={() => onHear(`sample:${p.id}`, { clipUrl: `/api/announcer/voice-sample/${p.id}`, label: `${p.name} sample` })} />
      <div className="announcer-item-text">
        <strong>{p.name}</strong>
        <span>{off ? `Not set up: ${p.unavailable_reason || 'service key missing'} on the server` : p.tagline}</span>
      </div>
      <div className="announcer-voice-actions">
        {isDefault
          ? <span className="announcer-voice-current"><Check size={14} /> Team voice</span>
          : (
            <button type="button" className="announcer-btn announcer-btn-accent" onClick={() => onChoose(p.id)}
              disabled={Boolean(busy) || off} aria-label={`Set ${p.name} as team voice`}>
              {busy === p.id ? <Spinner /> : 'Set as team voice'}
            </button>
          )}
        <button type="button" className="announcer-btn announcer-btn-secondary" onClick={() => onMakeAll(p)}
          disabled={Boolean(busy) || off} aria-label={`Make all calls in ${p.name}`}>
          {busy === `all:${p.id}` ? <Spinner /> : makingHere && rendering > 0 ? <><Spinner /> {rendering}</> : <><Mic size={14} /> All calls</>}
        </button>
        {p.custom && (
          <button type="button" className={`announcer-icon-btn${confirm === p.id ? ' announcer-icon-btn--danger' : ''}`}
            onClick={() => onDelete(p)} disabled={Boolean(busy)}
            aria-label={confirm === p.id ? `Tap again to remove ${p.name}` : `Remove ${p.name}`}>
            {confirm === p.id ? <Check size={16} /> : <Trash2 size={16} />}
          </button>
        )}
      </div>
    </div>
  );
}

// Search the public fish.audio catalogue and add a voice to the list.
function VoiceSearch({ profiles, onAdd, setMsg }) {
  const [q, setQ] = useState('');
  const [results, setResults] = useState(null);
  const [busy, setBusy] = useState('');
  const added = new Set(profiles.map(p => p.fish_reference_id).filter(Boolean));

  const search = async (e) => {
    e.preventDefault();
    const term = q.trim();
    if (term.length < 2) { setMsg({ text: 'Type at least 2 letters to search.', kind: 'error' }); return; }
    setBusy('search'); setMsg(null);
    try {
      const res = await fetch(`/api/announcer/voice-library/search?q=${encodeURIComponent(term.slice(0, 60))}`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(describeApiError(res.status, data.error));
      setResults(data.results || []);
    } catch (ex) { setMsg({ text: ex.message, kind: 'error' }); }
    finally { setBusy(''); }
  };
  const add = async (v) => {
    setBusy(v.id); setMsg(null);
    try {
      await onAdd(v);
      setMsg({ text: `Added ${v.title}. Hear it or use it above.`, kind: 'ok' });
    } catch (ex) { setMsg({ text: ex.message, kind: 'error' }); }
    finally { setBusy(''); }
  };

  return (
    <>
      <form className="announcer-add-row" onSubmit={search}>
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Find more voices" maxLength={60}
          aria-label="Search fish.audio voices" />
        <button type="submit" className="announcer-btn announcer-btn-secondary" disabled={Boolean(busy)}>
          {busy === 'search' ? <Spinner /> : 'Search'}
        </button>
      </form>
      {results && results.length === 0 && <small className="announcer-hint">No voices found. Try another name.</small>}
      {results && results.map(v => (
        <div key={v.id} className="announcer-item-row">
          <div className="announcer-item-text">
            <strong>{v.title}</strong>
            <span>{v.likes.toLocaleString()} likes{v.author ? ` · by ${v.author}` : ''}</span>
          </div>
          {added.has(v.id)
            ? <span className="announcer-voice-current"><Check size={14} /> Added</span>
            : (
              <button type="button" className="announcer-btn announcer-btn-accent" onClick={() => add(v)}
                disabled={Boolean(busy)} aria-label={`Add ${v.title}`}>
                {busy === v.id ? <Spinner /> : <><Plus size={14} /> Add</>}
              </button>
            )}
        </div>
      ))}
    </>
  );
}

function SettingsSheet({ profiles, defaultVoiceId, audio, former, rendering, onHear, onChooseVoice, onMakeAllInVoice,
  onAddVoice, onDeleteVoice, onAddSub, onEdit, onClose }) {
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState(null);
  const [sub, setSub] = useState({ first: '', last: '', number: '' });
  const [makingVoice, setMakingVoice] = useState('');
  const [confirm, setConfirm] = useState('');

  const choose = async (id) => {
    setBusy(id); setMsg(null);
    try { setMsg({ text: await onChooseVoice(id), kind: 'ok' }); }
    catch (e) { setMsg({ text: e.message, kind: 'error' }); }
    finally { setBusy(''); }
  };
  const makeAll = async (p) => {
    setBusy(`all:${p.id}`); setMsg(null);
    try {
      const n = await onMakeAllInVoice(p.id);
      setMakingVoice(p.id);
      setMsg({ text: n ? `Making ${n} call${n === 1 ? '' : 's'} in ${p.name}. Each is added next to the calls players already have.` : 'No players to make calls for.', kind: 'ok' });
    } catch (e) { setMsg({ text: e.message, kind: 'error' }); }
    finally { setBusy(''); }
  };
  const remove = async (p) => {
    if (confirm !== p.id) { setConfirm(p.id); return; }
    setConfirm(''); setBusy(p.id); setMsg(null);
    try { await onDeleteVoice(p.id); setMsg({ text: `Removed ${p.name}.`, kind: 'ok' }); }
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
      {VOICE_GROUPS.map(g => {
        const list = profiles.filter(p => groupOf(p) === g.key);
        if (!list.length && g.key !== 'fish_audio') return null;
        return (
          <section key={g.key || 'worker'} className="announcer-section">
            <div className="announcer-section-head">
              <span>{g.label} voices</span>
              <small>{rendering > 0 ? <><Spinner size={11} /> Making {rendering} call{rendering === 1 ? '' : 's'}</> : 'Team voice remakes every team-voice call'}</small>
            </div>
            {list.map(p => (
              <VoiceRow key={p.id} p={p} isDefault={p.id === defaultVoiceId} audio={audio} busy={busy}
                makingHere={makingVoice === p.id} rendering={rendering} confirm={confirm}
                onHear={onHear} onChoose={choose} onMakeAll={makeAll} onDelete={remove} />
            ))}
            {g.key === 'fish_audio' && <VoiceSearch profiles={profiles} onAdd={onAddVoice} setMsg={setMsg} />}
          </section>
        );
      })}

      <SheetMessage msg={msg} />

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

// ── Reorder: drag a row by its grip ────────────────────────────────────────
// No long-press: the grip is the handle, so a finger on it drags at once and
// a finger anywhere else scrolls the page. The dragged row lifts; the rows it
// passes slide out of its way; letting go saves. Near the top of the screen
// or the now-playing bar the page scrolls so any slot can be reached.
const EDGE_PX = 80;

function ReorderList({ players, onDrop, onStep }) {
  const listRef = useRef(null);
  const dragRef = useRef(null);
  const [drag, setDrag] = useState(null); // { from, over, dy, pitch }

  const pitchOf = () => {
    const rows = listRef.current?.querySelectorAll('.announcer-reorder-row') || [];
    if (rows.length > 1) return rows[1].getBoundingClientRect().top - rows[0].getBoundingClientRect().top;
    return rows[0]?.offsetHeight || 64;
  };
  const measure = (d) => {
    const dy = d.lastY - d.startY + (window.scrollY - d.scroll0);
    return { from: d.from, dy, pitch: d.pitch, over: dropIndex(d.from, dy, d.pitch, players.length) };
  };
  const tick = () => {
    const d = dragRef.current;
    if (!d) return;
    const bottom = document.querySelector('.announcer-bar')?.getBoundingClientRect().top ?? window.innerHeight;
    let v = 0;
    if (d.lastY < EDGE_PX) v = -Math.ceil((EDGE_PX - d.lastY) / 5);
    else if (d.lastY > bottom - EDGE_PX) v = Math.ceil((d.lastY - (bottom - EDGE_PX)) / 5);
    if (v) { window.scrollBy(0, v); setDrag(measure(d)); }
    d.raf = requestAnimationFrame(tick);
  };
  const start = (e, i) => {
    if (e.button > 0) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture?.(e.pointerId);
    dragRef.current = { from: i, startY: e.clientY, lastY: e.clientY, scroll0: window.scrollY, pitch: pitchOf() };
    setDrag(measure(dragRef.current));
    dragRef.current.raf = requestAnimationFrame(tick);
  };
  const move = (e) => {
    const d = dragRef.current;
    if (!d) return;
    d.lastY = e.clientY;
    setDrag(measure(d));
  };
  const end = (commit) => {
    const d = dragRef.current;
    if (!d) return;
    cancelAnimationFrame(d.raf);
    dragRef.current = null;
    const { from, over } = measure(d);
    setDrag(null);
    if (commit && over !== from) onDrop(from, over);
  };
  useEffect(() => () => { if (dragRef.current) cancelAnimationFrame(dragRef.current.raf); }, []);

  const shift = (i) => {
    if (!drag || i === drag.from) return 0;
    if (drag.from < drag.over && i > drag.from && i <= drag.over) return -drag.pitch;
    if (drag.from > drag.over && i >= drag.over && i < drag.from) return drag.pitch;
    return 0;
  };

  return (
    <div className={`announcer-roster-list announcer-reorder-list${drag ? ' announcer-reorder-list--dragging' : ''}`} ref={listRef}>
      {players.map((p, i) => {
        const lifted = drag?.from === i;
        const slot = lifted ? drag.over + 1 : i + 1 + (shift(i) ? (shift(i) > 0 ? 1 : -1) : 0);
        return (
          <div key={p.id} className={`announcer-reorder-row glass-panel${lifted ? ' announcer-reorder-row--lifted' : ''}`}
            style={{ transform: lifted ? `translateY(${drag.dy}px) scale(1.02)` : `translateY(${shift(i)}px)` }}>
            <span className="announcer-row-slot">{slot}</span>
            <span className="announcer-jersey">{jersey(p)}</span>
            <span className="announcer-reorder-name">{p.first} <strong>{p.last}</strong></span>
            <button type="button" className="announcer-reorder-grip"
              aria-label={`Move ${fullName(p)}, batting ${ordinal(i + 1)}. Drag, or use the arrow keys.`}
              onPointerDown={e => start(e, i)} onPointerMove={move}
              onPointerUp={() => end(true)} onPointerCancel={() => end(false)} onLostPointerCapture={() => end(true)}
              onKeyDown={e => {
                if (e.key === 'ArrowUp' && i > 0) { e.preventDefault(); onStep(p.id, -1); }
                if (e.key === 'ArrowDown' && i < players.length - 1) { e.preventDefault(); onStep(p.id, 1); }
              }}>
              <GripVertical size={26} />
            </button>
          </div>
        );
      })}
    </div>
  );
}

// ── Soundboard ─────────────────────────────────────────────────────────────
const SOUND_ICONS = { 'air-horn': Megaphone, charge: Flag, 'drum-roll': Drum, cowbell: Bell, whistle: Wind, crowd: Users };
const LONG_PRESS_MS = 550;
const labelFromFile = (name) => (name || '').replace(/\.[a-z0-9]+$/i, '').replace(/[_]+/g, ' ').trim().slice(0, 24);

// Tap a tile: it plays at once, over the walk-up, without stopping it.
// The sheet stays open so several can be fired in a row. Press and hold (or
// Edit) to remove your own sounds; built-ins stay.
function SoundboardSheet({ audio, onClose }) {
  const [sounds, setSounds] = useState(null);
  const [msg, setMsg] = useState(null);
  const [firing, setFiring] = useState({});
  const [edit, setEdit] = useState(false);
  const [armed, setArmed] = useState('');
  const [pending, setPending] = useState(null); // { file, label } picked, not yet uploaded
  const [busy, setBusy] = useState(false);
  const fileRef = useRef(null);
  const timers = useRef({});
  const press = useRef({ timer: null, long: false });

  useEffect(() => {
    let live = true;
    fetch('/api/announcer/soundboard', { cache: 'no-store' })
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(`server said ${r.status}`))))
      .then(d => {
        if (!live) return;
        const list = d.sounds || [];
        setSounds(list);
        const urls = list.map(s => s.url);
        // Fetch every file (the service worker keeps them for offline), then
        // decode them so the first tap is instant.
        warm(urls).then(() => preloadEffects(urls));
      })
      .catch(e => { if (live) { setSounds([]); setMsg({ text: `Couldn't load the sounds (${e.message}).`, kind: 'error' }); } });
    const t = timers.current;
    const hold = press.current;
    return () => { live = false; Object.values(t).forEach(clearTimeout); clearTimeout(hold.timer); };
  }, []);

  const unmark = (id) => setFiring(f => { const n = { ...f }; delete n[id]; return n; });
  const fire = async (s) => {
    setFiring(f => ({ ...f, [s.id]: true }));
    const r = await playEffect(s.url); // starts the AudioContext before its first await
    clearTimeout(timers.current[s.id]);
    if (!r.ok) { unmark(s.id); setMsg({ text: `${s.label} didn't play (${r.error}).`, kind: 'error' }); return; }
    timers.current[s.id] = setTimeout(() => unmark(s.id), Math.max(300, (r.duration || 0) * 1000));
  };
  const remove = async (s) => {
    setArmed(''); setMsg(null);
    try {
      await api(`/api/announcer/soundboard/${s.id}`, 'DELETE');
      setSounds(list => list.filter(x => x.id !== s.id));
      setMsg({ text: `Removed ${s.label}.`, kind: 'ok' });
    } catch (e) { setMsg({ text: e.message, kind: 'error' }); }
  };
  const tap = (s) => {
    if (press.current.long) { press.current.long = false; return; }
    if (!edit) { fire(s); return; }
    if (s.builtin) return;
    if (armed === s.id) remove(s); else setArmed(s.id);
  };
  const holdStart = () => {
    press.current.long = false;
    clearTimeout(press.current.timer);
    press.current.timer = setTimeout(() => {
      press.current.long = true;
      setEdit(true); setArmed('');
      navigator.vibrate?.(15);
    }, LONG_PRESS_MS);
  };
  const holdEnd = () => clearTimeout(press.current.timer);

  const pick = (file) => {
    const problem = uploadProblem(file);
    if (problem) { setMsg({ text: problem, kind: 'error' }); return; }
    setMsg(null);
    setPending({ file, label: labelFromFile(file.name) || 'Sound' });
  };
  const send = async (e) => {
    e.preventDefault();
    if (!pending) return;
    setBusy(true); setMsg(null);
    try {
      const { sound } = await upload('/api/announcer/soundboard/upload', pending.file, { label: pending.label.trim() });
      setSounds(list => [...(list || []), sound]);
      preloadEffects([sound.url]);
      setPending(null);
      setMsg({ text: `Added ${sound.label}. Tap it to play.`, kind: 'ok' });
    } catch (ex) { setMsg({ text: ex.message, kind: 'error' }); }
    finally { setBusy(false); }
  };

  const walkup = audio.status === 'playing' || audio.status === 'loading';
  const ownCount = (sounds || []).filter(s => !s.builtin).length;

  return (
    <Sheet title="Sounds" onClose={onClose}>
      <div className="announcer-sound-status">
        <span className={walkup ? 'announcer-sound-status-live' : ''}>
          {walkup ? <>Walk-up playing: <strong>{audio.label}</strong></> : 'Nothing else is playing.'}
        </span>
        {walkup && (
          <button type="button" className="announcer-btn announcer-btn-secondary" onClick={stopAudio} aria-label="Stop the walk-up">
            <Square size={14} /> Stop walk-up
          </button>
        )}
        {ownCount > 0 && (
          <button type="button" className={`announcer-btn announcer-btn-secondary${edit ? ' announcer-btn--on' : ''}`} aria-pressed={edit}
            onClick={() => { setEdit(v => !v); setArmed(''); }}>
            {edit ? <><Check size={14} /> Done</> : <><Pencil size={14} /> Edit</>}
          </button>
        )}
      </div>
      <small className="announcer-hint">
        {edit ? 'Tap one of your sounds twice to remove it. Built-in sounds stay.'
          : 'Tap to play over the walk-up; it keeps playing. Press and hold to remove your own sounds.'}
      </small>

      {sounds === null ? <div className="announcer-msg"><Spinner /> Loading sounds…</div> : (
        <div className="announcer-sound-grid">
          {sounds.map(s => {
            const Icon = SOUND_ICONS[s.id] || AudioLines;
            const isArmed = edit && armed === s.id;
            const label = edit
              ? (s.builtin ? `${s.label}, built in, can't be removed` : isArmed ? `Tap again to remove ${s.label}` : `Remove ${s.label}`)
              : `Play ${s.label}`;
            return (
              <button key={s.id} type="button" aria-label={label}
                className={`announcer-sound-tile${firing[s.id] ? ' announcer-sound-tile--firing' : ''}${edit ? ' announcer-sound-tile--edit' : ''}${isArmed ? ' announcer-sound-tile--armed' : ''}${edit && s.builtin ? ' announcer-sound-tile--locked' : ''}`}
                onClick={() => tap(s)} onPointerDown={holdStart} onPointerUp={holdEnd} onPointerLeave={holdEnd} onPointerCancel={holdEnd}
                onContextMenu={e => e.preventDefault()}>
                {edit ? (s.builtin ? <Lock size={24} /> : isArmed ? <Check size={26} /> : <Trash2 size={24} />) : <Icon size={28} />}
                <span>{isArmed ? 'Tap to remove' : s.label}</span>
              </button>
            );
          })}
          {!edit && (
            <button type="button" className="announcer-sound-tile announcer-sound-tile--add" onClick={() => fileRef.current?.click()}
              disabled={busy} aria-label="Add a sound">
              <Plus size={28} /><span>Add sound</span>
            </button>
          )}
        </div>
      )}
      <input ref={fileRef} type="file" accept={AUDIO_ACCEPT} hidden tabIndex={-1} aria-hidden="true"
        onChange={e => { const f = e.target.files?.[0]; e.target.value = ''; if (f) pick(f); }} />

      {pending && (
        <form className="announcer-add-row" onSubmit={send}>
          <input value={pending.label} onChange={e => setPending(p => ({ ...p, label: e.target.value }))} maxLength={24}
            aria-label="Name for the new sound" placeholder="Name" />
          <button type="submit" className="announcer-btn announcer-btn-primary" disabled={busy || !pending.label.trim()}>
            {busy ? <Spinner /> : <Upload size={14} />} Add
          </button>
          <button type="button" className="announcer-icon-btn" onClick={() => setPending(null)} aria-label="Cancel" disabled={busy}>
            <X size={16} />
          </button>
        </form>
      )}
      <SheetMessage msg={msg} />
    </Sheet>
  );
}

// ── More sheet: everything the coach rarely touches ────────────────────────
function MoreSheet({ todo, failed, batchBusy, cached, onMakeMissing, onOpen, onClose }) {
  return (
    <Sheet title="More" onClose={onClose}>
      <div className="announcer-more-grid">
        {todo > 0 && !cached && (
          <button type="button" className="announcer-btn announcer-btn-primary" onClick={onMakeMissing} disabled={batchBusy}>
            {batchBusy ? <Spinner /> : <Mic size={16} />} {failed ? 'Make / retry' : 'Make'} {todo} missing call{todo === 1 ? '' : 's'}
          </button>
        )}
        <button type="button" className="announcer-btn announcer-btn-secondary" onClick={() => onOpen('pa')}><Megaphone size={16} /> PA announcement</button>
        <button type="button" className="announcer-btn announcer-btn-secondary" onClick={() => onOpen('sounds')}><Zap size={16} /> Sounds</button>
        <button type="button" className="announcer-btn announcer-btn-secondary" onClick={() => onOpen('settings')}><Volume2 size={16} /> Team voice, subs and former players</button>
      </div>
      <small className="announcer-hint">Big moments (grand slam and the like) are in each player's sheet under Advanced.</small>
    </Sheet>
  );
}

// ── Now-playing bar ────────────────────────────────────────────────────────
// One big button, whatever the state: Play the up-next batter, Fade while
// something plays, Stop dead during the fade, Retry after a failure.
function NowPlayingBar({ audio, upNext, upNextDetail, moment, canShuffle, onAnnounce, onRetry, onShuffle, onSkip, onSounds }) {
  const pct = audio.duration > 0 ? Math.min(100, (audio.elapsed / audio.duration) * 100) : 0;
  const act = mainAction(audio.status);
  let head, name, detail, action;
  const big = (label, className, icon, onClick, disabled = false) => (
    <span className="announcer-bar-main">
      <button type="button" className={`announcer-bar-btn ${className}`} onClick={onClick} aria-label={label} disabled={disabled}>{icon}</button>
      <span className="announcer-bar-btn-label" aria-hidden="true">{label.split(' ')[0]}</span>
    </span>
  );
  if (act === 'fade') {
    head = audio.status === 'loading' ? 'Loading…' : 'Now playing';
    name = audio.label;
    detail = audio.detail;
    action = big('Fade out', 'announcer-bar-btn--fade', audio.status === 'loading' ? <Spinner size={26} /> : <Volume1 size={28} />, () => fadeOut());
  } else if (act === 'stop') {
    head = 'Fading out';
    name = audio.label;
    detail = 'Press again to stop now.';
    action = big('Stop now', 'announcer-bar-btn--stopnow', <Square size={26} />, stopAudio);
  } else if (act === 'retry') {
    head = "Couldn't play";
    name = audio.label;
    detail = audio.error;
    action = big('Retry', '', <RotateCcw size={26} />, onRetry);
  } else if (moment) {
    head = 'Big moment';
    name = moment.text;
    detail = 'It plays as soon as it is ready.';
    action = <span className="announcer-bar-btn announcer-bar-btn--wait" aria-hidden="true"><Spinner size={24} /></span>;
  } else if (upNext) {
    head = 'Up next';
    name = `${jersey(upNext)} ${fullName(upNext)}`;
    detail = upNextDetail;
    action = big(`Play ${fullName(upNext)}`, '', <Play size={30} style={{ marginLeft: 3 }} />, () => onAnnounce(upNext), !rowState(upNext).canPlay);
  } else {
    head = 'Ready';
    name = 'Nothing playing';
    action = null;
  }
  const idle = audio.status === 'idle' && !moment;
  return (
    <div className={`announcer-bar glass-panel announcer-bar--${audio.status}`} role="region" aria-label="Now playing">
      {(audio.status === 'playing' || audio.status === 'fading') && <div className="announcer-progress-track"><div className="announcer-progress-fill" style={{ width: `${pct}%` }} /></div>}
      <div className="announcer-bar-row">
        {/* Always here, in every state: effects play over whatever is on. */}
        <button type="button" className="announcer-bar-mini announcer-bar-sounds" onClick={onSounds} aria-label="Sounds" title="Sounds">
          <Zap size={20} />
        </button>
        <div className="announcer-bar-text" aria-live="polite">
          <span className="announcer-bar-head">{head}</span>
          <span className="announcer-bar-name">{name}</span>
          {detail && <span className={`announcer-bar-detail${audio.status === 'error' ? ' announcer-text-danger' : ''}`}>{detail}</span>}
          {audio.warning && <span className="announcer-bar-detail announcer-text-warning"><AlertCircle size={12} /> {audio.warning}</span>}
        </div>
        {idle && canShuffle && (
          <button type="button" className="announcer-bar-mini" onClick={onShuffle} aria-label="Pick a different call and song"><Shuffle size={18} /></button>
        )}
        {idle && upNext && (
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
  const [sheet, setSheet] = useState(null); // { kind: 'player', id } | { kind: 'settings' } | { kind: 'pa' } | { kind: 'sounds' } | { kind: 'more' }
  const [manualOrder, setManualOrder] = useState(null); // the coach's order (player ids), or null
  const [reordering, setReordering] = useState(false);
  const savedOrder = useRef(null);   // last order the server confirmed
  const pendingOrder = useRef(null); // order waiting for its PUT
  const orderTimer = useRef(null);
  const [undo, setUndo] = useState(null); // { target: undoTarget(...), name } for 6 s after a drop
  const undoTimer = useRef(null);
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
      .then(d => {
        if (!d) return;
        setGcLineup(d);
        const manual = Array.isArray(d.manual_order) && d.manual_order.length ? d.manual_order : null;
        savedOrder.current = manual;
        if (!pendingOrder.current) setManualOrder(manual);
      })
      .catch(() => {});
    // Fetch the soundboard files now, so the service worker has them if the
    // signal is gone by the time the coach first opens Sounds.
    fetch('/api/announcer/soundboard')
      .then(r => (r.ok ? r.json() : null))
      .then(d => { const urls = (d?.sounds || []).map(s => s.url); if (urls.length) warm(urls); })
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
  const { battingOrder, lineupSource, manual: isManual } = useMemo(
    () => orderBattingLineup(active, gcLineup, lineups, manualOrder), [active, gcLineup, lineups, manualOrder]);
  const upNext = battingOrder.find(p => p.id === upNextId) || battingOrder[0] || null;
  const fallbackSource = useMemo(() => orderBattingLineup(active, gcLineup, lineups).lineupSource, [active, gcLineup, lineups]);
  // game-lineup also answers with the optimiser lineup when no GC game exists.
  const resetLabel = gcLineup?.source === 'gc_game' && gcLineup?.players?.length ? 'Reset to GameChanger order' : 'Reset order';

  const profileName = useCallback((id) => (id === UPLOAD_VOICE ? 'Uploaded'
    : profiles.find(v => v.id === id)?.name || (id ? 'Announcer' : 'Big-moment call')), [profiles]);
  const describePair = useCallback((pair) => [
    pair.intro && `${profileName(pair.intro.voice)} call`,
    pair.song && songTitle(pair.song),
  ].filter(Boolean).join(' + '), [profileName]);

  // ── the coach's batting order ──
  // Every change updates the list at once. A drag saves straight away; the
  // sheet's Move up / Move down and the arrow keys wait 0.7 s for the last
  // tap, so walking a player down eight slots is one save, not eight (the
  // API allows 12 writes a minute). A failed save puts the last saved order
  // back and says so.
  const flushOrder = useCallback(async () => {
    clearTimeout(orderTimer.current);
    orderTimer.current = null;
    const order = pendingOrder.current;
    if (!order) return;
    try {
      await api('/api/announcer/batting-order', 'PUT', { order });
      savedOrder.current = order;
      if (pendingOrder.current === order) pendingOrder.current = null;
    } catch (e) {
      if (pendingOrder.current === order) {
        pendingOrder.current = null;
        setManualOrder(savedOrder.current);
        say(`Batting order not saved: ${e.message}`, 'error');
      }
    }
  }, [say]);
  const setOrder = useCallback((ids, debounceMs) => {
    setManualOrder(ids);
    pendingOrder.current = ids;
    clearTimeout(orderTimer.current);
    orderTimer.current = setTimeout(flushOrder, debounceMs);
  }, [flushOrder]);
  useEffect(() => {
    // Leaving the app (lock screen, switch app) saves a pending move now.
    const onHide = () => { if (document.visibilityState === 'hidden' && pendingOrder.current) flushOrder(); };
    document.addEventListener('visibilitychange', onHide);
    return () => {
      document.removeEventListener('visibilitychange', onHide);
      if (pendingOrder.current) flushOrder();
    };
  }, [flushOrder]);
  const orderIds = battingOrder.map(p => p.id);
  const resetOrder = useCallback(async () => {
    clearTimeout(orderTimer.current);
    pendingOrder.current = null;
    const before = manualOrder;
    setManualOrder(null);
    try {
      await api('/api/announcer/batting-order', 'DELETE');
      savedOrder.current = null;
      say(`Batting order is back to: ${fallbackSource}.`, 'ok');
    } catch (e) {
      setManualOrder(before);
      say(`Order not reset: ${e.message}`, 'error');
    }
  }, [manualOrder, fallbackSource, say]);
  // A drop saves at once and offers Undo for 6 s. Undo puts back the order
  // the coach had before; after her very first drag that is a reset, so the
  // list returns to the GameChanger / optimiser order, not a copy of it.
  const dropRow = (from, to) => {
    const moved = battingOrder[from];
    setUndo({ target: undoTarget(isManual ? manualOrder : null), name: moved ? fullName(moved) : 'that' });
    clearTimeout(undoTimer.current);
    undoTimer.current = setTimeout(() => setUndo(null), 6000);
    setOrder(moveItem(orderIds, from, to), 0);
  };
  const undoDrop = () => {
    const u = undo;
    clearTimeout(undoTimer.current);
    setUndo(null);
    if (!u) return;
    if (u.target.kind === 'restore') setOrder(u.target.order, 0);
    else resetOrder();
  };
  useEffect(() => () => clearTimeout(undoTimer.current), []);
  const stepPlayer = (id, dir) => {
    const i = orderIds.indexOf(id);
    if (i >= 0) setOrder(moveItem(orderIds, i, i + dir), 700);
  };

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
  // Tapping the batter who is playing fades her out; tapping again during the
  // fade stops dead. Tapping anyone else cuts straight to her (no fade).
  const announce = useCallback((p) => {
    if (audio.key === p.id) {
      const act = mainAction(audio.status);
      if (act === 'fade') { fadeOut(); return; }
      if (act === 'stop') { stopAudio(); return; }
    }
    const pair = pairFor(p, queued[p.id]);
    lastPlayed.current[p.id] = { intro: pair.intro?.id, song: pair.song?.id };
    setQueued(q => ({ ...q, [p.id]: rollPair(p, lastPlayed.current[p.id]) }));
    const idx = battingOrder.findIndex(x => x.id === p.id);
    if (idx >= 0 && battingOrder.length) setUpNextId(battingOrder[(idx + 1) % battingOrder.length].id);
    const req = {
      key: p.id, label: `${jersey(p)} ${fullName(p)}`, detail: describePair(pair),
      songUrl: pair.song?.url || '', clipUrl: pair.intro?.clip_url || '', songStart: pair.song?.start ?? 0,
      songGap: clampGap(p.song_gap),
    };
    lastRequest.current = req;
    play(req);
  }, [audio.key, audio.status, queued, battingOrder, describePair]);

  const hear = useCallback((key, { clipUrl = '', songUrl = '', songStart = 0, label = '' }) => {
    const s = getAudioState();
    if (s.key === key && (s.status === 'playing' || s.status === 'loading' || s.status === 'fading')) { stopAudio(); return; }
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
  const uploadSong = async (playerId, file) => {
    await upload(`/api/announcer/songs/${playerId}/upload`, file);
    await fetchRoster();
  };
  const uploadCall = async (playerId, file) => {
    await upload(`/api/announcer/calls/${playerId}/upload`, file);
    await fetchRoster();
  };
  const removePlayer = async (playerId) => {
    await api(`/api/announcer/player/${playerId}`, 'DELETE');
    await fetchRoster();
  };
  const renderAll = async (voiceId) => {
    setBatchBusy(true);
    try {
      const data = await api('/api/announcer/render-all', 'POST', voiceId ? { voice_id: voiceId } : {});
      await fetchRoster();
      return data.count ?? 0;
    } finally { setBatchBusy(false); }
  };
  const addVoice = async (v) => {
    await api('/api/announcer/voice-profiles', 'POST', { fish_reference_id: v.id, name: v.title });
    await fetchProfiles();
  };
  const deleteVoice = async (profileId) => {
    await api(`/api/announcer/voice-profiles/${profileId}`, 'DELETE');
    await fetchProfiles();
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
    if (pendingOrder.current) flushOrder(); // don't sit on a Move up/down
    if (result && typeof result.then === 'function') result.then(t => say(t, /not saved/i.test(t) ? 'error' : 'ok'));
    else if (typeof result === 'string') say(result, 'ok');
  }, [say, flushOrder]);

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
          {battingOrder.length > 1 && (
            <button type="button" className={`announcer-btn ${reordering ? 'announcer-btn-primary' : 'announcer-btn-secondary'} announcer-header-btn`}
              onClick={() => { if (reordering) flushOrder(); setReordering(v => !v); }} aria-pressed={reordering}>
              {reordering ? <><Check size={16} /> Done</> : <><ListOrdered size={16} /> Reorder</>}
            </button>
          )}
          <button type="button" className="announcer-btn announcer-btn-secondary announcer-header-btn" onClick={() => setSheet({ kind: 'more' })} aria-label="More">
            <MoreHorizontal size={18} />
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

      {undo && (
        <div className="announcer-msg announcer-msg--ok" role="status">
          <span>Moved {undo.name}.</span>
          <button type="button" className="announcer-btn announcer-btn-secondary announcer-msg-action" onClick={undoDrop}>
            <RotateCcw size={14} /> Undo
          </button>
        </div>
      )}

      <div className="announcer-summary">
        <span className={`announcer-lineup-source${isManual ? ' announcer-lineup-source--manual' : ''}`}>{lineupSource}</span>
        {!reordering && counts.rendering > 0 && <span className="announcer-summary-busy"><Spinner size={12} /> Making {counts.rendering}</span>}
        {!reordering && counts.failed > 0 && <span className="announcer-text-danger">{counts.failed} failed</span>}
        {!reordering && counts.todo > 0 && !cached && (
          <button type="button" className="announcer-btn announcer-btn-secondary announcer-summary-btn" onClick={() => setSheet({ kind: 'more' })}>
            <Mic size={14} /> {counts.todo} missing call{counts.todo === 1 ? '' : 's'}
          </button>
        )}
      </div>
      {(isManual || reordering) && (
        <div className="announcer-order-bar">
          <span>{reordering ? 'Drag a batter by the grip. It saves when you let go, and you can undo.' : 'You set this batting order.'}</span>
          {isManual && (
            <button type="button" className="announcer-btn announcer-btn-secondary" onClick={resetOrder}>
              <RotateCcw size={14} /> {resetLabel}
            </button>
          )}
        </div>
      )}

      {reordering ? (
        <ReorderList players={battingOrder} onDrop={dropRow} onStep={stepPlayer} />
      ) : (
        <div className="announcer-roster-list">
          {battingOrder.map((p, i) => (
            <PlayerRow key={p.id} player={p} slot={i + 1} audio={audio} isNext={upNext?.id === p.id}
              voiceName={profileName} onAnnounce={announce} onEdit={(x) => setSheet({ kind: 'player', id: x.id })} />
          ))}
          {battingOrder.length === 0 && !loadError && (
            <div className="glass-panel announcer-empty">No players yet. Sync the team, or add a sub in settings.</div>
          )}
        </div>
      )}

      <NowPlayingBar audio={audio} upNext={upNext} upNextDetail={upNextDetail} moment={moment} canShuffle={canShuffle}
        onAnnounce={announce} onRetry={retry} onShuffle={shuffle} onSkip={skip} onSounds={() => setSheet({ kind: 'sounds' })} />

      {sheetPlayer && (
        <PlayerSheet key={sheetPlayer.id} player={sheetPlayer} profiles={profiles} defaultVoiceId={defaultVoiceId} audio={audio}
          slot={orderIds.indexOf(sheetPlayer.id) + 1} total={orderIds.length}
          voiceName={profileName} onHear={hear} onClose={closeSheet} onSave={savePlayer} onRender={renderPlayer}
          onRemove={removePlayer} onMoment={fireMoment} onMove={stepPlayer} onUploadSong={uploadSong} onUploadCall={uploadCall} />
      )}
      {sheet?.kind === 'more' && (
        <MoreSheet todo={counts.todo} failed={counts.failed} batchBusy={batchBusy} cached={cached}
          onMakeMissing={() => { setSheet(null); makeMissing(); }} onOpen={(kind) => setSheet({ kind })} onClose={closeSheet} />
      )}
      {sheet?.kind === 'sounds' && <SoundboardSheet audio={audio} onClose={closeSheet} />}
      {sheet?.kind === 'settings' && (
        <SettingsSheet profiles={profiles} defaultVoiceId={defaultVoiceId} audio={audio} former={former}
          rendering={counts.rendering} onHear={hear} onChooseVoice={chooseVoice} onMakeAllInVoice={renderAll}
          onAddVoice={addVoice} onDeleteVoice={deleteVoice} onAddSub={addSub}
          onEdit={(x) => setSheet({ kind: 'player', id: x.id })} onClose={closeSheet} />
      )}
      {sheet?.kind === 'pa' && <PASheet audio={audio} onClose={closeSheet} />}
    </div>
  );
}
