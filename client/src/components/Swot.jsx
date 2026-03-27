import React, { useState, useEffect } from 'react';
import { AlertTriangle, TrendingUp, ShieldAlert, Target, ChevronDown, ChevronUp, Swords, Clock, Home, Plane, Zap, ThumbsDown, CheckCircle, AlertCircle, CircleDot, Shield, Eye } from 'lucide-react';
import { getTodayEST, formatDateMMDDYYYY } from '../utils/formatDate';
import { TipBadge, PlayerName } from './StatTooltip';
import OpponentFieldMap from './OpponentFieldMap';

const quadrantIcons = {
  'Strengths': { Icon: CheckCircle, color: 'var(--success)' },
  'Weaknesses': { Icon: AlertCircle, color: 'var(--danger)' },
  'Opportunities': { Icon: TrendingUp, color: '#3b9ede' },
  'Threats': { Icon: ShieldAlert, color: '#c87533' },
};

const SwotQuadrant = ({ title, items, color, icon }) => {
  const itemIcon = quadrantIcons[title] || null;
  return (
    <div>
      <h4 className="swot-label" style={{ color }}>
        {icon} {title}
      </h4>
      {items?.length > 0 ? (
        <div style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)', margin: 0, display: 'flex', flexDirection: 'column', gap: '3px' }}>
          {items.map((s, i) => {
            const ItemIcon = itemIcon?.Icon;
            return (
              <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: '0.4rem' }}>
                {ItemIcon && <ItemIcon size={14} color={itemIcon.color} style={{ flexShrink: 0, marginTop: '2px' }} />}
                <span>{s}</span>
              </div>
            );
          })}
        </div>
      ) : (
        <p style={{ fontSize: 'var(--text-sm)', color: 'rgba(255,255,255,0.3)', fontStyle: 'italic', margin: 0 }}>Need more data</p>
      )}
    </div>
  );
};

const fmtStat = (v) => {
  if (v == null || v === '' || v === 0 || v === '0' || v === '0.0') return '\u2014';
  const n = Number(v);
  if (isNaN(n)) return v;
  if (n === 0) return '\u2014';
  // Rates between 0-1 → .xxx format; percentages/larger values → as-is
  if (n > 0 && n < 1) return n.toFixed(3).replace(/^0/, '');
  if (Number.isInteger(n)) return String(n);
  return n.toFixed(2);
};

const StatCompare = ({ label, ours, theirs, lowerIsBetter }) => {
  const oFmt = fmtStat(ours);
  const tFmt = fmtStat(theirs);
  const oNum = Number(ours || 0);
  const tNum = Number(theirs || 0);
  const diff = lowerIsBetter ? tNum - oNum : oNum - tNum;
  const color = (oFmt === '\u2014' || tFmt === '\u2014') ? 'var(--text-muted)' : diff > 0 ? 'var(--success)' : diff < 0 ? 'var(--danger)' : 'var(--text-muted)';
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: 'minmax(0, 70px) minmax(0, 60px) 30px minmax(0, 60px)', alignItems: 'center',
      gap: '0.25rem', padding: '0.4rem 0', fontSize: 'var(--text-sm)'
    }}>
      <span style={{ color: 'var(--text-muted)', fontSize: 'var(--text-xs)', textTransform: 'uppercase' }}>{label}</span>
      <span style={{ textAlign: 'right', fontWeight: '600', color }}>{oFmt}</span>
      <span style={{ textAlign: 'center', color: 'rgba(255,255,255,0.2)', fontSize: 'var(--text-xs)' }}>vs</span>
      <span style={{ fontWeight: '600', color: 'var(--text-muted)' }}>{tFmt}</span>
    </div>
  );
};

