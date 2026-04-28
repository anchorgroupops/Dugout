import React, { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import {
  Mic, Music, Play, Square, SkipBack, SkipForward,
  ChevronDown, ChevronUp, RefreshCw, UserPlus, Save,
  AlertCircle, CheckCircle, Clock, Volume2, Settings2, List,
  Zap, Target, Activity, Plus, X, Upload, Wand2
} from 'lucide-react';
import { playIntro, playClip, stop as stopAudio, preload, cleanup, detectBPM, calcBeatOffset, loadBuffer } from '../utils/audioController';
import WorkerBadge from './WorkerBadge';

function StatusLed({ status }) {
  const colors = {
    ready: 'var(--success, #4ade80)',
    pending: 'var(--warning, #facc15)',
    rendering: 'var(--warning, #facc15)',
    error: 'var(--danger, #f87171)',
  };
  return (
    <span
      className="announcer-status-led"
      style={{ background: colors[status] || 'var(--text-muted)' }}
      title={status}
      aria-label={`Status: ${status}`}
    />
  );
}

function StatsBar({ stats }) {
  const total = stats.total || 0;
  const readyPct = total > 0 ? Math.round((stats.ready / total) * 100) : 0;
  return (
    <div className="announcer-stats-bar glass-panel">
      <div className="announcer-stats-counts">
        <span className="announcer-stat-item" style={{ color: 'var(--success, #4ade80)' }}>
          <CheckCircle size={14} /> {stats.ready} Ready
        </span>
        <span className="announcer-stat-item" style={{ color: 'var(--warning, #facc15)' }}>
          <Clock size={14} /> {stats.pending} Pending
        </span>
        <span className="announcer-stat-item" style={{ color: 'var(--danger, #f87171)' }}>
          <AlertCircle size={14} /> {stats.error} Error
        </span>
      </div>
      <div className="announcer-progress-track">
        <div className="announcer-progress-fill" style={{ width: `${readyPct}%` }} />
      </div>
    </div>
  );
}

function AddSubModal({ onClose, onAdd }) {
  const [first, setFirst] = useState('');
  const [last, setLast] = useState('');
  const [number, setNumber] = useState('');
  const [walkupUrl, setWalkupUrl] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!first.trim()) return;
    setLoading(true);
    try {
      await onAdd({ first: first.trim(), last: last.trim(), number: number.trim(), walkup_song_url: walkupUrl.trim() });
      onClose();
    } catch {
      setLoading(false);
    }
  };

  return createPortal(
    <div className="announcer-modal-overlay" onClick={onClose}>
      <div className="announcer-modal glass-panel" onClick={e => e.stopPropagation()}>
        <h3>Add Sub Player</h3>
        <form onSubmit={handleSubmit}>
          <div className="announcer-form-row">
            <input placeholder="First name *" value={first} onChange={e => setFirst(e.target.value)} required maxLength={64} />
            <input placeholder="Last name" value={last} onChange={e => setLast(e.target.value)} maxLength={64} />
          </div>
          <div className="announcer-form-row">
            <input placeholder="Jersey #" value={number} onChange={e => setNumber(e.target.value)} maxLength={4} style={{ width: '80px' }} />
            <input placeholder="Walk-up song URL (https://)" value={walkupUrl} onChange={e => setWalkupUrl(e.target.value)} maxLength={500} type="url" pattern="https://.*" />
          </div>
          <div className="announcer-form-actions">
            <button type="button" onClick={onClose} className="announcer-btn announcer-btn-secondary">Cancel</button>
            <button type="submit" disabled={loading || !first.trim()} className="announcer-btn announcer-btn-primary">
              {loading ? <RefreshCw size={14} className="sync-spin" /> : <UserPlus size={14} />}
              {loading ? 'Adding...' : 'Add Player'}
            </button>
          </div>
        </form>
      </div>
    </div>,
    document.body
  );
}

