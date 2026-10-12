import { useCallback, useEffect, useRef, useState } from 'react';
import { apiFetch, apiRequest } from '../../utils/apiClient';
import SprayField from './SprayField.jsx';
import { bannerFor, countDots, historyLine, isFinalView } from './tabletHelpers.js';
import './dugoutTablet.css';

const POLL_MS = 5000;

function Dots({ count, max, cls, label }) {
  return (
    <div className="dt-count" aria-label={`${label} ${count}`}>
      <span className="dt-count-label">{label}</span>
      {countDots(count, max).map((on, i) => <i key={i} className={`dt-dot ${cls}${on ? ' on' : ''}`} />)}
    </div>
  );
}

function Diamond({ bases }) {
  const occ = (k) => !!bases?.[k];
  const base = (x, y, k) => (
    <rect x={x - 14} y={y - 14} width="28" height="28" transform={`rotate(45 ${x} ${y})`}
      fill={occ(k) ? '#ffd23f' : 'transparent'} stroke="#fff" strokeWidth="4" />
  );
  return (
    <svg className="dt-diamond" viewBox="0 0 120 110" role="img" aria-label="Runners on base">
      {base(60, 22, '2')}{base(98, 58, '1')}{base(22, 58, '3')}
      <polygon points="60,96 52,88 52,82 68,82 68,88" fill="#fff" />
    </svg>
  );
}

function BatterCard({ batter, label, compact }) {
  if (!batter) return null;
  const opp = batter.team === 'opponent';
  return (
    <div className={`dt-batter${compact ? ' compact' : ''}`}>
      <div className="dt-batter-top">
        <span className="dt-tag">{label}</span>
        <span className={`dt-badge ${opp ? 'opp' : 'sharks'}`}>{opp ? 'OPP' : 'SHARKS'}</span>
      </div>
      <div className="dt-name">{batter.number ? `#${batter.number} ` : ''}{batter.name}</div>
      {!compact && (
        <>
          <div className="dt-chips">
            {(batter.today || []).length === 0
              ? <span className="dt-chip dim">No PA yet today</span>
              : batter.today.map((t, i) => <span key={i} className="dt-chip">{t.result}</span>)}
          </div>
          <div className="dt-history">{historyLine(batter.history)}</div>
        </>
      )}
    </div>
  );
}

