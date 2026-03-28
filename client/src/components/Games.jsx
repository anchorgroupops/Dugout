import React, { useState } from 'react';
import { Calendar, ChevronDown, ChevronUp, Home, Plane, Clock } from 'lucide-react';
import { getTodayEST, formatDateMMDDYYYY } from '../utils/formatDate';
import { TipBadge, PlayerName } from './StatTooltip';

// ─── Normalisation helpers ───────────────────────────────────────────────────
// GC-scraped rows are flat { name, pa, ab, h, ... }
// Legacy PDF rows are      { name, pos, batting: { pa, ab, h, ... } }
// Normalise to always return { name, number, pos, at_bats_raw, batting, pitching, fielding, ... }

const normBatting = (row) => {
  if (!row) return {};
  if (row.batting && typeof row.batting === 'object') return row.batting;
  // Flat GC format — extract known batting keys
  const BATTING_KEYS = ['pa','ab','h','singles','doubles','triples','hr','rbi','r','bb','hbp','sac','sf','so','kl','avg','obp','slg','ops','sb'];
  const b = {};
  BATTING_KEYS.forEach(k => { if (row[k] != null) b[k] = row[k]; });
  return b;
};

const normAdvBatting = (row) => {
  if (!row) return null;
  const ADV_KEYS = ['pa','tb','xbh','ba_risp','babip','ps','ps_pa','qab','two_out_rbi','hhb','qab_pct','bb_per_k','ld_pct','fb_pct','gb_pct','c_pct'];
  const b = {};
  ADV_KEYS.forEach(k => { if (row[k] != null) b[k] = row[k]; });
  return Object.keys(b).length ? b : null;
};

const fmt3 = (v) => {
  if (v == null || v === '') return null;
  if (typeof v === 'string' && v.startsWith('.')) return v;
  const n = parseFloat(v);
  if (isNaN(n)) return null;
  const s = n.toFixed(3);
  return (n >= 0 && n < 1) ? s.replace(/^0/, '') : s;
};
const fmtPct = (v) => {
  if (v == null || v === '') return null;
  const n = parseFloat(v);
  return isNaN(n) ? null : `${(n * 100).toFixed(1)}%`;
};

// ─── Player row components ────────────────────────────────────────────────────
const PlayerBattingRow = ({ player }) => {
  const b = normBatting(player);
  const name = player.name || player.player;
  const number = player.number || player.jersey;
  const pos = player.pos;
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '0.75rem',
      padding: '0.5rem 0.75rem', borderRadius: '6px',
      background: 'rgba(0,0,0,0.15)', flexWrap: 'wrap'
    }}>
      <div style={{ minWidth: '120px' }}>
        <PlayerName name={name} number={number} size="sm" />
        {pos && <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginLeft: '0.4rem' }}>({pos})</span>}
      </div>
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        <TipBadge label="PA" value={b.pa} />
        <TipBadge label="AB" value={b.ab} />
        <TipBadge label="H" value={b.h} />
        <TipBadge label="2B" value={b.doubles} />
        <TipBadge label="3B" value={b.triples} />
        <TipBadge label="HR" value={b.hr} />
        <TipBadge label="BB" value={b.bb} />
        <TipBadge label="HBP" value={b.hbp} />
        <TipBadge label="SO" value={b.so} />
        <TipBadge label="RBI" value={b.rbi} />
        <TipBadge label="R" value={b.r} />
        <TipBadge label="SB" value={b.sb} />
        <TipBadge label="AVG" value={fmt3(b.avg)} />
        <TipBadge label="OBP" value={fmt3(b.obp)} />
      </div>
      {player.at_bats_raw?.length > 0 && (
        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', fontStyle: 'italic' }}>
          {player.at_bats_raw.join(' \u00b7 ')}
        </div>
      )}
    </div>
  );
};

