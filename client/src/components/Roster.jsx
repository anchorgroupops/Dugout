import React, { useState } from 'react';

const StatBadge = ({ label, value }) => (
  <div style={{
    background: 'rgba(0, 0, 0, 0.2)',
    padding: '0.4rem 0.6rem',
    borderRadius: '6px',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '2px',
    flex: 1
  }}>
    <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
      {label}
    </span>
    <span style={{ fontSize: '1rem', fontWeight: 'bold', color: 'var(--text-main)' }}>
      {value ?? '—'}
    </span>
  </div>
);

// Helper to safely get a stat value from either nested or flat player object
const getStat = (player, category, key, fallbackKey) => {
  // Try nested first (new schema)
  if (player[category] && player[category][key] !== undefined) {
    return player[category][key];
  }
  // Fallback to flat key (old schema)
  if (fallbackKey && player[fallbackKey] !== undefined) {
    return player[fallbackKey];
  }
  if (player[key] !== undefined) {
    return player[key];
  }
  return null;
};

const fmt = (val) => (val !== null && val !== undefined ? String(val) : '—');

const ExpandedStats = ({ player }) => {
  const b = player.batting || {};
  const ba = player.batting_advanced || {};
  const p = player.pitching || {};
  const f = player.fielding || {};
  const c = player.catching || {};
  const ip = player.innings_played || {};

  return (
    <div style={{ marginTop: '1rem', borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: '1rem' }}>
      {/* Batting Advanced */}
      {Object.keys(ba).length > 0 && (
        <div style={{ marginBottom: '0.75rem' }}>
          <div style={{ fontSize: '0.7rem', color: 'var(--primary-color)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '0.4rem', fontWeight: 'bold' }}>
            Batting Advanced
          </div>
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
            <StatBadge label="BABIP" value={fmt(ba.babip)} />
            <StatBadge label="QAB%" value={fmt(ba.qab_pct)} />
            <StatBadge label="BB/K" value={fmt(ba.bb_k)} />
            <StatBadge label="TB" value={fmt(ba.tb)} />
          </div>
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', marginTop: '0.4rem' }}>
            <StatBadge label="FB%" value={fmt(ba.fb_pct)} />
            <StatBadge label="GB%" value={fmt(ba.gb_pct)} />
            <StatBadge label="LD%" value={fmt(ba.ld_pct)} />
            <StatBadge label="PS/PA" value={fmt(ba.ps_pa)} />
          </div>
        </div>
      )}

      {/* Pitching */}
      {Object.keys(p).length > 0 && (
        <div style={{ marginBottom: '0.75rem' }}>
          <div style={{ fontSize: '0.7rem', color: 'var(--primary-color)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '0.4rem', fontWeight: 'bold' }}>
            Pitching
          </div>
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
            <StatBadge label="IP" value={fmt(p.ip)} />
            <StatBadge label="ERA" value={fmt(p.era)} />
            <StatBadge label="WHIP" value={fmt(p.whip)} />
            <StatBadge label="SO" value={fmt(p.so)} />
          </div>
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', marginTop: '0.4rem' }}>
            <StatBadge label="W-L" value={`${fmt(p.w)}-${fmt(p.l)}`} />
            <StatBadge label="BAA" value={fmt(p.baa)} />
            <StatBadge label="#P" value={fmt(p.np)} />
            <StatBadge label="BB" value={fmt(p.bb)} />
          </div>
        </div>
      )}

      {/* Fielding */}
      {Object.keys(f).length > 0 && (
        <div style={{ marginBottom: '0.75rem' }}>
          <div style={{ fontSize: '0.7rem', color: 'var(--primary-color)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '0.4rem', fontWeight: 'bold' }}>
            Fielding
          </div>
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
            <StatBadge label="FPCT" value={fmt(f.fpct)} />
            <StatBadge label="TC" value={fmt(f.tc)} />
            <StatBadge label="PO" value={fmt(f.po)} />
            <StatBadge label="E" value={fmt(f.e)} />
          </div>
        </div>
      )}

      {/* Catching */}
      {Object.keys(c).length > 0 && (
        <div style={{ marginBottom: '0.75rem' }}>
          <div style={{ fontSize: '0.7rem', color: 'var(--primary-color)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '0.4rem', fontWeight: 'bold' }}>
            Catching
          </div>
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
            <StatBadge label="INN" value={fmt(c.inn)} />
            <StatBadge label="CS%" value={fmt(c.cs_pct)} />
            <StatBadge label="PB" value={fmt(c.pb)} />
            <StatBadge label="SB-ATT" value={fmt(c.sb_att)} />
          </div>
        </div>
      )}

      {/* Innings Played */}
      {Object.keys(ip).length > 0 && (
        <div>
          <div style={{ fontSize: '0.7rem', color: 'var(--primary-color)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '0.4rem', fontWeight: 'bold' }}>
            Innings Played
          </div>
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
            <StatBadge label="Total" value={fmt(ip.total)} />
            <StatBadge label="P" value={fmt(ip.p)} />
            <StatBadge label="C" value={fmt(ip.c)} />
            <StatBadge label="1B" value={fmt(ip.first_base)} />
            <StatBadge label="SS" value={fmt(ip.ss)} />
          </div>
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', marginTop: '0.4rem' }}>
            <StatBadge label="2B" value={fmt(ip.second_base)} />
            <StatBadge label="3B" value={fmt(ip.third_base)} />
            <StatBadge label="LF" value={fmt(ip.lf)} />
            <StatBadge label="CF" value={fmt(ip.cf)} />
            <StatBadge label="RF" value={fmt(ip.rf)} />
          </div>
        </div>
      )}
    </div>
  );
};

const Roster = ({ team, availability, onAvailabilityChange }) => {
  const [expandedPlayer, setExpandedPlayer] = useState(null);
  const [updating, setUpdating] = useState(null); // name of player being updated

  if (!team || !team.roster) return <div className="loader"></div>;

  const handleToggleActive = async (e, player) => {
    e.stopPropagation(); // Don't expand the card
    const name = `${player.first} ${player.last}`.trim();
    const newStatus = !availability[name];
    const newAvailability = { ...availability, [name]: newStatus };
    
    setUpdating(name);
    try {
      const res = await fetch('/api/availability', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newAvailability)
      });
      
      if (res.ok) {
        onAvailabilityChange(newAvailability);
      } else {
        console.error("Failed to update availability");
      }
    } catch (err) {
      console.error("Error updating availability", err);
    } finally {
      setUpdating(null);
    }
  };

  // Sharks-only roster (exclude non-core/sub players)
  const filteredRoster = team.roster.filter(p => p.core !== false);
  const sortedRoster = [...filteredRoster].sort((a, b) => (a.first || "").localeCompare(b.first || ""));
  const coreCount = team.roster.filter(p => p.core !== false).length;
  const totalCount = coreCount;

  return (
    <div>
      <h2 style={{ marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
        Active Roster <span style={{ fontSize: '1rem', color: 'var(--text-muted)', fontWeight: 'normal' }}>({sortedRoster.length} Players)</span>
        <span style={{ marginLeft: 'auto', fontSize: '0.85rem', color: 'var(--text-muted)', fontWeight: '600' }}>
          Sharks Only ({totalCount})
        </span>
      </h2>
      
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
        gap: '1.5rem'
      }}>
        {sortedRoster.map(player => {
          const name = `${player.first} ${player.last}`.trim();
          const isExpanded = expandedPlayer === `${player.number}-${player.last}`;
          const isActive = availability && availability[name] !== false;
          const isUpdating = updating === name;
          const isSub = !player.core;
          const b = player.batting || {};

          return (
            <div
              key={`${player.number}-${player.last}`}
              className={`glass-panel ${isActive ? '' : 'inactive-player'}`}
              style={{
                padding: '1.5rem',
                position: 'relative',
                overflow: 'hidden',
                cursor: 'pointer',
                transition: 'all 0.3s ease',
                opacity: isActive ? 1 : 0.6,
                filter: isActive ? 'none' : 'grayscale(0.5)',
                borderLeft: !isActive ? '4px solid #666' : isSub ? '4px solid rgba(255,165,0,0.5)' : '4px solid var(--primary-color)',
                background: isSub && isActive ? 'rgba(255,165,0,0.03)' : undefined
              }}
              onClick={() => setExpandedPlayer(isExpanded ? null : `${player.number}-${player.last}`)}
            >
              <div style={{
                position: 'absolute',
                top: '-15px',
                right: '-10px',
                fontSize: '4rem',
                fontWeight: '900',
                opacity: '0.05',
                fontFamily: 'var(--font-heading)'
              }}>
                {player.number}
              </div>
              
              <div style={{ position: 'absolute', top: '10px', right: '10px', display: 'flex', gap: '5px' }}>
                {!player.core && (
                  <div style={{
                    background: 'rgba(255, 165, 0, 0.2)', color: '#ffa500',
                    padding: '2px 8px', borderRadius: '4px', fontSize: '0.65rem',
                    fontWeight: 'bold', letterSpacing: '1px', border: '1px solid rgba(255,165,0,0.3)'
                  }}>SUB</div>
                )}
                
                <button
                  onClick={(e) => handleToggleActive(e, player)}
                  disabled={isUpdating}
                  style={{
                    background: isActive ? 'var(--primary-color)' : 'rgba(255,255,255,0.1)',
                    color: isActive ? '#fff' : 'var(--text-muted)',
                    border: 'none',
                    padding: '8px 14px',
                    borderRadius: '8px',
                    fontSize: '0.8rem',
                    fontWeight: 'bold',
                    cursor: 'pointer',
                    transition: 'all 0.2s ease',
                    opacity: isUpdating ? 0.5 : 1,
                    minWidth: '88px',
                    minHeight: '36px',
                    letterSpacing: '0.4px'
                  }}
                >
                  {isUpdating ? '...' : (isActive ? 'ACTIVE' : 'INACTIVE')}
                </button>
              </div>
              
              <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1.25rem' }}>
                <div style={{
                  width: '45px',
                  height: '45px',
                  borderRadius: '50%',
                  background: isActive ? 'linear-gradient(135deg, var(--primary-color), var(--secondary-color))' : '#444',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '1.2rem',
                  fontWeight: 'bold',
                  color: '#fff',
                  flexShrink: 0,
                  transition: 'all 0.3s ease'
                }}>
                  {player.number}
                </div>
                <div>
                  <h3 style={{ fontSize: '1.2rem', marginBottom: '2px' }}>{player.first} {player.last}</h3>
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    {b.gp != null ? `${b.gp} GP` : ''}{b.pa != null ? ` • ${b.pa} PA` : ''}
                    {!isExpanded && ' • Click to expand'}
                  </span>
                  {player.teams && player.teams.length > 0 && (
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                      Teams: {player.teams.join(', ')}
                    </div>
                  )}
                </div>
              </div>

              {/* Primary batting stats — works with both nested and flat schema */}
              <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem' }}>
                <StatBadge label="AVG" value={fmt(b.avg ?? player.avg)} />
                <StatBadge label="OBP" value={fmt(b.obp ?? player.obp)} />
                <StatBadge label="OPS" value={fmt(b.ops ?? player.ops)} />
              </div>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <StatBadge label="H" value={fmt(b.h ?? player.h)} />
                <StatBadge label="RBI" value={fmt(b.rbi ?? player.rbi)} />
                <StatBadge label="R" value={fmt(b.r ?? player.r)} />
                <StatBadge label="SB" value={fmt(b.sb ?? player.sb)} />
              </div>

              {isExpanded && <ExpandedStats player={player} />}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default Roster;
