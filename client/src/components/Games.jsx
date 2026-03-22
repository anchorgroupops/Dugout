import React, { useState, useEffect } from 'react';
import { Calendar, ChevronDown, ChevronUp, Home, Plane, Clock } from 'lucide-react';

const StatCell = ({ label, value }) => (
  <div style={{ textAlign: 'center', minWidth: '40px' }}>
    <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>{label}</div>
    <div style={{ fontSize: '0.95rem', fontWeight: '600', color: 'var(--text-main)' }}>{value ?? '—'}</div>
  </div>
);

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
      <div style={{ width: '32px', fontSize: '0.85rem', fontWeight: '700', color: 'var(--primary-color)' }}>
        #{player.number}
      </div>
      <div style={{ minWidth: '120px', fontSize: '0.9rem', fontWeight: '600' }}>
        {player.name}
        {player.pos && <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginLeft: '0.4rem' }}>({player.pos})</span>}
      </div>
      <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
        <StatCell label="PA" value={b.pa} />
        <StatCell label="AB" value={b.ab} />
        <StatCell label="H" value={b.h} />
        <StatCell label="BB" value={b.bb} />
        <StatCell label="HBP" value={b.hbp} />
        <StatCell label="SO" value={b.so} />
        <StatCell label="AVG" value={b.avg != null ? b.avg.toFixed(3) : null} />
        <StatCell label="OBP" value={b.obp != null ? b.obp.toFixed(3) : null} />
      </div>
      {player.at_bats_raw?.length > 0 && (
        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>
          {player.at_bats_raw.join(' · ')}
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
      <span style={{
        padding: '3px 10px', borderRadius: '20px', fontSize: '0.75rem', fontWeight: '800',
        background: isWin ? 'rgba(35,134,54,0.2)' : 'rgba(220,70,70,0.2)',
        color: isWin ? 'var(--success)' : 'var(--danger)',
        border: `1px solid ${isWin ? 'rgba(35,134,54,0.4)' : 'rgba(220,70,70,0.4)'}`,
        letterSpacing: '0.5px'
      }}>{result}</span>
      {score && <span style={{ fontSize: '0.88rem', fontWeight: '600', color: 'var(--text-muted)' }}>{sharksScore}–{oppScore}</span>}
    </div>
  );
};

const GameCard = ({ game, onExpand, isExpanded, detail }) => {
  const t = game.sharks_totals || {};
  const isHome = game.sharks_side === 'home';
  const dateStr = game.date
    ? new Date(game.date + 'T12:00:00').toLocaleDateString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', year: 'numeric' })
    : 'Unknown Date';

  return (
    <div className="glass-panel" style={{ padding: '1.25rem', cursor: 'pointer' }} onClick={onExpand}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.75rem' }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem', flexWrap: 'wrap' }}>
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: '0.25rem',
              background: isHome ? 'rgba(35,134,54,0.15)' : 'rgba(100,160,220,0.15)',
              color: isHome ? 'var(--success)' : '#4a9ede',
              padding: '2px 8px', borderRadius: '12px', fontSize: '0.7rem', fontWeight: '700'
            }}>
              {isHome ? <Home size={10} /> : <Plane size={10} />}
              {isHome ? 'HOME' : 'AWAY'}
            </span>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{dateStr}</span>
            <ResultBadge result={game.result} score={game.score} />
          </div>
          <h3 style={{ fontSize: '1.1rem', margin: 0 }}>vs. {game.opponent}</h3>
        </div>
        {game.sharks_totals && (isExpanded ? <ChevronUp size={18} color="var(--text-muted)" /> : <ChevronDown size={18} color="var(--text-muted)" />)}
      </div>

      {/* Batting totals — only shown when PDF data exists */}
      {game.sharks_totals && <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
        <StatCell label="PA" value={t.pa} />
        <StatCell label="AB" value={t.ab} />
        <StatCell label="H" value={t.h} />
        <StatCell label="2B" value={t.doubles || 0} />
        <StatCell label="HR" value={t.hr || 0} />
        <StatCell label="BB" value={t.bb} />
        <StatCell label="HBP" value={t.hbp} />
        <StatCell label="SO" value={t.so} />
        <StatCell label="AVG" value={t.avg != null ? t.avg.toFixed(3) : null} />
      </div>}

      {/* Per-player breakdown */}
      {isExpanded && detail && (
        <div style={{ marginTop: '1rem', borderTop: '1px solid var(--surface-border)', paddingTop: '1rem' }}>
          <div style={{ fontSize: '0.7rem', color: 'var(--primary-color)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '0.5rem', fontWeight: '700' }}>
            Sharks Batting
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
            {detail.map((p, i) => <PlayerBattingRow key={i} player={p} />)}
          </div>
          <div style={{ marginTop: '0.75rem', fontSize: '0.75rem', color: 'rgba(255,255,255,0.3)', fontStyle: 'italic' }}>
            Source: {game.pdf_file || 'scorebook PDF'}
          </div>
        </div>
      )}
    </div>
  );
};