const PlayerAdvBattingRow = ({ player }) => {
  const b = normAdvBatting(player);
  if (!b) return null;
  const name = player.name || player.player;
  const number = player.number || player.jersey;
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '0.75rem',
      padding: '0.5rem 0.75rem', borderRadius: '6px',
      background: 'rgba(0,0,0,0.15)', flexWrap: 'wrap'
    }}>
      <div style={{ minWidth: '120px' }}>
        <PlayerName name={name} number={number} size="sm" />
      </div>
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        <TipBadge label="PA" value={b.pa} />
        <TipBadge label="TB" value={b.tb} />
        <TipBadge label="XBH" value={b.xbh} />
        <TipBadge label="QAB" value={b.qab} />
        <TipBadge label="QAB%" value={fmtPct(b.qab_pct != null ? b.qab_pct / 100 : null) ?? (b.qab != null && b.pa ? `${((b.qab / b.pa) * 100).toFixed(1)}%` : null)} />
        <TipBadge label="PS/PA" value={b.ps_pa != null ? parseFloat(b.ps_pa).toFixed(2) : null} />
        <TipBadge label="BABIP" value={fmt3(b.babip)} />
        <TipBadge label="BA/RISP" value={fmt3(b.ba_risp)} />
        <TipBadge label="LD%" value={fmtPct(b.ld_pct != null ? b.ld_pct / 100 : null)} />
        <TipBadge label="GB%" value={fmtPct(b.gb_pct != null ? b.gb_pct / 100 : null)} />
        <TipBadge label="FB%" value={fmtPct(b.fb_pct != null ? b.fb_pct / 100 : null)} />
        <TipBadge label="HHB" value={b.hhb} />
        <TipBadge label="2-Out RBI" value={b.two_out_rbi} />
      </div>
    </div>
  );
};

const PlayerPitchingRow = ({ player }) => {
  const name = player.name || player.player;
  const number = player.number || player.jersey;
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '0.75rem',
      padding: '0.5rem 0.75rem', borderRadius: '6px',
      background: 'rgba(0,0,0,0.15)', flexWrap: 'wrap'
    }}>
      <div style={{ minWidth: '120px' }}>
        <PlayerName name={name} number={number} size="sm" />
      </div>
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        <TipBadge label="IP" value={player.ip != null ? parseFloat(player.ip).toFixed(1) : null} />
        <TipBadge label="GS" value={player.gs} />
        <TipBadge label="BF" value={player.bf} />
        <TipBadge label="#P" value={player.np} />
        <TipBadge label="H" value={player.h} />
        <TipBadge label="R" value={player.r} />
        <TipBadge label="ER" value={player.er} />
        <TipBadge label="BB" value={player.bb} />
        <TipBadge label="HBP" value={player.hbp} />
        <TipBadge label="SO" value={player.so} />
        <TipBadge label="KL" value={player.kl} />
        <TipBadge label="ERA" value={player.era != null ? parseFloat(player.era).toFixed(2) : null} />
        <TipBadge label="WHIP" value={player.whip != null ? parseFloat(player.whip).toFixed(2) : null} />
        <TipBadge label="BAA" value={player.baa != null ? fmt3(player.baa) : null} />
        <TipBadge label="WP" value={player.wp} />
        <TipBadge label="BK" value={player.bk} />
        <TipBadge label="LOB" value={player.lob} />
      </div>
    </div>
  );
};

const PlayerFieldingRow = ({ player }) => {
  const name = player.name || player.player;
  const number = player.number || player.jersey;
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '0.75rem',
      padding: '0.5rem 0.75rem', borderRadius: '6px',
      background: 'rgba(0,0,0,0.15)', flexWrap: 'wrap'
    }}>
      <div style={{ minWidth: '120px' }}>
        <PlayerName name={name} number={number} size="sm" />
      </div>
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        <TipBadge label="TC" value={player.tc} />
        <TipBadge label="PO" value={player.po} />
        <TipBadge label="A" value={player.a} />
        <TipBadge label="E" value={player.e} />
        <TipBadge label="FPCT" value={player.fpct != null ? parseFloat(player.fpct).toFixed(3) : null} />
        <TipBadge label="DP" value={player.dp} />
      </div>
    </div>
  );
};

const PlayerAdvPitchingRow = ({ player }) => {
  const name = player.name || player.player;
  const number = player.number || player.jersey;
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '0.75rem',
      padding: '0.5rem 0.75rem', borderRadius: '6px',
      background: 'rgba(0,0,0,0.15)', flexWrap: 'wrap'
    }}>
      <div style={{ minWidth: '120px' }}>
        <PlayerName name={name} number={number} size="sm" />
      </div>
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        <TipBadge label="IP" value={player.ip != null ? parseFloat(player.ip).toFixed(1) : null} />
        <TipBadge label="S%" value={player.s_pct != null ? `${parseFloat(player.s_pct).toFixed(1)}%` : null} />
        <TipBadge label="P/IP" value={player.p_ip != null ? parseFloat(player.p_ip).toFixed(1) : null} />
        <TipBadge label="P/BF" value={player.p_bf != null ? parseFloat(player.p_bf).toFixed(1) : null} />
        <TipBadge label="FPS%" value={player.fps_pct != null ? `${parseFloat(player.fps_pct).toFixed(1)}%` : null} />
        <TipBadge label="FPSw%" value={player.fpsw_pct != null ? `${parseFloat(player.fpsw_pct).toFixed(1)}%` : null} />
        <TipBadge label="FPSo%" value={player.fpso_pct != null ? `${parseFloat(player.fpso_pct).toFixed(1)}%` : null} />
        <TipBadge label="FPSh%" value={player.fpsh_pct != null ? `${parseFloat(player.fpsh_pct).toFixed(1)}%` : null} />
        <TipBadge label="LOO" value={player.loo} />
        <TipBadge label="1st2Out" value={player.first_2out} />
        <TipBadge label="1-2-3" value={player.one23_inn} />
      </div>
    </div>
  );
};

