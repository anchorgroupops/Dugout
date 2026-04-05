import React, { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import {
  Mic, Music, Play, Square, SkipBack, SkipForward,
  ChevronDown, ChevronUp, RefreshCw, UserPlus, Save,
  AlertCircle, CheckCircle, Clock, Volume2, Settings2, List
} from 'lucide-react';
import { playIntro, playClip, stop as stopAudio, preload, cleanup } from '../utils/audioController';

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
            <input placeholder="Walk-up song URL" value={walkupUrl} onChange={e => setWalkupUrl(e.target.value)} maxLength={500} />
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

function PlayerCard({ player, onSavePhonetics, onRender }) {
  const [expanded, setExpanded] = useState(false);
  const [phonetic, setPhonetic] = useState(player.phonetic_hint || '');
  const [instruction, setInstruction] = useState(player.tts_instruction || '');
  const [walkupUrl, setWalkupUrl] = useState(player.walkup_song_url || '');
  const [introTs, setIntroTs] = useState(player.intro_timestamp ?? 5);
  const [saving, setSaving] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [previewing, setPreviewing] = useState(false);

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
      await onRender(player.id);
    } finally {
      setTimeout(() => setRendering(false), 2000);
    }
  };

  const handlePreview = () => {
    if (previewing) {
      stopAudio();
      setPreviewing(false);
    } else if (player.announcer_audio_url) {
      setPreviewing(true);
      playClip(player.announcer_audio_url, () => setPreviewing(false));
    }
  };

  return (
    <div className={`announcer-player-card glass-panel ${expanded ? 'expanded' : ''}`}>
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
              <label>Walk-up Song URL</label>
              <input
                value={walkupUrl}
                onChange={e => setWalkupUrl(e.target.value)}
                placeholder="https://example.com/walkup.mp3"
                maxLength={500}
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

  // Build batting order from lineups or fall back to roster order
  const battingOrder = (() => {
    if (lineups) {
      for (const key of Object.keys(lineups)) {
        const val = lineups[key];
        if (val && typeof val === 'object' && Array.isArray(val.order)) {
          return val.order
            .map(name => {
              const lower = name.toLowerCase();
              return roster.find(p =>
                `${p.first} ${p.last}`.toLowerCase() === lower ||
                p.first.toLowerCase() === lower
              );
            })
            .filter(Boolean);
        }
      }
    }
    return roster.filter(p => p.is_active && p.status === 'ready');
  })();

  const current = battingOrder[currentIdx] || null;
  const progressPct = progress.duration > 0 ? Math.min(100, (progress.elapsed / progress.duration) * 100) : 0;

  const handlePlay = async () => {
    if (!current) return;
    if (playing) {
      stopAudio();
      setPlaying(false);
      return;
    }
    setPlaying(true);
    try {
      await playIntro({
        walkupUrl: current.walkup_song_url || '',
        clipUrl: current.announcer_audio_url || '',
        introTimestamp: current.intro_timestamp ?? 5,
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

  return (
    <div className="announcer-now-playing">
      <div className="announcer-np-header">
        <button onClick={onBack} className="announcer-btn announcer-btn-secondary" aria-label="Back to roster">
          <List size={16} /> Roster
        </button>
        <span className="announcer-np-position">{currentIdx + 1} of {battingOrder.length}</span>
      </div>

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
    </div>
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

export default function Announcer({ lineups }) {
  const [view, setView] = useState('roster'); // 'roster' | 'nowplaying'
  const [roster, setRoster] = useState([]);
  const [stats, setStats] = useState({ total: 0, ready: 0, pending: 0, error: 0 });
  const [loading, setLoading] = useState(true);
  const [renderAllLoading, setRenderAllLoading] = useState(false);
  const [showAddSub, setShowAddSub] = useState(false);
  const [error, setError] = useState('');
  const pollRef = useRef(null);

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

  useEffect(() => () => { stopPolling(); cleanup(); }, [stopPolling]);

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
      setTimeout(() => {
        setRenderAllLoading(false);
        // Poll a few more times then stop
        setTimeout(stopPolling, 30000);
      }, 5000);
    } catch {
      setRenderAllLoading(false);
      stopPolling();
    }
  };

  const handleRender = async (playerId) => {
    startPolling();
    try {
      await fetch(`/api/announcer/render/${playerId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Origin': window.location.origin },
        body: '{}',
      });
      setTimeout(() => { fetchRoster(); stopPolling(); }, 5000);
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

  const handleAddSub = async (data) => {
    startPolling();
    const res = await fetch('/api/announcer/add-sub', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Origin': window.location.origin },
      body: JSON.stringify(data),
    });
    if (!res.ok) throw new Error('Failed to add player');
    await fetchRoster();
    setTimeout(stopPolling, 10000);
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
    </div>
  );
}
