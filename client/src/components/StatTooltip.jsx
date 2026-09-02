import React, { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { STAT_GLOSSARY } from '../utils/formatDate';

/**
 * ─── Touch-reachable stat glossary ──────────────────────────────────────────
 *
 * Every stat abbreviation in this dashboard (AVG, OBP, BABIP, QAB%, FPSw%, …)
 * used to explain itself through a native `title` attribute alone. A phone
 * never fires `title`: there is no hover, and neither iOS Safari nor Android
 * Chrome long-press a non-link element into a tooltip. Since the dashboard is
 * explicitly a dugout tool used on a phone, that meant the glossary was
 * unreachable on the primary device.
 *
 * `useTipAnchor` gives any element a tap/click/keyboard-activated popover,
 * rendered through a portal on `document.body` so it escapes the
 * `overflow: hidden` on `.glass-panel` and `#root`. `title` is kept as-is for
 * pointer devices, which still get the zero-cost native behaviour.
 *
 * Two details that matter here specifically:
 *  - Stat badges sit INSIDE clickable player cards (Roster, Swot, League).
 *    The handler stops propagation so tapping a badge explains the stat
 *    instead of collapsing the card underneath it.
 *  - The popover closes on scroll rather than trying to follow the anchor.
 *    A tooltip that chases the page while you scroll a roster is worse than
 *    one that gets out of the way.
 */

const TIP_GAP = 8;      // px between anchor and bubble
const VIEWPORT_PAD = 8; // px minimum distance from the viewport edge

function useTipAnchor(text) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState(null);
  const anchorRef = useRef(null);
  const bubbleRef = useRef(null);
  const id = useId();
  const hasText = Boolean(text);

  const close = useCallback(() => setOpen(false), []);

  const toggle = useCallback((e) => {
    if (!hasText) return;
    // The badge lives inside a tappable card; explaining the stat must not
    // also toggle that card.
    e.stopPropagation();
    e.preventDefault();
    setOpen(prev => !prev);
  }, [hasText]);

  const onKeyDown = useCallback((e) => {
    if (!hasText) return;
    if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
      e.stopPropagation();
      e.preventDefault();
      setOpen(prev => !prev);
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  }, [hasText]);

  // Measure after paint so the bubble's real width is known before placing it.
  useLayoutEffect(() => {
    if (!open || !anchorRef.current) return;
    const a = anchorRef.current.getBoundingClientRect();
    const b = bubbleRef.current?.getBoundingClientRect();
    const bw = b?.width || 220;
    const bh = b?.height || 40;

    // Prefer above; flip below when the anchor is near the top of the screen.
    const above = a.top - bh - TIP_GAP >= VIEWPORT_PAD;
    const top = above ? a.top - bh - TIP_GAP : a.bottom + TIP_GAP;

    // Centre on the anchor, then clamp so the bubble never leaves the viewport.
    let left = a.left + a.width / 2 - bw / 2;
    const maxLeft = window.innerWidth - bw - VIEWPORT_PAD;
    if (left > maxLeft) left = maxLeft;
    if (left < VIEWPORT_PAD) left = VIEWPORT_PAD;

    setPos({ top, left, maxWidth: window.innerWidth - VIEWPORT_PAD * 2 });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDocDown = (e) => {
      if (anchorRef.current?.contains(e.target)) return;
      if (bubbleRef.current?.contains(e.target)) return;
      setOpen(false);
    };
    const onEsc = (e) => { if (e.key === 'Escape') setOpen(false); };
    // `pointerdown` covers mouse, touch and pen in one listener. The old
    // `mousedown`-only pattern elsewhere in this app misses taps on iOS,
    // which only synthesises mouse events over "clickable" elements.
    document.addEventListener('pointerdown', onDocDown, true);
    document.addEventListener('keydown', onEsc);
    window.addEventListener('scroll', close, true);
    window.addEventListener('resize', close);
    return () => {
      document.removeEventListener('pointerdown', onDocDown, true);
      document.removeEventListener('keydown', onEsc);
      window.removeEventListener('scroll', close, true);
      window.removeEventListener('resize', close);
    };
  }, [open, close]);

  const bubble = open && hasText && typeof document !== 'undefined'
    ? createPortal(
        <span
          ref={bubbleRef}
          id={id}
          role="tooltip"
          className="stat-tip-pop"
          style={pos
            ? { top: `${pos.top}px`, left: `${pos.left}px`, maxWidth: `${pos.maxWidth}px` }
            // First paint is off-screen: it lets the bubble size itself before
            // the layout effect places it, with no visible jump.
            : { top: '-9999px', left: '-9999px', visibility: 'hidden' }}
        >
          {text}
        </span>,
        document.body,
      )
    : null;

  const anchorProps = hasText
    ? {
        ref: anchorRef,
        onClick: toggle,
        onKeyDown,
        role: 'button',
        tabIndex: 0,
        'aria-expanded': open,
        'aria-describedby': open ? id : undefined,
      }
    : { ref: anchorRef };

  return { anchorProps, bubble, open };
}