const PlayerCatchingRow = ({ player }) => {
  const name = player.name || player.player;
  const number = player.number || player.jersey;
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '0.75rem',
      padding: '0.5rem 0.75rem', borderRadius: '6px',
      background: 'rgba(0,0,0,0.15)', flexWrap: 'wrap'
    }}>
      <div style={{ minWidth: '120px' }}>
        <PlayerName name={name} number={number} size="sm" />
      </div>
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        <TipBadge label="INN" value={player.inn != null ? parseFloat(player.inn).toFixed(1) : null} />
        <TipBadge label="SB-ATT" value={player.sb_att} />
        <TipBadge label="SB" value={player.sb} />
        <TipBadge label="CS" value={player.cs} />
        <TipBadge label="CS%" value={player.cs_pct != null ? `${parseFloat(player.cs_pct).toFixed(1)}%` : null} />
        <TipBadge label="PB" value={player.pb} />
        <TipBadge label="PIK" value={player.pik} />
      </div>
    </div>
  );
};

const PlayerOppBattingRow = ({ player }) => {
  const b = normBatting(player);
  const name = player.name || player.player;
  const number = player.number || player.jersey;
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '0.75rem',
      padding: '0.5rem 0.75rem', borderRadius: '6px',
      background: 'rgba(248, 113, 113, 0.05)', flexWrap: 'wrap',
      border: '1px solid rgba(248, 113, 113, 0.1)'
    }}>
      <div style={{ minWidth: '120px' }}>
        <PlayerName name={name} number={number} size="sm" />
      </div>
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        <TipBadge label="PA" value={b.pa} />
        <TipBadge label="AB" value={b.ab} />
        <TipBadge label="H" value={b.h} />
        <TipBadge label="2B" value={b.doubles} />
        <TipBadge label="HR" value={b.hr} />
        <TipBadge label="BB" value={b.bb} />
        <TipBadge label="SO" value={b.so} />
        <TipBadge label="RBI" value={b.rbi} />
        <TipBadge label="AVG" value={fmt3(b.avg)} />
        <TipBadge label="OBP" value={fmt3(b.obp)} />
      </div>
    </div>
  );
};

// ─── Result badge ─────────────────────────────────────────────────────────────
const ResultBadge = ({ result }) => {
  if (!result) return null;
  const upper = result.toUpperCase();
  if (upper === 'W') return <span className="result-badge result-badge--win">WIN</span>;
  if (upper === 'T') return <span className="result-badge result-badge--tie">TIE</span>;
  return <span className="result-badge result-badge--loss">LOSS</span>;
};

// ─── Tab bar ──────────────────────────────────────────────────────────────────
const TabBar = ({ tabs, active, onChange }) => (
  <div style={{
    display: 'flex', gap: '0.25rem', flexWrap: 'wrap',
    marginBottom: '0.75rem', borderBottom: '1px solid rgba(255,255,255,0.08)',
    paddingBottom: '0.5rem'
  }}>
    {tabs.map(t => (
      <button key={t.id} onClick={() => onChange(t.id)} style={{
        padding: '0.25rem 0.75rem', borderRadius: '4px', border: 'none',
        cursor: 'pointer', fontSize: 'var(--text-xs)', fontWeight: active === t.id ? '700' : '500',
        background: active === t.id ? 'rgba(4,101,104,0.35)' : 'rgba(255,255,255,0.06)',
        color: active === t.id ? 'var(--primary-color)' : 'var(--text-muted)',
        transition: 'all 0.15s',
      }}>
        {t.label}{t.count != null ? ` (${t.count})` : ''}
      </button>
    ))}
  </div>
);

