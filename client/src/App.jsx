import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Users, Activity, RefreshCw, ListOrdered, Calendar, Trophy, Dumbbell, Volume2, Target, AlertTriangle, MoreHorizontal, Download, Globe, GlobeLock, Clock, Radio, Mic } from 'lucide-react';
import { formatDateTime, formatRelative } from './utils/formatDate';
import { usePWAInstall } from './utils/usePWAInstall';
import { useOnlineStatus } from './utils/useOnlineStatus';
import Roster from './components/Roster';
import Swot from './components/Swot';
import Lineup from './components/Lineup';
import Games from './components/Games';
import League from './components/League';
import Practice from './components/Practice';
import Scouting from './components/Scouting';
import Scoreboard from './components/Scoreboard';
import Announcer from './components/Announcer';
import ErrorBoundary from './components/ErrorBoundary';


function SyncProgressBar({ progress, stage, milestones }) {
  const activeIdx = milestones.findIndex(m => m.id === stage);
  return (
    <div className="sync-progress-wrap">
      <div className="sync-progress-track">
        <div className="sync-progress-fill" style={{ width: `${progress}%` }} />
        {milestones.map((m, i) => {
          const done = progress >= m.pct;
          const active = i === activeIdx;
          return (
            <div key={m.id} className={`sync-milestone ${done ? 'done' : ''} ${active ? 'active' : ''}`} style={{ left: `${m.pct}%` }}>
              <div className="sync-milestone-dot" />
              <span className="sync-milestone-label">{m.label}</span>
            </div>
          );
        })}
      </div>
      <div className="sync-progress-pct">{progress}%</div>
    </div>
  );
}

