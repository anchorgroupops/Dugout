import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Settings2, UserPlus, Check, X, Search, ChevronDown } from 'lucide-react';

const ToggleRow = ({ player, available, onToggle, updating }) => {
  const name = `${player.first} ${player.last}`.trim();
  const isSub = !player.core;
  const b = player.batting || {};
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '0.75rem',
      padding: '0.75rem 1rem', borderRadius: '8px',
      background: available
        ? (isSub ? 'rgba(255, 165, 0, 0.04)' : 'rgba(0,0,0,0.2)')
        : 'rgba(200,50,50,0.08)',
      borderLeft: `3px solid ${!available ? 'var(--danger)' : isSub ? 'rgba(255,165,0,0.5)' : 'var(--primary-color)'}`,
      opacity: available ? 1 : 0.65,
      transition: 'all 0.2s ease'
    }}>
      <div style={{
        width: '36px', height: '36px', borderRadius: '50%', flexShrink: 0,
        background: available
          ? (isSub ? 'linear-gradient(135deg, #ffa500, #cc8400)' : 'linear-gradient(135deg, var(--primary-color), var(--secondary-color))')
          : '#444',
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
          {isSub && <span style={{ color: '#ffa500', marginLeft: '0.4rem', fontWeight: '600' }}>SUB</span>}
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

/* ─── Searchable Player Combobox ─── */
const PlayerCombobox = ({ players, onSelect, placeholder }) => {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const filtered = useMemo(() => {
    if (!query.trim()) return players.slice(0, 50);
    const q = query.toLowerCase();
    return players.filter(p => {
      const full = `${p.first} ${p.last} ${p.team_name} #${p.number}`.toLowerCase();
      return full.includes(q);
    }).slice(0, 50);
  }, [players, query]);

  return (
    <div ref={ref} style={{ position: 'relative', width: '100%' }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: '0.5rem',
        padding: '0.5rem 0.75rem', borderRadius: '8px',
        border: open ? '1px solid var(--primary-color)' : '1px solid var(--surface-border)',
        background: 'rgba(0,0,0,0.3)', transition: 'border-color 0.2s ease'
      }}>
        <Search size={14} color="var(--text-muted)" />
        <input
          type="text"
          value={query}
          onChange={e => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          placeholder={placeholder || 'Search PCLL players...'}
          style={{
            flex: 1, background: 'transparent', border: 'none', outline: 'none',
            color: 'var(--text-main)', fontSize: '0.9rem', fontFamily: 'inherit'
          }}
        />
        <ChevronDown size={14} color="var(--text-muted)" style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }} />
      </div>
      {open && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, right: 0, marginTop: '4px',
          background: '#1a2333', border: '1px solid var(--surface-border)',
          borderRadius: '8px', maxHeight: '240px', overflowY: 'auto', zIndex: 50,
          boxShadow: '0 8px 24px rgba(0,0,0,0.5)'
        }}>
          {filtered.length === 0 ? (
            <div style={{ padding: '0.75rem 1rem', color: 'var(--text-muted)', fontSize: '0.85rem', fontStyle: 'italic' }}>
              {players.length === 0 ? 'No league data scraped yet. Use manual entry below.' : 'No players match your search.'}
            </div>
          ) : (
            filtered.map((p, i) => (
              <div
                key={`${p.gc_team_id}-${p.number}-${p.last}-${i}`}
                onClick={() => { onSelect(p); setQuery(''); setOpen(false); }}
                style={{
                  padding: '0.6rem 1rem', cursor: 'pointer',
                  borderBottom: i < filtered.length - 1 ? '1px solid rgba(255,255,255,0.05)' : 'none',
                  transition: 'background 0.15s ease'
                }}
                onMouseEnter={e => e.currentTarget.style.background = 'rgba(0,210,255,0.08)'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              >
                <div style={{ fontWeight: '600', fontSize: '0.9rem' }}>
                  #{p.number} {p.first} {p.last}
                </div>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                  {p.team_name}
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
};

const RosterManager = ({
  team,
  availability,
  onAvailabilityChange,
  onRosterMutated,
  title = 'Manage Roster',
  showTitle = true
}) => {
  const [updatingPlayer, setUpdatingPlayer] = useState(null);
  const [showBorrowForm, setShowBorrowForm] = useState(false);
  const [borrowForm, setBorrowForm] = useState({ first: '', last: '', number: '', gc_team_id: '' });
  const [borrowStatus, setBorrowStatus] = useState(null);
  const [leaguePlayers, setLeaguePlayers] = useState([]);
  const [manualMode, setManualMode] = useState(false);

  useEffect(() => {
    fetch('/api/league-players')
      .then(r => r.ok ? r.json() : [])
      .then(setLeaguePlayers)
      .catch(() => setLeaguePlayers([]));
  }, []);

  if (!team || !team.roster) return <div className="loader"></div>;

  const roster = [...team.roster].sort((a, b) => (a.first || '').localeCompare(b.first || ''));

  const isAvailable = (player) => {
    if (!availability) return player.core !== false;
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
      if (res.ok) {
        onAvailabilityChange(newAvailability);
        if (onRosterMutated) await onRosterMutated();
      }
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
      if (res.ok) {
        onAvailabilityChange(newAvailability);
        if (onRosterMutated) await onRosterMutated();
      }
    } catch (e) {
      console.error('Set all failed', e);
    }
  };

  const handleSharksOnly = async () => {
    const newAvailability = {};
    for (const p of roster) {
      const name = `${p.first} ${p.last}`.trim();
      newAvailability[name] = p.core !== false;
    }
    try {
      const res = await fetch('/api/availability', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newAvailability)
      });
      if (res.ok) {
        onAvailabilityChange(newAvailability);
        if (onRosterMutated) await onRosterMutated();
      }
    } catch (e) {
      console.error('Sharks only failed', e);
    }
  };

  const handlePlayerSelect = (player) => {
    setBorrowForm({
      first: player.first,
      last: player.last,
      number: String(player.number || ''),
      gc_team_id: player.gc_team_id || ''
    });
    setShowBorrowForm(true);
    setManualMode(false);
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
        if (onRosterMutated) await onRosterMutated();
        setTimeout(() => {
          setShowBorrowForm(false);
          setBorrowStatus(null);
          setManualMode(false);
        }, 2000);
      } else {
        setBorrowStatus('error');
      }
    } catch {
      setBorrowStatus('error');
    }
  };

  const activeCount = roster.filter(p => isAvailable(p)).length;
  const coreRoster = roster.filter(p => p.core !== false);
  const subRoster = roster.filter(p => !p.core);

  return (
    <div>
      {showTitle && (
        <h2 style={{ marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Settings2 size={24} color="var(--primary-color)" /> {title}
          <span style={{ fontSize: '0.9rem', color: 'var(--text-muted)', fontWeight: 'normal', marginLeft: '0.5rem' }}>
            ({activeCount} / {roster.length} available)
          </span>
        </h2>
      )}

      {/* Availability section */}
      <div className="glass-panel" style={{ padding: '1.5rem', marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <h3 style={{ margin: 0, color: 'var(--primary-color)', fontSize: '1rem' }}>Game-Day Availability</h3>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              onClick={handleSharksOnly}
              style={{ padding: '0.3rem 0.75rem', borderRadius: '6px', border: '1px solid rgba(0,210,255,0.3)', background: 'rgba(0,210,255,0.1)', color: 'var(--primary-color)', cursor: 'pointer', fontSize: '0.8rem', fontWeight: '600' }}
            >
              Sharks Only
            </button>
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

        {/* Core players */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {coreRoster.map(player => (
            <ToggleRow
              key={`${player.number}-${player.last}`}
              player={player}
              available={isAvailable(player)}
              onToggle={handleToggle}
              updating={updatingPlayer === `${player.first} ${player.last}`.trim()}
            />
          ))}
        </div>

        {/* Sub players */}
        {(subRoster.filter(p => isAvailable(p)).length > 0 || subRoster.filter(p => !isAvailable(p)).length > 0) && (
          <div style={{ marginTop: '1rem', paddingTop: '1rem', borderTop: '1px solid rgba(255,165,0,0.15)' }}>
            
            {/* Active Subs */}
            {subRoster.filter(p => isAvailable(p)).length > 0 && (
              <div style={{ marginBottom: subRoster.filter(p => !isAvailable(p)).length > 0 ? '1rem' : 0 }}>
                <div style={{ fontSize: '0.7rem', color: '#ffa500', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '0.5rem', fontWeight: '700' }}>
                  Active Borrowed Players
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                  {subRoster.filter(p => isAvailable(p)).map(player => (
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
            )}

            {/* Inactive / Recent Subs */}
            {subRoster.filter(p => !isAvailable(p)).length > 0 && (
              <div style={{ paddingTop: subRoster.filter(p => isAvailable(p)).length > 0 ? '1rem' : 0, borderTop: subRoster.filter(p => isAvailable(p)).length > 0 ? '1px dashed rgba(255,255,255,0.1)' : 'none' }}>
                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '0.5rem', fontWeight: '700' }}>
                  Recent / Inactive Subs
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                  {subRoster.filter(p => !isAvailable(p)).map(player => (
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
            )}

          </div>
        )}
      </div>

      {/* Add borrowed player section */}
      <div className="glass-panel" style={{ padding: '1.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
          <h3 style={{ margin: 0, color: 'var(--primary-color)', fontSize: '1rem' }}>Add Borrowed Player</h3>
          <button
            onClick={() => { setShowBorrowForm(!showBorrowForm); setBorrowStatus(null); setManualMode(false); }}
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
          Search PCLL league players or manually add a borrowed player. Stats auto-scrape if their team has been scraped.
        </p>

        {showBorrowForm && (
          <div>
            {/* Search dropdown */}
            {!manualMode && (
              <div style={{ marginBottom: '1rem' }}>
                <PlayerCombobox
                  players={leaguePlayers}
                  onSelect={handlePlayerSelect}
                  placeholder="Search by name, team, or jersey #..."
                />
                <button
                  onClick={() => setManualMode(true)}
                  style={{
                    marginTop: '0.5rem', background: 'none', border: 'none',
                    color: 'var(--text-muted)', fontSize: '0.8rem', cursor: 'pointer',
                    textDecoration: 'underline', padding: 0
                  }}
                >
                  Or enter player details manually
                </button>
              </div>
            )}

            {/* Form (shown when player selected from dropdown or manual mode) */}
            {(manualMode || borrowForm.first) && (
              <form onSubmit={handleBorrowSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                {borrowForm.first && !manualMode && (
                  <div style={{
                    padding: '0.6rem 0.75rem', borderRadius: '6px',
                    background: 'rgba(0,210,255,0.06)', border: '1px solid rgba(0,210,255,0.15)',
                    fontSize: '0.85rem', color: 'var(--primary-color)', fontWeight: '600'
                  }}>
                    Selected: #{borrowForm.number} {borrowForm.first} {borrowForm.last}
                    <button
                      type="button"
                      onClick={() => setBorrowForm({ first: '', last: '', number: '', gc_team_id: '' })}
                      style={{ marginLeft: '0.75rem', background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.8rem' }}
                    >
                      (clear)
                    </button>
                  </div>
                )}

                {manualMode && (
                  <>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                      <div>
                        <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: '0.3rem' }}>First Name *</label>
                        <input
                          type="text" value={borrowForm.first}
                          onChange={e => setBorrowForm(p => ({ ...p, first: e.target.value }))}
                          placeholder="e.g. Alexa" required
                          style={{ width: '100%', padding: '0.5rem 0.75rem', borderRadius: '6px', border: '1px solid var(--surface-border)', background: 'rgba(0,0,0,0.3)', color: 'var(--text-main)', fontSize: '0.9rem', boxSizing: 'border-box' }}
                        />
                      </div>
                      <div>
                        <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: '0.3rem' }}>Last Name</label>
                        <input
                          type="text" value={borrowForm.last}
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
                          type="text" value={borrowForm.number}
                          onChange={e => setBorrowForm(p => ({ ...p, number: e.target.value }))}
                          placeholder="e.g. 42"
                          style={{ width: '100%', padding: '0.5rem 0.75rem', borderRadius: '6px', border: '1px solid var(--surface-border)', background: 'rgba(0,0,0,0.3)', color: 'var(--text-main)', fontSize: '0.9rem', boxSizing: 'border-box' }}
                        />
                      </div>
                      <div>
                        <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: '0.3rem' }}>GC Team ID (optional)</label>
                        <input
                          type="text" value={borrowForm.gc_team_id}
                          onChange={e => setBorrowForm(p => ({ ...p, gc_team_id: e.target.value }))}
                          placeholder="e.g. AbCdEfGhIjKl"
                          style={{ width: '100%', padding: '0.5rem 0.75rem', borderRadius: '6px', border: '1px solid var(--surface-border)', background: 'rgba(0,0,0,0.3)', color: 'var(--text-main)', fontSize: '0.9rem', boxSizing: 'border-box' }}
                        />
                      </div>
                    </div>
                  </>
                )}

                <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
                  <button
                    type="submit"
                    disabled={borrowStatus === 'adding' || !borrowForm.first.trim()}
                    style={{
                      padding: '0.5rem 1.5rem', borderRadius: '8px', border: 'none',
                      background: 'var(--primary-color)', color: '#fff',
                      cursor: (borrowStatus === 'adding' || !borrowForm.first.trim()) ? 'not-allowed' : 'pointer',
                      fontWeight: '600', fontSize: '0.9rem',
                      opacity: (borrowStatus === 'adding' || !borrowForm.first.trim()) ? 0.6 : 1
                    }}
                  >
                    {borrowStatus === 'adding' ? 'Adding...' : 'Add Player'}
                  </button>
                  {borrowStatus === 'success' && (
                    <span style={{ color: 'var(--success)', fontSize: '0.85rem', fontWeight: '600' }}>
                      Player added! Stats scraping in background.
                    </span>
                  )}
                  {borrowStatus === 'error' && (
                    <span style={{ color: 'var(--danger)', fontSize: '0.85rem' }}>Failed to add player.</span>
                  )}
                </div>
              </form>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default RosterManager;
