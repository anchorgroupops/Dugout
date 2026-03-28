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
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
            <AlertTriangle size={18} color="var(--danger)" />
            <h3 style={{ margin: 0, color: 'var(--danger)', fontSize: 'var(--text-base)' }}>
              Something went wrong
            </h3>
          </div>
          <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)', margin: '0 0 0.75rem' }}>
            {this.state.error?.message || 'An unexpected error occurred in this section.'}
          </p>
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
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