function PlayerCard({ player, onSavePhonetics, onRender, onRemove }) {
  const [expanded, setExpanded] = useState(false);
  const [phonetic, setPhonetic] = useState(player.phonetic_hint || '');
  const [instruction, setInstruction] = useState(player.tts_instruction || '');
  const [walkupUrl, setWalkupUrl] = useState(player.walkup_song_url || '');
  const [introTs, setIntroTs] = useState(player.intro_timestamp ?? 5);
  const [saving, setSaving] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [bpmResult, setBpmResult] = useState(null);
  const [bpmLoading, setBpmLoading] = useState(false);
  const [songs, setSongs] = useState([]);
  const [songsLoading, setSongsLoading] = useState(false);
  const [newSongUrl, setNewSongUrl] = useState('');
  const [newSongLabel, setNewSongLabel] = useState('');
  const [newSongOptimalStart, setNewSongOptimalStart] = useState(0);
  const [addingSong, setAddingSong] = useState(false);
  const [detecting, setDetecting] = useState(false);
  const [renderQuality, setRenderQuality] = useState('best');

  useEffect(() => {
    if (!expanded) return;
    let cancelled = false;
    setSongsLoading(true);
    fetch(`/api/announcer/songs/${player.id}`)
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (!cancelled && data) setSongs(data.songs || []); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setSongsLoading(false); });
    return () => { cancelled = true; };
  }, [expanded, player.id]);

  const _spotifyTrackId = (url) => {
    const m = url.match(/open\.spotify\.com\/track\/([A-Za-z0-9]+)/);
    return m ? m[1] : null;
  };

  const handleDetectStart = async () => {
    const trackId = _spotifyTrackId(newSongUrl);
    if (!trackId) return;
    setDetecting(true);
    try {
      const { getAudioAnalysis, getToken } = await import('../services/SpotifyService');
      const token = await getToken();
      if (!token) return;
      const analysis = await getAudioAnalysis(trackId);
      const res = await fetch('/api/announcer/optimal-start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ audio_analysis: analysis }),
      });
      if (res.ok) {
        const data = await res.json();
        setNewSongOptimalStart(data.optimal_start_ms || 0);
      }
    } catch { /* silent — optional feature */ } finally {
      setDetecting(false);
    }
  };

  const handleAddSong = async () => {
    const url = newSongUrl.trim();
    if (!url) return;
    setAddingSong(true);
    try {
      const res = await fetch(`/api/announcer/songs/${player.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          song_url: url,
          song_label: newSongLabel.trim(),
          optimal_start_ms: newSongOptimalStart || 0,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setSongs(data.songs || []);
        setNewSongUrl('');
        setNewSongLabel('');
        setNewSongOptimalStart(0);
      }
    } finally {
      setAddingSong(false);
    }
  };

  const handleDeleteSong = async (songId) => {
    const res = await fetch(`/api/announcer/songs/${player.id}/${songId}`, { method: 'DELETE' });
    if (res.ok) {
      const data = await res.json();
      setSongs(data.songs || []);
    }
  };

  const numWord = numToWord(player.number);
  const displayName = phonetic || `${player.first} ${player.last}`;
  const previewText = `Now batting, number ${numWord}, ${displayName}!`;

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSavePhonetics(player.id, { phonetic_hint: phonetic, tts_instruction: instruction, walkup_song_url: walkupUrl, intro_timestamp: introTs });
    } finally {
      setSaving(false);
    }
  };

  const handleRender = async () => {
    setRendering(true);
    try {
      await onRender(player.id, renderQuality);
    } finally {
      setTimeout(() => setRendering(false), 2000);
    }
  };

  const handlePreview = async () => {
    if (previewing) {
      stopAudio();
      setPreviewing(false);
    } else if (player.announcer_audio_url) {
      setPreviewing(true);
      try {
        await playClip(player.announcer_audio_url, () => setPreviewing(false));
      } catch {
        setPreviewing(false);
      }
    }
  };

  const handleDetectBPM = async () => {
    const url = walkupUrl.trim();
    if (!url) return;
    setBpmLoading(true);
    try {
      const buf = await loadBuffer(url);
      const result = detectBPM(buf);
      setBpmResult(result);
      if (result) {
        const offset = calcBeatOffset(result.bpm);
        setIntroTs(offset);
      }
    } catch {
      setBpmResult(null);
    } finally {
      setBpmLoading(false);
    }
  };

  return (
    <div className={`announcer-player-card glass-panel ${expanded ? 'expanded' : ''}${player.is_ghost ? ' announcer-ghost-player' : ''}`}
      style={player.is_ghost ? { borderLeft: '3px solid var(--warning, #facc15)', opacity: 0.75 } : undefined}>
      {player.is_ghost && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 12px', background: 'rgba(250,204,21,0.08)', borderBottom: '1px solid rgba(250,204,21,0.2)', fontSize: 'var(--text-xs)', color: 'rgba(250,204,21,0.9)' }}>
          <span><AlertCircle size={12} style={{ display: 'inline', marginRight: 4 }} />Not on current roster</span>
          <button onClick={() => onRemove?.(player.id)} style={{ background: 'rgba(250,204,21,0.15)', border: '1px solid rgba(250,204,21,0.3)', borderRadius: 4, color: 'rgba(250,204,21,0.9)', fontSize: 'var(--text-xs)', padding: '2px 8px', cursor: 'pointer' }}>
            Remove
          </button>
        </div>
      )}
      <button className="announcer-player-header" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
        <div className="announcer-player-info">
          <span className="announcer-jersey">#{player.number || '?'}</span>
          <span className="announcer-player-name">{player.first} {player.last}</span>
          <StatusLed status={player.status} />
        </div>
        <div className="announcer-player-actions-mini">
          {player.status === 'ready' && (
            <span
              className="announcer-mini-play"
              onClick={e => { e.stopPropagation(); handlePreview(); }}
              role="button"
              tabIndex={0}
              aria-label={previewing ? 'Stop preview' : 'Preview clip'}
            >
              {previewing ? <Square size={16} /> : <Play size={16} />}
            </span>
          )}
          {expanded ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
        </div>
      </button>

      {expanded && (
        <div className="announcer-player-details">
          <div className="announcer-form-group">
            <label>Phonetic Spelling</label>
            <input
              value={phonetic}
              onChange={e => setPhonetic(e.target.value)}
              placeholder="e.g. Mih-KAY-lah Van-DOO-sen"
              maxLength={200}
            />
          </div>
          <div className="announcer-form-group">
            <label>TTS Instruction</label>
            <textarea
              value={instruction}
              onChange={e => setInstruction(e.target.value)}
              placeholder="e.g. Say with extra energy and enthusiasm"
              rows={2}
              maxLength={500}
            />
          </div>
          <div className="announcer-form-row">
            <div className="announcer-form-group" style={{ flex: 1 }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                Walk-up Song URL
                {bpmResult && (
                  <span style={{ fontSize: '0.7rem', background: 'var(--warning, #facc15)', color: '#000', borderRadius: 4, padding: '1px 6px', fontWeight: 700 }}>
                    ♩ {bpmResult.bpm} BPM
                  </span>
                )}
              </label>
              <input
                value={walkupUrl}
                onChange={e => { setWalkupUrl(e.target.value); setBpmResult(null); }}
                placeholder="https://example.com/walkup.mp3"
                maxLength={500}
                type="url"
                pattern="https://.*"
              />
            </div>
            <div className="announcer-form-group" style={{ width: '100px' }}>
              <label>Duck at (s)</label>
              <input
                type="number"
                value={introTs}
                onChange={e => setIntroTs(parseFloat(e.target.value) || 0)}
                min={0}
                max={300}
                step={0.5}
              />
            </div>
          </div>
          {walkupUrl.trim() && (
            <div style={{ marginBottom: '0.5rem' }}>
              <button
                type="button"
                onClick={handleDetectBPM}
                disabled={bpmLoading}
                className="announcer-btn announcer-btn-secondary"
                style={{ fontSize: '0.75rem', padding: '3px 10px' }}
              >
                {bpmLoading ? <RefreshCw size={12} className="sync-spin" /> : <Activity size={12} />}
                {bpmLoading ? 'Analyzing…' : 'Auto-set Duck Point'}
              </button>
              {bpmResult === null && !bpmLoading && walkupUrl && (
                <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginLeft: 8 }}>
                  Click to detect BPM and auto-fill duck timing
                </span>
              )}
            </div>
          )}

          <div className="announcer-song-pool">
            <div className="announcer-song-pool-header">
              <Music size={13} />
              Walk-up Pool
              {songs.length > 0 && (
                <span className="announcer-song-count">{songs.length}</span>
              )}
            </div>

            {songsLoading ? (
              <div className="announcer-song-empty">
                <RefreshCw size={11} className="sync-spin" /> Loading…
              </div>
            ) : songs.length === 0 ? (
              <div className="announcer-song-empty">
                No songs — add URLs below to enable LRU shuffle during games.
              </div>
            ) : (
              <ul className="announcer-song-list">
                {songs.map(song => (
                  <li key={song.id} className="announcer-song-item">
                    <span className="announcer-song-label" title={song.song_url}>
                      {song.song_label || song.song_url.split('/').pop().split('?')[0] || song.song_url}
                    </span>
                    {song.optimal_start_ms > 0 && (
                      <span className="announcer-song-start-badge" title="Optimal start point">
                        {(song.optimal_start_ms / 1000).toFixed(1)}s
                      </span>
                    )}
                    {song.play_count > 0 && (
                      <span className="announcer-song-plays">×{song.play_count}</span>
                    )}
                    <button
                      className="announcer-song-delete"
                      onClick={() => handleDeleteSong(song.id)}
                      aria-label="Remove song"
                    >
                      <X size={12} />
                    </button>
                  </li>
                ))}
              </ul>
            )}

            <div className="announcer-song-add">
              <input
                className="announcer-song-input"
                value={newSongUrl}
                onChange={e => { setNewSongUrl(e.target.value); setNewSongOptimalStart(0); }}
                onKeyDown={e => e.key === 'Enter' && handleAddSong()}
                placeholder="https://… audio URL"
                type="url"
                maxLength={500}
              />
              <input
                className="announcer-song-input announcer-song-label-input"
                value={newSongLabel}
                onChange={e => setNewSongLabel(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleAddSong()}
                placeholder="Label"
                maxLength={100}
              />
              {_spotifyTrackId(newSongUrl) && (
                <button
                  onClick={handleDetectStart}
                  disabled={detecting}
                  className="announcer-btn announcer-btn-secondary"
                  style={{ flexShrink: 0, fontSize: '0.72rem', padding: '4px 8px' }}
                  title="Detect optimal start point via Spotify audio analysis"
                >
                  {detecting ? <RefreshCw size={11} className="sync-spin" /> : '⚡'}
                  {newSongOptimalStart > 0 ? `${(newSongOptimalStart / 1000).toFixed(1)}s` : 'Start'}
                </button>
              )}
              <button
                onClick={handleAddSong}
                disabled={addingSong || !newSongUrl.trim()}
                className="announcer-btn announcer-btn-secondary"
                style={{ flexShrink: 0, fontSize: '0.75rem', padding: '4px 10px' }}
              >
                {addingSong ? <RefreshCw size={12} className="sync-spin" /> : <Plus size={12} />}
                Add
              </button>
            </div>
          </div>

          <div className="announcer-preview-text">
            <Mic size={14} /> <em>{previewText}</em>
          </div>

          {player.error_message && (
            <div className="announcer-error-msg">
              <AlertCircle size={14} /> {player.error_message}
            </div>
          )}

          <div className="announcer-card-actions">
            <button onClick={handleSave} disabled={saving} className="announcer-btn announcer-btn-secondary">
              {saving ? <RefreshCw size={14} className="sync-spin" /> : <Save size={14} />}
              {saving ? 'Saving...' : 'Save'}
            </button>
            <div className="announcer-quality-toggle">
              <button
                className={`announcer-quality-btn${renderQuality === 'best' ? ' active' : ''}`}
                onClick={() => setRenderQuality('best')}
                title="Best quality — Qwen3-TTS-1.7B (slow)"
              >Best</button>
              <button
                className={`announcer-quality-btn${renderQuality === 'quick' ? ' active' : ''}`}
                onClick={() => setRenderQuality('quick')}
                title="Quick render — faster"
              >Quick</button>
            </div>
            <button onClick={handleRender} disabled={rendering} className="announcer-btn announcer-btn-primary">
              {rendering ? <RefreshCw size={14} className="sync-spin" /> : <Mic size={14} />}
              {rendering ? 'Rendering...' : 'Re-render'}
            </button>
            {player.status === 'ready' && player.announcer_audio_url && (
              <button onClick={handlePreview} className="announcer-btn announcer-btn-accent">
                {previewing ? <Square size={14} /> : <Volume2 size={14} />}
                {previewing ? 'Stop' : 'Preview'}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function NowPlayingView({ roster, lineups, onBack }) {
  const [currentIdx, setCurrentIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState({ elapsed: 0, duration: 0 });
  const [gameState, setGameState] = useState(() => {
    try {
      const saved = localStorage.getItem('apex_game_state');
      return saved ? JSON.parse(saved) : DEFAULT_GAME_STATE;
    } catch { return DEFAULT_GAME_STATE; }
  });
  const [showGamePanel, setShowGamePanel] = useState(false);
  const [showHalo, setShowHalo] = useState(false);
  const [gcLineup, setGcLineup] = useState(null); // {source, source_label, players}

  // Fetch GC-synced batting order on mount
  useEffect(() => {
    let cancelled = false;
    fetch('/api/announcer/game-lineup')
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data && !cancelled) setGcLineup(data); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  // Build batting order: GC game → optimizer lineup → active roster
  const battingOrder = (() => {
    // Priority 1: GC game or optimizer lineup from /api/announcer/game-lineup
    if (gcLineup?.players?.length) {
      return gcLineup.players
        .map(p => {
          // Match against full roster by id, then jersey number, then name
          return roster.find(r =>
            (p.id && r.id === p.id) ||
            String(r.number) === String(p.number) ||
            `${r.first} ${r.last}`.toLowerCase() === `${p.first} ${p.last}`.toLowerCase()
          ) || null;
        })
        .filter(Boolean);
    }

    // Priority 2: lineups.json — use recommended_strategy's lineup array (key is 'lineup', not 'order')
    if (lineups) {
      const strategy = lineups.recommended_strategy || 'balanced';
      const entry = lineups[strategy] || lineups.balanced;
      const lineup = entry?.lineup;
      if (Array.isArray(lineup) && lineup.length) {
        return lineup
          .sort((a, b) => (a.slot || 0) - (b.slot || 0))
          .map(p => roster.find(r =>
            String(r.number) === String(p.number) ||
            `${r.first} ${r.last}`.toLowerCase() === `${p.first} ${p.last}`.toLowerCase()
          ))
          .filter(Boolean);
      }
    }

    return roster.filter(p => p.is_active);
  })();

  const current = battingOrder[currentIdx] || null;
  const progressPct = progress.duration > 0 ? Math.min(100, (progress.elapsed / progress.duration) * 100) : 0;

  const pushGameState = useCallback(async (next) => {
    setGameState(next);
    localStorage.setItem('apex_game_state', JSON.stringify(next));
    try {
      await fetch('/api/announcer/game-state', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(next),
      });
    } catch { /* non-critical */ }
  }, []);

  const updateGameField = (field, value) => {
    pushGameState({ ...gameState, [field]: value });
  };

  const toggleBase = (idx) => {
    const bases = [...gameState.bases];
    bases[idx] = !bases[idx];
    pushGameState({ ...gameState, bases });
  };

  // Fetch server game state on mount
  useEffect(() => {
    fetch('/api/announcer/game-state')
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) setGameState({ ...DEFAULT_GAME_STATE, ...data }); })
      .catch(() => {});
  }, []);

  // Halo achievement: trigger re-render with achievement context then auto-play
  const triggerHaloAchievement = useCallback(async (achievementKey) => {
    if (!current) return;
    const newState = { ...gameState, achievement: achievementKey };
    await pushGameState(newState);
    // Request a fresh render with achievement context
    try {
      await fetch(`/api/announcer/render/${current.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ game_context: newState }),
      });
    } catch { /* best-effort */ }
    // Clear achievement after trigger
    setTimeout(() => pushGameState({ ...newState, achievement: null }), 2000);
  }, [current, gameState, pushGameState]);

  const handlePlay = async () => {
    if (!current) return;
    if (playing) {
      stopAudio();
      setPlaying(false);
      return;
    }
    setPlaying(true);
    const introTs = current.intro_timestamp ?? 5;
    try {
      await playIntro({
        walkupUrl: current.walkup_song_url || '',
        clipUrl: current.announcer_audio_url || '',
        introTimestamp: introTs,
        autoBPM: introTs === 0,
        onEnd: () => setPlaying(false),
        onProgress: (p) => setProgress(p),
      });
    } catch {
      setPlaying(false);
    }
  };

  const goPrev = () => {
    stopAudio();
    setPlaying(false);
    setProgress({ elapsed: 0, duration: 0 });
    setCurrentIdx(i => Math.max(0, i - 1));
  };

  const goNext = () => {
    stopAudio();
    setPlaying(false);
    setProgress({ elapsed: 0, duration: 0 });
    setCurrentIdx(i => Math.min(battingOrder.length - 1, i + 1));
  };

  // Preload next batter's audio
  useEffect(() => {
    const next = battingOrder[currentIdx + 1];
    if (next) {
      preload([next.walkup_song_url, next.announcer_audio_url].filter(Boolean));
    }
  }, [currentIdx, battingOrder]);

  useEffect(() => () => stopAudio(), []);

  if (!battingOrder.length) {
    return (
      <div className="announcer-now-playing glass-panel">
        <p style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
          No players with rendered audio clips yet. Go to the Roster view and render clips first.
        </p>
        <button onClick={onBack} className="announcer-btn announcer-btn-secondary" style={{ margin: '1rem auto', display: 'flex' }}>
          <List size={14} /> Back to Roster
        </button>
      </div>
    );
  }

  const isHighStakes = gameState.bases.every(Boolean) && gameState.outs >= 2;

  return (
    <div className="announcer-now-playing">
      <div className="announcer-np-header">
        <button onClick={onBack} className="announcer-btn announcer-btn-secondary" aria-label="Back to roster">
          <List size={16} /> Roster
        </button>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <button
            onClick={() => setShowHalo(true)}
            className="announcer-btn announcer-btn-accent"
            style={{ padding: '4px 10px', fontSize: '0.75rem' }}
            aria-label="Halo achievement"
          >
            <Zap size={14} /> Achievement
          </button>
          <button
            onClick={() => setShowGamePanel(v => !v)}
            className={`announcer-btn ${showGamePanel ? 'announcer-btn-primary' : 'announcer-btn-secondary'}`}
            style={{ padding: '4px 10px', fontSize: '0.75rem' }}
            aria-label="Toggle game state panel"
          >
            <Target size={14} /> Game State
          </button>
          <span className="announcer-np-position">{currentIdx + 1} / {battingOrder.length}</span>
          {gcLineup?.source_label && (
            <span
              className={`announcer-lineup-source${gcLineup.source === 'gc_game' ? ' announcer-lineup-source--gc' : ''}`}
              title={gcLineup.source === 'gc_game' ? 'Batting order from GameChanger — re-ingest CSV to refresh' : 'Batting order from lineup optimizer'}
            >
              {gcLineup.source === 'gc_game' ? '⚾' : '📊'} {gcLineup.source_label}
            </span>
          )}
        </div>
      </div>

      {showGamePanel && (
        <div className="announcer-np-game-state glass-panel" style={{ padding: '0.75rem', marginBottom: '0.5rem' }}>
          <div style={{ display: 'flex', gap: '1rem', alignItems: 'flex-start', flexWrap: 'wrap' }}>
            {/* Inning */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
              <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Inning</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <button className="announcer-btn announcer-btn-round" style={{ width: 24, height: 24, fontSize: '1rem' }}
                  onClick={() => updateGameField('inning', Math.max(1, gameState.inning - 1))}>−</button>
                <span style={{ fontWeight: 800, fontSize: '1.1rem', minWidth: 20, textAlign: 'center' }}>{gameState.inning}</span>
                <button className="announcer-btn announcer-btn-round" style={{ width: 24, height: 24, fontSize: '1rem' }}
                  onClick={() => updateGameField('inning', Math.min(15, gameState.inning + 1))}>+</button>
              </div>
              <div style={{ display: 'flex', gap: 4 }}>
                {['top', 'bottom'].map(h => (
                  <button key={h} onClick={() => updateGameField('half', h)}
                    className={`announcer-btn ${gameState.half === h ? 'announcer-btn-primary' : 'announcer-btn-secondary'}`}
                    style={{ padding: '2px 6px', fontSize: '0.65rem' }}>{h === 'top' ? '▲' : '▼'}</button>
                ))}
              </div>
            </div>

            {/* Outs */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
              <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Outs</span>
              <div style={{ display: 'flex', gap: 4 }}>
                {[0, 1, 2].map(o => (
                  <button key={o} onClick={() => updateGameField('outs', o)}
                    className={`announcer-btn ${gameState.outs === o ? 'announcer-btn-primary' : 'announcer-btn-secondary'}`}
                    style={{ width: 28, height: 28, padding: 0, fontWeight: 800 }}>{o}</button>
                ))}
              </div>
            </div>

            {/* Bases */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
              <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Bases</span>
              <BaseDiamond bases={gameState.bases} onToggle={toggleBase} />
            </div>

            {/* Score */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
              <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Score</span>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: '0.6rem', opacity: 0.7 }}>Us</div>
                  <div style={{ display: 'flex', gap: 3 }}>
                    <button className="announcer-btn announcer-btn-round" style={{ width: 20, height: 20, fontSize: '0.75rem' }}
                      onClick={() => updateGameField('score_us', Math.max(0, gameState.score_us - 1))}>−</button>
                    <span style={{ fontWeight: 800, minWidth: 20, textAlign: 'center' }}>{gameState.score_us}</span>
                    <button className="announcer-btn announcer-btn-round" style={{ width: 20, height: 20, fontSize: '0.75rem' }}
                      onClick={() => updateGameField('score_us', gameState.score_us + 1)}>+</button>
                  </div>
                </div>
                <span style={{ opacity: 0.5 }}>–</span>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: '0.6rem', opacity: 0.7 }}>Them</div>
                  <div style={{ display: 'flex', gap: 3 }}>
                    <button className="announcer-btn announcer-btn-round" style={{ width: 20, height: 20, fontSize: '0.75rem' }}
                      onClick={() => updateGameField('score_them', Math.max(0, gameState.score_them - 1))}>−</button>
                    <span style={{ fontWeight: 800, minWidth: 20, textAlign: 'center' }}>{gameState.score_them}</span>
                    <button className="announcer-btn announcer-btn-round" style={{ width: 20, height: 20, fontSize: '0.75rem' }}
                      onClick={() => updateGameField('score_them', gameState.score_them + 1)}>+</button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {isHighStakes && (
            <div style={{ marginTop: '0.5rem', padding: '4px 8px', background: 'rgba(250,204,21,0.15)', borderRadius: 6, fontSize: '0.75rem', color: 'var(--warning, #facc15)', fontWeight: 700 }}>
              HIGH STAKES — Script will automatically intensify
            </div>
          )}
        </div>
      )}

      <div className="announcer-np-card glass-panel">
        <div className="announcer-np-jersey">#{current?.number || '?'}</div>
        <div className="announcer-np-name">{current?.first} {current?.last}</div>
        <StatusLed status={current?.status || 'pending'} />
      </div>

      <div className="announcer-np-timeline">
        <div className="announcer-progress-track">
          <div className="announcer-progress-fill" style={{ width: `${progressPct}%` }} />
        </div>
        <div className="announcer-np-time">
          {Math.floor(progress.elapsed)}s / {Math.floor(progress.duration)}s
        </div>
      </div>

      <div className="announcer-np-controls">
        <button onClick={goPrev} disabled={currentIdx === 0} className="announcer-btn announcer-btn-round" aria-label="Previous batter">
          <SkipBack size={24} />
        </button>
        <button onClick={handlePlay} className={`announcer-btn announcer-btn-play ${playing ? 'active' : ''}`} aria-label={playing ? 'Stop' : 'Play intro'}>
          {playing ? <Square size={32} /> : <Play size={32} />}
        </button>
        <button onClick={goNext} disabled={currentIdx >= battingOrder.length - 1} className="announcer-btn announcer-btn-round" aria-label="Next batter">
          <SkipForward size={24} />
        </button>
      </div>

      {showHalo && (
        <HaloOverlay
          onSelect={triggerHaloAchievement}
          onClose={() => setShowHalo(false)}
        />
      )}
    </div>
  );
}

