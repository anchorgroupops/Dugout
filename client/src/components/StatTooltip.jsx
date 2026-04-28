import React from 'react';
import { STAT_GLOSSARY } from '../utils/formatDate';

/**
 * Wraps children with a tooltip that shows the full meaning of a stat abbreviation.
 * Usage: <Tip label="OPS">{value}</Tip>
 * Or:    <Tip label="OPS" /> for just the label
 */
export const Tip = ({ label, children }) => {
  const explanation = STAT_GLOSSARY[label] || STAT_GLOSSARY[label?.toUpperCase()] || '';
  return (
    <span className="stat-tip" title={explanation} data-tip={explanation}>
      {children !== undefined ? children : label}
    </span>
  );
};

/**
 * StatBadge with built-in tooltip on the label.
 */
export const TipBadge = ({ label, value, dim }) => {
  const explanation = STAT_GLOSSARY[label] || '';
  const title = dim ? `${explanation}${explanation ? ' \u2014 ' : ''}small sample (< 10 PA)` : explanation;
  return (
    <div className="stat-badge" title={title} style={dim ? { opacity: 0.45 } : undefined}>
      <span className="stat-badge__label">{label}</span>
      <span className="stat-badge__value">
        {dim && value && value !== '\u2014'
          ? <><span style={{ fontSize: '0.7em', opacity: 0.6, verticalAlign: 'super' }}>~</span>{value}</>
          : (value ?? '\u2014')}
      </span>
    </div>
  );
};

/**
 * Display a player name with their number styled to the right.
 * name first, number after (e.g., "Leila VanDeusen  #13")
 */
export const PlayerName = ({ name, number, first, last, size = 'md' }) => {
  const displayName = name || `${first || ''} ${last || ''}`.trim() || '\u2014';
  const displayNum = number != null && number !== '' ? `#${number}` : '';
  const fontSize = size === 'sm' ? 'var(--text-sm)' : size === 'xs' ? 'var(--text-xs)' : 'var(--text-base)';

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem', fontSize }}>
      <span style={{ fontWeight: '600' }}>{displayName}</span>
      {displayNum && (
        <span style={{
          color: 'var(--primary-color)',
          fontWeight: '700',
          fontFamily: 'var(--font-heading)',
          fontSize: size === 'sm' ? 'var(--text-xs)' : 'var(--text-sm)',
          opacity: 0.85,
        }}>
          {displayNum}
        </span>
      )}
    </span>
  );
};

export default Tip;
