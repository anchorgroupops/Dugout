import React, { useState } from 'react';

const StatBadge = ({ label, value }) => (
  <div className="stat-badge">
    <span className="stat-badge__label">{label}</span>
    <span className="stat-badge__value">{value ?? '\u2014'}</span>
  </div>
);

const fmt = (val) => (val !== null && val !== undefined ? String(val) : '\u2014');

const ExpandedStats = ({ player }) => {
  const b = player.batting || {};
  const ba = player.batting_advanced || {};
  const p = player.pitching || {};
  const f = player.fielding || {};
  const c = player.catching || {};
  const ip = player.innings_played || {};

  return (
    <div style={{ marginTop: '1rem', borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: '1rem' }}>
      {Object.keys(ba).length > 0 && (
        <div style={{ marginBottom: 'var(--space-sm)' }}>
          <div className="section-label">Batting Advanced</div>
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

      {Object.keys(p).length > 0 && (
        <div style={{ marginBottom: 'var(--space-sm)' }}>
          <div className="section-label">Pitching</div>
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

      {Object.keys(f).length > 0 && (
        <div style={{ marginBottom: 'var(--space-sm)' }}>
          <div className="section-label">Fielding</div>
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
            <StatBadge label="FPCT" value={fmt(f.fpct)} />
            <StatBadge label="TC" value={fmt(f.tc)} />
            <StatBadge label="PO" value={fmt(f.po)} />
            <StatBadge label="E" value={fmt(f.e)} />
          </div>
        </div>
      )}

      {Object.keys(c).length > 0 && (
        <div style={{ marginBottom: 'var(--space-sm)' }}>
          <div className="section-label">Catching</div>
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
            <StatBadge label="INN" value={fmt(c.inn)} />
            <StatBadge label="CS%" value={fmt(c.cs_pct)} />
            <StatBadge label="PB" value={fmt(c.pb)} />
            <StatBadge label="SB-ATT" value={fmt(c.sb_att)} />
          </div>
        </div>
      )}

      {Object.keys(ip).length > 0 && (
        <div>
          <div className="section-label">Innings Played</div>
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

const Roster = ({ team, availability, isMobile = false }) => {
  const [expandedPlayer, setExpandedPlayer] = useState(null);

  if (!team || !team.roster) return <div className="loader"></div>;

  const filteredRoster = team.roster.filter(p => p.core !== false);
  const sortedRoster = [...filteredRoster].sort((a, b) => (a.first || "").localeCompare(b.first || ""));
  const totalCount = filteredRoster.length;

  return (
    <div>
      <h2 className="view-title">
        Active Roster <span style={{ fontSize: 'var(--text-base)', color: 'var(--text-muted)', fontWeight: 'normal' }}>({sortedRoster.length} Players)</span>
        <span style={{ marginLeft: 'auto', fontSize: 'var(--text-sm)', color: 'var(--text-muted)', fontWeight: '600' }}>
          Sharks Only ({totalCount})
        </span>
      </h2>

      <div className="card-grid">
        {sortedRoster.map(player => {
          const name = `${player.first} ${player.last}`.trim();
          const isExpanded = expandedPlayer === `${player.number}-${player.last}`;
          const isActive = availability && availability[name] !== false;
          const isSub = !player.core;
          const b = player.batting || {};

          return (
            <div
              key={`${player.number}-${player.last}`}
              className={`glass-panel ${isActive ? '' : 'inactive-player'}`}
              style={{
                padding: isMobile ? 'var(--space-lg)' : '1.5rem',
                position: 'relative',
                overflow: 'hidden',
                cursor: isMobile ? 'default' : 'pointer',
                transition: 'all 0.3s ease',
                opacity: isActive ? 1 : 0.6,
                filter: isActive ? 'none' : 'grayscale(0.5)',
                borderLeft: !isActive ? '4px solid #666' : isSub ? '4px solid rgba(63, 143, 136, 0.42)' : '4px solid var(--primary-color)',
                background: isSub && isActive ? 'rgba(63, 143, 136, 0.06)' : undefined
              }}
              onClick={() => {
                if (!isMobile) setExpandedPlayer(isExpanded ? null : `${player.number}-${player.last}`);
              }}
            >
              {!isMobile && (
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
              )}

              {!player.core && (
                <div style={{ position: 'absolute', top: '10px', right: '10px' }}>
                  <div style={{
                    background: 'rgba(63, 143, 136, 0.18)', color: 'var(--accent-sub)',
                    padding: '2px 8px', borderRadius: '4px', fontSize: 'var(--text-xs)',
                    fontWeight: 'bold', letterSpacing: '1px', border: '1px solid rgba(63, 143, 136, 0.28)'
                  }}>SUB</div>
                </div>
              )}

              <div style={{ display: 'flex', alignItems: 'center', gap: isMobile ? '0.75rem' : '1rem', marginBottom: isMobile ? '0.85rem' : '1.25rem' }}>
                <div className="player-avatar" style={{
                  background: isActive ? 'linear-gradient(135deg, var(--primary-color), var(--secondary-color))' : '#444',
                  transition: 'all 0.3s ease'
                }}>
                  {player.number}
                </div>
                <div>
                  <h3 style={{ fontSize: isMobile ? 'var(--text-base)' : '1.2rem', marginBottom: '2px' }}>{player.first} {player.last}</h3>
                  <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
                    {b.gp != null ? `${b.gp} GP` : ''}{b.pa != null ? ` \u2022 ${b.pa} PA` : ''}
                    {!isExpanded && !isMobile && ' \u2022 Click to expand'}
                  </span>
                  {player.teams && player.teams.length > 0 && (
                    <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: '2px' }}>
                      Teams: {player.teams.join(', ')}
                    </div>
                  )}
                </div>
              </div>

              <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem' }}>
                <StatBadge label="AVG" value={fmt(b.avg ?? player.avg)} />
                <StatBadge label="OBP" value={fmt(b.obp ?? player.obp)} />
                <StatBadge label="OPS" value={fmt(b.ops ?? player.ops)} />
              </div>
              {!isMobile && (
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                  <StatBadge label="H" value={fmt(b.h ?? player.h)} />
                  <StatBadge label="RBI" value={fmt(b.rbi ?? player.rbi)} />
                  <StatBadge label="R" value={fmt(b.r ?? player.r)} />
                  <StatBadge label="SB" value={fmt(b.sb ?? player.sb)} />
                </div>
              )}

              {!isMobile && isExpanded && <ExpandedStats player={player} />}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default Roster;
