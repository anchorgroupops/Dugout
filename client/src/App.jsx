import React, { useState, useEffect } from 'react';
import { Users, Activity, ListOrdered, Settings2, Calendar, Trophy } from 'lucide-react';
import { formatDateTime } from './utils/formatDate';
import Roster from './components/Roster';
import Swot from './components/Swot';
import Lineup from './components/Lineup';
import Games from './components/Games';
import RosterManager from './components/RosterManager';
import League from './components/League';


function App() {
  const [currentView, setCurrentView] = useState('roster');
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

  useEffect(() => {
    const fetchData = async () => {
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
    };
    fetchData(); // Initial fetch
    
    // Set up real-time polling every 30 seconds
    const intervalId = setInterval(fetchData, 30000);
    
    return () => clearInterval(intervalId);
  }, []);

  const navItems = [
    { id: 'roster', label: 'Roster', icon: <Users size={18} /> },
    { id: 'swot', label: 'SWOT', icon: <Activity size={18} /> },
    { id: 'lineups', label: 'Lineups', icon: <ListOrdered size={18} /> },
    { id: 'games', label: 'Games', icon: <Calendar size={18} /> },
    { id: 'league', label: 'League', icon: <Trophy size={18} /> },
    { id: 'manage', label: 'Manage', icon: <Settings2 size={18} /> }
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
          lineupsData={data.lineups}
          availability={data.availability}
          schedule={data.schedule}
          onRegenerate={(newLineups) => setData(prev => ({ ...prev, lineups: newLineups }))}
        />
      );
      case 'games': return <Games gamesData={data.games} schedule={data.schedule} />;
      case 'league': return <League />;
      case 'manage': return (
        <RosterManager
          team={data.team}
          availability={data.availability}
          onAvailabilityChange={(newAvail) => setData(prev => ({ ...prev, availability: newAvail }))}
          onTeamChange={(newTeam) => setData(prev => ({ ...prev, team: newTeam }))}
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
          <h1 style={{ fontSize: '2.5rem', marginBottom: '0.5rem' }}>{data.team ? data.team.team_name : 'The Sharks'}</h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '1.1rem' }}>
            {data.team ? `${data.team.league} • Last Updated: ${formatDateTime(data.team.last_updated)}` : 'Loading...'}
          </p>
        </div>
        
        {renderContent()}
      </main>
    </>
  );
}

export default App;
