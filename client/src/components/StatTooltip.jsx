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
 *
 * Small-sample marker: when `dim=true`, attach an `sm` chip to the LABEL
 * rather than prefixing the value. The previous implementation used a
 * superscripted `~` immediately before the number, which visually merged
 * with values \u2265 1.000 (e.g. an OPS of 2.000 read as "~-2.000" / "negative
 * two") because the tilde glyph at 0.7em sat at the same horizontal level
 * as a minus sign would. Putting the marker on the label removes any chance
 * of that collision and keeps numeric values clean.
 */
export const TipBadge = ({ label, value, dim }) => {
  const explanation = STAT_GLOSSARY[label] || '';
  const title = dim ? `${explanation}${explanation ? ' \u2014 ' : ''}small sample (< 10 PA)` : explanation;
  const displayValue = (value === undefined || value === null || value === '') ? '\u2014' : value;
  return (
    <div className="stat-badge" title={title} style={dim ? { opacity: 0.55 } : undefined}>
      <span className="stat-badge__label">
        {label}
        {dim && (
          <span
            aria-label="small sample"
            style={{
              display: 'inline-block', marginLeft: '3px',
              padding: '0 4px', borderRadius: '3px',
              background: 'rgba(168, 116, 33, 0.25)',
              color: 'var(--warning, #facc15)',
              fontSize: '0.55em', fontWeight: '800',
              letterSpacing: '0.5px', verticalAlign: 'middle',
              lineHeight: 1.4,
            }}
          >
            sm
          </span>
        )}
      </span>
      <span className="stat-badge__value">{displayValue}</span>
    </div>
  );
};

/**
 * Display a player name with their number styled to the right.
 * name first, number after (e.g., "Leila VanDeusen  #13")
 */
export const PlayerName = ({ name, number, first, last, size = 'md' }) => {
  const displayName = name || `${first || ''} ${last || ''}`.trim() || '\u2014';
  // Show `#\u2014` (em-dash) when GameChanger hasn't supplied a jersey number
  // (sub players who haven't been issued one yet). The previous `#?` read
  // as a data error; `#\u2014` reads as "unassigned".
  const numStr = number == null ? '' : String(number).trim();
  const displayNum = numStr !== '' ? `#${numStr}` : '#\u2014';
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
