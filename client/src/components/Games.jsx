import React, { useState, useEffect } from 'react';
import { Calendar, ChevronDown, ChevronUp, Home, Plane } from 'lucide-react';

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

const GameCard = ({ game, onExpand, isExpanded, detail }) => {
  const t = game.sharks_totals || {};
  const isHome = game.sharks_side === 'home';
  const dateStr = game.date
    ? new Date(game.date + 'T12:00:00').toLocaleDateString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', year: 'numeric' })
    : 'Unknown Date';

  return (
    <div className="glass-panel" style={{ padding: '1.25rem', cursor: 'pointer' }} onClick={onExpand}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.75rem' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
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
          </div>
          <h3 style={{ fontSize: '1.1rem', margin: 0 }}>vs. {game.opponent}</h3>
        </div>
        {isExpanded ? <ChevronUp size={18} color="var(--text-muted)" /> : <ChevronDown size={18} color="var(--text-muted)" />}
      </div>

      {/* Batting totals */}
      <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
        <StatCell label="PA" value={t.pa} />
        <StatCell label="AB" value={t.ab} />
        <StatCell label="H" value={t.h} />
        <StatCell label="2B" value={t.doubles || 0} />
        <StatCell label="HR" value={t.hr || 0} />
        <StatCell label="BB" value={t.bb} />
        <StatCell label="HBP" value={t.hbp} />
        <StatCell label="SO" value={t.so} />
        <StatCell label="AVG" value={t.avg != null ? t.avg.toFixed(3) : null} />
      </div>

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

const Games = ({ gamesData }) => {
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

  if (!gamesData || gamesData.length === 0) {
    return (
      <div>
        <h2 style={{ marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Calendar size={24} color="var(--primary-color)" /> Games
        </h2>
        <div className="glass-panel" style={{ padding: '2rem', textAlign: 'center' }}>
          <p style={{ color: 'var(--text-muted)' }}>No game data available. Run the scorebook parser to import games.</p>
        </div>
      </div>
    );
  }

  const sorted = [...gamesData].sort((a, b) => (b.date || '').localeCompare(a.date || ''));

  return (
    <div>
      <h2 style={{ marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <Calendar size={24} color="var(--primary-color)" /> Games
        <span style={{ fontSize: '0.9rem', color: 'var(--text-muted)', fontWeight: 'normal', marginLeft: '0.5rem' }}>
          ({gamesData.length} games)
        </span>
      </h2>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {sorted.map(game => (
          <GameCard
            key={game.game_id}
            game={game}
            isExpanded={expanded === game.game_id}
            detail={details[game.game_id]}
            onExpand={() => handleExpand(game.game_id)}
          />
        ))}
      </div>
    </div>
  );
};

export default Games;