// ─── Expanded detail panel ────────────────────────────────────────────────────
const GameDetailPanel = ({ gameDetail, source }) => {
  const [tab, setTab] = useState('batting');

  const batting        = gameDetail.sharks_batting           || [];
  const advBatting     = gameDetail.sharks_batting_advanced  || [];
  const pitching       = gameDetail.sharks_pitching          || [];
  const advPitching    = gameDetail.sharks_pitching_advanced || [];
  const fielding       = gameDetail.sharks_fielding          || [];
  const catching       = gameDetail.sharks_catching          || [];
  const oppBatting     = gameDetail.opponent_batting         || [];
  const oppPitching    = gameDetail.opponent_pitching        || [];

  const tabs = [
    batting.length      ? { id: 'batting',      label: 'Batting',      count: batting.length }      : null,
    advBatting.length   ? { id: 'adv_batting',  label: 'Adv. Batting', count: advBatting.length }   : null,
    pitching.length     ? { id: 'pitching',     label: 'Pitching',     count: pitching.length }     : null,
    advPitching.length  ? { id: 'adv_pitching', label: 'Adv. Pitch',   count: advPitching.length }  : null,
    fielding.length     ? { id: 'fielding',     label: 'Fielding',     count: fielding.length }     : null,
    catching.length     ? { id: 'catching',     label: 'Catching',     count: catching.length }     : null,
    oppBatting.length   ? { id: 'opp_batting',  label: 'Opp Batting',  count: oppBatting.length }   : null,
    oppPitching.length  ? { id: 'opp_pitching', label: 'Opp Pitching', count: oppPitching.length }  : null,
  ].filter(Boolean);

  // If no tabs available
  if (tabs.length === 0) {
    return (
      <div style={{ padding: '1rem', color: 'var(--text-muted)', fontStyle: 'italic', fontSize: 'var(--text-sm)' }}>
        No stat detail available for this game.
      </div>
    );
  }

  // Auto-select first available tab if current tab is gone
  const validTabIds = tabs.map(t => t.id);
  const activeTab = validTabIds.includes(tab) ? tab : validTabIds[0];

  return (
    <div>
      {tabs.length > 1 && <TabBar tabs={tabs} active={activeTab} onChange={setTab} />}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
        {activeTab === 'batting'      && batting.map((p, i)     => <PlayerBattingRow key={i} player={p} />)}
        {activeTab === 'adv_batting'  && advBatting.map((p, i)  => <PlayerAdvBattingRow key={i} player={p} />)}
        {activeTab === 'pitching'     && pitching.map((p, i)    => <PlayerPitchingRow key={i} player={p} />)}
        {activeTab === 'adv_pitching' && advPitching.map((p, i) => <PlayerAdvPitchingRow key={i} player={p} />)}
        {activeTab === 'fielding'     && fielding.map((p, i)    => <PlayerFieldingRow key={i} player={p} />)}
        {activeTab === 'catching'     && catching.map((p, i)    => <PlayerCatchingRow key={i} player={p} />)}
        {activeTab === 'opp_batting'  && oppBatting.map((p, i)  => <PlayerOppBattingRow key={i} player={p} />)}
        {activeTab === 'opp_pitching' && oppPitching.map((p, i) => <PlayerPitchingRow key={i} player={p} />)}
      </div>

      {source && (
        <div style={{ marginTop: '0.75rem', fontSize: 'var(--text-xs)', color: 'rgba(255,255,255,0.25)', fontStyle: 'italic' }}>
          Source: {source}
        </div>
      )}
    </div>
  );
};