export default function DugoutTablet({ fullscreen = false }) {
  const [payload, setPayload] = useState(null);
  const [netFail, setNetFail] = useState(false);
  const [lastOk, setLastOk] = useState(null);
  const [now, setNow] = useState(() => Date.now());
  const [busy, setBusy] = useState(false);
  const [actionErr, setActionErr] = useState('');
  const mounted = useRef(true);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch('/api/live/tablet', { cache: 'no-store' });
      if (!res.ok) throw new Error(`http_${res.status}`);
      const json = await res.json();
      if (!mounted.current) return;
      setPayload(json);
      setNetFail(false);
      setLastOk(Date.now());
    } catch {
      if (mounted.current) setNetFail(true);
    }
  }, []);

  // Poll every 5 s while visible; pause while hidden; refresh on return.
  useEffect(() => {
    mounted.current = true;
    let timer = null;
    const stop = () => { if (timer) { clearInterval(timer); timer = null; } };
    const start = () => {
      stop();
      load();
      timer = setInterval(load, POLL_MS);
    };
    const onVis = () => (document.visibilityState === 'visible' ? start() : stop());
    if (document.visibilityState === 'visible') start();
    document.addEventListener('visibilitychange', onVis);
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      mounted.current = false;
      stop();
      clearInterval(tick);
      document.removeEventListener('visibilitychange', onVis);
    };
  }, [load]);

  // Keep the screen awake while the view is shown.
  useEffect(() => {
    let lock = null;
    let cancelled = false;
    const acquire = async () => {
      try {
        if (!('wakeLock' in navigator) || document.visibilityState !== 'visible') return;
        const l = await navigator.wakeLock.request('screen');
        if (cancelled) { l.release?.().catch(() => {}); return; }
        lock = l;
      } catch { /* denied or unsupported: screen may dim */ }
    };
    const onVis = () => { if (document.visibilityState === 'visible') acquire(); };
    acquire();
    document.addEventListener('visibilitychange', onVis);
    return () => {
      cancelled = true;
      document.removeEventListener('visibilitychange', onVis);
      lock?.release?.().catch(() => {});
    };
  }, []);

  const act = async (path, body) => {
    setBusy(true);
    setActionErr('');
    try {
      const res = await apiRequest(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {}),
      });
      if (!res.ok) setActionErr(res.status === 401 ? 'Not authorised (write token)' : `Failed (${res.status})`);
      await load();
    } catch {
      setActionErr('Network error');
    } finally {
      if (mounted.current) setBusy(false);
    }
  };

  const banner = bannerFor(payload, netFail, now, lastOk);
  const game = payload?.game;
  const armed = !!payload?.armed;
  const final = isFinalView(payload);
  const showGame = !!game;
  const batter = payload?.batter;
  const half = game?.half === 'top' ? '▲' : '▼';

  const stopBtn = armed
    ? <button className="dt-stop" disabled={busy} onClick={() => act('/api/live/disarm')}>Stop</button>
    : null;

  return (
    <div className={`dt-root${fullscreen ? ' full' : ''}`}>
      {banner && <div className={`dt-banner ${banner.tone}`}>{banner.text}</div>}
      {actionErr && <div className="dt-banner error">{actionErr}</div>}

      {!armed && !showGame && (
        <div className="dt-idle">
          <div className="dt-idle-title">No live game</div>
          <button className="dt-start" disabled={busy} onClick={() => act('/api/live/arm', { hours: 3 })}>
            Start live game
          </button>
        </div>
      )}

      {armed && !showGame && (
        <div className="dt-idle">
          <div className="dt-idle-title">{payload?.status === 'error' ? 'Live feed stopped' : 'Waiting for first pitch data…'}</div>
          {stopBtn}
        </div>
      )}

      {showGame && (
        <div className="dt-main">
          <section className="dt-left">
            {batter ? (
              <SprayField field={payload.field} spray={batter.spray || []} />
            ) : (
              <div className="dt-nobatter">{final ? 'Game over' : 'No batter at the plate'}</div>
            )}
          </section>
          <section className="dt-right">
            <div className="dt-score">
              <div className="dt-score-team"><span>Sharks</span><b>{game.score?.sharks ?? 0}</b></div>
              <div className="dt-inning">
                {final ? 'FINAL' : <><span className="dt-half">{half}</span>{game.inning}</>}
              </div>
              <div className="dt-score-team"><span className="dt-opp-name">{game.opponent || 'Opponent'}</span><b>{game.score?.opponent ?? 0}</b></div>
            </div>
            {!final && (
              <div className="dt-state">
                <div className="dt-counts">
                  <Dots label="B" count={game.balls} max={3} cls="ball" />
                  <Dots label="S" count={game.strikes} max={2} cls="strike" />
                  <Dots label="O" count={game.outs} max={2} cls="out" />
                </div>
                <Diamond bases={game.bases} />
              </div>
            )}
            {!final && <BatterCard batter={batter} label="AT BAT" />}
            {!final && <BatterCard batter={payload.on_deck} label="ON DECK" compact />}
            {!final && game.pitcher && (
              <div className="dt-pitcher">PITCHING: {game.pitcher.number ? `#${game.pitcher.number} ` : ''}{game.pitcher.name}</div>
            )}
            {!armed && (
              <button className="dt-start" disabled={busy} onClick={() => act('/api/live/arm', { hours: 3 })}>Start live game</button>
            )}
            {stopBtn}
          </section>
        </div>
      )}
    </div>
  );
}
