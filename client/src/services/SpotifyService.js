/**
 * Spotify PKCE auth + track search service.
 *
 * No client secret is stored in the browser.
 * Tokens are kept in localStorage under 'spotify_auth'.
 */

const CLIENT_ID = import.meta.env.VITE_SPOTIFY_CLIENT_ID || '';
const REDIRECT_URI = `${window.location.origin}/spotify-callback`;
const SCOPES = 'user-read-private playlist-read-private';
const AUTH_KEY = 'spotify_auth';

// ---------------------------------------------------------------------------
// PKCE helpers
// ---------------------------------------------------------------------------

function _base64url(buf) {
  return btoa(String.fromCharCode(...new Uint8Array(buf)))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

async function _generateCodeChallenge(verifier) {
  const data = new TextEncoder().encode(verifier);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return _base64url(digest);
}

function _randomString(length = 64) {
  const bytes = crypto.getRandomValues(new Uint8Array(length));
  return _base64url(bytes).slice(0, length);
}

// ---------------------------------------------------------------------------
// Auth flow
// ---------------------------------------------------------------------------

export async function startAuth() {
  const verifier = _randomString();
  const challenge = await _generateCodeChallenge(verifier);
  sessionStorage.setItem('spotify_verifier', verifier);

  const params = new URLSearchParams({
    response_type: 'code',
    client_id: CLIENT_ID,
    scope: SCOPES,
    redirect_uri: REDIRECT_URI,
    code_challenge_method: 'S256',
    code_challenge: challenge,
  });
  window.location.href = `https://accounts.spotify.com/authorize?${params}`;
}

export async function handleCallback(code) {
  const verifier = sessionStorage.getItem('spotify_verifier');
  if (!verifier) throw new Error('No PKCE verifier in session');

  const res = await fetch('https://accounts.spotify.com/api/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'authorization_code',
      code,
      redirect_uri: REDIRECT_URI,
      client_id: CLIENT_ID,
      code_verifier: verifier,
    }),
  });
  if (!res.ok) throw new Error(`Spotify token exchange failed: ${res.status}`);
  const data = await res.json();
  _saveTokens(data);
  sessionStorage.removeItem('spotify_verifier');

  // Persist to Pi via announcer music-auth endpoint
  try {
    await fetch('/api/announcer/music-auth/spotify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        access_token: data.access_token,
        refresh_token: data.refresh_token,
        expires_at: new Date(Date.now() + data.expires_in * 1000).toISOString(),
        scope: data.scope,
      }),
    });
  } catch { /* non-fatal — token already in localStorage */ }

  return data;
}

function _saveTokens(data) {
  localStorage.setItem(AUTH_KEY, JSON.stringify({
    access_token: data.access_token,
    refresh_token: data.refresh_token,
    expires_at: Date.now() + data.expires_in * 1000,
    scope: data.scope,
  }));
}

async function _refreshToken(refreshToken) {
  const res = await fetch('https://accounts.spotify.com/api/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'refresh_token',
      refresh_token: refreshToken,
      client_id: CLIENT_ID,
    }),
  });
  if (!res.ok) throw new Error(`Spotify token refresh failed: ${res.status}`);
  const data = await res.json();
  _saveTokens({ ...data, refresh_token: data.refresh_token ?? refreshToken });
  return data.access_token;
}

export async function getToken() {
  const raw = localStorage.getItem(AUTH_KEY);
  if (!raw) return null;
  const auth = JSON.parse(raw);
  if (!auth.access_token) return null;

  // Refresh 60 s before expiry
  if (auth.expires_at - Date.now() < 60_000) {
    if (!auth.refresh_token) return null;
    return _refreshToken(auth.refresh_token);
  }
  return auth.access_token;
}

export function isAuthenticated() {
  const raw = localStorage.getItem(AUTH_KEY);
  if (!raw) return false;
  try { return !!JSON.parse(raw).access_token; } catch { return false; }
}

export function clearAuth() {
  localStorage.removeItem(AUTH_KEY);
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function _spotifyGet(path) {
  const token = await getToken();
  if (!token) throw new Error('Not authenticated with Spotify');
  const res = await fetch(`https://api.spotify.com/v1${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (res.status === 401) {
    clearAuth();
    throw new Error('Spotify token expired — please reconnect');
  }
  if (!res.ok) throw new Error(`Spotify API error: ${res.status}`);
  return res.json();
}

function _normalizeTrack(track) {
  return {
    spotify_id: track.id,
    title: track.name,
    artist: track.artists?.map(a => a.name).join(', ') || '',
    album: track.album?.name || '',
    duration_ms: track.duration_ms,
    preview_url: track.preview_url,
    image_url: track.album?.images?.[0]?.url || null,
  };
}

export async function searchTracks(query, limit = 10) {
  const params = new URLSearchParams({ q: query, type: 'track', limit: Math.min(limit, 50) });
  const data = await _spotifyGet(`/search?${params}`);
  return (data.tracks?.items || []).map(_normalizeTrack);
}

export async function getAudioAnalysis(spotifyId) {
  return _spotifyGet(`/audio-analysis/${spotifyId}`);
}

export async function getTrack(spotifyId) {
  const data = await _spotifyGet(`/tracks/${spotifyId}`);
  return _normalizeTrack(data);
}