/**
 * Wraps children with a tooltip that shows the full meaning of a stat abbreviation.
 * Usage: <Tip label="OPS">{value}</Tip>
 * Or:    <Tip label="OPS" /> for just the label
 */
export const Tip = ({ label, children }) => {
  const explanation = STAT_GLOSSARY[label] || STAT_GLOSSARY[label?.toUpperCase()] || '';
  const { anchorProps, bubble, open } = useTipAnchor(explanation);
  return (
    <>
      <span
        {...anchorProps}
        className={`stat-tip${open ? ' stat-tip--open' : ''}`}
        title={explanation}
      >
        {children !== undefined ? children : label}
      </span>
      {bubble}
    </>
  );
};

/**
 * StatBadge with built-in tooltip on the label.
 *
 * Small-sample marker: when `dim=true`, attach an `sm` chip to the LABEL
 * rather than prefixing the value. The previous implementation used a
 * superscripted `~` immediately before the number, which visually merged
 * with values ≥ 1.000 (e.g. an OPS of 2.000 read as "~-2.000" / "negative
 * two") because the tilde glyph at 0.7em sat at the same horizontal level
 * as a minus sign would. Putting the marker on the label removes any chance
 * of that collision and keeps numeric values clean.
 */
export const TipBadge = ({ label, value, dim }) => {
  const explanation = STAT_GLOSSARY[label] || '';
  const title = dim ? `${explanation}${explanation ? ' — ' : ''}small sample (< 10 PA)` : explanation;
  const displayValue = (value === undefined || value === null || value === '') ? '—' : value;
  const { anchorProps, bubble, open } = useTipAnchor(title);
  return (
    <>
      <div
        {...anchorProps}
        className={`stat-badge${open ? ' stat-badge--open' : ''}`}
        style={dim ? { opacity: 0.55 } : undefined}
        title={title}
      >
        <span className="stat-badge__label">
          {label}
          {dim && (
            <span
              aria-label="small sample"
              className="stat-badge__sm"
            >
              sm
            </span>
          )}
        </span>
        <span className="stat-badge__value">{displayValue}</span>
      </div>
      {bubble}
    </>
  );
};

/**
 * Icon or glyph whose meaning would otherwise live only in a `title`.
 * Gives it the same tap-to-explain treatment as a stat badge, so strength
 * icons, availability dots and threat glyphs are legible on a phone.
 */
export const TipIcon = ({ text, children, className = '', style }) => {
  const { anchorProps, bubble, open } = useTipAnchor(text);
  return (
    <>
      <span
        {...anchorProps}
        className={`tip-icon${open ? ' tip-icon--open' : ''}${className ? ` ${className}` : ''}`}
        style={style}
        title={text}
        aria-label={text}
      >
        {children}
      </span>
      {bubble}
    </>
  );
};

/**
 * Display a player name with their number styled to the right.
 * name first, number after (e.g., "Leila VanDeusen  #13")
 */
export const PlayerName = ({ name, number, first, last, size = 'md' }) => {
  const displayName = name || `${first || ''} ${last || ''}`.trim() || '—';
  // Show `#—` (em-dash) when GameChanger hasn't supplied a jersey number
  // (sub players who haven't been issued one yet). The previous `#?` read
  // as a data error; `#—` reads as "unassigned".
  const numStr = number == null ? '' : String(number).trim();
  const displayNum = numStr !== '' ? `#${numStr}` : '#—';
  const fontSize = size === 'sm' ? 'var(--text-sm)' : size === 'xs' ? 'var(--text-xs)' : 'var(--text-base)';

  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: '0.4rem', fontSize,
      // Long names must be free to shrink inside the flex rows that hold
      // them, rather than pushing stats off the edge of a phone screen.
      minWidth: 0, maxWidth: '100%',
    }}>
      <span style={{ fontWeight: '600', overflowWrap: 'anywhere', minWidth: 0 }}>{displayName}</span>
      {displayNum && (
        <span style={{
          color: 'var(--primary-color)',
          fontWeight: '700',
          fontFamily: 'var(--font-heading)',
          fontSize: size === 'sm' ? 'var(--text-xs)' : 'var(--text-sm)',
          opacity: 0.85,
          flexShrink: 0,
        }}>
          {displayNum}
        </span>
      )}
    </span>
  );
};

export default Tip;