// ─── GameCard ─────────────────────────────────────────────────────────────────
const GameCard = ({ game, onExpand, isExpanded, gameDetail, isMobile = false, isLandscape = false }) => {
  const t = game.sharks_totals || {};
  const isHome = game.sharks_side === 'home';
  const dateStr = game.date ? formatDateMMDDYYYY(game.date) : 'Unknown Date';
  const isWin = game.result === 'W';
  const isTie = game.result === 'T';
  const scoreStr = game.score || game.score_str || '';

  // Parse score respecting result direction (handle both hyphen and en-dash)
  let sharksScore = null, oppScore = null;
  if (scoreStr) {
    const parts = scoreStr.split(/[-\u2013]/).map(Number);
    if (parts.length === 2 && !isNaN(parts[0]) && !isNaN(parts[1])) {
      if (game.result === 'W') { sharksScore = Math.max(...parts); oppScore = Math.min(...parts); }
      else if (game.result === 'L') { sharksScore = Math.min(...parts); oppScore = Math.max(...parts); }
      else { [sharksScore, oppScore] = parts; }
    }
  }

  const canExpand = !isMobile && (game.sharks_totals || game.source === 'gc_full_scraper_v2');

  const cardTint = isWin
    ? 'rgba(35, 134, 54, 0.06)'
    : isTie
      ? 'rgba(251, 191, 36, 0.06)'
      : game.result === 'L'
        ? 'rgba(220, 70, 70, 0.06)'
        : undefined;
  const cardBorder = isWin
    ? '1px solid rgba(35, 134, 54, 0.2)'
    : isTie
      ? '1px solid rgba(251, 191, 36, 0.2)'
      : game.result === 'L'
        ? '1px solid rgba(220, 70, 70, 0.2)'
        : undefined;

  return (
    <div
      className="glass-panel"
      style={{
        padding: isLandscape ? 'var(--space-sm)' : isMobile ? 'var(--space-lg)' : '1.25rem',
        cursor: canExpand ? 'pointer' : 'default',
        background: cardTint,
        border: cardBorder,
      }}
      onClick={canExpand ? onExpand : undefined}
    >
      {/* Header row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.75rem' }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem', flexWrap: 'wrap' }}>
            <span className={`home-away-pill ${isHome ? 'home-away-pill--home' : 'home-away-pill--away'}`}>
              {isHome ? <Home size={10} /> : <Plane size={10} />}
              {isHome ? 'HOME' : 'AWAY'}
            </span>
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{dateStr}</span>
            <ResultBadge result={game.result} />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem' }}>
            <h3 style={{ fontSize: isMobile ? 'var(--text-base)' : '1.1rem', margin: 0 }}>vs. {game.opponent}</h3>
            {sharksScore != null && (
              <span style={{
                fontSize: isMobile ? '1.5rem' : '1.75rem',
                fontWeight: '800',
                color: isTie ? 'var(--warning, #fbbf24)' : (isWin ? 'var(--success, #4ade80)' : 'var(--danger, #f87171)'),
                letterSpacing: '1px',
                lineHeight: 1,
                whiteSpace: 'nowrap',
              }}>{sharksScore}{'\u2013'}{oppScore}</span>
            )}
          </div>
        </div>
        {canExpand && (isExpanded ? <ChevronUp size={18} color="var(--text-muted)" /> : <ChevronDown size={18} color="var(--text-muted)" />)}
      </div>

      {/* Summary stat badges */}
      {game.sharks_totals && (
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          <TipBadge label="PA" value={t.pa} />
          <TipBadge label="H" value={t.h} />
          {!isMobile && <TipBadge label="AB" value={t.ab} />}
          {!isMobile && <TipBadge label="2B" value={t.doubles || 0} />}
          {!isMobile && <TipBadge label="HR" value={t.hr || 0} />}
          {!isMobile && <TipBadge label="BB" value={t.bb} />}
          {!isMobile && <TipBadge label="HBP" value={t.hbp != null ? t.hbp : 0} />}
          {!isMobile && <TipBadge label="SO" value={t.so} />}
          <TipBadge label="AVG" value={t.avg != null ? fmt3(t.avg) : null} />
        </div>
      )}

      {/* Expanded detail */}
      {!isMobile && isExpanded && gameDetail && (
        <div style={{ marginTop: '1rem', borderTop: '1px solid var(--surface-border)', paddingTop: '1rem' }}>
          <GameDetailPanel
            gameDetail={gameDetail}
            source={game.pdf_file || game.source || null}
          />
        </div>
      )}
    </div>
  );
};

// ─── Upcoming schedule ────────────────────────────────────────────────────────
const ScheduleRow = ({ game }) => {
  const isHome = game.home_away === 'home';
  const dateStr = game.date ? formatDateMMDDYYYY(game.date) : '\u2014';
  const isNext = game._isNext;

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '0.75rem', padding: '0.625rem 0.75rem',
      borderRadius: '8px', flexWrap: 'wrap', minHeight: 'var(--touch-min)',
      background: isNext ? 'rgba(4, 101, 104, 0.08)' : 'rgba(0,0,0,0.15)',
      border: isNext ? '1px solid rgba(4, 101, 104, 0.2)' : '1px solid transparent',
    }}>
      <span style={{ minWidth: '110px', fontSize: 'var(--text-sm)', color: 'var(--text-muted)' }}>{dateStr}</span>
      <span className={`home-away-pill ${isHome ? 'home-away-pill--home' : 'home-away-pill--away'}`}>
        {isHome ? <Home size={9} /> : <Plane size={9} />}
        {isHome ? 'HOME' : 'AWAY'}
      </span>
      <span style={{ flex: 1, fontWeight: isNext ? '700' : '500', fontSize: 'var(--text-sm)' }}>
        {isNext && (
          <span style={{ color: 'var(--primary-color)', marginRight: '0.4rem', fontSize: 'var(--text-xs)', fontWeight: '800', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
            NEXT &#9654;
          </span>
        )}
        vs. {game.opponent}
      </span>
      {game.time && <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{game.time}</span>}
    </div>
  );
};