const HALO_ACHIEVEMENTS = [
  { key: 'triple_rbi',   label: 'Triple Kill',   desc: '3 RBI' },
  { key: 'quad_rbi',     label: 'Overkill',       desc: '4 RBI' },
  { key: '3_strikeouts', label: 'Killtacular',    desc: '3 Ks' },
  { key: '4_strikeouts', label: 'Running Riot',   desc: '4 Ks' },
  { key: '5_strikeouts', label: 'Rampage',        desc: '5 Ks' },
  { key: 'grand_slam',   label: 'Monster Kill',   desc: 'Grand Slam' },
  { key: 'cycle',        label: 'Perfection',     desc: 'Hit for Cycle' },
];

const DEFAULT_GAME_STATE = {
  inning: 1, half: 'top', outs: 0,
  score_us: 0, score_them: 0,
  bases: [false, false, false],
  achievement: null,
};

function BaseDiamond({ bases, onToggle }) {
  // bases = [1B, 2B, 3B]
  const occupied = 'var(--warning, #facc15)';
  const empty = 'rgba(255,255,255,0.15)';
  const baseStyle = (idx) => ({
    width: 18, height: 18,
    background: bases[idx] ? occupied : empty,
    border: '2px solid rgba(255,255,255,0.4)',
    transform: 'rotate(45deg)',
    cursor: 'pointer',
    borderRadius: 2,
    transition: 'background 0.15s',
  });
  return (
    <div style={{ position: 'relative', width: 60, height: 60, flexShrink: 0 }}>
      {/* 2B — top center */}
      <div style={{ position: 'absolute', top: 0, left: '50%', transform: 'translateX(-50%)' }}
           onClick={() => onToggle(1)} title="2nd base">
        <div style={baseStyle(1)} />
      </div>
      {/* 3B — left */}
      <div style={{ position: 'absolute', top: '50%', left: 0, transform: 'translateY(-50%)' }}
           onClick={() => onToggle(2)} title="3rd base">
        <div style={baseStyle(2)} />
      </div>
      {/* 1B — right */}
      <div style={{ position: 'absolute', top: '50%', right: 0, transform: 'translateY(-50%)' }}
           onClick={() => onToggle(0)} title="1st base">
        <div style={baseStyle(0)} />
      </div>
      {/* Home plate — bottom center */}
      <div style={{ position: 'absolute', bottom: 0, left: '50%', transform: 'translateX(-50%)' }}>
        <div style={{ width: 18, height: 18, background: 'rgba(255,255,255,0.3)', border: '2px solid rgba(255,255,255,0.4)', transform: 'rotate(45deg)', borderRadius: 2 }} />
      </div>
    </div>
  );
}

