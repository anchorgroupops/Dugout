import React, { useState } from 'react';
import { Settings2, UserPlus, Check, X } from 'lucide-react';

const ToggleRow = ({ player, available, onToggle, updating }) => {
  const name = `${player.first} ${player.last}`.trim();
  const b = player.batting || {};
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '0.75rem',
      padding: '0.75rem 1rem', borderRadius: '8px',
      background: available ? 'rgba(0,0,0,0.2)' : 'rgba(200,50,50,0.08)',
      borderLeft: `3px solid ${available ? 'var(--primary-color)' : 'var(--danger)'}`,
      opacity: available ? 1 : 0.65,
      transition: 'all 0.2s ease'
    }}>
      <div style={{
        width: '36px', height: '36px', borderRadius: '50%', flexShrink: 0,
        background: available ? 'linear-gradient(135deg, var(--primary-color), var(--secondary-color))' : '#444',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: '0.85rem', fontWeight: 'bold', color: '#fff', transition: 'all 0.2s ease'
      }}>
        {player.number}
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: '600', fontSize: '0.95rem' }}>{name}</div>
        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          {b.gp != null ? `${b.gp} GP` : ''}
          {b.avg != null ? ` · .${String(Math.round((b.avg || 0) * 1000)).padStart(3, '0')} AVG` : ''}
          {!player.core && <span style={{ color: '#ffa500', marginLeft: '0.4rem' }}>SUB</span>}
        </div>
      </div>
      <button
        onClick={() => onToggle(player, !available)}
        disabled={updating}
        style={{
          display: 'flex', alignItems: 'center', gap: '0.3rem',
          padding: '0.3rem 0.8rem', borderRadius: '6px', border: 'none',
          background: available ? 'var(--primary-glow)' : 'rgba(200,50,50,0.15)',
          color: available ? 'var(--success)' : 'var(--danger)',
          cursor: updating ? 'not-allowed' : 'pointer',
          fontWeight: '600', fontSize: '0.75rem',
          opacity: updating ? 0.5 : 1, transition: 'all 0.2s ease'
        }}
      >
        {updating ? '...' : available ? <><Check size={12} /> IN</> : <><X size={12} /> OUT</>}
      </button>
    </div>
  );
};

