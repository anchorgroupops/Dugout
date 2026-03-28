import React, { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { TipBadge, PlayerName } from './StatTooltip';

const fmt = (val) => (val !== null && val !== undefined ? String(val) : '\u2014');
const fmtPct = (val) => {
  if (val === null || val === undefined || val === '') return '\u2014';
  const n = parseFloat(val);
  return isNaN(n) ? '\u2014' : `${n.toFixed(1)}%`;
};
const fmt3 = (val) => {
  if (val === null || val === undefined || val === '') return '\u2014';
  // Already formatted like ".750"
  if (typeof val === 'string' && val.startsWith('.')) return val;
  const n = parseFloat(val);
  if (isNaN(n)) return '\u2014';
  const s = n.toFixed(3);
  // Strip leading zero for values 0 ≤ n < 1 (batting average convention: .400 not 0.400)
  return (n >= 0 && n < 1) ? s.replace(/^0/, '') : s;
};
const fmt2 = (val) => {
  if (val === null || val === undefined || val === '') return '\u2014';
  const n = parseFloat(val);
  return isNaN(n) ? '\u2014' : n.toFixed(2);
};

const getStrengthBadges = (player) => {
  const b = player.batting || {};
  const f = player.fielding || {};
  const badges = [];

  const avg = parseFloat(b.avg ?? player.avg);
  const obp = parseFloat(b.obp ?? player.obp);
  const ops = parseFloat(b.ops ?? player.ops);
  const sb = parseFloat(b.sb ?? player.sb);
  const fpct = parseFloat(f.fpct);

  if (!isNaN(avg) && avg >= 0.350) badges.push({ icon: '\uD83D\uDD25', tip: `AVG ${avg.toFixed(3)}` });
  if (!isNaN(obp) && obp >= 0.420) badges.push({ icon: '\uD83D\uDC41\uFE0F', tip: `OBP ${obp.toFixed(3)}` });
  if (!isNaN(ops) && ops >= 0.700) badges.push({ icon: '\uD83D\uDCAA', tip: `OPS ${ops.toFixed(3)}` });
  if (!isNaN(sb) && sb >= 2) badges.push({ icon: '\u26A1', tip: `${sb} SB` });
  if (!isNaN(fpct) && fpct >= 0.900) badges.push({ icon: '\uD83C\uDFAF', tip: `FPCT ${fpct.toFixed(3)}` });

  return badges;
};

const ExpandedStats = ({ player }) => {
  const b = player.batting || {};
  const ba = player.batting_advanced || {};
  const p = player.pitching || {};
  const f = player.fielding || {};
  const c = player.catching || {};
  const ip = player.innings_played || {};

  const sectionStyle = { marginBottom: '0.75rem' };
  const rowStyle = { display: 'flex', gap: '0.4rem', flexWrap: 'wrap' };
  const rowGapStyle = { display: 'flex', gap: '0.4rem', flexWrap: 'wrap', marginTop: '0.4rem' };

  return (
    <div style={{ marginTop: '1rem', borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: '1rem' }}>
      {/* Batting */}
      <div style={sectionStyle}>
        <div className="section-label">Batting</div>
        <div style={rowStyle}>
          <TipBadge label="AVG" value={fmt3(b.avg ?? player.avg)} />
          <TipBadge label="OBP" value={fmt3(b.obp ?? player.obp)} />
          <TipBadge label="SLG" value={fmt3(b.slg ?? player.slg)} />
          <TipBadge label="OPS" value={fmt3(b.ops ?? player.ops)} />
        </div>
        <div style={rowGapStyle}>
          <TipBadge label="GP" value={fmt(b.gp)} />
          <TipBadge label="PA" value={fmt(b.pa ?? player.pa)} />
          <TipBadge label="AB" value={fmt(b.ab ?? player.ab)} />
          <TipBadge label="H" value={fmt(b.h ?? player.h)} />
          <TipBadge label="2B" value={fmt(b['2b'] ?? b.doubles)} />
          <TipBadge label="3B" value={fmt(b['3b'] ?? b.triples)} />
          <TipBadge label="HR" value={fmt(b.hr)} />
        </div>
        <div style={rowGapStyle}>
          <TipBadge label="RBI" value={fmt(b.rbi ?? player.rbi)} />
          <TipBadge label="R" value={fmt(b.r ?? player.r)} />
          <TipBadge label="BB" value={fmt(b.bb)} />
          <TipBadge label="HBP" value={fmt(b.hbp)} />
          <TipBadge label="SO" value={fmt(b.so)} />
          <TipBadge label="SB" value={fmt(b.sb ?? player.sb)} />
          <TipBadge label="SAC" value={fmt(b.sac)} />
        </div>
      </div>

      {/* Batting Advanced */}
      {Object.keys(ba).length > 0 && (
        <div style={sectionStyle}>
          <div className="section-label">Batting Advanced</div>
          <div style={rowStyle}>
            <TipBadge label="BABIP" value={fmt3(ba.babip)} />
            <TipBadge label="BA/RISP" value={fmt3(ba.ba_risp)} />
            <TipBadge label="QAB%" value={fmtPct(ba.qab_pct)} />
            <TipBadge label="BB/K" value={fmt(ba.bb_k ?? ba.bb_per_k)} />
          </div>
          <div style={rowGapStyle}>
            <TipBadge label="TB" value={fmt(ba.tb)} />
            <TipBadge label="XBH" value={fmt(ba.xbh)} />
            <TipBadge label="PS/PA" value={ba.ps_pa != null ? parseFloat(ba.ps_pa).toFixed(2) : '\u2014'} />
            <TipBadge label="QAB" value={fmt(ba.qab)} />
          </div>
          <div style={rowGapStyle}>
            <TipBadge label="FB%" value={fmtPct(ba.fb_pct)} />
            <TipBadge label="GB%" value={fmtPct(ba.gb_pct)} />
            <TipBadge label="LD%" value={fmtPct(ba.ld_pct)} />
            <TipBadge label="C%" value={fmtPct(ba.c_pct)} />
          </div>
        </div>
      )}

      {/* Pitching */}
      {Object.keys(p).length > 0 && (
        <div style={sectionStyle}>
          <div className="section-label">Pitching</div>
          <div style={rowStyle}>
            <TipBadge label="IP" value={fmt(p.ip)} />
            <TipBadge label="ERA" value={fmt2(p.era)} />
            <TipBadge label="WHIP" value={fmt2(p.whip)} />
            <TipBadge label="BAA" value={fmt3(p.baa)} />
          </div>
          <div style={rowGapStyle}>
            <TipBadge label="W-L" value={`${fmt(p.w)}-${fmt(p.l)}`} />
            <TipBadge label="GP" value={fmt(p.gp)} />
            <TipBadge label="GS" value={fmt(p.gs)} />
            <TipBadge label="SV" value={fmt(p.sv)} />
          </div>
          <div style={rowGapStyle}>
            <TipBadge label="BF" value={fmt(p.bf)} />
            <TipBadge label="#P" value={fmt(p.np)} />
            <TipBadge label="SO" value={fmt(p.so)} />
            <TipBadge label="KL" value={fmt(p.kl)} />
            <TipBadge label="BB" value={fmt(p.bb)} />
            <TipBadge label="HBP" value={fmt(p.hbp)} />
          </div>
          <div style={rowGapStyle}>
            <TipBadge label="H" value={fmt(p.h)} />
            <TipBadge label="R" value={fmt(p.r)} />
            <TipBadge label="ER" value={fmt(p.er)} />
            <TipBadge label="WP" value={fmt(p.wp)} />
            <TipBadge label="PIK" value={fmt(p.pik)} />
          </div>
        </div>
      )}

      {/* Fielding */}
      {Object.keys(f).length > 0 && (
        <div style={sectionStyle}>
          <div className="section-label">Fielding</div>
          <div style={rowStyle}>
            <TipBadge label="FPCT" value={fmt3(f.fpct)} />
            <TipBadge label="TC" value={fmt(f.tc)} />
            <TipBadge label="PO" value={fmt(f.po)} />
            <TipBadge label="A" value={fmt(f.a)} />
            <TipBadge label="E" value={fmt(f.e)} />
          </div>
        </div>
      )}

      {/* Catching */}
      {Object.keys(c).length > 0 && (() => {
        const sbAtt = c.sb_att || (c.sb != null && c.cs != null ? `${c.sb}-${c.sb + c.cs}` : null);
        return (
          <div style={sectionStyle}>
            <div className="section-label">Catching</div>
            <div style={rowStyle}>
              <TipBadge label="INN" value={fmt(c.inn)} />
              <TipBadge label="SB-ATT" value={fmt(sbAtt)} />
              <TipBadge label="CS%" value={fmtPct(c.cs_pct)} />
              <TipBadge label="PB" value={fmt(c.pb)} />
              <TipBadge label="SB" value={fmt(c.sb)} />
              <TipBadge label="CS" value={fmt(c.cs)} />
              <TipBadge label="PIK" value={fmt(c.pik)} />
            </div>
          </div>
        );
      })()}

      {/* Innings Played */}
      {Object.keys(ip).length > 0 && (
        <div style={sectionStyle}>
          <div className="section-label">Innings Played</div>
          <div style={rowStyle}>
            <TipBadge label="Total" value={fmt(ip.total)} />
            <TipBadge label="P" value={fmt(ip.p)} />
            <TipBadge label="C" value={fmt(ip.c)} />
            <TipBadge label="1B" value={fmt(ip.first_base)} />
            <TipBadge label="SS" value={fmt(ip.ss)} />
          </div>
          <div style={rowGapStyle}>
            <TipBadge label="2B" value={fmt(ip.second_base)} />
            <TipBadge label="3B" value={fmt(ip.third_base)} />
            <TipBadge label="LF" value={fmt(ip.lf)} />
            <TipBadge label="CF" value={fmt(ip.cf)} />
            <TipBadge label="RF" value={fmt(ip.rf)} />
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
  const sortedRoster = [...filteredRoster].sort((a, b) => {
    // Sort available (active) players first
    const nameA = `${a.first || ''} ${a.last || ''}`.trim();
    const nameB = `${b.first || ''} ${b.last || ''}`.trim();
    const activeA = availability ? availability[nameA] !== false : true;
    const activeB = availability ? availability[nameB] !== false : true;
    if (activeA !== activeB) return activeA ? -1 : 1;
    const cmp = (a.first || '').localeCompare(b.first || '');
    return cmp !== 0 ? cmp : (a.last || '').localeCompare(b.last || '');
  });
  const totalCount = filteredRoster.length;
  const activeCount = sortedRoster.filter(p => {
    const name = `${p.first || ''} ${p.last || ''}`.trim();
    return availability ? availability[name] !== false : true;
  }).length;

  return (
    <div>
      <h2 className="view-title">
        Active Roster <span style={{ fontSize: 'var(--text-base)', color: 'var(--text-muted)', fontWeight: 'normal' }}>({sortedRoster.length} Players)</span>
        <span style={{ marginLeft: 'auto', fontSize: 'var(--text-sm)', color: 'var(--text-muted)', fontWeight: '600' }}>
          {activeCount} Available
        </span>
      </h2>

      <div className="card-grid">
        {sortedRoster.map(player => {
          const playerKey = `${player.number}-${player.last}`;
          const isExpanded = expandedPlayer === playerKey;
          const name = `${player.first} ${player.last}`.trim();
          const isActive = availability && availability[name] !== false;
          const isSub = !player.core;
          const b = player.batting || {};
          const strengthBadges = getStrengthBadges(player);

          return (
            <div
              key={playerKey}
              className={`glass-panel ${isActive ? '' : 'inactive-player'}`}
              style={{
                padding: 'var(--space-lg)',
                position: 'relative',
                overflow: 'hidden',
                cursor: 'pointer',
                transition: 'all 0.3s ease',
                opacity: isActive ? 1 : 0.6,
                filter: isActive ? 'none' : 'grayscale(0.5)',
                borderLeft: !isActive ? '4px solid #666' : isSub ? '4px solid rgba(63, 143, 136, 0.42)' : '4px solid var(--primary-color)',
                background: isSub && isActive ? 'rgba(63, 143, 136, 0.06)' : undefined
              }}
              onClick={() => setExpandedPlayer(isExpanded ? null : playerKey)}
            >
              {/* Watermark number */}
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

              {/* SUB badge */}
              {!player.core && (
                <div style={{ position: 'absolute', top: '10px', right: '10px' }}>
                  <div style={{
                    background: 'rgba(63, 143, 136, 0.18)', color: 'var(--accent-sub)',
                    padding: '2px 8px', borderRadius: '4px', fontSize: 'var(--text-xs)',
                    fontWeight: 'bold', letterSpacing: '1px', border: '1px solid rgba(63, 143, 136, 0.28)'
                  }}>SUB</div>
                </div>
              )}

              {/* Player header: Name first, number to the right */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.75rem' }}>
                <div className="player-avatar" style={{
                  background: isActive ? 'linear-gradient(135deg, var(--primary-color), var(--secondary-color))' : '#444',
                  transition: 'all 0.3s ease'
                }}>
                  {player.number}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                    <PlayerName first={player.first} last={player.last} number={player.number} size="md" />
                    {/* Strength icons next to name */}
                    {strengthBadges.length > 0 && (
                      <span style={{ display: 'inline-flex', gap: '0.2rem', fontSize: 'var(--text-sm)' }}>
                        {strengthBadges.map((badge, i) => (
                          <span key={i} title={badge.tip} style={{ cursor: 'default', lineHeight: 1 }}>{badge.icon}</span>
                        ))}
                      </span>
                    )}
                  </div>
                  <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', display: 'block', marginTop: '2px' }}>
                    {b.gp != null ? `${b.gp} GP` : ''}{b.pa != null ? ` \u2022 ${b.pa} PA` : ''}
                    {!isExpanded && (
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.2rem', marginLeft: '0.3rem', color: 'var(--primary-color)' }}>
                        <ChevronDown size={12} /> Stats
                      </span>
                    )}
                    {isExpanded && (
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.2rem', marginLeft: '0.3rem', color: 'var(--primary-color)' }}>
                        <ChevronUp size={12} /> Collapse
                      </span>
                    )}
                  </span>
                  {player.teams && player.teams.length > 0 && (
                    <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: '2px' }}>
                      Teams: {player.teams.join(', ')}
                    </div>
                  )}
                </div>
              </div>

              {/* Collapsed: compact summary with key stat badges */}
              {!isExpanded && (
                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                  <TipBadge label="AVG" value={fmt3(b.avg ?? player.avg)} />
                  <TipBadge label="OBP" value={fmt3(b.obp ?? player.obp)} />
                  <TipBadge label="OPS" value={fmt3(b.ops ?? player.ops)} />
                </div>
              )}

              {/* Expanded: full stats in organized sections */}
              {isExpanded && <ExpandedStats player={player} />}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default Roster;