const MatchupPanel = ({ defaultOpponent, isMobile = false }) => {
  const [opponents, setOpponents] = useState([]);
  const [selected, setSelected] = useState('');
  const [matchup, setMatchup] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch('/api/opponents')
      .then(r => r.ok ? r.json() : [])
      .then(data => {
        setOpponents(data);
        if (defaultOpponent) {
          const matched = data.find(o => o.team_name.toLowerCase() === defaultOpponent.toLowerCase() || o.slug === defaultOpponent.toLowerCase().replace(/ /g, '_'));
          if (matched && selected !== matched.slug) {
            handleSelect(matched.slug);
          }
        }
      })
      .catch(() => setOpponents([]));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaultOpponent]);

  const handleSelect = async (slug) => {
    setSelected(slug);
    if (!slug) { setMatchup(null); return; }
    setLoading(true);
    try {
      const res = await fetch(`/api/matchup/${slug}`);
      if (res.ok) setMatchup(await res.json());
    } catch (e) {
      console.error('Matchup fetch failed', e);
    } finally {
      setLoading(false);
    }
  };

  const isNextGame = defaultOpponent && selected === opponents.find(o =>
    o.team_name.toLowerCase() === defaultOpponent.toLowerCase() ||
    o.slug === defaultOpponent.toLowerCase().replace(/ /g, '_')
  )?.slug;

  if (opponents.length === 0) {
    return (
      <div className="glass-panel" style={{ padding: 'var(--space-xl)', marginBottom: '2rem', opacity: 0.7 }}>
        <h3 style={{ color: 'var(--primary-color)', display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
          <Swords size={20} /> Matchup Analysis
        </h3>
        <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)' }}>
          No opponent data available yet. Run the league scraper to populate opponent stats.
        </p>
      </div>
    );
  }

  return (
    <div className="glass-panel" style={{ padding: 'var(--space-xl)', marginBottom: '0' }}>
      <div style={{ marginBottom: '1rem' }}>
        <h3 style={{ margin: 0, color: 'var(--primary-color)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Swords size={20} /> {isNextGame ? 'Next Game Matchup' : 'Matchup Analysis'}
        </h3>
        {isNextGame && (
          <div style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)', marginTop: '0.25rem', paddingLeft: '1.75rem' }}>
            vs {defaultOpponent}
          </div>
        )}
      </div>

      <div style={{ marginBottom: '1rem' }}>
        <select
          value={selected}
          onChange={e => handleSelect(e.target.value)}
          style={{
            padding: '0.5rem 0.75rem', borderRadius: '6px', minHeight: 'var(--touch-min)',
            background: 'rgba(0,0,0,0.3)', border: '1px solid var(--surface-border)',
            color: 'var(--text-main)', fontSize: 'var(--text-sm)', fontFamily: 'inherit', cursor: 'pointer',
            width: '100%', maxWidth: '320px'
          }}
        >
          <option value="">Select opponent...</option>
          {opponents.map(o => (
            <option key={o.slug} value={o.slug}>
              {o.team_name} - {o.roster_size} players
            </option>
          ))}
        </select>
      </div>

      {loading && <div className="loader" style={{ margin: '1rem auto' }}></div>}

      {matchup && !loading && (
        <div>
          <div style={{
            padding: '0.75rem 1rem', borderRadius: '8px', marginBottom: matchup.empty ? '0' : '1rem',
            background: matchup.empty ? 'rgba(4,101,104,0.18)' : 'rgba(4, 101, 104, 0.08)',
            border: `1px solid ${matchup.empty ? 'rgba(130,203,195,0.5)' : 'rgba(4, 101, 104, 0.2)'}`,
            fontSize: 'var(--text-sm)', fontWeight: '600',
            color: matchup.empty ? '#82CBC3' : 'var(--primary-color)',
            display: 'flex', alignItems: 'center', gap: '0.6rem'
          }}>
            {matchup.empty && <AlertTriangle size={16} color="#82CBC3" style={{ flexShrink: 0 }} />}
            {matchup.recommendation}
          </div>
          <div style={{ marginTop: '0.45rem', marginBottom: matchup.empty ? '0.85rem' : '0.5rem', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
            Data source: {matchup.data_source === 'opponent_game_history'
              ? 'scorebook game history'
              : matchup.data_source === 'opponent_team_json'
                ? 'opponent team feed'
                : matchup.data_source === 'opponent_public_games'
                  ? 'opponent public game feed'
                : 'none'}
            {matchup.empty && matchup.reason ? ` \u00b7 reason: ${matchup.reason}` : ''}
            {!matchup.empty && matchup.opponent_ab > 0 ? ` \u00b7 ${matchup.opponent_ab} opp. AB on record` : ''}
          </div>
          {!matchup.empty && matchup.batting_sample_limited && (
            <div style={{
              marginBottom: '0.85rem', padding: '0.4rem 0.65rem', borderRadius: '6px',
              background: 'rgba(251,191,36,0.07)', border: '1px solid rgba(251,191,36,0.2)',
              fontSize: 'var(--text-xs)', color: 'rgba(251,191,36,0.8)',
              display: 'flex', alignItems: 'center', gap: '0.4rem',
            }}>
              ⚠️ Stat comparisons require 10+ opponent AB on record. Advantages shown are based on limited game-fragment data — treat as directional only.
            </div>
          )}

          {!matchup.empty && (
            <>
              <div style={{ overflowX: 'auto', maxWidth: '100%' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem', marginBottom: '1rem' }}>
                <div>
                  <div className="section-label">Batting</div>
                  <StatCompare label="AVG" ours={matchup.our_stats.batting.avg} theirs={matchup.their_stats.batting.avg} />
                  <StatCompare label="OBP" ours={matchup.our_stats.batting.obp} theirs={matchup.their_stats.batting.obp} />
                  <StatCompare label="OPS" ours={matchup.our_stats.batting.ops} theirs={matchup.their_stats.batting.ops} />
                  <StatCompare label="QAB%" ours={matchup.our_stats.batting_advanced?.qab_pct ?? 0} theirs={matchup.their_stats.batting_advanced?.qab_pct ?? 0} />
                  <StatCompare label="C%" ours={matchup.our_stats.batting_advanced?.c_pct ?? 0} theirs={matchup.their_stats.batting_advanced?.c_pct ?? 0} />
                  <StatCompare label="LD%" ours={matchup.our_stats.batting_advanced?.ld_pct ?? 0} theirs={matchup.their_stats.batting_advanced?.ld_pct ?? 0} />
                  <StatCompare label="K%" ours={matchup.our_stats.batting.k_rate} theirs={matchup.their_stats.batting.k_rate} lowerIsBetter />
                  <StatCompare label="BB%" ours={matchup.our_stats.batting.bb_rate} theirs={matchup.their_stats.batting.bb_rate} />
                </div>
                <div>
                  <div className="section-label">Pitching</div>
                  <StatCompare label="ERA" ours={matchup.our_stats.pitching.era} theirs={matchup.their_stats.pitching.era} lowerIsBetter />
                  <StatCompare label="WHIP" ours={matchup.our_stats.pitching.whip} theirs={matchup.their_stats.pitching.whip} lowerIsBetter />
                  <StatCompare label="K/IP" ours={matchup.our_stats.pitching.k_per_ip} theirs={matchup.their_stats.pitching.k_per_ip} />
                  <StatCompare label="FPCT" ours={matchup.our_stats.fielding.fpct} theirs={matchup.their_stats.fielding.fpct} />
                </div>
              </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                <div>
                  <div className="section-label" style={{ color: 'var(--success)' }}>Our Advantages</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                    {matchup.our_advantages.map((a, i) => (
                      <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem', fontSize: 'var(--text-sm)', color: 'var(--text-muted)' }}>
                        <span style={{ color: 'var(--success)', fontSize: '1rem', lineHeight: 1, flexShrink: 0 }}>{'\u2714'}</span>
                        <span>{a}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <div className="section-label" style={{ color: 'var(--danger)' }}>Their Advantages</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                    {matchup.their_advantages.map((a, i) => (
                      <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem', fontSize: 'var(--text-sm)', color: 'var(--text-muted)' }}>
                        <span style={{ color: 'var(--danger)', fontSize: '1rem', lineHeight: 1, flexShrink: 0 }}>{'\u26A0'}</span>
                        <span>{a}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {matchup.key_matchups.length > 0 && (
                <div style={{ marginTop: '1rem', paddingTop: '0.75rem', borderTop: '1px solid var(--surface-border)' }}>
                  <div className="section-label" style={{ color: 'var(--warning)' }}>Key Matchups</div>
                  <ul style={{ paddingLeft: '1.2rem', fontSize: 'var(--text-sm)', color: 'var(--text-muted)', margin: 0 }}>
                    {matchup.key_matchups.map((m, i) => <li key={i} style={{ marginBottom: '2px' }}>{m}</li>)}
                  </ul>
                </div>
              )}

              {matchup.their_roster?.length > 0 && (
                <div style={{ marginTop: '1rem', paddingTop: '0.75rem', borderTop: '1px solid var(--surface-border)' }}>
                  <div className="section-label section-label--muted">
                    Roster ({matchup.their_roster.length})
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
                    {[...matchup.their_roster].sort((a,b) => {
                      const sortKey = (p) => {
                        if (p.last) return `${p.last} ${p.first || ''}`.trim();
                        const n = (p.name || '').trim();
                        const parts = n.split(' ');
                        return parts.length > 1
                          ? `${parts[parts.length - 1]} ${parts.slice(0, -1).join(' ')}`
                          : n;
                      };
                      return sortKey(a).toLowerCase().localeCompare(sortKey(b).toLowerCase());
                    }).map((p, i) => (
                      <span key={i} style={{
                        background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)',
                        borderRadius: '6px', padding: '3px 8px', fontSize: 'var(--text-xs)', color: 'var(--text-muted)'
                      }}>
                        <PlayerName
                          name={p.name || `${p.first || ''} ${p.last || ''}`.trim()}
                          number={p.number}
                          size="xs"
                        />
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* ── Opponent Field Tendencies (spray chart inference) ── */}
              <div style={{ marginTop: '1rem', paddingTop: '0.75rem', borderTop: '1px solid var(--surface-border)' }}>
                <OpponentFieldMap matchup={matchup} isMobile={isMobile} />
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
};

const UpcomingGameBanner = ({ next }) => {
  if (!next) return null;

  const dateStr = formatDateMMDDYYYY(next.date);
  const isHome = next.home_away === 'home';

  return (
    <div className="glass-panel" style={{
      padding: '1rem 1.5rem', marginBottom: '0.75rem',
      borderColor: 'rgba(4, 101, 104, 0.32)', background: 'rgba(4, 101, 104, 0.06)'
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
        <Clock size={18} color="var(--primary-color)" />
        <span className="section-label" style={{ marginBottom: 0 }}>Next Game</span>
        <span className={`home-away-pill ${isHome ? 'home-away-pill--home' : 'home-away-pill--away'}`}>
          {isHome ? <Home size={10} /> : <Plane size={10} />}
          {isHome ? 'HOME' : 'AWAY'}
        </span>
        <span style={{ fontWeight: '700', fontSize: 'var(--text-base)' }}>vs. {next.opponent}</span>
        <span style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)' }}>
          {dateStr}{next.time ? ` \u00b7 ${next.time}` : ''}
        </span>
        {next.location && next.location !== 'TBD' && (
          <span style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)' }}>@ {next.location}</span>
        )}
      </div>
    </div>
  );
};

/** Map a SWOT text string to a skill-specific icon component */
const getSkillIcon = (text) => {
  const t = (text || '').toLowerCase();
  if (/bat|hit|contact|slug|avg|obp|ops/.test(t)) return CircleDot;
  if (/field|defense|glove|catch/.test(t)) return Shield;
  if (/speed|base|run|steal/.test(t)) return Zap;
  if (/pitch|throw|control|strike/.test(t)) return Target;
  if (/eye|walk|discipline|patient/.test(t)) return Eye;
  return TrendingUp;
};

/** Compact player card with collapsible detail */
const PlayerSwotCard = ({ player, isMobile, isExpanded, onToggle }) => {
  const hitting = player.derivedStats?.hitting || {};
  const pa = Number(hitting.pa || 0);
  const fmtRate = (v) => { const n = Number(v || 0); return n === 0 ? '\u2014' : n.toFixed(3).replace(/^0/, ''); };
  const fmtPct = (v) => { const n = Number(v || 0); return n === 0 ? '\u2014' : `${Math.round(n * 100)}%`; };
  const avg = fmtRate(hitting.ba);
  const obp = fmtRate(hitting.obp);
  const ops = fmtRate(hitting.ops);
  const kRate = fmtPct(hitting.k_rate);
  const bbRate = fmtPct(hitting.bb_rate);

  const strengths = player.swot?.strengths || [];
  const weaknesses = player.swot?.weaknesses || [];
  const hasStrengths = strengths.length > 0;
  const hasWeaknesses = weaknesses.length > 0;

  return (
    <div
      className="glass-panel"
      style={{ padding: isMobile ? 'var(--space-lg)' : '1.25rem', cursor: 'pointer' }}
      onClick={onToggle}
    >
      {/* Collapsed header: name, number, key badges, trait icons */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        overflow: 'hidden',
        marginBottom: isExpanded ? '0.75rem' : 0,
        paddingBottom: isExpanded ? '0.5rem' : 0,
        borderBottom: isExpanded ? '1px solid var(--surface-border)' : 'none'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap', flex: 1, minWidth: 0 }}>
          <PlayerName
            first={player.first}
            last={player.last}
            number={player.number}
            size={isMobile ? 'sm' : 'md'}
          />
          {/* Compact stat badges — always visible */}
          {pa > 0 ? (
            <span style={{ display: 'inline-flex', gap: '0.3rem', flexWrap: 'wrap', minWidth: 0, alignItems: 'center' }}>
              <TipBadge label="AVG" value={avg} />
              <TipBadge label="OBP" value={obp} />
              {!isMobile && <TipBadge label="OPS" value={ops} />}
              {pa < 5 && (
                <span title={`Only ${pa} PA — stats not reliable yet`} style={{
                  fontSize: '10px', color: 'var(--text-muted)', background: 'rgba(255,255,255,0.07)',
                  border: '1px solid rgba(255,255,255,0.12)', borderRadius: '4px',
                  padding: '1px 5px', lineHeight: 1.4,
                }}>
                  {pa} PA ⚠
                </span>
              )}
            </span>
          ) : (
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', fontStyle: 'italic', minWidth: 0 }}>No PAs</span>
          )}
          {/* Skill-specific trait icons for quick scanning */}
          <span style={{ display: 'inline-flex', gap: '0.25rem', alignItems: 'center', minWidth: 0 }}>
            {hasStrengths && strengths.slice(0, 3).map((s, i) => {
              const SkillIcon = getSkillIcon(s);
              return (
                <span key={`s-${i}`} title={s} style={{ color: 'var(--success)', display: 'inline-flex', alignItems: 'center' }}>
                  <SkillIcon size={14} />
                </span>
              );
            })}
            {hasWeaknesses && weaknesses.slice(0, 3).map((w, i) => {
              const SkillIcon = getSkillIcon(w);
              return (
                <span key={`w-${i}`} title={w} style={{ color: 'var(--danger)', display: 'inline-flex', alignItems: 'center' }}>
                  <SkillIcon size={14} />
                </span>
              );
            })}
          </span>
        </div>
        {isExpanded ? <ChevronUp size={18} color="var(--text-muted)" /> : <ChevronDown size={18} color="var(--text-muted)" />}
      </div>

      {/* Expanded detail */}
      {isExpanded && (
        <div style={{ marginTop: '0.5rem' }}>
          {/* Full stat row */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem', marginBottom: '0.9rem' }}>
            {pa > 0 ? (
              <>
                <TipBadge label="PA" value={pa} />
                <TipBadge label="AVG" value={avg} />
                <TipBadge label="OBP" value={obp} />
                <TipBadge label="OPS" value={ops} />
                <TipBadge label="K%" value={kRate} />
                <TipBadge label="BB%" value={bbRate} />
              </>
            ) : (
              <TipBadge label="Stats" value="No plate appearances yet" />
            )}
          </div>

          {/* Full SWOT quadrants */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <SwotQuadrant title="Strengths" items={strengths} color="var(--success)" icon={<TrendingUp size={13} />} />
            <SwotQuadrant title="Weaknesses" items={weaknesses} color="var(--danger)" icon={<AlertTriangle size={13} />} />
            <SwotQuadrant title="Opportunities" items={player.swot?.opportunities} color="#3b9ede" icon={<Target size={13} />} />
            <SwotQuadrant title="Threats" items={player.swot?.threats} color="var(--warning)" icon={<ShieldAlert size={13} />} />
          </div>
        </div>
      )}
    </div>
  );
};

const Swot = ({ swotData, roster, schedule, isMobile = false }) => {
  const [expandedPlayer, setExpandedPlayer] = useState(null);
  const [showMatchup, setShowMatchup] = useState(!isMobile);
  if (!swotData) return <p>Loading SWOT Analysis...</p>;

  const evaluations = swotData.player_analyses || swotData.player_evaluations || [];
  const playersWithSwot = (roster || []).filter(p => p.core !== false).map(player => {
    const evaluation = evaluations.find(e =>
      (e.number && String(e.number) === String(player.number)) ||
      (e.name && e.name.toLowerCase() === `${player.first} ${player.last}`.trim().toLowerCase()) ||
      (e.name && e.name.toLowerCase() === String(player.first || '').toLowerCase())
    );
    return {
      ...player,
      swot: evaluation?.swot || evaluation,
      derivedStats: evaluation?.derived_stats || null
    };
  }).filter(p => p.swot)
    .sort((a, b) => {
      const textA = `${a.last || ''} ${a.first || ''}`.trim().toLowerCase();
      const textB = `${b.last || ''} ${b.first || ''}`.trim().toLowerCase();
      return textA.localeCompare(textB);
    });

  const teamSwot = swotData.team_swot;

  const today = getTodayEST();
  const nextGame = schedule?.upcoming
    ?.filter(g => g.date >= today)
    ?.sort((a, b) => a.date.localeCompare(b.date))[0];

  return (
    <div>
      <h2 className="view-title">
        <Target size={isMobile ? 20 : 24} color="var(--primary-color)" /> SWOT Analysis
        <span style={{ fontSize: isMobile ? 'var(--text-xs)' : 'var(--text-sm)', color: 'var(--text-muted)', fontWeight: 'normal', marginLeft: '0.5rem' }}>
          ({playersWithSwot.length} players)
        </span>
      </h2>

      {/* ──── 1. Team-level SWOT — most prominent, shown FIRST ──── */}
      {teamSwot && (
        isMobile ? (
          <div className="glass-panel" style={{ marginBottom: 'var(--space-md)', padding: 'var(--space-lg)', borderColor: 'var(--primary-glow)' }}>
            <h3 style={{ marginBottom: '1rem', color: 'var(--primary-color)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <ShieldAlert size={20} /> Team Analysis
            </h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.85rem' }}>
              <SwotQuadrant title="Strengths" items={(teamSwot.strengths || []).slice(0, 4)} color="var(--success)" icon={<TrendingUp size={14} />} />
              <SwotQuadrant title="Weaknesses" items={(teamSwot.weaknesses || []).slice(0, 4)} color="var(--danger)" icon={<AlertTriangle size={14} />} />
              <SwotQuadrant title="Opportunities" items={(teamSwot.opportunities || []).slice(0, 4)} color="#3b9ede" icon={<Target size={14} />} />
              <SwotQuadrant title="Threats" items={(teamSwot.threats || []).slice(0, 4)} color="var(--warning)" icon={<ShieldAlert size={14} />} />
            </div>
          </div>
        ) : (
          <div className="glass-panel" style={{ marginBottom: '2rem', padding: '1.5rem', borderColor: 'var(--primary-glow)' }}>
            <h3 style={{ marginBottom: '1.25rem', color: 'var(--primary-color)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <ShieldAlert size={20} /> Team Analysis
            </h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '1.25rem' }}>
              <SwotQuadrant title="Strengths" items={teamSwot.strengths} color="var(--success)" icon={<TrendingUp size={14} />} />
              <SwotQuadrant title="Weaknesses" items={teamSwot.weaknesses} color="var(--danger)" icon={<AlertTriangle size={14} />} />
              <SwotQuadrant title="Opportunities" items={teamSwot.opportunities} color="#3b9ede" icon={<Target size={14} />} />
              <SwotQuadrant title="Threats" items={teamSwot.threats} color="var(--warning)" icon={<ShieldAlert size={14} />} />
            </div>
          </div>
        )
      )}

      {/* ──── 2. Next Game Banner + Matchup ──── */}
      <div style={{ marginBottom: isMobile ? 'var(--space-md)' : '2rem' }}>
        <UpcomingGameBanner next={nextGame} />
        {isMobile ? (
          <div className="glass-panel" style={{ padding: 'var(--space-lg)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.75rem' }}>
              <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
                Matchup details are optional on mobile.
              </span>
              <button
                onClick={() => setShowMatchup(prev => !prev)}
                style={{
                  background: 'var(--primary-glow)',
                  color: 'var(--primary-color)',
                  border: '1px solid rgba(4, 101, 104, 0.24)',
                  borderRadius: '8px',
                  padding: '0.5rem 0.75rem',
                  fontSize: 'var(--text-xs)',
                  fontWeight: '700',
                  cursor: 'pointer',
                  minHeight: 'var(--touch-min)',
                }}
              >
                {showMatchup ? 'Hide Matchup' : 'Show Matchup'}
              </button>
            </div>
            {showMatchup && <div style={{ marginTop: '0.75rem' }}><MatchupPanel defaultOpponent={nextGame?.opponent} isMobile={isMobile} /></div>}
          </div>
        ) : (
          <MatchupPanel defaultOpponent={nextGame?.opponent} isMobile={isMobile} />
        )}
      </div>

      {/* ──── 3. Player cards — collapsible ──── */}
      <div className="card-grid">
        {playersWithSwot.map(player => {
          const key = `${player.number}-${player.last}`;
          const isExpanded = expandedPlayer === key;
          return (
            <PlayerSwotCard
              key={key}
              player={player}
              isMobile={isMobile}
              isExpanded={isExpanded}
              onToggle={() => setExpandedPlayer(isExpanded ? null : key)}
            />
          );
        })}
      </div>

      {playersWithSwot.length === 0 && (
        <div className="glass-panel" style={{ padding: '2rem', textAlign: 'center' }}>
          <p style={{ color: 'var(--text-muted)' }}>No SWOT data available. Run the scraper to populate player stats.</p>
        </div>
      )}
    </div>
  );
};

export default Swot;