const RosterManager = ({ team, availability, onAvailabilityChange, onTeamChange }) => {
  const [updatingPlayer, setUpdatingPlayer] = useState(null);
  const [showBorrowForm, setShowBorrowForm] = useState(false);
  const [borrowForm, setBorrowForm] = useState({ first: '', last: '', number: '', gc_team_id: '' });
  const [borrowStatus, setBorrowStatus] = useState(null); // null | 'adding' | 'success' | 'error'

  if (!team || !team.roster) return <div className="loader"></div>;

  const roster = [...team.roster].sort((a, b) => (a.first || '').localeCompare(b.first || ''));

  const isAvailable = (player) => {
    if (!availability) return true;
    const name = `${player.first} ${player.last}`.trim();
    return availability[name] !== false;
  };

  const handleToggle = async (player, newStatus) => {
    const name = `${player.first} ${player.last}`.trim();
    const newAvailability = { ...availability, [name]: newStatus };
    setUpdatingPlayer(name);
    try {
      const res = await fetch('/api/availability', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newAvailability)
      });
      if (res.ok) onAvailabilityChange(newAvailability);
    } catch (e) {
      console.error('Toggle failed', e);
    } finally {
      setUpdatingPlayer(null);
    }
  };

  const handleSetAll = async (status) => {
    const newAvailability = {};
    for (const p of roster) {
      const name = `${p.first} ${p.last}`.trim();
      newAvailability[name] = status;
    }
    try {
      const res = await fetch('/api/availability', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newAvailability)
      });
      if (res.ok) onAvailabilityChange(newAvailability);
    } catch (e) {
      console.error('Set all failed', e);
    }
  };

  const handleBorrowSubmit = async (e) => {
    e.preventDefault();
    if (!borrowForm.first.trim()) return;
    setBorrowStatus('adding');
    try {
      const res = await fetch('/api/borrowed-player', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(borrowForm)
      });
      if (res.ok) {
        setBorrowStatus('success');
        setBorrowForm({ first: '', last: '', number: '', gc_team_id: '' });
        setTimeout(() => {
          setShowBorrowForm(false);
          setBorrowStatus(null);
        }, 2000);
      } else {
        setBorrowStatus('error');
      }
    } catch (e) {
      setBorrowStatus('error');
    }
  };

  const activeCount = roster.filter(p => isAvailable(p)).length;

  return (
    <div>
      <h2 style={{ marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <Settings2 size={24} color="var(--primary-color)" /> Manage Roster
        <span style={{ fontSize: '0.9rem', color: 'var(--text-muted)', fontWeight: 'normal', marginLeft: '0.5rem' }}>
          ({activeCount} / {roster.length} available)
        </span>
      </h2>

      {/* Availability section */}
      <div className="glass-panel" style={{ padding: '1.5rem', marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <h3 style={{ margin: 0, color: 'var(--primary-color)', fontSize: '1rem' }}>Game-Day Availability</h3>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              onClick={() => handleSetAll(true)}
              style={{ padding: '0.3rem 0.75rem', borderRadius: '6px', border: '1px solid rgba(35,134,54,0.3)', background: 'rgba(35,134,54,0.1)', color: 'var(--success)', cursor: 'pointer', fontSize: '0.8rem', fontWeight: '600' }}
            >
              All In
            </button>
            <button
              onClick={() => handleSetAll(false)}
              style={{ padding: '0.3rem 0.75rem', borderRadius: '6px', border: '1px solid rgba(200,50,50,0.3)', background: 'rgba(200,50,50,0.1)', color: 'var(--danger)', cursor: 'pointer', fontSize: '0.8rem', fontWeight: '600' }}
            >
              All Out
            </button>
          </div>
        </div>
        <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: '1rem' }}>
          Toggle players in/out for the next game. Lineups and SWOT will regenerate automatically.
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {roster.map(player => (
            <ToggleRow
              key={`${player.number}-${player.last}`}
              player={player}
              available={isAvailable(player)}
              onToggle={handleToggle}
              updating={updatingPlayer === `${player.first} ${player.last}`.trim()}
            />
          ))}
        </div>
      </div>

      {/* Borrowed player section */}
      <div className="glass-panel" style={{ padding: '1.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <h3 style={{ margin: 0, color: 'var(--primary-color)', fontSize: '1rem' }}>Add Borrowed Player</h3>
          <button
            onClick={() => { setShowBorrowForm(!showBorrowForm); setBorrowStatus(null); }}
            style={{
              display: 'flex', alignItems: 'center', gap: '0.4rem',
              padding: '0.4rem 0.9rem', borderRadius: '8px',
              border: '1px solid rgba(100,200,100,0.3)',
              background: showBorrowForm ? 'rgba(200,50,50,0.1)' : 'var(--primary-glow)',
              color: showBorrowForm ? 'var(--danger)' : 'var(--primary-color)',
              cursor: 'pointer', fontWeight: '600', fontSize: '0.85rem'
            }}
          >
            {showBorrowForm ? <><X size={14} /> Cancel</> : <><UserPlus size={14} /> Add Player</>}
          </button>
        </div>

        <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: showBorrowForm ? '1rem' : 0 }}>
          Borrow a player from another team. If you provide their GC Team ID, their stats will be scraped automatically.
        </p>

        {showBorrowForm && (
          <form onSubmit={handleBorrowSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
              <div>
                <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: '0.3rem' }}>First Name *</label>
                <input
                  type="text"
                  value={borrowForm.first}
                  onChange={e => setBorrowForm(p => ({ ...p, first: e.target.value }))}
                  placeholder="e.g. Alexa"
                  required
                  style={{ width: '100%', padding: '0.5rem 0.75rem', borderRadius: '6px', border: '1px solid var(--surface-border)', background: 'rgba(0,0,0,0.3)', color: 'var(--text-main)', fontSize: '0.9rem', boxSizing: 'border-box' }}
                />
              </div>
              <div>
                <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: '0.3rem' }}>Last Name</label>
                <input
                  type="text"
                  value={borrowForm.last}
                  onChange={e => setBorrowForm(p => ({ ...p, last: e.target.value }))}
                  placeholder="e.g. Smith"
                  style={{ width: '100%', padding: '0.5rem 0.75rem', borderRadius: '6px', border: '1px solid var(--surface-border)', background: 'rgba(0,0,0,0.3)', color: 'var(--text-main)', fontSize: '0.9rem', boxSizing: 'border-box' }}
                />
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '0.75rem' }}>
              <div>
                <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: '0.3rem' }}>Jersey #</label>
                <input
                  type="text"
                  value={borrowForm.number}
                  onChange={e => setBorrowForm(p => ({ ...p, number: e.target.value }))}
                  placeholder="e.g. 42"
                  style={{ width: '100%', padding: '0.5rem 0.75rem', borderRadius: '6px', border: '1px solid var(--surface-border)', background: 'rgba(0,0,0,0.3)', color: 'var(--text-main)', fontSize: '0.9rem', boxSizing: 'border-box' }}
                />
              </div>
              <div>
                <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: '0.3rem' }}>GC Team ID (optional, for auto-scrape)</label>
                <input
                  type="text"
                  value={borrowForm.gc_team_id}
                  onChange={e => setBorrowForm(p => ({ ...p, gc_team_id: e.target.value }))}
                  placeholder="e.g. AbCdEfGhIjKl"
                  style={{ width: '100%', padding: '0.5rem 0.75rem', borderRadius: '6px', border: '1px solid var(--surface-border)', background: 'rgba(0,0,0,0.3)', color: 'var(--text-main)', fontSize: '0.9rem', boxSizing: 'border-box' }}
                />
              </div>
            </div>
            <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
              <button
                type="submit"
                disabled={borrowStatus === 'adding'}
                style={{
                  padding: '0.5rem 1.5rem', borderRadius: '8px', border: 'none',
                  background: 'var(--primary-color)', color: '#fff',
                  cursor: borrowStatus === 'adding' ? 'not-allowed' : 'pointer',
                  fontWeight: '600', fontSize: '0.9rem', opacity: borrowStatus === 'adding' ? 0.6 : 1
                }}
              >
                {borrowStatus === 'adding' ? 'Adding...' : 'Add Player'}
              </button>
              {borrowStatus === 'success' && (
                <span style={{ color: 'var(--success)', fontSize: '0.85rem', fontWeight: '600' }}>
                  Player added! Stats scraping in background if GC ID provided.
                </span>
              )}
              {borrowStatus === 'error' && (
                <span style={{ color: 'var(--danger)', fontSize: '0.85rem' }}>Failed to add player.</span>
              )}
            </div>
          </form>
        )}

        {/* Show existing borrowed players */}
        {roster.filter(p => !p.core).length > 0 && (
          <div style={{ marginTop: '1rem', borderTop: '1px solid var(--surface-border)', paddingTop: '1rem' }}>
            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '0.5rem' }}>
              Current Borrowed Players
            </div>
            {roster.filter(p => !p.core).map(p => (
              <div key={`${p.number}-${p.last}`} style={{ fontSize: '0.85rem', color: 'var(--text-muted)', padding: '0.25rem 0' }}>
                #{p.number} {p.first} {p.last}
                {p.teams?.length > 0 && <span style={{ color: 'rgba(255,255,255,0.3)', marginLeft: '0.5rem' }}>({p.teams.join(', ')})</span>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default RosterManager;
