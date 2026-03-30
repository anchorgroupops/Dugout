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
  if (typeof val === 'string' && val.startsWith('.')) return val;
  const n = parseFloat(val);
  if (isNaN(n)) return '\u2014';
  const s = n.toFixed(3);
  return (n >= 0 && n < 1) ? s.replace(/^0/, '') : s;
};
const fmt2 = (val) => {
  if (val === null || val === undefined || val === '') return '\u2014';
  const n = parseFloat(val);
  return isNaN(n) ? '\u2014' : n.toFixed(2);
};
const fmt1 = (val) => {
  if (val === null || val === undefined || val === '') return '\u2014';
  const n = parseFloat(val);
  return isNaN(n) ? '\u2014' : n.toFixed(1);
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

/** Check if a stat sub-object has any non-null values worth showing */
const hasData = (obj) => {
  if (!obj || typeof obj !== 'object') return false;
  return Object.values(obj).some(v => v !== null && v !== undefined && v !== '' && v !== '\u2014');
};

const ExpandedStats = ({ player }) => {
  const b = player.batting || {};
  const ba = player.batting_advanced || {};
  const p = player.pitching || {};
  const pa2 = player.pitching_advanced || {};
  const pb = player.pitching_breakdown || {};
  const f = player.fielding || {};
  const c = player.catching || {};
  const ip = player.innings_played || {};

  const sectionStyle = { marginBottom: '0.75rem' };
  const rowStyle = { display: 'flex', gap: '0.4rem', flexWrap: 'wrap' };
  const rowGapStyle = { display: 'flex', gap: '0.4rem', flexWrap: 'wrap', marginTop: '0.4rem' };

  return (
    <div style={{ marginTop: '1rem', borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: '1rem' }}>

      {/* ===== BATTING STANDARD ===== */}
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
          <TipBadge label="1B" value={fmt(b.singles ?? b['1b'])} />
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
          <TipBadge label="K-L" value={fmt(b.kl)} />
          <TipBadge label="ROE" value={fmt(b.roe)} />
        </div>
        <div style={rowGapStyle}>
          <TipBadge label="SB" value={fmt(b.sb ?? player.sb)} />
          <TipBadge label="CS" value={fmt(b.cs)} />
          <TipBadge label="SB%" value={fmtPct(b.sb_pct)} />
          <TipBadge label="SAC" value={fmt(b.sac)} />
          <TipBadge label="SF" value={fmt(b.sf)} />
          <TipBadge label="FC" value={fmt(b.fc)} />
          <TipBadge label="PIK" value={fmt(b.pik)} />
          <TipBadge label="CI" value={fmt(b.ci)} />
        </div>
      </div>

      {/* ===== BATTING ADVANCED ===== */}
      {hasData(ba) && (
        <div style={sectionStyle}>
          <div className="section-label">Batting Advanced</div>
          <div style={rowStyle}>
            <TipBadge label="BABIP" value={fmt3(ba.babip)} />
            <TipBadge label="BA/RISP" value={fmt3(ba.ba_risp)} />
            <TipBadge label="QAB%" value={fmtPct(ba.qab_pct)} />
            <TipBadge label="BB/K" value={fmt2(ba.bb_k ?? ba.bb_per_k)} />
          </div>
          <div style={rowGapStyle}>
            <TipBadge label="TB" value={fmt(ba.tb)} />
            <TipBadge label="XBH" value={fmt(ba.xbh)} />
            <TipBadge label="HHB" value={fmt(ba.hhb)} />
            <TipBadge label="PS" value={fmt(ba.ps)} />
            <TipBadge label="PS/PA" value={ba.ps_pa != null ? parseFloat(ba.ps_pa).toFixed(2) : '\u2014'} />
            <TipBadge label="QAB" value={fmt(ba.qab)} />
            <TipBadge label="AB/HR" value={fmt2(ba.ab_hr)} />
          </div>
          <div style={rowGapStyle}>
            <TipBadge label="FB%" value={fmtPct(ba.fb_pct)} />
            <TipBadge label="GB%" value={fmtPct(ba.gb_pct)} />
            <TipBadge label="LD%" value={fmtPct(ba.ld_pct)} />
            <TipBadge label="C%" value={fmtPct(ba.c_pct)} />
          </div>
          <div style={rowGapStyle}>
            <TipBadge label="2OUTRBI" value={fmt(ba.two_out_rbi)} />
            <TipBadge label="GIDP" value={fmt(ba.gidp)} />
            <TipBadge label="GITP" value={fmt(ba.gitp)} />
            <TipBadge label="6+" value={fmt(ba.six_plus)} />
            <TipBadge label="6+%" value={fmtPct(ba.six_plus_pct)} />
            <TipBadge label="2S+3" value={fmt(ba.two_s_three)} />
            <TipBadge label="2S+3%" value={fmtPct(ba.two_s_three_pct)} />
          </div>
        </div>
      )}

      {/* ===== PITCHING STANDARD ===== */}
      {hasData(p) && (
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
            <TipBadge label="SVO" value={fmt(p.svo)} />
            <TipBadge label="SV%" value={fmtPct(p.sv_pct)} />
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
            <TipBadge label="BK" value={fmt(p.bk)} />
            <TipBadge label="PIK" value={fmt(p.pik)} />
            <TipBadge label="LOB" value={fmt(p.lob)} />
          </div>
          <div style={rowGapStyle}>
            <TipBadge label="SB" value={fmt(p.sb)} />
            <TipBadge label="CS" value={fmt(p.cs)} />
            <TipBadge label="SB%" value={fmtPct(p.sb_pct)} />
          </div>
        </div>
      )}

      {/* ===== PITCHING ADVANCED ===== */}
      {hasData(pa2) && (
        <div style={sectionStyle}>
          <div className="section-label">Pitching Advanced</div>
          <div style={rowStyle}>
            <TipBadge label="FIP" value={fmt2(pa2.fip)} />
            <TipBadge label="S%" value={fmtPct(pa2.s_pct)} />
            <TipBadge label="K/BF" value={fmt2(pa2.k_bf)} />
            <TipBadge label="K/BB" value={fmt2(pa2.k_bb)} />
          </div>
          <div style={rowGapStyle}>
            <TipBadge label="P/IP" value={fmt1(pa2.p_ip)} />
            <TipBadge label="P/BF" value={fmt1(pa2.p_bf)} />
            <TipBadge label="BB/INN" value={fmt2(pa2.bb_inn)} />
            <TipBadge label="GO/AO" value={fmt2(pa2.go_ao)} />
          </div>
          <div style={rowGapStyle}>
            <TipBadge label="FPS%" value={fmtPct(pa2.fps_pct)} />
            <TipBadge label="FPSW%" value={fmtPct(pa2.fpsw_pct)} />
            <TipBadge label="FPSO%" value={fmtPct(pa2.fpso_pct)} />
            <TipBadge label="FPSH%" value={fmtPct(pa2.fpsh_pct)} />
          </div>
          <div style={rowGapStyle}>
            <TipBadge label="123INN" value={fmt(pa2.one23_inn)} />
            <TipBadge label="0BBINN" value={fmt(pa2.zero_bb_inn)} />
            <TipBadge label="&lt;3%" value={fmtPct(pa2.lt3_pct)} />
            <TipBadge label="1ST2OUT" value={fmt(pa2.first_2out)} />
            <TipBadge label="LOO" value={fmt(pa2.loo)} />
          </div>
          <div style={rowGapStyle}>
            <TipBadge label="BABIP" value={fmt3(pa2.babip)} />
            <TipBadge label="BA/RISP" value={fmt3(pa2.ba_risp)} />
            <TipBadge label="LD%" value={fmtPct(pa2.ld_pct)} />
            <TipBadge label="GB%" value={fmtPct(pa2.gb_pct)} />
            <TipBadge label="FB%" value={fmtPct(pa2.fb_pct)} />
          </div>
          <div style={rowGapStyle}>
            <TipBadge label="HHB%" value={fmtPct(pa2.hhb_pct)} />
            <TipBadge label="WEAK%" value={fmtPct(pa2.weak_pct)} />
            <TipBadge label="SM%" value={fmtPct(pa2.sm_pct)} />
          </div>
        </div>
      )}

      {/* ===== PITCHING BREAKDOWN (pitch types + velocity) ===== */}
      {hasData(pb) && (
        <div style={sectionStyle}>
          <div className="section-label">Pitch Arsenal</div>
          <div style={rowStyle}>
            <TipBadge label="#P" value={fmt(pb.np)} />
          </div>
          {/* Fastball */}
          {(pb.fb != null || pb.mph_fb != null) && (
            <div style={rowGapStyle}>
              <TipBadge label="FB" value={fmt(pb.fb)} />
              <TipBadge label="S%" value={fmtPct(pb.fbs_pct)} />
              <TipBadge label="SM%" value={fmtPct(pb.fbsm_pct)} />
              <TipBadge label="SW%" value={fmtPct(pb.fbsw_pct)} />
              {pb.mph_fb != null && <TipBadge label="MPH" value={fmt1(pb.mph_fb)} />}
            </div>
          )}
          {/* Change-Up */}
          {(pb.ch != null || pb.mph_ch != null) && (
            <div style={rowGapStyle}>
              <TipBadge label="CH" value={fmt(pb.ch)} />
              <TipBadge label="S%" value={fmtPct(pb.chs_pct)} />
              <TipBadge label="SM%" value={fmtPct(pb.chsm_pct)} />
              <TipBadge label="SW%" value={fmtPct(pb.chsw_pct)} />
              {pb.mph_ch != null && <TipBadge label="MPH" value={fmt1(pb.mph_ch)} />}
            </div>
          )}
          {/* Curveball */}
          {(pb.cb != null || pb.mph_cb != null) && (
            <div style={rowGapStyle}>
              <TipBadge label="CB" value={fmt(pb.cb)} />
              <TipBadge label="S%" value={fmtPct(pb.cbs_pct)} />
              <TipBadge label="SM%" value={fmtPct(pb.cbsm_pct)} />
              <TipBadge label="SW%" value={fmtPct(pb.cbsw_pct)} />
              {pb.mph_cb != null && <TipBadge label="MPH" value={fmt1(pb.mph_cb)} />}
            </div>
          )}
          {/* Slider/Cutter */}
          {(pb.sc != null || pb.mph_sc != null) && (
            <div style={rowGapStyle}>
              <TipBadge label="SC" value={fmt(pb.sc)} />
              <TipBadge label="S%" value={fmtPct(pb.scs_pct)} />
              <TipBadge label="SM%" value={fmtPct(pb.scsm_pct)} />
              <TipBadge label="SW%" value={fmtPct(pb.scsw_pct)} />
              {pb.mph_sc != null && <TipBadge label="MPH" value={fmt1(pb.mph_sc)} />}
            </div>
          )}
          {/* Riseball */}
          {(pb.rb != null || pb.mph_rb != null) && (
            <div style={rowGapStyle}>
              <TipBadge label="RB" value={fmt(pb.rb)} />
              <TipBadge label="S%" value={fmtPct(pb.rbs_pct)} />
              <TipBadge label="SM%" value={fmtPct(pb.rbsm_pct)} />
              <TipBadge label="SW%" value={fmtPct(pb.rbsw_pct)} />
              {pb.mph_rb != null && <TipBadge label="MPH" value={fmt1(pb.mph_rb)} />}
            </div>
          )}
          {/* Dropball */}
          {(pb.db != null || pb.mph_db != null) && (
            <div style={rowGapStyle}>
              <TipBadge label="DB" value={fmt(pb.db)} />
              <TipBadge label="S%" value={fmtPct(pb.dbs_pct)} />
              <TipBadge label="SM%" value={fmtPct(pb.dbsm_pct)} />
              <TipBadge label="SW%" value={fmtPct(pb.dbsw_pct)} />
              {pb.mph_db != null && <TipBadge label="MPH" value={fmt1(pb.mph_db)} />}
            </div>
          )}
          {/* Drop Curve */}
          {(pb.dc != null || pb.mph_dc != null) && (
            <div style={rowGapStyle}>
              <TipBadge label="DC" value={fmt(pb.dc)} />
              <TipBadge label="S%" value={fmtPct(pb.dcs_pct)} />
              <TipBadge label="SM%" value={fmtPct(pb.dcsm_pct)} />
              <TipBadge label="SW%" value={fmtPct(pb.dcsw_pct)} />
              {pb.mph_dc != null && <TipBadge label="MPH" value={fmt1(pb.mph_dc)} />}
            </div>
          )}
          {/* Knuckle Ball */}
          {(pb.kb != null || pb.mph_kb != null) && (
            <div style={rowGapStyle}>
              <TipBadge label="KB" value={fmt(pb.kb)} />
              <TipBadge label="S%" value={fmtPct(pb.kbs_pct)} />
              <TipBadge label="SM%" value={fmtPct(pb.kbsm_pct)} />
              <TipBadge label="SW%" value={fmtPct(pb.kbsw_pct)} />
              {pb.mph_kb != null && <TipBadge label="MPH" value={fmt1(pb.mph_kb)} />}
            </div>
          )}
          {/* Knuckle Curve */}
          {(pb.kc != null || pb.mph_kc != null) && (
            <div style={rowGapStyle}>
              <TipBadge label="KC" value={fmt(pb.kc)} />
              <TipBadge label="S%" value={fmtPct(pb.kcs_pct)} />
              <TipBadge label="SM%" value={fmtPct(pb.kcsm_pct)} />
              <TipBadge label="SW%" value={fmtPct(pb.kcsw_pct)} />
              {pb.mph_kc != null && <TipBadge label="MPH" value={fmt1(pb.mph_kc)} />}
            </div>
          )}
          {/* Other/Off-Speed */}
          {pb.os_pitch != null && (
            <div style={rowGapStyle}>
              <TipBadge label="OS" value={fmt(pb.os_pitch)} />
              <TipBadge label="S%" value={fmtPct(pb.oss_pct)} />
              <TipBadge label="SM%" value={fmtPct(pb.ossm_pct)} />
              <TipBadge label="SW%" value={fmtPct(pb.ossw_pct)} />
            </div>
          )}
        </div>
      )}

      {/* ===== FIELDING STANDARD ===== */}
      {hasData(f) && (
        <div style={sectionStyle}>
          <div className="section-label">Fielding</div>
          <div style={rowStyle}>
            <TipBadge label="FPCT" value={fmt3(f.fpct)} />
            <TipBadge label="TC" value={fmt(f.tc)} />
            <TipBadge label="PO" value={fmt(f.po)} />
            <TipBadge label="A" value={fmt(f.a)} />
            <TipBadge label="E" value={fmt(f.e)} />
            <TipBadge label="DP" value={fmt(f.dp)} />
            <TipBadge label="TP" value={fmt(f.tp)} />
          </div>
        </div>
      )}

      {/* ===== CATCHING ===== */}
      {hasData(c) && (() => {
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
              <TipBadge label="CI" value={fmt(c.ci)} />
            </div>
          </div>
        );
      })()}

      {/* ===== INNINGS PLAYED ===== */}
      {hasData(ip) && (
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
            <TipBadge label="SF" value={fmt(ip.sf)} />
          </div>
        </div>
      )}
    </div>
  );
};