// ─── Main Games component ─────────────────────────────────────────────────────
const Games = ({ gamesData, schedule, isMobile = false, isLandscape = false }) => {
  const [expanded, setExpanded] = useState(null);
  const [details, setDetails] = useState({});

  const fetchDetail = async (gameId) => {
    if (details[gameId]) return;
    try {
      const res = await fetch(`/api/games/${gameId}`);
      if (res.ok) {
        const data = await res.json();
        setDetails(prev => ({ ...prev, [gameId]: data }));
      }
    } catch (e) {
      console.error('Failed to fetch game detail', e);
    }
  };

  const handleExpand = (gameId) => {
    if (expanded === gameId) {
      setExpanded(null);
    } else {
      setExpanded(gameId);
      fetchDetail(gameId);
    }
  };

  const today = getTodayEST();
  const upcoming = (schedule?.upcoming || [])
    .filter(g => g.date >= today)
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(0, isMobile ? 4 : 10)
    .map((g, i) => ({ ...g, _isNext: i === 0 }));

  const sorted = [...(gamesData || [])].sort((a, b) => (b.date || '').localeCompare(a.date || ''));

  return (
    <div>
      <h2 className="view-title">
        <Calendar size={isMobile ? 20 : 24} color="var(--primary-color)" /> Games
      </h2>

      {upcoming.length > 0 && (
        <div className="glass-panel" style={{ padding: isLandscape ? 'var(--space-sm)' : isMobile ? 'var(--space-lg)' : '1.25rem', marginBottom: isLandscape ? 'var(--space-sm)' : isMobile ? 'var(--space-md)' : '2rem' }}>
          <div className="section-label" style={{
            color: 'var(--primary-color)', fontSize: 'var(--text-base)',
            fontWeight: '800', letterSpacing: '0.5px', textTransform: 'uppercase',
            borderBottom: '2px solid rgba(4, 101, 104, 0.3)',
            paddingBottom: '0.5rem', marginBottom: '0.75rem',
          }}>Upcoming Schedule ({upcoming.length} games)</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
            {upcoming.map((g, i) => <ScheduleRow key={i} game={g} />)}
          </div>
        </div>
      )}

      {upcoming.length > 0 && sorted.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', margin: '2rem 0 1.5rem' }}>
          <div style={{ flex: 1, height: '2px', background: 'linear-gradient(to right, transparent, rgba(255,255,255,0.15), transparent)' }} />
          <span style={{ fontSize: 'var(--text-sm)', fontWeight: '700', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px' }}>
            Past Games ({sorted.length})
          </span>
          <div style={{ flex: 1, height: '2px', background: 'linear-gradient(to right, transparent, rgba(255,255,255,0.15), transparent)' }} />
        </div>
      )}

      {sorted.length > 0 ? (
        <>
          <div style={{
          display: isLandscape ? 'grid' : 'flex',
          gridTemplateColumns: isLandscape ? 'repeat(auto-fill, minmax(280px, 1fr))' : undefined,
          flexDirection: isLandscape ? undefined : 'column',
          gap: isLandscape ? 'var(--space-sm)' : 'var(--space-md)',
        }}>
            {sorted.map(game => (
              <GameCard
                key={game.game_id}
                game={game}
                isExpanded={expanded === game.game_id}
                gameDetail={details[game.game_id] || null}
                isMobile={isMobile}
                isLandscape={isLandscape}
                onExpand={() => handleExpand(game.game_id)}
              />
            ))}
          </div>
        </>
      ) : (
        <div className="glass-panel" style={{ padding: '2rem', textAlign: 'center' }}>
          <p style={{ color: 'var(--text-muted)' }}>No past game data yet.</p>
        </div>
      )}
    </div>
  );
};

export default Games;
