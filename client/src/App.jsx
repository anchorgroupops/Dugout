import React, { useState, useEffect } from 'react';
import { Users, Activity, ListOrdered, Calendar } from 'lucide-react';
import Roster from './components/Roster';
import Swot from './components/Swot';
import Lineup from './components/Lineup';

// Placeholder for Schedule
const Schedule = () => (
  <div className="glass-panel" style={{ padding: '2rem', textAlign: 'center' }}>
    <h2 style={{ marginBottom: '1rem', color: 'var(--primary-color)' }}>Upcoming Schedule</h2>
    <p style={{ color: 'var(--text-muted)' }}>Schedule and Box Score integrations coming soon...</p>
  </div>
);

function App() {
  const [currentView, setCurrentView] = useState('roster');
  const [data, setData] = useState({
    team: null,
    swot: null,
    lineups: null,
    loading: true,
    error: null
  });

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [teamRes, swotRes, lineupsRes] = await Promise.all([
          fetch('/data/sharks/team.json'),
          fetch('/data/sharks/swot_analysis.json'),
          fetch('/data/sharks/lineups.json')
        ]);
        
        if (!teamRes.ok) throw new Error('Failed to load team data');
        
        const team = await teamRes.json();
        const swot = swotRes.ok ? await swotRes.json() : null;
        const lineups = lineupsRes.ok ? await lineupsRes.json() : null;
        
        setData({ team, swot, lineups, loading: false, error: null });
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
    { id: 'swot', label: 'SWOT Analysis', icon: <Activity size={18} /> },
    { id: 'lineups', label: 'Lineups', icon: <ListOrdered size={18} /> },
    { id: 'schedule', label: 'Schedule', icon: <Calendar size={18} /> }
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
      case 'roster': return <Roster team={data.team} />;
      case 'swot': return <Swot swotData={data.swot} roster={data.team?.roster} />;
      case 'lineups': return <Lineup lineupsData={data.lineups} />;
      case 'schedule': return <Schedule />;
      default: return <Roster team={data.team} />;
    }
  };

  return (
    <>
      <nav className="navbar">
        <div className="brand">
          <Activity size={24} color="var(--primary-color)" />
          Softball Strategy
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
            {data.team ? `${data.team.league} • Last Updated: ${new Date(data.team.last_updated).toLocaleString()}` : 'Loading...'}
          </p>
        </div>
        
        {renderContent()}
      </main>
    </>
  );
}

export default App;
