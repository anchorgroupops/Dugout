import React from 'react';

const MODE_CONFIG = {
  ELITE: {
    label: 'ELITE',
    color: '#82cbc3',
    glow: 'rgba(130,203,195,0.55)',
    bg: 'rgba(130,203,195,0.10)',
    border: 'rgba(130,203,195,0.40)',
  },
  RAPID: {
    label: 'RAPID',
    color: '#f0b429',
    glow: 'rgba(240,180,41,0.45)',
    bg: 'rgba(240,180,41,0.10)',
    border: 'rgba(240,180,41,0.35)',
  },
  OFFLINE: {
    label: 'OFFLINE',
    color: '#f87171',
    glow: 'rgba(248,113,113,0.40)',
    bg: 'rgba(248,113,113,0.10)',
    border: 'rgba(248,113,113,0.35)',
  },
};

export default function WorkerBadge({ workerStatus }) {
  if (!workerStatus) return null;

  const mode = workerStatus.current_mode || 'OFFLINE';
  const cfg = MODE_CONFIG[mode] || MODE_CONFIG.OFFLINE;
  const queueDepth = workerStatus.primary_worker?.queue_depth ?? 0;
  const workerAlive = workerStatus.primary_worker?.status !== 'OFFLINE';

  return (
    <div
      className="worker-badge"
      title={`${mode} — ${workerAlive ? 'Mac online' : 'Mac offline'}`}
      style={{
        '--badge-color': cfg.color,
        '--badge-glow': cfg.glow,
        '--badge-bg': cfg.bg,
        '--badge-border': cfg.border,
      }}
    >
      <span
        className={`worker-badge-ping${workerAlive ? ' worker-badge-ping--active' : ''}`}
        aria-hidden="true"
      />
      <span className="worker-badge-label">{cfg.label}</span>
      {queueDepth > 0 && (
        <span className="worker-badge-queue" aria-label={`${queueDepth} jobs queued`}>
          {queueDepth}
        </span>
      )}
    </div>
  );
}