function HaloOverlay({ onSelect, onClose }) {
  return createPortal(
    <div className="announcer-modal-overlay" onClick={onClose}>
      <div className="announcer-modal glass-panel" onClick={e => e.stopPropagation()} style={{ maxWidth: 340 }}>
        <h3 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Zap size={18} style={{ color: 'var(--warning, #facc15)' }} /> Halo Achievement
        </h3>
        <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '0.75rem' }}>
          Select an achievement to render a special Steitzer-style call.
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
          {HALO_ACHIEVEMENTS.map(a => (
            <button
              key={a.key}
              className="announcer-btn announcer-btn-accent"
              style={{ flexDirection: 'column', padding: '0.5rem', textAlign: 'center', height: 'auto' }}
              onClick={() => { onSelect(a.key); onClose(); }}
            >
              <span style={{ fontWeight: 700, fontSize: '0.85rem' }}>{a.label}</span>
              <span style={{ fontSize: '0.7rem', opacity: 0.75 }}>{a.desc}</span>
            </button>
          ))}
        </div>
        <button onClick={onClose} className="announcer-btn announcer-btn-secondary" style={{ marginTop: '0.75rem', width: '100%' }}>
          Cancel
        </button>
      </div>
    </div>,
    document.body
  );
}

function numToWord(num) {
  const words = {
    '0': 'zero', '1': 'one', '2': 'two', '3': 'three', '4': 'four',
    '5': 'five', '6': 'six', '7': 'seven', '8': 'eight', '9': 'nine',
    '10': 'ten', '11': 'eleven', '12': 'twelve', '13': 'thirteen',
    '14': 'fourteen', '15': 'fifteen', '16': 'sixteen', '17': 'seventeen',
    '18': 'eighteen', '19': 'nineteen', '20': 'twenty',
    '21': 'twenty-one', '22': 'twenty-two', '23': 'twenty-three',
    '24': 'twenty-four', '25': 'twenty-five', '00': 'double-zero',
  };
  return words[String(num).trim()] || String(num);
}