const Roster = ({ team, availability, isMobile = false, isLandscape = false }) => {
  const [expandedPlayer, setExpandedPlayer] = useState(null);

  if (!team || !team.roster) return <div className="loader"></div>;

  const filteredRoster = team.roster.filter(p => p.core !== false);
  const sortedRoster = [...filteredRoster].sort((a, b) => {
    const nameA = `${a.first || ''} ${a.last || ''}`.trim();
    const nameB = `${b.first || ''} ${b.last || ''}`.trim();
    const activeA = availability ? availability[nameA] !== false : true;
    const activeB = availability ? availability[nameB] !== false : true;
    if (activeA !== activeB) return activeA ? -1 : 1;
    const cmp = (a.first || '').localeCompare(b.first || '');
    return cmp !== 0 ? cmp : (a.last || '').localeCompare(b.last || '');
  });

  const activeCount = sortedRoster.filter(p => {
    const name = `${p.first || ''} ${p.last || ''}`.trim();
    return availability ? availability[name] !== false : true;
  }).length;

  return (
    <div>
      <h2 className="view-title">
        Active Roster
        <span style={{ fontSize: 'var(--text-base)', color: 'var(--text-muted)', fontWeight: 'normal' }}>({sortedRoster.length} Players)</span>
        <span style={{ marginLeft: 'auto', fontSize: 'var(--text-sm)', color: 'var(--text-muted)', fontWeight: '600' }}>
          {activeCount} Available
        </span>
      </h2>
      <div className="card-grid" style={isLandscape ? { gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))' } : undefined}>
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
                padding: isLandscape ? 'var(--space-sm)' : 'var(--space-lg)',
                position: 'relative',
                overflow: 'hidden',
                cursor: 'pointer',
                transition: 'all 0.3s ease',
                opacity: isActive ? 1 : 0.6,
                filter: isActive ? 'none' : 'grayscale(0.5)',
                borderLeft: !isActive ? '4px solid #666'
                  : isSub ? '4px solid rgba(63, 143, 136, 0.42)'
                  : '4px solid var(--primary-color)',
                background: isSub && isActive ? 'rgba(63, 143, 136, 0.06)' : undefined
              }}
              onClick={() => setExpandedPlayer(isExpanded ? null : playerKey)}
            >
              {/* Watermark number */}
              {!isMobile && (
                <div style={{
                  position: 'absolute', top: '-15px', right: '-10px',
                  fontSize: '4rem', fontWeight: '900', opacity: '0.05',
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
                    padding: '2px 8px', borderRadius: '4px',
                    fontSize: 'var(--text-xs)', fontWeight: 'bold',
                    letterSpacing: '1px', border: '1px solid rgba(63, 143, 136, 0.28)'
                  }}>SUB</div>
                </div>
              )}

              {/* Player header */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.75rem' }}>
                <div className="player-avatar" style={{
                  background: isActive
                    ? 'linear-gradient(135deg, var(--primary-color), var(--secondary-color))'
                    : '#444',
                  transition: 'all 0.3s ease'
                }}>
                  {player.number}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                    <PlayerName first={player.first} last={player.last} number={player.number} size="md" />
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

              {/* Collapsed: compact summary */}
              {!isExpanded && (
                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                  <TipBadge label="AVG" value={fmt3(b.avg ?? player.avg)} />
                  <TipBadge label="OBP" value={fmt3(b.obp ?? player.obp)} />
                  <TipBadge label="OPS" value={fmt3(b.ops ?? player.ops)} />
                </div>
              )}

              {/* Expanded: full stats */}
              {isExpanded && <ExpandedStats player={player} />}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default Roster;
