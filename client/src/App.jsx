import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Users, Activity, RefreshCw, ListOrdered, Calendar, Trophy, Dumbbell, Volume2, Target, AlertTriangle, MoreHorizontal, Download, Globe, GlobeLock, Clock, Radio, Mic } from 'lucide-react';
import { formatDateTime, formatRelative } from './utils/formatDate';
import { usePWAInstall } from './utils/usePWAInstall';
import { useOnlineStatus } from './utils/useOnlineStatus';
import Roster from './components/Roster';
import Lineup from './components/Lineup';
import Scoreboard from './components/Scoreboard';
import ErrorBoundary from './components/ErrorBoundary';
import { lazyWithRetry } from './utils/lazyWithRetry';
import { fetchWithBackoff } from './utils/apiClient';
const Swot = lazyWithRetry(() => import('./components/Swot'));
const Games = lazyWithRetry(() => import('./components/Games'));
const League = lazyWithRetry(() => import('./components/League'));
const Practice = lazyWithRetry(() => import('./components/Practice'));
const Scouting = lazyWithRetry(() => import('./components/Scouting'));
const Announcer = lazyWithRetry(() => import('./components/Announcer'));


function SyncProgressBar({ progress, stage, milestones }) {
  const activeIdx = milestones.findIndex(m => m.id === stage);
  return (
    <div className="sync-progress-wrap animate-fade-in glass-panel" style={{ padding: '0.75rem', borderRadius: '12px', background: 'rgba(130, 203, 195, 0.05)' }}>
      <div className="sync-progress-track">
        <div className="sync-progress-fill" style={{ width: `${progress}%`, transition: 'width 1s cubic-bezier(0.34, 1.56, 0.64, 1)' }} />
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
      <div className="sync-progress-pct" style={{ minWidth: '3.5rem', fontWeight: 800 }}>{progress}%</div>
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
  const [loadingTimedOut, setLoadingTimedOut] = useState(false);
  // Hydrate team/availability/lineups from localStorage so the UI has
  // something to show before (or instead of) a successful network fetch.
  const cachedFromLocal = (() => {
    try {
      const raw = window.localStorage.getItem('sharks_data_cache');
      return raw ? JSON.parse(raw) : null;
    } catch { return null; }
  })();
  const [data, setData] = useState({
    team: cachedFromLocal?.team || null,
    swot: cachedFromLocal?.swot || null,
    lineups: cachedFromLocal?.lineups || null,
    availability: cachedFromLocal?.availability || null,
    games: cachedFromLocal?.games || null,
    schedule: cachedFromLocal?.schedule || null,
    loading: true,
    error: null,
    isCached: Boolean(cachedFromLocal?.team),
    cachedAt: cachedFromLocal?.cachedAt || null,
    staleKeys: [],
  });
  const audioRef = useRef(null);
  const audioUrlRef = useRef('');
  const syncPollRef = useRef(null);

  const fetchWithRetry = useCallback(async (url) => {
    // Delegate to apiClient's fetchWithBackoff: exponential backoff with
    // jitter, 429-aware global pause, idempotent-GET-only retry policy.
    // The previous bespoke linear retry hammered the API on every loop
    // tick during an outage; backoff cuts that to the bone.
    return fetchWithBackoff(url);
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

      // Graceful team fallback. The previous code threw on a non-OK
      // /api/team response, which crashed the entire data-loading
      // pipeline and left every tab showing the "Failed to load team
      // data" error banner. Instead: try the bundled static fallbacks
      // (/data/sharks/team.json from the image) and the localStorage
      // cache, then degrade-but-still-render. If we genuinely have
      // nothing, pass `team: null` through and let downstream tabs
      // show their own empty states.
      let team = null;
      let teamFromFallback = false;
      if (teamRes.ok) {
        try { team = await teamRes.json(); } catch { team = null; }
      }
      if (!team || (typeof team === 'object' && !team.roster)) {
        try {
          const staticRes = await fetch('/data/sharks/team.json', { cache: 'no-store' });
          if (staticRes.ok) {
            team = await staticRes.json();
            teamFromFallback = true;
          }
        } catch { /* fall through to localStorage */ }
        if (!team) {
          try {
            const raw = window.localStorage.getItem('sharks_data_cache');
            const parsed = raw ? JSON.parse(raw) : null;
            if (parsed?.team) {
              team = parsed.team;
              teamFromFallback = true;
            }
          } catch { /* nothing — render empty */ }
        }
      }

      const swot = swotRes.ok ? await swotRes.json() : null;
      const lineups = lineupsRes.ok ? await lineupsRes.json() : null;
      const availability = availRes.ok ? await availRes.json() : {};
      const games = gamesRes.ok ? await gamesRes.json() : null;
      const schedule = scheduleRes.ok ? await scheduleRes.json() : null;

      // "Never downgrade" cache policy: if a fresh fetch produced a null /
      // empty value but our previous cache had real data, keep the prior
      // value. This prevents the Games tab from emptying out and the
      // Schedule from disappearing when the upstream scraper has a bad day.
      // We MERGE rather than overwrite — every key independently chooses
      // between the new value and the prior cached value.
      const isUseful = (v) => {
        if (v == null) return false;
        if (Array.isArray(v)) return v.length > 0;
        if (typeof v === 'object') {
          // For schedule: {upcoming:[], past:[]} is empty even though it's an object
          if (Array.isArray(v.upcoming) || Array.isArray(v.past)) {
            return (v.upcoming?.length || 0) + (v.past?.length || 0) > 0;
          }
          return Object.keys(v).length > 0;
        }
        return true;
      };
      // Read the latest cached values FRESHLY from localStorage rather than
      // relying on the closure value (which would be stale on the 2nd+ fetch
      // since this useCallback only re-creates when fetchWithRetry changes).
      let priorCache = null;
      try {
        const raw = window.localStorage.getItem('sharks_data_cache');
        priorCache = raw ? JSON.parse(raw) : null;
      } catch { priorCache = null; }

      // Helper: prefer fresh value if useful, else prior-cached value if
      // useful, else fall back to fresh (which may be null/empty). This
      // prevents the case where both fresh AND priorCache contain empty
      // arrays — without it, ?? would keep the empty object indefinitely.
      const pickUseful = (fresh, prior, defaultEmpty = null) => {
        if (isUseful(fresh)) return fresh;
        if (isUseful(prior)) return prior;
        return fresh ?? defaultEmpty;
      };
      const merged = {
        team:         pickUseful(team,         priorCache?.team,         team),
        swot:         pickUseful(swot,         priorCache?.swot,         swot),
        lineups:      pickUseful(lineups,      priorCache?.lineups,      lineups),
        availability: pickUseful(availability, priorCache?.availability, availability),
        games:        pickUseful(games,        priorCache?.games,        null),
        schedule:     pickUseful(schedule,     priorCache?.schedule,     null),
      };
      // Track which keys came from the prior cache so we can surface a
      // "stale" indicator in components that depend on them.
      const staleKeys = [];
      if (!isUseful(games) && isUseful(priorCache?.games)) staleKeys.push('games');
      if (!isUseful(schedule) && isUseful(priorCache?.schedule)) staleKeys.push('schedule');

      const cachedAt = new Date().toISOString();
      setData({
        ...merged,
        loading: false,
        error: null,
        isCached: teamFromFallback,
        isOffline: teamFromFallback,
        cachedAt,
        staleKeys,
      });
      setLoadingTimedOut(false);
      try {
        // Never persist a non-useful schedule/games payload — that's how
        // localStorage.schedule ended up frozen at {upcoming:[], past:[]}.
        const persisted = { ...merged, cachedAt };
        if (!isUseful(persisted.schedule)) delete persisted.schedule;
        if (!isUseful(persisted.games)) delete persisted.games;
        window.localStorage.setItem('sharks_data_cache', JSON.stringify(persisted));
      } catch { /* localStorage may be full or disabled */ }
      if (staleKeys.length > 0) {
        console.warn('[Cache] preserving prior values for empty/null fetch result:', staleKeys);
      }

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
      setData(prev => ({ ...prev, loading: false, error: err.message, isCached: Boolean(prev.team) }));
    }
  }, [fetchWithRetry]);

  useEffect(() => {
    // Backoff-aware polling loop. Replace the naive 30s setInterval with
    // a setTimeout chain that doubles delay on consecutive failed loads
    // (network OR /api/team !ok) to keep the rate-limit cascade from
    // re-igniting itself. A successful fetch resets to BASE_INTERVAL.
    let cancelled = false;
    let nextTimer = null;
    const BASE_INTERVAL = 30_000;
    const MAX_INTERVAL = 300_000; // 5 min
    let consecutiveFailures = 0;

    const loop = async () => {
      if (cancelled) return;
      let success = false;
      try {
        await fetchData();
        // We reach here even on caught errors inside fetchData (it sets
        // its own error state). Decide success on whether we currently
        // have team data — that's the critical signal.
        success = true;
      } catch {
        success = false;
      }
      // Use the post-fetch React state hook isn't available here, so we
      // approximate by reading from localStorage: if team was successfully
      // refreshed in the last loop the cache will hold a fresh value.
      // Simpler: just trust fetchData not to throw — it logs but resolves.
      // Instead read /api/health for an authoritative pulse.
      try {
        const h = await fetch('/api/health', { cache: 'no-store' });
        if (!h.ok) success = false;
      } catch {
        success = false;
      }

      if (success) {
        consecutiveFailures = 0;
      } else {
        consecutiveFailures += 1;
      }
      const delay = Math.min(
        BASE_INTERVAL * Math.pow(2, consecutiveFailures),
        MAX_INTERVAL,
      );
      if (cancelled) return;
      nextTimer = setTimeout(loop, delay);
    };

    // Initial fire (also paced via the loop helper).
    loop();
    // After 10s, flip the "Loading..." subtitle to an offline fallback.
    const timeoutId = setTimeout(() => setLoadingTimedOut(true), 10000);
    return () => {
      cancelled = true;
      if (nextTimer) clearTimeout(nextTimer);
      clearTimeout(timeoutId);
    };
  }, [fetchData]);

  // Handle Spotify OAuth callback — SPA catches /spotify-callback via nginx try_files
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    if (code && window.location.pathname === '/spotify-callback') {
      import('./services/SpotifyService').then(({ handleCallback }) => {
        handleCallback(code).catch(console.error).finally(() => {
          window.history.replaceState({}, '', '/');
          setCurrentView('announcer');
        });
      });
    }
  }, []);

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
          if (body?.detail || body?.message) detail = body.detail || body.message;
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
      // 1. Try local sync first
      let res = await fetch('/api/run', { method: 'POST' }).catch(() => ({ ok: false }));
      
      // 2. Fallback to Modal cloud if local fails (e.g. dev environment vs cloud production)
      if (!res.ok) {
        console.log("Local sync unavailable, trying Modal cloud fallback...");
        res = await fetch('https://anchorgroupops--softball-strategy-sharks-manual-sync.modal.run', {
          method: 'POST'
        });
      }
      
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

          // Also check health timestamp for completion (skip if already cleared above)
          if (!syncPollRef.current) return;
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
              return;
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

  // All nav items for desktop — order: Live → Scout → SWOT → Roster → Lineups → Games → League → Practice → Announcer
  const navItems = [
    { id: 'scoreboard', label: 'Live', icon: <Radio size={18} /> },
    { id: 'scout', label: 'Scout', icon: <Target size={18} /> },
    { id: 'swot', label: 'SWOT', icon: <Activity size={18} /> },
    { id: 'roster', label: 'Roster', icon: <Users size={18} /> },
    { id: 'lineups', label: 'Lineups', icon: <ListOrdered size={18} /> },
    { id: 'games', label: 'Games', icon: <Calendar size={18} /> },
    { id: 'league', label: 'League', icon: <Trophy size={18} /> },
    { id: 'practice', label: 'Practice', icon: <Dumbbell size={18} /> },
    { id: 'announcer', label: 'Announcer', icon: <Mic size={18} /> },
  ];

  // Mobile: 4 primary bottom tabs + "More" overflow
  const primaryNavItems = [
    { id: 'scoreboard', label: 'Live', icon: <Radio size={22} /> },
    { id: 'announcer', label: 'Announcer', icon: <Mic size={22} /> },
    { id: 'practice', label: 'Practice', icon: <Dumbbell size={22} /> },
    { id: 'roster', label: 'Roster', icon: <Users size={22} /> },
  ];

  const overflowNavItems = [
    { id: 'scout', label: 'Scout', icon: <Activity size={20} /> },
    { id: 'swot', label: 'SWOT', icon: <Activity size={20} /> },
    { id: 'lineups', label: 'Lineups', icon: <ListOrdered size={20} /> },
    { id: 'games', label: 'Games', icon: <Calendar size={20} /> },
    { id: 'league', label: 'League', icon: <Trophy size={20} /> },
  ];

  const renderContent = () => {
    if (data.loading) return <div className="loader"></div>;

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
                  const labels = { scoreboard: 'Live', scout: 'Scout', swot: 'SWOT', lineups: 'Lineups', practice: 'Practice', roster: 'Roster', games: 'Games', league: 'League', announcer: 'Announcer' };
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
                title={item.label}
                aria-label={item.label}
              >
                {item.icon}
                <span className="nav-label">{item.label}</span>
              </button>
            ))}
          </div>
        </nav>
      )}

      <main id="main-content" className="animate-fade-in">
        {/* Desktop hero */}
        {!isMobile && (
          <div style={{ marginBottom: '2rem' }}>
            <h1 style={{ fontSize: 'clamp(1.6rem, 5.5vw, 2.5rem)', marginBottom: '0.4rem', lineHeight: 1.1 }}>
              {displayTeamName}
            </h1>
            <div className="hero-meta-row">
              <p style={{ color: 'var(--text-muted)', fontSize: '1.1rem' }}>
                {(() => {
                  if (data.team) {
                    const offlineSuffix = (data.error || data.isCached) ? '  \u26a0 offline' : '';
                    return `${data.team.league} \u2022 Last Updated: ${formatDateTime(data.team.last_updated)}${offlineSuffix}`;
                  }
                  if (loadingTimedOut || data.error) {
                    const ts = data.cachedAt ? formatDateTime(data.cachedAt) : 'unknown';
                    return `Offline \u2014 last updated ${ts}`;
                  }
                  return 'Loading...';
                })()}
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

        {data.error && (
          <div className="stale-banner" style={{ borderColor: 'rgba(179,74,57,0.4)', background: 'rgba(179,74,57,0.12)' }}>
            <AlertTriangle size={16} style={{ color: 'var(--danger)', flexShrink: 0 }} />
            <span style={{ color: 'var(--danger)' }}>Backend offline — live data unavailable.</span>
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
          <React.Suspense fallback={<div className="loader"></div>}>
            {renderContent()}
          </React.Suspense>
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
