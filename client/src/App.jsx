import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Users, Activity, ListOrdered, Calendar, Trophy, Dumbbell, Volume2 } from 'lucide-react';
import { formatDateTime } from './utils/formatDate';
import Roster from './components/Roster';
import Swot from './components/Swot';
import Lineup from './components/Lineup';
import Games from './components/Games';
import League from './components/League';
import Practice from './components/Practice';


function App() {
  const [currentView, setCurrentView] = useState('roster');
  const [voiceLoading, setVoiceLoading] = useState(false);
  const [voiceError, setVoiceError] = useState('');
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
    } catch (err) {
      console.error("Data fetch error", err);
      setData(prev => ({ ...prev, loading: false, error: err.message }));
    }
  }, []);

  useEffect(() => {
    fetchData(); // Initial fetch
    
    // Set up real-time polling every 30 seconds
    const intervalId = setInterval(fetchData, 30000);
    
    return () => clearInterval(intervalId);
  }, [fetchData]);

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

  const navItems = [
    { id: 'roster', label: 'Roster', icon: <Users size={18} /> },
    { id: 'swot', label: 'SWOT', icon: <Activity size={18} /> },
    { id: 'lineups', label: 'Lineups', icon: <ListOrdered size={18} /> },
    { id: 'games', label: 'Games', icon: <Calendar size={18} /> },
    { id: 'league', label: 'League', icon: <Trophy size={18} /> },
    { id: 'practice', label: 'Practice', icon: <Dumbbell size={18} /> }
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
      case 'roster': return (
        <Roster
          team={data.team}
          availability={data.availability}
          onAvailabilityChange={(newAvail) => setData(prev => ({ ...prev, availability: newAvail }))}
        />
      );
      case 'swot': return <Swot swotData={data.swot} roster={data.team?.roster} schedule={data.schedule} />;
      case 'lineups': return (
        <Lineup
          team={data.team}
          lineupsData={data.lineups}
          availability={data.availability}
          schedule={data.schedule}
          onAvailabilityChange={(newAvail) => setData(prev => ({ ...prev, availability: newAvail }))}
          onDataRefresh={fetchData}
          onRegenerate={(newLineups) => setData(prev => ({ ...prev, lineups: newLineups }))}
        />
      );
      case 'games': return <Games gamesData={data.games} schedule={data.schedule} />;
      case 'league': return <League />;
      case 'practice': return (
        <Practice
          team={data.team}
          schedule={data.schedule}
        />
      );
      default: return (
        <Roster
          team={data.team}
          availability={data.availability}
          onAvailabilityChange={(newAvail) => setData(prev => ({ ...prev, availability: newAvail }))}
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
      
      <main className="animate-fade-in">
        <div style={{ marginBottom: '2rem' }}>
          <h1 style={{ fontSize: 'clamp(1.6rem, 5.5vw, 2.5rem)', marginBottom: '0.5rem', lineHeight: 1.1 }}>{displayTeamName}</h1>
          <div className="hero-meta-row">
            <p style={{ color: 'var(--text-muted)', fontSize: '1.1rem' }}>
              {data.team ? `${data.team.league} • Last Updated: ${formatDateTime(data.team.last_updated)}` : 'Loading...'}
            </p>
            <button
              className="voice-btn"
              onClick={handleVoiceUpdate}
              disabled={voiceLoading}
              title="Play latest audio overview"
            >
              <Volume2 size={16} />
              {voiceLoading ? 'Preparing...' : 'Voice Update'}
            </button>
          </div>
          {voiceError && <p className="voice-error">{voiceError}</p>}
        </div>
        
        {renderContent()}
      </main>
    </>
  );
}

export default App;
