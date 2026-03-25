import React, { useState, useEffect } from 'react';
import { Calendar, ChevronDown, ChevronUp, Home, Plane, Clock } from 'lucide-react';
import { getTodayEST, formatDateMMDDYYYY } from '../utils/formatDate';
import { TipBadge, PlayerName } from './StatTooltip';

const PlayerBattingRow = ({ player }) => {
  const b = player.batting || {};
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: '0.75rem',
      padding: '0.5rem 0.75rem',
      borderRadius: '6px',
      background: 'rgba(0,0,0,0.15)',
      flexWrap: 'wrap'
    }}>
      <div style={{ minWidth: '120px' }}>
        <PlayerName name={player.name} number={player.number} size="sm" />
        {player.pos && <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginLeft: '0.4rem' }}>({player.pos})</span>}
      </div>
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        <TipBadge label="PA" value={b.pa} />
        <TipBadge label="AB" value={b.ab} />
        <TipBadge label="H" value={b.h} />
        <TipBadge label="BB" value={b.bb} />
        <TipBadge label="HBP" value={b.hbp} />
        <TipBadge label="SO" value={b.so} />
        <TipBadge label="AVG" value={b.avg != null ? b.avg.toFixed(3) : null} />
        <TipBadge label="OBP" value={b.obp != null ? b.obp.toFixed(3) : null} />
      </div>
      {player.at_bats_raw?.length > 0 && (
        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', fontStyle: 'italic' }}>
          {player.at_bats_raw.join(' \u00b7 ')}
        </div>
      )}
    </div>
  );
};

const ResultBadge = ({ result, score }) => {
  if (!result) return null;
  const isWin = result === 'W';
  const parts = (score || '').split('-');
  const sharksScore = isWin ? Math.max(...parts.map(Number)) : Math.min(...parts.map(Number));
  const oppScore = isWin ? Math.min(...parts.map(Number)) : Math.max(...parts.map(Number));
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
      <span className={`result-badge ${isWin ? 'result-badge--win' : 'result-badge--loss'}`}>{result}</span>
      {score && <span style={{ fontSize: 'var(--text-sm)', fontWeight: '600', color: 'var(--text-muted)' }}>{sharksScore}\u2013{oppScore}</span>}
    </div>
  );
};

const GameCard = ({ game, onExpand, isExpanded, detail, isMobile = false }) => {
  const t = game.sharks_totals || {};
  const isHome = game.sharks_side === 'home';
  const dateStr = game.date ? formatDateMMDDYYYY(game.date) : 'Unknown Date';

  return (
    <div className="glass-panel" style={{ padding: isMobile ? 'var(--space-lg)' : '1.25rem', cursor: isMobile ? 'default' : 'pointer' }} onClick={onExpand}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.75rem' }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem', flexWrap: 'wrap' }}>
            <span className={`home-away-pill ${isHome ? 'home-away-pill--home' : 'home-away-pill--away'}`}>
              {isHome ? <Home size={10} /> : <Plane size={10} />}
              {isHome ? 'HOME' : 'AWAY'}
            </span>
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{dateStr}</span>
            <ResultBadge result={game.result} score={game.score} />
          </div>
          <h3 style={{ fontSize: isMobile ? 'var(--text-base)' : '1.1rem', margin: 0 }}>vs. {game.opponent}</h3>
        </div>
        {!isMobile && game.sharks_totals && (isExpanded ? <ChevronUp size={18} color="var(--text-muted)" /> : <ChevronDown size={18} color="var(--text-muted)" />)}
      </div>

      {game.sharks_totals && <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
        <TipBadge label="PA" value={t.pa} />
        <TipBadge label="H" value={t.h} />
        {!isMobile && <TipBadge label="AB" value={t.ab} />}
        {!isMobile && <TipBadge label="2B" value={t.doubles || 0} />}
        {!isMobile && <TipBadge label="HR" value={t.hr || 0} />}
        {!isMobile && <TipBadge label="BB" value={t.bb} />}
        {!isMobile && <TipBadge label="HBP" value={t.hbp} />}
        {!isMobile && <TipBadge label="SO" value={t.so} />}
        <TipBadge label="AVG" value={t.avg != null ? t.avg.toFixed(3) : null} />
      </div>}

      {!isMobile && isExpanded && detail && (
        <div style={{ marginTop: '1rem', borderTop: '1px solid var(--surface-border)', paddingTop: '1rem' }}>
          <div className="section-label">Sharks Batting</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
            {detail.map((p, i) => <PlayerBattingRow key={i} player={p} />)}
          </div>
          <div style={{ marginTop: '0.75rem', fontSize: 'var(--text-xs)', color: 'rgba(255,255,255,0.3)', fontStyle: 'italic' }}>
            Source: {game.pdf_file || 'scorebook PDF'}
          </div>
        </div>
      )}
    </div>
  );
};

