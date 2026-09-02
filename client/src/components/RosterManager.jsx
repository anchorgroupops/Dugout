import React, { useState, useEffect, useRef, useMemo, useId } from 'react';
import { Settings2, UserPlus, Check, X, Search, ChevronDown } from 'lucide-react';
import { apiRequest } from '../utils/apiClient';
import { PlayerName } from './StatTooltip';

const ToggleRow = ({ player, available, onToggle, updating, isMobile = false }) => {
  const name = `${player.first} ${player.last}`.trim();
  const isSub = !player.core;
  const b = player.batting || {};
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '0.75rem',
      padding: isMobile ? '0.6rem 0.75rem' : '0.75rem 1rem', borderRadius: '8px',
      background: available
        ? (isSub ? 'rgba(255, 165, 0, 0.04)' : 'rgba(0,0,0,0.2)')
        : 'rgba(200,50,50,0.08)',
      borderLeft: `3px solid ${!available ? 'var(--danger)' : isSub ? 'rgba(63, 143, 136, 0.42)' : 'var(--primary-color)'}`,
      opacity: available ? 1 : 0.65,
      transition: 'all 0.2s ease'
    }}>
      <div style={{
        width: isMobile ? '40px' : '44px', height: isMobile ? '40px' : '44px', borderRadius: '50%', flexShrink: 0,
        background: available
          ? (isSub ? 'linear-gradient(135deg, var(--accent-sub), #cc8400)' : 'linear-gradient(135deg, var(--primary-color), var(--secondary-color))')
          : '#444',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: isMobile ? 'var(--text-sm)' : '0.85rem', fontWeight: 'bold', color: '#fff', transition: 'all 0.2s ease'
      }}>
        {player.number}
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: isMobile ? 'var(--text-sm)' : '0.95rem' }}>
          <PlayerName name={name} number={player.number} size="sm" />
        </div>
        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
          {b.gp != null ? `${b.gp} GP` : ''}
          {b.avg != null ? ` · ${Number(b.avg || 0).toFixed(3).replace(/^0/, '')} AVG` : ''}
          {isSub && <span style={{ color: 'var(--accent-sub)', marginLeft: '0.4rem', fontWeight: '600' }}>SUB</span>}
        </div>
      </div>
      <button
        onClick={() => onToggle(player, !available)}
        disabled={updating}
        style={{
          display: 'flex', alignItems: 'center', gap: '0.3rem',
          padding: isMobile ? '0.5rem 0.75rem' : '0.3rem 0.8rem', borderRadius: '6px', border: 'none',
          background: available ? 'var(--primary-glow)' : 'rgba(200,50,50,0.15)',
          color: available ? 'var(--success)' : 'var(--danger)',
          cursor: updating ? 'not-allowed' : 'pointer',
          fontWeight: '600', fontSize: 'var(--text-xs)',
          minHeight: 'var(--touch-min)',
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
  // A phone never fires hover, so the "which row am I on" highlight has to be
  // real state driven by pointer-press and keyboard focus rather than the old
  // onMouseEnter/onMouseLeave background swap, which was invisible on touch.
  const [pressedKey, setPressedKey] = useState(null);
  const [focusedKey, setFocusedKey] = useState(null);
  const ref = useRef(null);
  const listRef = useRef(null);
  const listId = useId();

  useEffect(() => {
    // `pointerdown`, not `mousedown`: iOS Safari only synthesises mouse events
    // over elements it considers clickable, so tapping inert page chrome left
    // this dropdown stuck open. Escape gives keyboard users the same exit.
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const onKeyDown = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('pointerdown', handler);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', handler);
      document.removeEventListener('keydown', onKeyDown);
    };
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
        <Search size={14} color="var(--text-muted)" style={{ flexShrink: 0 }} />
        <input
          type="text"
          value={query}
          onChange={e => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onKeyDown={e => {
            // Escape closes; ArrowDown hands focus to the list so the dropdown
            // is operable without a pointer at all.
            if (e.key === 'Escape') { setOpen(false); return; }
            if (e.key === 'ArrowDown') {
              e.preventDefault();
              setOpen(true);
              listRef.current?.querySelector('[role="option"]')?.focus();
            }
          }}
          placeholder={placeholder || 'Search PCLL players...'}
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          // Phone keyboard hints: a search key instead of return, and none of
          // the autocorrect/autocapitalise mangling of surnames mid-query.
          inputMode="search"
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="none"
          enterKeyHint="search"
          style={{
            flex: 1, minWidth: 0, background: 'transparent', border: 'none', outline: 'none',
            color: 'var(--text-main)', fontSize: '0.9rem', fontFamily: 'inherit'
          }}
        />
        <ChevronDown size={14} color="var(--text-muted)" style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }} />
      </div>
      {open && (
        <div
          ref={listRef}
          id={listId}
          role="listbox"
          aria-label="PCLL players"
          style={{
            position: 'absolute', top: '100%', left: 0, right: 0, marginTop: '4px',
            background: '#1a2333', border: '1px solid var(--surface-border)',
            borderRadius: '8px', maxHeight: '240px', overflowY: 'auto', zIndex: 50,
            // This list scrolls inside a page that also scrolls. Without
            // `overscrollBehavior: contain` a flick past the end drags the page
            // (and can dismiss the whole panel); `-webkit-overflow-scrolling`
            // keeps momentum scrolling on older iOS.
            overscrollBehavior: 'contain',
            WebkitOverflowScrolling: 'touch',
            boxShadow: '0 8px 24px rgba(0,0,0,0.5)'
          }}
        >
          {filtered.length === 0 ? (
            <div style={{ padding: '0.75rem 1rem', color: 'var(--text-muted)', fontSize: '0.85rem', fontStyle: 'italic' }}>
              {players.length === 0 ? 'No league data scraped yet. Use manual entry below.' : 'No players match your search.'}
            </div>
          ) : (
            filtered.map((p, i) => {
              const optKey = `${p.gc_team_id}-${p.number}-${p.last}-${i}`;
              const isActive = pressedKey === optKey || focusedKey === optKey;
              return (
                // A real <button> (not a bare div) so the row is tab-reachable,
                // fires on Enter/Space, and clears the 44px minimum target.
                <button
                  key={optKey}
                  type="button"
                  role="option"
                  aria-selected={isActive}
                  onClick={() => { onSelect(p); setQuery(''); setOpen(false); setPressedKey(null); }}
                  onPointerDown={() => setPressedKey(optKey)}
                  onPointerUp={() => setPressedKey(null)}
                  onPointerCancel={() => setPressedKey(null)}
                  onPointerLeave={() => setPressedKey(null)}
                  onFocus={() => setFocusedKey(optKey)}
                  onBlur={() => setFocusedKey(null)}
                  style={{
                    display: 'block', width: '100%', textAlign: 'left',
                    padding: '0.6rem 1rem', cursor: 'pointer',
                    minHeight: 'var(--touch-min)',
                    border: 'none',
                    borderBottom: i < filtered.length - 1 ? '1px solid rgba(255,255,255,0.05)' : 'none',
                    background: isActive ? 'rgba(4, 101, 104, 0.22)' : 'transparent',
                    color: 'var(--text-main)', fontFamily: 'inherit',
                    outline: focusedKey === optKey ? '2px solid var(--primary-color)' : 'none',
                    outlineOffset: '-2px',
                    transition: 'background 0.15s ease',
                    touchAction: 'manipulation',
                    WebkitTapHighlightColor: 'transparent',
                  }}
                >
                  <div style={{ fontWeight: '600', fontSize: '0.9rem' }}>
                    {p.first} {p.last} <span style={{ color: 'var(--primary-color)' }}>#{p.number}</span>
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    {p.team_name}
                  </div>
                </button>
              );
            })
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
  showTitle = true,
  isMobile = false
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
      const res = await apiRequest('/api/availability', {
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
      const res = await apiRequest('/api/availability', {
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
      const res = await apiRequest('/api/availability', {
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
      const res = await apiRequest('/api/borrowed-player', {
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
      <div className="glass-panel" style={{ padding: isMobile ? 'var(--space-lg)' : '1.5rem', marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: isMobile ? 'flex-start' : 'center', marginBottom: '1rem', flexDirection: isMobile ? 'column' : 'row', gap: isMobile ? '0.65rem' : 0 }}>
          <h3 style={{ margin: 0, color: 'var(--primary-color)', fontSize: '1rem' }}>Game-Day Availability</h3>
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
            <button
              onClick={handleSharksOnly}
              style={{ padding: isMobile ? '0.5rem 0.75rem' : '0.3rem 0.75rem', borderRadius: '6px', border: '1px solid rgba(4, 101, 104, 0.32)', background: 'rgba(4, 101, 104, 0.13)', color: 'var(--primary-color)', cursor: 'pointer', fontSize: 'var(--text-xs)', fontWeight: '600', minHeight: 'var(--touch-min)' }}
            >
              Sharks Only
            </button>
            <button
              onClick={() => handleSetAll(true)}
              style={{ padding: isMobile ? '0.5rem 0.75rem' : '0.3rem 0.75rem', borderRadius: '6px', border: '1px solid rgba(35,134,54,0.3)', background: 'rgba(35,134,54,0.1)', color: 'var(--success)', cursor: 'pointer', fontSize: 'var(--text-xs)', fontWeight: '600', minHeight: 'var(--touch-min)' }}
            >
              All In
            </button>
            <button
              onClick={() => handleSetAll(false)}
              style={{ padding: isMobile ? '0.5rem 0.75rem' : '0.3rem 0.75rem', borderRadius: '6px', border: '1px solid rgba(200,50,50,0.3)', background: 'rgba(200,50,50,0.1)', color: 'var(--danger)', cursor: 'pointer', fontSize: 'var(--text-xs)', fontWeight: '600', minHeight: 'var(--touch-min)' }}
            >
              All Out
            </button>
          </div>
        </div>
        <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)', marginBottom: '1rem', display: isMobile ? 'none' : 'block' }}>
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
              isMobile={isMobile}
            />
          ))}
        </div>

        {/* Sub players */}
        {(subRoster.filter(p => isAvailable(p)).length > 0 || subRoster.filter(p => !isAvailable(p)).length > 0) && (
          <div style={{ marginTop: '1rem', paddingTop: '1rem', borderTop: '1px solid rgba(63, 143, 136, 0.2)' }}>

            {/* Active Subs */}
            {subRoster.filter(p => isAvailable(p)).length > 0 && (
              <div style={{ marginBottom: subRoster.filter(p => !isAvailable(p)).length > 0 ? '1rem' : 0 }}>
                <div className="section-label" style={{ color: 'var(--accent-sub)', marginBottom: '0.5rem' }}>
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
                      isMobile={isMobile}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* Inactive / Recent Subs */}
            {subRoster.filter(p => !isAvailable(p)).length > 0 && (
              <div style={{ paddingTop: subRoster.filter(p => isAvailable(p)).length > 0 ? '1rem' : 0, borderTop: subRoster.filter(p => isAvailable(p)).length > 0 ? '1px dashed rgba(255,255,255,0.1)' : 'none' }}>
                <div className="section-label section-label--muted" style={{ marginBottom: '0.5rem' }}>
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
                      isMobile={isMobile}
                    />
                  ))}
                </div>
              </div>
            )}

          </div>
        )}
      </div>

      {/* Add borrowed player section */}
      <div className="glass-panel" style={{ padding: isMobile ? 'var(--space-lg)' : '1.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: isMobile ? 'flex-start' : 'center', marginBottom: '1rem', flexDirection: isMobile ? 'column' : 'row', gap: isMobile ? '0.65rem' : 0 }}>
          <h3 style={{ margin: 0, color: 'var(--primary-color)', fontSize: '1rem' }}>Add Borrowed Player</h3>
          <button
            onClick={() => { setShowBorrowForm(!showBorrowForm); setBorrowStatus(null); setManualMode(false); }}
            style={{
              display: 'flex', alignItems: 'center', gap: '0.4rem',
              padding: isMobile ? '0.5rem 0.85rem' : '0.4rem 0.9rem', borderRadius: '8px',
              border: '1px solid rgba(100,200,100,0.3)',
              background: showBorrowForm ? 'rgba(200,50,50,0.1)' : 'var(--primary-glow)',
              color: showBorrowForm ? 'var(--danger)' : 'var(--primary-color)',
              cursor: 'pointer', fontWeight: '600', fontSize: 'var(--text-sm)',
              minHeight: 'var(--touch-min)',
            }}
          >
            {showBorrowForm ? <><X size={14} /> Cancel</> : <><UserPlus size={14} /> Add Player</>}
          </button>
        </div>

        <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)', marginBottom: showBorrowForm ? '1rem' : 0, display: isMobile ? 'none' : 'block' }}>
          Search PCLL league players or manually add a borrowed player. Stats auto-scrape if their team has been scraped.
        </p>

        {showBorrowForm && (
          <div>
            {/* Search dropdown — only shown if league data has been scraped */}
            {!manualMode && leaguePlayers.length > 0 && (
              <div style={{ marginBottom: '1rem' }}>
                <PlayerCombobox
                  players={leaguePlayers}
                  onSelect={handlePlayerSelect}
                  placeholder="Search by name, team, or jersey #..."
                />
                <button
                  onClick={() => setManualMode(true)}
                  style={{
                    marginTop: '0.25rem', background: 'none', border: 'none',
                    color: 'var(--text-muted)', fontSize: 'var(--text-sm)', cursor: 'pointer',
                    textDecoration: 'underline',
                    // `minHeight` alone left the hit area the width of the text
                    // with zero side padding; the negative margin keeps the
                    // label optically flush with the field above it.
                    padding: '0.5rem 0.75rem', marginLeft: '-0.75rem',
                    minHeight: 'var(--touch-min)', textAlign: 'left',
                  }}
                >
                  Or enter player details manually
                </button>
              </div>
            )}
            {!manualMode && leaguePlayers.length === 0 && (
              <div style={{ marginBottom: '1rem' }}>
                <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)', margin: '0 0 0.5rem 0' }}>
                  No league roster data available yet. Enter player details manually.
                </p>
                <button
                  onClick={() => setManualMode(true)}
                  style={{
                    background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.12)',
                    color: 'var(--text-main)', fontSize: 'var(--text-sm)', cursor: 'pointer',
                    borderRadius: '6px', padding: '0.5rem 1rem',
                    // Was ~28px tall — below the 44px thumb minimum.
                    minHeight: 'var(--touch-min)',
                  }}
                >
                  Enter manually
                </button>
              </div>
            )}

            {/* Form (shown when player selected from dropdown or manual mode) */}
            {(manualMode || borrowForm.first) && (
              <form onSubmit={handleBorrowSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                {borrowForm.first && !manualMode && (
                  <div style={{
                    padding: '0.6rem 0.75rem', borderRadius: '6px',
                    background: 'rgba(4, 101, 104, 0.08)', border: '1px solid rgba(4, 101, 104, 0.2)',
                    fontSize: '0.85rem', color: 'var(--primary-color)', fontWeight: '600',
                    overflowWrap: 'anywhere',
                  }}>
                    Selected: {borrowForm.first} {borrowForm.last} #{borrowForm.number}
                    {/* `touch-target` puts a 44px transparent hit area behind
                        this ~13px text without disturbing the inline layout. */}
                    <button
                      type="button"
                      className="touch-target"
                      onClick={() => setBorrowForm({ first: '', last: '', number: '', gc_team_id: '' })}
                      style={{
                        marginLeft: '0.5rem', background: 'none', border: 'none',
                        color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.8rem',
                        padding: '0.25rem 0.5rem', minHeight: 'var(--touch-min)',
                        textDecoration: 'underline',
                      }}
                    >
                      (clear)
                    </button>
                  </div>
                )}

                {manualMode && (
                  <>
                    {/* Two columns become ~90-140px fields on a 360px phone —
                        stack them instead. */}
                    <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr', gap: '0.75rem' }}>
                      <div>
                        <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: '0.3rem' }}>First Name *</label>
                        <input
                          type="text" value={borrowForm.first}
                          onChange={e => setBorrowForm(p => ({ ...p, first: e.target.value }))}
                          placeholder="e.g. Alexa" required
                          autoComplete="given-name" autoCapitalize="words"
                          style={{ width: '100%', padding: '0.5rem 0.75rem', borderRadius: '6px', border: '1px solid var(--surface-border)', background: 'rgba(0,0,0,0.3)', color: 'var(--text-main)', fontSize: '0.9rem', boxSizing: 'border-box' }}
                        />
                      </div>
                      <div>
                        <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: '0.3rem' }}>Last Name</label>
                        <input
                          type="text" value={borrowForm.last}
                          onChange={e => setBorrowForm(p => ({ ...p, last: e.target.value }))}
                          placeholder="e.g. Smith"
                          autoComplete="family-name" autoCapitalize="words"
                          style={{ width: '100%', padding: '0.5rem 0.75rem', borderRadius: '6px', border: '1px solid var(--surface-border)', background: 'rgba(0,0,0,0.3)', color: 'var(--text-main)', fontSize: '0.9rem', boxSizing: 'border-box' }}
                        />
                      </div>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : '1fr 2fr', gap: '0.75rem' }}>
                      <div>
                        <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: '0.3rem' }}>Jersey #</label>
                        {/* Numeric pad, but kept type=text so the value stays a
                            free-form string (leading zeros, "00"). */}
                        <input
                          type="text" value={borrowForm.number}
                          onChange={e => setBorrowForm(p => ({ ...p, number: e.target.value }))}
                          placeholder="e.g. 42"
                          inputMode="numeric" pattern="[0-9]*" autoComplete="off"
                          style={{ width: '100%', padding: '0.5rem 0.75rem', borderRadius: '6px', border: '1px solid var(--surface-border)', background: 'rgba(0,0,0,0.3)', color: 'var(--text-main)', fontSize: '0.9rem', boxSizing: 'border-box' }}
                        />
                      </div>
                      <div>
                        <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: '0.3rem' }}>GC Team ID (optional)</label>
                        {/* An opaque case-sensitive ID — autocapitalise and
                            autocorrect would silently corrupt it. */}
                        <input
                          type="text" value={borrowForm.gc_team_id}
                          onChange={e => setBorrowForm(p => ({ ...p, gc_team_id: e.target.value }))}
                          placeholder="e.g. AbCdEfGhIjKl"
                          autoCapitalize="none" autoCorrect="off" spellCheck={false} autoComplete="off"
                          style={{ width: '100%', padding: '0.5rem 0.75rem', borderRadius: '6px', border: '1px solid var(--surface-border)', background: 'rgba(0,0,0,0.3)', color: 'var(--text-main)', fontSize: '0.9rem', boxSizing: 'border-box' }}
                        />
                      </div>
                    </div>
                  </>
                )}

                {/* Wraps so the success/error message drops below the button
                    instead of running off a 360px screen. */}
                <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
                  <button
                    type="submit"
                    disabled={borrowStatus === 'adding' || !borrowForm.first.trim()}
                    style={{
                      padding: '0.5rem 1.5rem', borderRadius: '8px', border: 'none',
                      background: 'var(--primary-color)', color: '#fff',
                      cursor: (borrowStatus === 'adding' || !borrowForm.first.trim()) ? 'not-allowed' : 'pointer',
                      fontWeight: '600', fontSize: 'var(--text-sm)',
                      opacity: (borrowStatus === 'adding' || !borrowForm.first.trim()) ? 0.6 : 1,
                      minHeight: 'var(--touch-min)',
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