function App() {
  const [currentView, setCurrentView] = useState('scoreboard');
  const { canInstall, triggerInstall } = usePWAInstall();
  const isOnline = useOnlineStatus();
  const [isMobile, setIsMobile] = useState(
    typeof window !== 'undefined'
      ? window.innerWidth <= 768 || (window.innerWidth <= 1024 && window.innerHeight <= 500)
      : false
  );
  const [isLandscape, setIsLandscape] = useState(
    typeof window !== 'undefined'
      ? window.innerWidth > window.innerHeight && window.innerHeight <= 500
      : false
  );
  const [voiceLoading, setVoiceLoading] = useState(false);
  const [voiceError, setVoiceError] = useState('');
  const [staleSources, setStaleSources] = useState([]);
  const [syncStage, setSyncStage] = useState('idle');
  const [syncProgress, setSyncProgress] = useState(0);
  const [syncMilestones, setSyncMilestones] = useState([]);
  const [syncLoading, setSyncLoading] = useState(false);
  const [moreMenuOpen, setMoreMenuOpen] = useState(false);
  const [data, setData] = useState({
    team: null,
    swot: null,
    lineups: null,
    availability: null,
    games: null,
    schedule: null,
    loading: true,
    error: null
  });
  const audioRef = useRef(null);
  const audioUrlRef = useRef('');
  const syncPollRef = useRef(null);

  const fetchWithRetry = useCallback(async (url, retries = 2) => {
    for (let i = 0; i <= retries; i++) {
      try {
        const res = await fetch(url);
        if (res.ok || i === retries) return res;
      } catch (e) {
        if (i === retries) throw e;
      }
      await new Promise(r => setTimeout(r, 300 * (i + 1)));
    }
  }, []);

  const fetchData = useCallback(async () => {
    try {
      const [teamRes, swotRes, lineupsRes, availRes, gamesRes, scheduleRes] = await Promise.all([
        fetchWithRetry('/api/team'),
        fetchWithRetry('/data/sharks/swot_analysis.json'),
        fetchWithRetry('/data/sharks/lineups.json'),
        fetchWithRetry('/api/availability'),
        fetchWithRetry('/api/games'),
        fetchWithRetry('/api/schedule')
      ]);

      if (!teamRes.ok) throw new Error('Failed to load team data');

      const team = await teamRes.json();
      const swot = swotRes.ok ? await swotRes.json() : null;
      const lineups = lineupsRes.ok ? await lineupsRes.json() : null;
      const availability = availRes.ok ? await availRes.json() : {};
      const games = gamesRes.ok ? await gamesRes.json() : null;
      const schedule = scheduleRes.ok ? await scheduleRes.json() : null;

      setData({ team, swot, lineups, availability, games, schedule, loading: false, error: null });

      // Check pipeline health and sync status (non-blocking)
      try {
        const [healthRes, syncRes] = await Promise.all([
          fetch('/api/health').catch(() => null),
          fetch('/api/sync/status').catch(() => null),
        ]);
        if (healthRes?.ok) {
          const health = await healthRes.json();
          setStaleSources(health.stale_sources || []);
        }
        if (syncRes?.ok) {
          const sync = await syncRes.json();
          setSyncStage(sync.stage || 'idle');
          setSyncProgress(sync.progress || 0);
          if (sync.milestones?.length) setSyncMilestones(sync.milestones);
          if (sync.stage && sync.stage !== 'idle') setSyncLoading(true);
        }
      } catch { /* ignore health/sync check failures */ }
    } catch (err) {
      console.error("Data fetch error", err);
      setData(prev => ({ ...prev, loading: false, error: err.message }));
    }
  }, [fetchWithRetry]);

  useEffect(() => {
    fetchData();
    const intervalId = setInterval(fetchData, 30000);
    return () => clearInterval(intervalId);
  }, [fetchData]);

  useEffect(() => {
    const onResize = () => {
      const w = window.innerWidth;
      const h = window.innerHeight;
      setIsMobile(w <= 768 || (w <= 1024 && h <= 500));
      setIsLandscape(w > h && h <= 500);
    };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
      }
      if (audioUrlRef.current) {
        URL.revokeObjectURL(audioUrlRef.current);
      }
      if (syncPollRef.current) {
        clearInterval(syncPollRef.current);
      }
    };
  }, []);

  const handleVoiceUpdate = useCallback(async () => {
    setVoiceLoading(true);
    setVoiceError('');
    try {
      if (audioRef.current) {
        audioRef.current.pause();
      }
      if (audioUrlRef.current) {
        URL.revokeObjectURL(audioUrlRef.current);
        audioUrlRef.current = '';
      }

      const res = await fetch('/api/voice-update');
      if (!res.ok) {
        let detail = 'Voice update unavailable';
        try {
          const body = await res.json();
          if (body?.detail) detail = body.detail;
        } catch {
          // ignored: non-json response
        }
        throw new Error(detail);
      }

      const blob = await res.blob();
      const objectUrl = URL.createObjectURL(blob);
      audioUrlRef.current = objectUrl;
      const audio = new Audio(objectUrl);
      audioRef.current = audio;
      await audio.play();
    } catch (err) {
      console.error('Voice update playback failed', err);
      setVoiceError(err?.message || 'Voice update playback failed');
    } finally {
      setVoiceLoading(false);
    }
  }, []);

  const [syncStatusText, setSyncStatusText] = useState('');

  const handleManualSync = useCallback(async () => {
    setSyncLoading(true);
    setSyncProgress(0);
    setSyncStatusText('Triggering sync...');
    try {
      const res = await fetch('https://anchorgroupops--softball-strategy-sharks-manual-sync.modal.run', {
        method: 'POST'
      });
      if (!res.ok) throw new Error('Sync trigger failed');

      // Capture the current health timestamp to detect fresh data
      let baseTimestamp = null;
      try {
        const hRes = await fetch('/api/health');
        if (hRes.ok) {
          const h = await hRes.json();
          baseTimestamp = h.last_updated || h.timestamp || null;
        }
      } catch { /* ignore */ }

      // Poll /api/sync/status for progress + /api/health for completion
      const POLL_INTERVAL = 5000;
      const TIMEOUT = 10 * 60 * 1000;
      const startTime = Date.now();

      if (syncPollRef.current) clearInterval(syncPollRef.current);
      syncPollRef.current = setInterval(async () => {
        try {
          const elapsed = Date.now() - startTime;
          if (elapsed >= TIMEOUT) {
            clearInterval(syncPollRef.current);
            syncPollRef.current = null;
            setSyncLoading(false);
            setSyncProgress(0);
            setSyncStatusText('Sync timed out — data may still be updating');
            return;
          }

          // Poll sync status for progress
          const sRes = await fetch('/api/sync/status').catch(() => null);
          if (sRes?.ok) {
            const s = await sRes.json();
            setSyncStage(s.stage || 'idle');
            setSyncProgress(s.progress || 0);
            if (s.milestones?.length) setSyncMilestones(s.milestones);
            setSyncStatusText(s.stage === 'idle' ? '' : s.stage.replace(/_/g, ' '));

            // If stage went back to idle, sync is done
            if (s.stage === 'idle' && elapsed > 5000) {
              clearInterval(syncPollRef.current);
              syncPollRef.current = null;
              setSyncLoading(false);
              setSyncProgress(100);
              setSyncStatusText('Sync complete');
              fetchData();
              setTimeout(() => { setSyncProgress(0); setSyncStatusText(''); }, 4000);
              return;
            }
          }

          // Also check health timestamp for completion
          const hRes = await fetch('/api/health').catch(() => null);
          if (hRes?.ok) {
            const h = await hRes.json();
            const newTimestamp = h.last_updated || h.timestamp || null;
            if (baseTimestamp && newTimestamp && newTimestamp !== baseTimestamp) {
              clearInterval(syncPollRef.current);
              syncPollRef.current = null;
              setSyncLoading(false);
              setSyncProgress(100);
              setSyncStatusText('Sync complete');
              fetchData();
              setTimeout(() => { setSyncProgress(0); setSyncStatusText(''); }, 4000);
            }
          }
        } catch { /* ignore poll errors */ }
      }, POLL_INTERVAL);
    } catch (err) {
      console.error('Sync failed', err);
      setSyncLoading(false);
      setSyncProgress(0);
      setSyncStatusText('Sync failed: ' + err.message);
    }
  }, [fetchData]);

  // All nav items for desktop
  const navItems = [
    { id: 'scoreboard', label: 'Live', icon: <Radio size={18} /> },
    { id: 'scout', label: 'Scout', icon: <Target size={18} /> },
    { id: 'swot', label: 'SWOT', icon: <Activity size={18} /> },
    { id: 'roster', label: 'Roster', icon: <Users size={18} /> },
    { id: 'lineups', label: 'Lineups', icon: <ListOrdered size={18} /> },
    { id: 'games', label: 'Games', icon: <Calendar size={18} /> },
    { id: 'league', label: 'League', icon: <Trophy size={18} /> },
    { id: 'practice', label: 'Practice', icon: <Dumbbell size={18} /> },
    { id: 'announcer', label: 'Announcer', icon: <Mic size={18} /> }
  ];

  // Mobile: 4 primary bottom tabs + "More" overflow
  // Live scoreboard gets primary position for game-day dugout use
  const primaryNavItems = [
    { id: 'scoreboard', label: 'Live', icon: <Radio size={22} /> },
    { id: 'scout', label: 'Scout', icon: <Target size={22} /> },
    { id: 'lineups', label: 'Lineups', icon: <ListOrdered size={22} /> },
    { id: 'practice', label: 'Practice', icon: <Dumbbell size={22} /> },
    { id: 'announcer', label: 'Announcer', icon: <Mic size={22} /> },
  ];

  const overflowNavItems = [
    { id: 'swot', label: 'SWOT', icon: <Activity size={20} /> },
    { id: 'roster', label: 'Roster', icon: <Users size={20} /> },
    { id: 'games', label: 'Games', icon: <Calendar size={20} /> },
    { id: 'league', label: 'League', icon: <Trophy size={20} /> },
  ];

  const renderContent = () => {
    if (data.loading) return <div className="loader"></div>;
    if (data.error) return (
      <div className="glass-panel" style={{ padding: '2rem', borderColor: 'var(--danger)' }}>
        <h3 style={{ color: 'var(--danger)' }}>Error loading data</h3>
        <p>{data.error}</p>
        <p style={{ marginTop: '1rem', fontSize: '0.9em', color: 'var(--text-muted)' }}>
          Tip: Ensure the sync_data script ran successfully during build.
        </p>
      </div>
    );

    switch(currentView) {
      case 'scoreboard': return <Scoreboard isMobile={isMobile} isLandscape={isLandscape} team={data.team} schedule={data.schedule} />;
      case 'scout': return <Scouting isMobile={isMobile} isLandscape={isLandscape} />;
      case 'roster': return (
        <Roster
          team={data.team}
          availability={data.availability}
          isMobile={isMobile}
          isLandscape={isLandscape}
        />
      );
      case 'swot': return <Swot swotData={data.swot} roster={data.team?.roster} schedule={data.schedule} isMobile={isMobile} isLandscape={isLandscape} />;
      case 'lineups': return (
        <Lineup
          team={data.team}
          lineupsData={data.lineups}
          availability={data.availability}
          schedule={data.schedule}
          isMobile={isMobile}
          isLandscape={isLandscape}
          onAvailabilityChange={(newAvail) => setData(prev => ({ ...prev, availability: newAvail }))}
          onDataRefresh={fetchData}
          onRegenerate={(newLineups) => setData(prev => ({ ...prev, lineups: newLineups }))}
        />
      );
      case 'games': return <Games gamesData={data.games} schedule={data.schedule} isMobile={isMobile} isLandscape={isLandscape} />;
      case 'league': return <League isMobile={isMobile} isLandscape={isLandscape} />;
      case 'practice': return (
        <Practice
          team={data.team}
          schedule={data.schedule}
          isMobile={isMobile}
          isLandscape={isLandscape}
        />
      );
      case 'announcer': return (
        <Announcer lineups={data.lineups} />
      );
      default: return (
        <Roster
          team={data.team}
          availability={data.availability}
          isMobile={isMobile}
        />
      );
    }
  };

  const displayTeamName = (() => {
    const raw = String(data.team?.team_name || 'The Sharks').trim();
    if (raw.toLowerCase() === 'sharks' || raw.toLowerCase() === 'the sharks') return 'The Sharks';
    return raw;
  })();

  return (
    <div data-landscape={isLandscape ? '' : undefined} className={isLandscape ? 'landscape-mode' : ''}>
      {/* ─── Top Navigation ─── */}
      {isMobile ? (
        <nav className="navbar navbar-mobile">
          <div className="mobile-header">
            <div className="mobile-header-left">
              <img src="/sharks-logo-round.png" alt="Sharks" className="logo-avatar" />
              <span className="brand" style={{ fontSize: '1.125rem' }}>
                {(() => {
                  const labels = { scoreboard: 'Live', scout: 'Scout', swot: 'SWOT', lineups: 'Lineups', practice: 'Practice', roster: 'Roster', games: 'Games', league: 'League' };
                  return labels[currentView] || 'Sharks';
                })()}
              </span>
              <span
                className={`sync-status-dot ${staleSources.length > 0 ? 'stale' : 'fresh'}`}
                title={staleSources.length > 0 ? `Stale: ${staleSources.join(', ')}` : 'Data is fresh'}
              />
              {!isOnline && (
                <span className="sync-stage-tag offline" style={{ background: '#711d1c' }}>OFFLINE</span>
              )}
            </div>
            <div className="mobile-header-actions">
              <button
                className="mobile-action-btn"
                onClick={fetchData}
                title="Refresh Data"
                aria-label="Refresh Data"
              >
                <RefreshCw size={22} />
              </button>
              <button
                className="mobile-action-btn"
                onClick={handleVoiceUpdate}
                disabled={voiceLoading}
                title="Voice Update"
                aria-label="Voice Update"
              >
                <Volume2 size={22} className={voiceLoading ? 'sync-spin' : ''} />
              </button>
            </div>
          </div>
          {syncLoading && syncMilestones.length > 0 && (
            <div className="mobile-sync-progress">
              <SyncProgressBar progress={syncProgress} stage={syncStage} milestones={syncMilestones} />
            </div>
          )}
          {!syncLoading && syncStatusText && (
            <div className="mobile-sync-status">{syncStatusText}</div>
          )}
        </nav>
      ) : (
        <nav className="navbar">
          <div className="brand">
            <img src="/sharks-logo-round.png" alt="Sharks" className="logo-avatar" />
            The Sharks
          </div>
          <div className="nav-links">
            {navItems.map(item => (
              <button
                key={item.id}
                className={`nav-btn ${currentView === item.id ? 'active' : ''}`}
                onClick={() => setCurrentView(item.id)}
              >
                {item.icon}
                {item.label}
              </button>
            ))}
          </div>
        </nav>
      )}

      <main className="animate-fade-in">
        {/* Desktop hero */}
        {!isMobile && (
          <div style={{ marginBottom: '2rem' }}>
            <h1 style={{ fontSize: 'clamp(1.6rem, 5.5vw, 2.5rem)', marginBottom: '0.4rem', lineHeight: 1.1 }}>
              {displayTeamName}
            </h1>
            <div className="hero-meta-row">
              <p style={{ color: 'var(--text-muted)', fontSize: '1.1rem' }}>
                {data.team ? `${data.team.league} \u2022 Last Updated: ${formatDateTime(data.team.last_updated)}` : 'Loading...'}
              </p>
              {canInstall && (
                <button 
                  className="voice-btn" 
                  onClick={triggerInstall} 
                  style={{ background: 'var(--primary-color)', color: 'var(--bg-color)' }}
                  title="Install the app for offline use"
                >
                  <Download size={16} />
                  Install App
                </button>
              )}
              <button className={`sync-btn ${syncLoading ? 'sync-btn--active' : ''}`} onClick={handleManualSync} disabled={syncLoading} title="Trigger manual data refresh" aria-label="Trigger manual data refresh">
                <RefreshCw size={16} className={syncLoading ? 'sync-spin' : ''} />
                {syncLoading ? 'Syncing...' : 'Manual Sync'}
              </button>
              {syncLoading && syncMilestones.length > 0 && (
                <SyncProgressBar progress={syncProgress} stage={syncStage} milestones={syncMilestones} />
              )}
              {!syncLoading && syncStatusText && <span style={{ fontSize: '0.75rem', color: 'var(--primary-color)' }}>{syncStatusText}</span>}
              <button className="voice-btn" onClick={handleVoiceUpdate} disabled={voiceLoading} title="Play latest audio overview" aria-label="Play latest audio overview">
                <Volume2 size={16} className={voiceLoading ? 'sync-spin' : ''} />
                {voiceLoading ? 'Preparing...' : 'Voice Update'}
              </button>
            </div>
          </div>
        )}

        {voiceError && <p className="voice-error">{voiceError}</p>}
        
        {!isOnline && (
          <div className="stale-banner offline-banner" style={{ background: 'var(--danger)', color: 'white', borderColor: 'rgba(255,255,255,0.2)' }}>
            <GlobeLock size={16} />
            <span>Currently working offline. Some features like Manual Sync and Voice Update are unavailable.</span>
          </div>
        )}

        {staleSources.length > 0 && (
          <div className="stale-banner">
            <AlertTriangle size={16} />
            <span>Data may be stale: {staleSources.join(', ')}</span>
          </div>
        )}

        {data.team?.last_updated && (
          <div className="last-updated-tag">
            <Clock size={12} />
            <span>Updated {formatRelative(data.team.last_updated)}</span>
          </div>
        )}

        <ErrorBoundary key={currentView}>
          {renderContent()}
        </ErrorBoundary>
      </main>

      {/* ─── Mobile Bottom Navigation ─── */}
      {isMobile && (
        <>
          {moreMenuOpen && (
            <div className="more-menu-overlay" onClick={() => setMoreMenuOpen(false)} />
          )}
          {moreMenuOpen && (
            <div className="more-menu">
              {overflowNavItems.map(item => (
                <button
                  key={item.id}
                  className={`more-menu-item ${currentView === item.id ? 'active' : ''}`}
                  onClick={() => {
                    setCurrentView(item.id);
                    setMoreMenuOpen(false);
                  }}
                >
                  {item.icon}
                  {item.label}
                </button>
              ))}
              {canInstall && (
                <button
                  className="more-menu-item install-item"
                  style={{ color: 'var(--primary-color)', fontWeight: 'bold' }}
                  onClick={() => {
                    triggerInstall();
                    setMoreMenuOpen(false);
                  }}
                >
                  <Download size={20} />
                  Install App (Offline)
                </button>
              )}
            </div>
          )}
          <nav className="bottom-nav">
            {primaryNavItems.map(item => (
              <button
                key={item.id}
                className={`bottom-nav-item ${currentView === item.id ? 'active' : ''}`}
                onClick={() => {
                  setCurrentView(item.id);
                  setMoreMenuOpen(false);
                }}
                aria-label={item.label}
              >
                {item.icon}
                <span>{item.label}</span>
              </button>
            ))}
            <button
              className={`bottom-nav-item ${overflowNavItems.some(i => i.id === currentView) ? 'active' : ''}`}
              onClick={() => setMoreMenuOpen(prev => !prev)}
            >
              <MoreHorizontal size={22} />
              <span>More</span>
            </button>
          </nav>
        </>
      )}
    </div>
  );
}

export default App;