const UpcomingGameBanner = ({ schedule }) => {
  if (!schedule?.upcoming?.length) return null;
  const today = getTodayEST();
  const next = schedule.upcoming
    .filter(g => g.date >= today)
    .sort((a, b) => a.date.localeCompare(b.date))[0];
  if (!next) return null;

  const dateStr = formatDateMMDDYYYY(next.date);
  const isHome = next.home_away === 'home';

  return (
    <div className="glass-panel" style={{
      padding: '1rem 1.5rem', marginBottom: '1.5rem',
      borderColor: 'rgba(4, 101, 104, 0.32)',
      background: 'rgba(4, 101, 104, 0.06)'
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
        {isHome ? 'H' : 'A'}
      </span>
      <span style={{ flex: 1, fontWeight: isNext ? '700' : '500', fontSize: 'var(--text-sm)' }}>
        {isNext && <span style={{ color: 'var(--primary-color)', marginRight: '0.4rem', fontSize: 'var(--text-xs)', fontWeight: '800', textTransform: 'uppercase', letterSpacing: '0.5px' }}>NEXT \u25b6</span>}
        vs. {game.opponent}
      </span>
      {game.time && <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{game.time}</span>}
    </div>
  );
};

const Games = ({ gamesData, schedule, isMobile = false }) => {
  const [expanded, setExpanded] = useState(null);
  const [details, setDetails] = useState({});

  const fetchDetail = async (gameId) => {
    if (details[gameId]) return;
    try {
      const res = await fetch(`/api/games/${gameId}`);
      if (res.ok) {
        const data = await res.json();
        setDetails(prev => ({ ...prev, [gameId]: data.sharks_batting || [] }));
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
        <div className="glass-panel" style={{ padding: isMobile ? 'var(--space-lg)' : '1.25rem', marginBottom: isMobile ? 'var(--space-md)' : '2rem' }}>
          <div className="section-label" style={{
            color: 'var(--primary-color)',
            fontSize: 'var(--text-base)',
            fontWeight: '800',
            letterSpacing: '0.5px',
            textTransform: 'uppercase',
            borderBottom: '2px solid rgba(4, 101, 104, 0.3)',
            paddingBottom: '0.5rem',
            marginBottom: '0.75rem',
          }}>Upcoming Schedule ({upcoming.length} games)</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
            {upcoming.map((g, i) => <ScheduleRow key={i} game={g} />)}
          </div>
        </div>
      )}

      {/* Visual divider between upcoming and past */}
      {upcoming.length > 0 && sorted.length > 0 && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: '1rem',
          margin: '1.5rem 0 1rem',
        }}>
          <div style={{ flex: 1, height: '1px', background: 'linear-gradient(to right, transparent, rgba(255,255,255,0.1), transparent)' }} />
        </div>
      )}

      {sorted.length > 0 ? (
        <>
          <div className="section-label" style={{
            color: 'var(--text-muted)',
            fontSize: 'var(--text-sm)',
            fontWeight: '600',
            letterSpacing: '0.3px',
            textTransform: 'uppercase',
            opacity: 0.6,
            marginBottom: '0.75rem',
          }}>Past Games ({sorted.length})</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
            {sorted.map(game => (
              <GameCard
                key={game.game_id}
                game={game}
                isExpanded={expanded === game.game_id}
                detail={details[game.game_id]}
                isMobile={isMobile}
                onExpand={() => {
                  if (!isMobile && game.sharks_totals) handleExpand(game.game_id);
                }}
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
