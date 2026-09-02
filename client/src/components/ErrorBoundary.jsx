import React from 'react';
import { AlertTriangle } from 'lucide-react';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    console.error('[ErrorBoundary]', error, info?.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="glass-panel" style={{
          padding: '1.5rem', margin: '1rem 0',
          borderColor: 'rgba(179, 74, 57, 0.3)',
          background: 'rgba(179, 74, 57, 0.08)',
          // The panel must never be wider than the phone: `#root` is
          // `overflow-x: hidden`, so anything that overflows is clipped away
          // rather than scrollable.
          maxWidth: '100%', boxSizing: 'border-box',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
            {/* Without flexShrink the icon squashes to a sliver next to a long
                heading on a narrow screen. */}
            <AlertTriangle size={18} color="var(--danger)" style={{ flexShrink: 0 }} />
            <h3 style={{ margin: 0, color: 'var(--danger)', fontSize: 'var(--text-base)', minWidth: 0 }}>
              Something went wrong
            </h3>
          </div>
          {/* React error messages routinely contain one unbroken token (a
              bundled asset URL, a minified identifier). `anywhere` forces it to
              break so the user can actually read what they're recovering from. */}
          <p style={{
            fontSize: 'var(--text-sm)', color: 'var(--text-muted)', margin: '0 0 0.75rem',
            overflowWrap: 'anywhere', wordBreak: 'break-word', maxWidth: '100%',
          }}>
            {this.state.error?.message || 'An unexpected error occurred in this section.'}
          </p>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            <button
              onClick={() => this.setState({ hasError: false, error: null })}
              style={{
                background: 'var(--primary-glow)', color: 'var(--primary-color)',
                border: '1px solid rgba(4, 101, 104, 0.27)',
                padding: '0.5rem 1rem', borderRadius: '8px', cursor: 'pointer',
                fontWeight: '600', fontSize: 'var(--text-sm)',
                minHeight: 'var(--touch-min)',
              }}
            >
              Try Again
            </button>
            {/* "Try Again" only resets local state, so a child that throws every
                render traps a phone user in a tap-loop with no way out — a full
                reload is the escape hatch. */}
            <button
              onClick={() => window.location.reload()}
              style={{
                background: 'rgba(255,255,255,0.06)', color: 'var(--text-main)',
                border: '1px solid rgba(255,255,255,0.15)',
                padding: '0.5rem 1rem', borderRadius: '8px', cursor: 'pointer',
                fontWeight: '600', fontSize: 'var(--text-sm)',
                minHeight: 'var(--touch-min)',
              }}
            >
              Reload app
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