function useWorkerStatus() {
  const [workerStatus, setWorkerStatus] = useState(null);

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const res = await fetch('/api/announcer/worker-status');
        if (res.ok && !cancelled) setWorkerStatus(await res.json());
      } catch {
        // leave previous value on network error
      }
    };

    poll();
    const id = setInterval(poll, 10_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return workerStatus;
}

function WizardModal({ onClose, roster, onAddSong }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState({});
  const [tab, setTab] = useState('search'); // 'search' | 'roster' | 'spotify'
  const [spotifyAuthed, setSpotifyAuthed] = useState(false);
  const [spotifyResults, setSpotifyResults] = useState([]);
  const [spotifyQuery, setSpotifyQuery] = useState('');
  const [spotifyLoading, setSpotifyLoading] = useState(false);
  // Player selector for adding songs from Catalog/Spotify tabs
  const [selectedPlayerId, setSelectedPlayerId] = useState(() => roster[0]?.id || '');
  const [addingId, setAddingId] = useState(null); // tracks which row is being added

  useEffect(() => {
    import('../services/SpotifyService').then(({ isAuthenticated }) => {
      setSpotifyAuthed(isAuthenticated());
    });
  }, []);

  useEffect(() => {
    if (tab !== 'roster') return;
    setLoading(true);
    fetch('/api/announcer/music-wizard')
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) setSuggestions(data.suggestions || {}); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [tab]);

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/announcer/catalog/search?q=${encodeURIComponent(query)}&limit=20`);
      if (res.ok) { const data = await res.json(); setResults(data.results || []); }
    } finally { setLoading(false); }
  };

  const handleSpotifySearch = async (e) => {
    e.preventDefault();
    if (!spotifyQuery.trim()) return;
    setSpotifyLoading(true);
    try {
      const { searchTracks } = await import('../services/SpotifyService');
      const tracks = await searchTracks(spotifyQuery, 15);
      setSpotifyResults(tracks);
    } catch { /* token may have expired */ } finally {
      setSpotifyLoading(false);
    }
  };

  const handleSpotifyConnect = async () => {
    const { startAuth } = await import('../services/SpotifyService');
    startAuth();
  };

  const handleAdd = async (rowId, url, label, startMs) => {
    if (!selectedPlayerId || !url) return;
    setAddingId(rowId);
    try {
      await onAddSong(selectedPlayerId, url, label, startMs || 0);
    } finally {
      setAddingId(null);
    }
  };

  // Player selector shown in Catalog and Spotify tabs
  const PlayerSelector = () => (
    <div className="announcer-wizard-player-selector">
      <label>Add to:</label>
      <select value={selectedPlayerId} onChange={e => setSelectedPlayerId(e.target.value)}>
        {roster.map(p => (
          <option key={p.id} value={p.id}>#{p.number} {p.first} {p.last}</option>
        ))}
      </select>
    </div>
  );

  return createPortal(
    <div className="announcer-modal-overlay" onClick={onClose}>
      <div className="announcer-modal glass-panel" onClick={e => e.stopPropagation()} style={{ maxWidth: 520 }}>
        <div className="announcer-modal-header">
          <h3><Wand2 size={16} /> Music Wizard</h3>
          <button className="announcer-modal-close" onClick={onClose}><X size={18} /></button>
        </div>
        <div className="announcer-wizard-tabs">
          <button className={`announcer-wizard-tab${tab === 'search' ? ' active' : ''}`} onClick={() => setTab('search')}>
            Catalog
          </button>
          <button className={`announcer-wizard-tab${tab === 'roster' ? ' active' : ''}`} onClick={() => setTab('roster')}>
            Roster
          </button>
          <button className={`announcer-wizard-tab${tab === 'spotify' ? ' active' : ''}`} onClick={() => setTab('spotify')}>
            Spotify
          </button>
        </div>

        {tab === 'search' && (
          <div className="announcer-wizard-body">
            <PlayerSelector />
            <form onSubmit={handleSearch} className="announcer-wizard-search-form">
              <input
                className="announcer-song-input"
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Search title or artist…"
                autoFocus
              />
              <button type="submit" className="announcer-btn announcer-btn-primary" disabled={loading}>
                {loading ? <RefreshCw size={13} className="sync-spin" /> : 'Search'}
              </button>
            </form>
            <div className="announcer-wizard-results">
              {results.map(row => (
                <div key={row.id} className="announcer-wizard-result-row">
                  <div className="announcer-wizard-result-info">
                    <span className="announcer-wizard-result-title">{row.title}</span>
                    <span className="announcer-wizard-result-artist">{row.artist}</span>
                  </div>
                  <div className="announcer-wizard-result-meta">
                    {row.optimal_start_ms > 0 && (
                      <span className="announcer-song-start-badge">{(row.optimal_start_ms / 1000).toFixed(1)}s</span>
                    )}
                    <span className="announcer-wizard-energy" title="Energy score">{Math.round(row.energy_score * 100)}%</span>
                    <button
                      className="announcer-btn announcer-btn-secondary"
                      style={{ padding: '2px 8px', fontSize: '0.72rem' }}
                      disabled={addingId === row.id || !selectedPlayerId}
                      onClick={() => handleAdd(row.id, row.audio_url || row.url, row.title, row.optimal_start_ms)}
                    >
                      {addingId === row.id ? <RefreshCw size={11} className="sync-spin" /> : <Plus size={11} />}
                      Add
                    </button>
                  </div>
                </div>
              ))}
              {results.length === 0 && !loading && query && (
                <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: '1rem' }}>No results</p>
              )}
            </div>
          </div>
        )}

        {tab === 'roster' && (
          <div className="announcer-wizard-body">
            {loading && <div className="loader" style={{ margin: '2rem auto' }} />}
            {roster.map(player => {
              const pid = player.id;
              const sugg = suggestions[pid] || [];
              return (
                <div key={pid} className="announcer-wizard-player-section">
                  <div className="announcer-wizard-player-name">
                    #{player.number} {player.first} {player.last}
                  </div>
                  {sugg.length === 0 && !loading && (
                    <p style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>No suggestions</p>
                  )}
                  {sugg.map((row, i) => {
                    const rowKey = `${pid}-${i}`;
                    return (
                      <div key={i} className="announcer-wizard-result-row">
                        <div className="announcer-wizard-result-info">
                          <span className="announcer-wizard-result-title">{row.title}</span>
                          <span className="announcer-wizard-result-artist">{row.artist}</span>
                        </div>
                        <div className="announcer-wizard-result-meta">
                          {row.optimal_start_ms > 0 && (
                            <span className="announcer-song-start-badge">{(row.optimal_start_ms / 1000).toFixed(1)}s</span>
                          )}
                          <span className="announcer-wizard-energy">{Math.round((row.energy_score || 0) * 100)}%</span>
                          <button
                            className="announcer-btn announcer-btn-secondary"
                            style={{ padding: '2px 8px', fontSize: '0.72rem' }}
                            disabled={addingId === rowKey}
                            onClick={async () => {
                              setAddingId(rowKey);
                              try { await onAddSong(pid, row.audio_url || row.url, row.title, row.optimal_start_ms || 0); }
                              finally { setAddingId(null); }
                            }}
                          >
                            {addingId === rowKey ? <RefreshCw size={11} className="sync-spin" /> : <Plus size={11} />}
                            Add
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        )}

        {tab === 'spotify' && (
          <div className="announcer-wizard-body">
            {!spotifyAuthed ? (
              <div className="announcer-wizard-spotify-connect">
                <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginBottom: '1rem' }}>
                  Connect Spotify to search 100M+ tracks and auto-detect optimal start points.
                  30-second previews are free. Full playback requires Spotify Premium.
                </p>
                <button className="announcer-btn announcer-btn-primary" onClick={handleSpotifyConnect}>
                  Connect Spotify
                </button>
              </div>
            ) : (
              <>
                <PlayerSelector />
                <form onSubmit={handleSpotifySearch} className="announcer-wizard-search-form">
                  <input
                    className="announcer-song-input"
                    value={spotifyQuery}
                    onChange={e => setSpotifyQuery(e.target.value)}
                    placeholder="Search Spotify…"
                    autoFocus
                  />
                  <button type="submit" className="announcer-btn announcer-btn-primary" disabled={spotifyLoading}>
                    {spotifyLoading ? <RefreshCw size={13} className="sync-spin" /> : 'Search'}
                  </button>
                </form>
                <div className="announcer-wizard-results">
                  {spotifyResults.map(track => (
                    <div key={track.spotify_id} className="announcer-wizard-result-row">
                      <div className="announcer-wizard-result-info">
                        <span className="announcer-wizard-result-title">{track.title}</span>
                        <span className="announcer-wizard-result-artist">{track.artist}</span>
                      </div>
                      <div className="announcer-wizard-result-meta">
                        {track.duration_ms && (
                          <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>
                            {Math.floor(track.duration_ms / 60000)}:{String(Math.floor((track.duration_ms % 60000) / 1000)).padStart(2, '0')}
                          </span>
                        )}
                        {track.preview_url && (
                          <audio
                            src={track.preview_url}
                            controls
                            style={{ height: 22, width: 140 }}
                            preload="none"
                          />
                        )}
                        <button
                          className="announcer-btn announcer-btn-secondary"
                          style={{ padding: '2px 8px', fontSize: '0.72rem' }}
                          disabled={addingId === track.spotify_id || !selectedPlayerId}
                          onClick={() => handleAdd(track.spotify_id, track.preview_url, `${track.title} — ${track.artist}`, 0)}
                        >
                          {addingId === track.spotify_id ? <RefreshCw size={11} className="sync-spin" /> : <Plus size={11} />}
                          Add
                        </button>
                      </div>
                    </div>
                  ))}
                  {spotifyResults.length === 0 && !spotifyLoading && spotifyQuery && (
                    <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: '1rem' }}>No results</p>
                  )}
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

export default function Announcer({ lineups }) {
  const [view, setView] = useState('roster'); // 'roster' | 'nowplaying'
  const [roster, setRoster] = useState([]);
  const [stats, setStats] = useState({ total: 0, ready: 0, pending: 0, error: 0 });
  const [loading, setLoading] = useState(true);
  const [renderAllLoading, setRenderAllLoading] = useState(false);
  const [showAddSub, setShowAddSub] = useState(false);
  const [showWizard, setShowWizard] = useState(false);
  const [csvImporting, setCsvImporting] = useState(false);
  const csvInputRef = useRef(null);
  const [error, setError] = useState('');
  const pollRef = useRef(null);
  const renderToRef = useRef(null);
  const pollStopToRef = useRef(null);
  const workerStatus = useWorkerStatus();

  const fetchRoster = useCallback(async () => {
    try {
      const res = await fetch('/api/announcer/roster');
      if (!res.ok) throw new Error(`${res.status}`);
      const data = await res.json();
      setRoster(data.roster || []);
      setStats(data.stats || { total: 0, ready: 0, pending: 0, error: 0 });
      setError('');
    } catch (e) {
      setError(`Failed to load roster: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRoster();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [fetchRoster]);

  // Poll during render operations
  const startPolling = useCallback(() => {
    if (pollRef.current) return;
    pollRef.current = setInterval(fetchRoster, 3000);
  }, [fetchRoster]);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => () => {
    stopPolling();
    cleanup();
    if (renderToRef.current) clearTimeout(renderToRef.current);
    if (pollStopToRef.current) clearTimeout(pollStopToRef.current);
  }, [stopPolling]);

  const handleRenderAll = async () => {
    setRenderAllLoading(true);
    startPolling();
    try {
      await fetch('/api/announcer/render-all', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Origin': window.location.origin },
        body: '{}',
      });
      // Keep polling for updates — don't await completion
      renderToRef.current = setTimeout(() => {
        renderToRef.current = null;
        setRenderAllLoading(false);
        pollStopToRef.current = setTimeout(stopPolling, 30000);
      }, 5000);
    } catch {
      setRenderAllLoading(false);
      stopPolling();
    }
  };

  const handleRender = async (playerId, quality = 'best') => {
    startPolling();
    try {
      await fetch(`/api/announcer/render/${playerId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Origin': window.location.origin },
        body: JSON.stringify({ quality }),
      });
      renderToRef.current = setTimeout(
        () => { renderToRef.current = null; fetchRoster(); stopPolling(); },
        quality === 'best' ? 120000 : 15000,
      );
    } catch { /* handled by polling */ }
  };

  const handleSavePhonetics = async (playerId, data) => {
    const res = await fetch(`/api/announcer/phonetics/${playerId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Origin': window.location.origin },
      body: JSON.stringify(data),
    });
    if (res.ok) {
      await fetchRoster();
    }
  };

  const handleCsvImport = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = '';
    setCsvImporting(true);
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await fetch('/api/announcer/csv-import', {
        method: 'POST',
        headers: { 'Origin': window.location.origin },
        body: form,
      });
      if (res.ok) {
        const data = await res.json();
        await fetchRoster();
        if (data.errors?.length) {
          setError(`CSV import: ${data.imported} songs added, ${data.skipped} skipped, ${data.errors.length} errors`);
        }
      }
    } catch { /* silent — user will see no change */ } finally {
      setCsvImporting(false);
    }
  };

  const handleAddSongFromWizard = async (playerId, url, label, startMs) => {
    const res = await fetch(`/api/announcer/songs/${playerId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Origin': window.location.origin },
      body: JSON.stringify({ song_url: url, song_label: label, optimal_start_ms: startMs || 0 }),
    });
    if (!res.ok) throw new Error('Failed to add song');
    await fetchRoster();
  };

  const handleAddSub = async (data) => {
    startPolling();
    const res = await fetch('/api/announcer/add-sub', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Origin': window.location.origin },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error('Failed to add player');
    await fetchRoster();
    pollStopToRef.current = setTimeout(stopPolling, 10000);
  };

  const handleRemovePlayer = async (playerId) => {
    try {
      const res = await fetch(`/api/announcer/player/${playerId}`, {
        method: 'DELETE',
        headers: { 'Origin': window.location.origin },
      });
      if (res.ok) await fetchRoster();
    } catch { /* silent */ }
  };

  if (loading) return <div className="loader" />;

  if (view === 'nowplaying') {
    return (
      <NowPlayingView
        roster={roster}
        lineups={lineups}
        onBack={() => setView('roster')}
      />
    );
  }

  return (
    <div className="announcer-container">
      <div className="announcer-header">
        <h2>
          <Mic size={22} /> The Announcer
        </h2>
        <div className="announcer-header-actions">
          <WorkerBadge workerStatus={workerStatus} />
          <button onClick={() => setView('nowplaying')} className="announcer-btn announcer-btn-accent">
            <Play size={14} /> Now Playing
          </button>
        </div>
      </div>

      {error && <div className="voice-error"><AlertCircle size={14} /> {error}</div>}

      <StatsBar stats={stats} />

      <div className="announcer-toolbar">
        <button onClick={handleRenderAll} disabled={renderAllLoading} className="announcer-btn announcer-btn-primary">
          {renderAllLoading ? <RefreshCw size={14} className="sync-spin" /> : <Mic size={14} />}
          {renderAllLoading ? 'Rendering...' : 'Render All'}
        </button>
        <button onClick={() => setShowAddSub(true)} className="announcer-btn announcer-btn-secondary">
          <UserPlus size={14} /> Add Sub
        </button>
        <button onClick={() => setShowWizard(true)} className="announcer-btn announcer-btn-secondary" title="Music Wizard">
          <Wand2 size={14} /> Wizard
        </button>
        <label className={`announcer-btn announcer-btn-secondary${csvImporting ? ' announcer-btn--loading' : ''}`} title="Import songs from CSV">
          <Upload size={14} />
          <input ref={csvInputRef} type="file" accept=".csv" onChange={handleCsvImport} style={{ display: 'none' }} />
        </label>
        <button onClick={fetchRoster} className="announcer-btn announcer-btn-secondary" aria-label="Refresh roster">
          <RefreshCw size={14} />
        </button>
      </div>

      <div className="announcer-roster-list">
        {roster.map(player => (
          <PlayerCard
            key={player.id}
            player={player}
            onSavePhonetics={handleSavePhonetics}
            onRender={handleRender}
            onPreview={() => {}}
            onRemove={handleRemovePlayer}
          />
        ))}
        {roster.length === 0 && (
          <div className="glass-panel" style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
            No players found. Make sure team data has been synced.
          </div>
        )}
      </div>

      {showAddSub && (
        <AddSubModal onClose={() => setShowAddSub(false)} onAdd={handleAddSub} />
      )}
      {showWizard && (
        <WizardModal onClose={() => setShowWizard(false)} roster={roster} onAddSong={handleAddSongFromWizard} />
      )}
    </div>
  );
}
