import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Users, Activity, RefreshCw, ListOrdered, Calendar, Trophy, Dumbbell, Volume2, Target, AlertTriangle, MoreHorizontal } from 'lucide-react';
import { formatDateTime } from './utils/formatDate';
import Roster from './components/Roster';
import Swot from './components/Swot';
import Lineup from './components/Lineup';
import Games from './components/Games';
import League from './components/League';
import Practice from './components/Practice';
import Scouting from './components/Scouting';


function App() {
  const [currentView, setCurrentView] = useState('scout');
  const [isMobile, setIsMobile] = useState(
    typeof window !== 'undefined' ? window.innerWidth <= 768 : false
  );
  const [voiceLoading, setVoiceLoading] = useState(false);
  const [voiceError, setVoiceError] = useState('');
  const [staleSources, setStaleSources] = useState([]);
  const [syncStage, setSyncStage] = useState('idle');
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

  const fetchData = useCallback(async () => {
    try {
      const [teamRes, swotRes, lineupsRes, availRes, gamesRes, scheduleRes] = await Promise.all([
        fetch('/api/team'),
        fetch('/data/sharks/swot_analysis.json'),
        fetch('/data/sharks/lineups.json'),
        fetch('/api/availability'),
        fetch('/api/games'),
        fetch('/api/schedule')
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
        }
      } catch { /* ignore health/sync check failures */ }
    } catch (err) {
      console.error("Data fetch error", err);
      setData(prev => ({ ...prev, loading: false, error: err.message }));
    }
  }, []);

  useEffect(() => {
    fetchData();
    const intervalId = setInterval(fetchData, 30000);
    return () => clearInterval(intervalId);
  }, [fetchData]);

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth <= 768);
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

  const handleManualSync = useCallback(async () => {
    if (!window.confirm("Trigger full end-to-end data refresh? (Scrape -> Analysis -> RAG)")) return;
    setSyncLoading(true);
    try {
      const res = await fetch('https://anchorgroupops--softball-strategy-sharks-manual-sync.modal.run', {
        method: 'POST'
      });
      if (!res.ok) throw new Error('Sync trigger failed');
      alert("Manual sync triggered successfully! Results will be available in ~5-10 minutes.");
    } catch (err) {
      console.error('Sync failed', err);
      alert("Sync failed: " + err.message);
    } finally {
      setSyncLoading(false);
    }
  }, []);

  // All nav items for desktop
  const navItems = [
    { id: 'scout', label: 'Scout', icon: <Target size={18} /> },
    { id: 'swot', label: 'SWOT', icon: <Activity size={18} /> },
    { id: 'roster', label: 'Roster', icon: <Users size={18} /> },
    { id: 'lineups', label: 'Lineups', icon: <ListOrdered size={18} /> },
    { id: 'games', label: 'Games', icon: <Calendar size={18} /> },
    { id: 'league', label: 'League', icon: <Trophy size={18} /> },
    { id: 'practice', label: 'Practice', icon: <Dumbbell size={18} /> }
  ];

  // Mobile: 4 primary bottom tabs + "More" overflow
  // Elevated: SWOT + Practice to primary (most used on the field)
  // Demoted: Roster + Games to overflow (reference tabs)
  const primaryNavItems = [
    { id: 'scout', label: 'Scout', icon: <Target size={22} /> },
    { id: 'swot', label: 'SWOT', icon: <Activity size={22} /> },
    { id: 'lineups', label: 'Lineups', icon: <ListOrdered size={22} /> },
    { id: 'practice', label: 'Practice', icon: <Dumbbell size={22} /> },
  ];

  const overflowNavItems = [
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
      case 'scout': return <Scouting isMobile={isMobile} />;
      case 'roster': return (
        <Roster
          team={data.team}
          availability={data.availability}
          isMobile={isMobile}
        />
      );
      case 'swot': return <Swot swotData={data.swot} roster={data.team?.roster} schedule={data.schedule} isMobile={isMobile} />;
      case 'lineups': return (
        <Lineup
          team={data.team}
          lineupsData={data.lineups}
          availability={data.availability}
          schedule={data.schedule}
          isMobile={isMobile}
          onAvailabilityChange={(newAvail) => setData(prev => ({ ...prev, availability: newAvail }))}
          onDataRefresh={fetchData}
          onRegenerate={(newLineups) => setData(prev => ({ ...prev, lineups: newLineups }))}
        />
      );
      case 'games': return <Games gamesData={data.games} schedule={data.schedule} isMobile={isMobile} />;
      case 'league': return <League isMobile={isMobile} />;
      case 'practice': return (
        <Practice
          team={data.team}
          schedule={data.schedule}
          isMobile={isMobile}
        />
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
    <>
      {/* ─── Top Navigation ─── */}
      {isMobile ? (
        <nav className="navbar navbar-mobile">
          <div className="mobile-header">
            <div className="mobile-header-left">
              <img src="/sharks-logo-round.png" alt="Sharks" className="logo-avatar" />
              <span className="brand" style={{ fontSize: '1.125rem' }}>Sharks</span>
              <span
                className={`sync-status-dot ${staleSources.length > 0 ? 'stale' : 'fresh'}`}
                title={staleSources.length > 0 ? `Stale: ${staleSources.join(', ')}` : 'Data is fresh'}
              />
              {syncStage !== 'idle' && (
                <span className="sync-stage-tag">{syncStage}</span>
              )}
            </div>
            <div className="mobile-header-actions">
              <button
                className="mobile-action-btn"
                onClick={handleManualSync}
                disabled={syncLoading}
                title="Manual Sync"
              >
                <RefreshCw size={20} className={syncLoading ? 'sync-spin' : ''} />
              </button>
              <button
                className="mobile-action-btn"
                onClick={handleVoiceUpdate}
                disabled={voiceLoading}
                title="Voice Update"
              >
                <Volume2 size={20} />
              </button>
            </div>
          </div>
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
              <button className={`sync-btn ${syncLoading ? 'sync-btn--active' : ''}`} onClick={handleManualSync} disabled={syncLoading} title="Trigger manual data refresh">
                <RefreshCw size={16} className={syncLoading ? 'sync-spin' : ''} />
                {syncLoading ? 'Syncing...' : syncStage !== 'idle' ? `Sync: ${syncStage}` : 'Manual Sync'}
              </button>
              <button className="voice-btn" onClick={handleVoiceUpdate} disabled={voiceLoading} title="Play latest audio overview">
                <Volume2 size={16} />
                {voiceLoading ? 'Preparing...' : 'Voice Update'}
              </button>
            </div>
          </div>
        )}

        {voiceError && <p className="voice-error">{voiceError}</p>}

        {staleSources.length > 0 && (
          <div className="stale-banner">
            <AlertTriangle size={16} />
            <span>Data may be stale: {staleSources.join(', ')}</span>
          </div>
        )}

        {renderContent()}
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
    </>
  );
}

export default App;
