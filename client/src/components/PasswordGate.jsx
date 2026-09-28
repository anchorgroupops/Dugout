import React, { useState } from 'react';
import { Lock } from 'lucide-react';
import { loginWithPassword } from '../utils/appAuth';

const MESSAGES = {
  wrong: 'Wrong password',
  rate_limited: 'Too many tries. Wait a minute and try again.',
  error: "Couldn't reach the server. Try again.",
};

// Full-screen team-password prompt (SIGN-021). Shown instead of the
// dashboard when /api/auth/check says 401.
export default function PasswordGate({ onUnlocked }) {
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const submit = async (e) => {
    e.preventDefault();
    if (submitting || !password) return;
    setSubmitting(true);
    setError('');
    const result = await loginWithPassword(password);
    if (result === 'ok') {
      onUnlocked();
      return;
    }
    setSubmitting(false);
    setError(MESSAGES[result] || MESSAGES.error);
  };

  return (
    <div className="password-gate">
      <form className="password-gate-card glass-panel" onSubmit={submit} noValidate>
        <img src="/sharks-logo-round.png" alt="" className="password-gate-crest" width="96" height="96" />
        <h1 className="password-gate-title">The Sharks</h1>
        <p className="password-gate-sub">Enter the team password</p>
        <input
          className="password-gate-input"
          type="password"
          name="password"
          aria-label="Team password"
          autoComplete="current-password"
          enterKeyHint="go"
          autoFocus
          value={password}
          onChange={(e) => { setPassword(e.target.value); if (error) setError(''); }}
          disabled={submitting}
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={error ? 'password-gate-error' : undefined}
        />
        <button type="submit" className="password-gate-btn" disabled={submitting}>
          <Lock size={18} />
          {submitting ? 'Checking…' : 'Enter'}
        </button>
        {error && (
          <p id="password-gate-error" className="password-gate-error" role="alert">{error}</p>
        )}
      </form>
    </div>
  );
}