const UpcomingGameBanner = ({ schedule }) => {
  if (!schedule?.upcoming?.length) return null;
  const today = new Date().toISOString().slice(0, 10);
  const next = schedule.upcoming
    .filter(g => g.date >= today)
    .sort((a, b) => a.date.localeCompare(b.date))[0];
  if (!next) return null;

  const dateStr = new Date(next.date + 'T12:00:00').toLocaleDateString('en-US', {
    timeZone: 'America/New_York', weekday: 'short', month: 'short', day: 'numeric'
  });
  const isHome = next.home_away === 'home';

  return (
    <div className="glass-panel" style={{
      padding: '1rem 1.5rem', marginBottom: '1.5rem',
      borderColor: 'rgba(0,210,255,0.3)',
      background: 'rgba(0,210,255,0.04)'
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
        <Clock size={18} color="var(--primary-color)" />
        <span style={{ fontSize: '0.7rem', color: 'var(--primary-color)', textTransform: 'uppercase', letterSpacing: '1px', fontWeight: '700' }}>
          Next Game
        </span>
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: '0.25rem',
          background: isHome ? 'rgba(35,134,54,0.15)' : 'rgba(100,160,220,0.15)',
          color: isHome ? 'var(--success)' : '#4a9ede',
          padding: '2px 8px', borderRadius: '12px', fontSize: '0.7rem', fontWeight: '700'
        }}>
          {isHome ? <Home size={10} /> : <Plane size={10} />}
          {isHome ? 'HOME' : 'AWAY'}
        </span>
        <span style={{ fontWeight: '700', fontSize: '1rem' }}>vs. {next.opponent}</span>
        <span style={{ color: 'var(--text-muted)', fontSize: '0.88rem' }}>
          {dateStr}{next.time ? ` · ${next.time}` : ''}
        </span>
        {next.location && next.location !== 'TBD' && (
          <span style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>@ {next.location}</span>
        )}
      </div>
    </div>
  );
};

const ScheduleRow = ({ game }) => {
  const isHome = game.home_away === 'home';
  const dateStr = game.date
    ? new Date(game.date + 'T12:00:00').toLocaleDateString('en-US', { timeZone: 'America/New_York', weekday: 'short', month: 'short', day: 'numeric' })
    : '—';
  const isNext = game._isNext;

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '0.75rem', padding: '0.6rem 0.75rem',
      borderRadius: '8px', flexWrap: 'wrap',
      background: isNext ? 'rgba(0,210,255,0.06)' : 'rgba(0,0,0,0.15)',
      border: isNext ? '1px solid rgba(0,210,255,0.2)' : '1px solid transparent',
    }}>
      <span style={{ minWidth: '110px', fontSize: '0.85rem', color: 'var(--text-muted)' }}>{dateStr}</span>
      <span style={{
        display: 'inline-flex', alignItems: 'center', gap: '0.2rem',
        background: isHome ? 'rgba(35,134,54,0.15)' : 'rgba(100,160,220,0.15)',
        color: isHome ? 'var(--success)' : '#4a9ede',
        padding: '1px 7px', borderRadius: '10px', fontSize: '0.68rem', fontWeight: '700'
      }}>
        {isHome ? <Home size={9} /> : <Plane size={9} />}
        {isHome ? 'H' : 'A'}
      </span>
      <span style={{ flex: 1, fontWeight: isNext ? '700' : '500', fontSize: '0.9rem' }}>
        {isNext && <span style={{ color: 'var(--primary-color)', marginRight: '0.4rem', fontSize: '0.7rem', fontWeight: '800', textTransform: 'uppercase', letterSpacing: '0.5px' }}>NEXT ▶</span>}
        vs. {game.opponent}
      </span>
      {game.time && <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{game.time}</span>}
    </div>
  );
};

const Games = ({ gamesData, schedule }) => {
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

  // Build upcoming schedule list
  const today = new Date().toISOString().slice(0, 10);
  const upcoming = (schedule?.upcoming || [])
    .filter(g => g.date >= today)
    .sort((a, b) => a.date.localeCompare(b.date))
    .map((g, i) => ({ ...g, _isNext: i === 0 }));

  const sorted = [...(gamesData || [])].sort((a, b) => (b.date || '').localeCompare(a.date || ''));

  return (
    <div>
      <h2 style={{ marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <Calendar size={24} color="var(--primary-color)" /> Games
      </h2>

      {/* Upcoming schedule */}
      {upcoming.length > 0 && (
        <div className="glass-panel" style={{ padding: '1.25rem', marginBottom: '2rem' }}>
          <div style={{ fontSize: '0.7rem', color: 'var(--primary-color)', textTransform: 'uppercase', letterSpacing: '1px', fontWeight: '700', marginBottom: '0.75rem' }}>
            Upcoming Schedule ({upcoming.length} games)
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
            {upcoming.map((g, i) => <ScheduleRow key={i} game={g} />)}
          </div>
        </div>
      )}

      {/* Past game results */}
      {sorted.length > 0 ? (
        <>
          <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '1px', fontWeight: '700', marginBottom: '0.75rem' }}>
            Past Games ({sorted.length})
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {sorted.map(game => (
              <GameCard
                key={game.game_id}
                game={game}
                isExpanded={expanded === game.game_id}
                detail={details[game.game_id]}
                onExpand={() => game.sharks_totals && handleExpand(game.game_id)}
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
