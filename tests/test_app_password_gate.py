"""Team-password gate (DUGOUT_APP_PASSWORD, SIGN-021).

Covers login / check / logout, cookie flags, gate on vs off, every
exemption (health, auth routes, worker token, deploy bearer, /api/deploy),
the negative cases (wrong worker token / wrong bearer still locked), the
write-token exemption of login/logout, and session invalidation when the
password or the session secret changes.
"""
from __future__ import annotations

import hashlib
import hmac
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import sync_daemon as sd


PASSWORD = "correct horse battery"
WRITE_TOKEN = "w-token-123"
DEPLOY_TOKEN = "d-token-456"
ORIGIN = "https://dugout.joelycannoli.com"
COOKIE = sd.APP_SESSION_COOKIE


@pytest.fixture
def client():
    sd.app.config["TESTING"] = True
    return sd.app.test_client()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Per-test env + no rate-limit carry-over + no real login delay."""
    for var in ("DUGOUT_APP_PASSWORD", "DUGOUT_SESSION_SECRET",
                "DUGOUT_WRITE_TOKEN", "DEPLOY_WEBHOOK_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(sd, "APP_LOGIN_FAIL_DELAY_SEC", 0)
    with sd._MUTATE_RATE_LOCK:
        sd._MUTATE_RATE_BUCKETS.clear()
    yield
    with sd._MUTATE_RATE_LOCK:
        sd._MUTATE_RATE_BUCKETS.clear()


@pytest.fixture
def gate_on(monkeypatch):
    monkeypatch.setenv("DUGOUT_APP_PASSWORD", PASSWORD)


def _login(client, password=PASSWORD, **headers):
    return client.post("/api/auth/login", json={"password": password},
                       headers={"Origin": ORIGIN, **headers})


def _set_cookie_header(resp) -> str:
    cookies = [v for k, v in resp.headers.items() if k.lower() == "set-cookie"]
    assert len(cookies) == 1, cookies
    return cookies[0]


# ---------------------------------------------------------------------------
# Gate off (DUGOUT_APP_PASSWORD unset) -> unchanged behaviour
# ---------------------------------------------------------------------------

class TestGateOff:
    def test_api_reads_are_open(self, client):
        r = client.get("/api/auth/check")
        assert r.status_code == 204
        r = client.get("/api/sync/status")
        assert r.status_code != 401

    def test_login_is_a_no_op(self, client):
        r = _login(client, password="anything")
        assert r.status_code == 204
        assert "set-cookie" not in {k.lower() for k in r.headers.keys()}


# ---------------------------------------------------------------------------
# Login / check / logout
# ---------------------------------------------------------------------------

class TestLogin:
    def test_right_password_sets_session_cookie(self, client, gate_on):
        r = _login(client)
        assert r.status_code == 204
        cookie = _set_cookie_header(r)
        pw_hash = hashlib.sha256(PASSWORD.encode()).digest()
        expected = hmac.new(pw_hash, b"dugout-session-v1" + pw_hash, hashlib.sha256).hexdigest()
        assert cookie.startswith(f"{COOKIE}={expected};")
        lower = cookie.lower()
        assert "httponly" in lower
        assert "samesite=lax" in lower
        assert "path=/" in lower
        assert f"max-age={180 * 24 * 60 * 60}" in lower
        assert "secure" not in lower  # plain http test request

    def test_cookie_value_is_the_hmac_not_the_password(self, client, gate_on):
        r = _login(client)
        cookie = _set_cookie_header(r)
        value = cookie.split(";", 1)[0].split("=", 1)[1]
        assert PASSWORD not in cookie
        assert len(value) == 64 and all(c in "0123456789abcdef" for c in value)

    def test_secure_flag_behind_https_proxy(self, client, gate_on):
        r = _login(client, **{"X-Forwarded-Proto": "https"})
        assert r.status_code == 204
        assert "secure" in _set_cookie_header(r).lower()

    def test_secure_flag_on_https_request(self, client, gate_on):
        r = client.post("/api/auth/login", json={"password": PASSWORD},
                        headers={"Origin": ORIGIN}, base_url="https://localhost")
        assert r.status_code == 204
        assert "secure" in _set_cookie_header(r).lower()

    def test_wrong_password_401_and_no_cookie(self, client, gate_on, monkeypatch):
        slept = []
        monkeypatch.setattr(sd.time, "sleep", lambda s: slept.append(s))
        monkeypatch.setattr(sd, "APP_LOGIN_FAIL_DELAY_SEC", 0.3)
        r = _login(client, password="nope")
        assert r.status_code == 401
        assert r.get_json() == {"error": "bad_password"}
        assert "set-cookie" not in {k.lower() for k in r.headers.keys()}
        assert slept == [0.3]

    @pytest.mark.parametrize("body", [{}, {"password": ""}, {"password": None}, [], "x"])
    def test_missing_or_malformed_password_is_401(self, client, gate_on, body):
        r = client.post("/api/auth/login", json=body, headers={"Origin": ORIGIN})
        assert r.status_code == 401
        assert r.get_json() == {"error": "bad_password"}

    def test_login_needs_allowed_origin(self, client, gate_on):
        r = client.post("/api/auth/login", json={"password": PASSWORD},
                        headers={"Origin": "https://evil.example"})
        assert r.status_code == 403

    def test_login_is_rate_limited(self, client, gate_on):
        codes = [_login(client, password="nope").status_code for _ in range(sd.MUTATE_RATE_MAX + 1)]
        assert codes[:-1] == [401] * sd.MUTATE_RATE_MAX
        assert codes[-1] == 429


class TestCheckAndLogout:
    def test_check_without_cookie_is_401(self, client, gate_on):
        r = client.get("/api/auth/check")
        assert r.status_code == 401
        assert r.get_json() == {"error": "auth_required"}

    def test_check_with_cookie_is_204(self, client, gate_on):
        assert _login(client).status_code == 204
        assert client.get("/api/auth/check").status_code == 204

    def test_forged_cookie_is_rejected(self, client, gate_on):
        client.set_cookie(COOKIE, "0" * 64)
        assert client.get("/api/auth/check").status_code == 401

    def test_logout_clears_the_session(self, client, gate_on):
        _login(client)
        r = client.post("/api/auth/logout", json={}, headers={"Origin": ORIGIN})
        assert r.status_code == 204
        cookie = _set_cookie_header(r).lower()
        assert cookie.startswith(f"{COOKIE}=;") and ("max-age=0" in cookie or "expires=thu, 01 jan 1970" in cookie)
        assert client.get("/api/auth/check").status_code == 401

    def test_password_change_invalidates_sessions(self, client, gate_on, monkeypatch):
        _login(client)
        assert client.get("/api/auth/check").status_code == 204
        monkeypatch.setenv("DUGOUT_APP_PASSWORD", "a new password")
        assert client.get("/api/auth/check").status_code == 401

    def test_password_change_invalidates_sessions_with_secret_set(self, client, gate_on, monkeypatch):
        monkeypatch.setenv("DUGOUT_SESSION_SECRET", "s" * 32)
        _login(client)
        assert client.get("/api/auth/check").status_code == 204
        monkeypatch.setenv("DUGOUT_APP_PASSWORD", "a new password")
        assert client.get("/api/auth/check").status_code == 401

    def test_secret_rotation_invalidates_sessions(self, client, gate_on, monkeypatch):
        monkeypatch.setenv("DUGOUT_SESSION_SECRET", "s" * 32)
        _login(client)
        monkeypatch.setenv("DUGOUT_SESSION_SECRET", "t" * 32)
        assert client.get("/api/auth/check").status_code == 401


# ---------------------------------------------------------------------------
# The gate on the rest of /api
# ---------------------------------------------------------------------------

class TestGate:
    @pytest.mark.parametrize("path", ["/api/team", "/api/sync/status", "/api/announcer/roster",
                                      "/api/no-such-route"])
    def test_reads_need_a_session(self, client, gate_on, path):
        r = client.get(path)
        assert r.status_code == 401
        assert r.get_json() == {"error": "auth_required"}

    def test_writes_need_a_session_before_anything_else(self, client, gate_on):
        r = client.post("/api/availability", json={}, headers={"Origin": ORIGIN})
        assert r.status_code == 401
        assert r.get_json() == {"error": "auth_required"}

    def test_session_opens_reads(self, client, gate_on):
        _login(client)
        r = client.get("/api/sync/status")
        assert r.status_code == 200

    def test_session_does_not_replace_the_write_token(self, client, gate_on, monkeypatch):
        monkeypatch.setenv("DUGOUT_WRITE_TOKEN", WRITE_TOKEN)
        _login(client)
        r = client.post("/api/auth/verify", json={}, headers={"Origin": ORIGIN})
        assert r.status_code == 401
        assert r.get_json()["error"] == "write_token_required"

    def test_non_api_paths_are_not_gated_by_flask(self, client, gate_on):
        # nginx fronts the SPA shell; Flask only gates /api/.
        r = client.get("/")
        assert r.status_code != 401

    def test_options_preflight_not_gated(self, client, gate_on):
        r = client.options("/api/team", headers={"Origin": ORIGIN,
                                                 "Access-Control-Request-Method": "GET"})
        assert r.status_code != 401


class _FakeAnnouncerDB:
    """Keeps the worker-route tests off the real data/ announcer DB."""
    def update_heartbeat(self, worker_id, version):
        pass

    def get_pending_jobs(self, quality=None):
        return []


class TestExemptions:
    @pytest.fixture(autouse=True)
    def _fake_announcer_db(self, monkeypatch):
        monkeypatch.setattr(sd, "_announcer_db", lambda: _FakeAnnouncerDB())

    def test_health_is_open(self, client, gate_on):
        assert client.get("/api/health").status_code == 200

    def test_worker_token_opens_worker_routes(self, client, gate_on, monkeypatch):
        monkeypatch.setenv("DUGOUT_WRITE_TOKEN", WRITE_TOKEN)
        r = client.get("/api/announcer/render-queue", headers={"X-Dugout-Token": WRITE_TOKEN})
        assert r.status_code == 200
        r = client.post("/api/announcer/heartbeat", json={"worker_id": "t"},
                        headers={"X-Dugout-Token": WRITE_TOKEN, "Origin": ORIGIN})
        assert r.status_code == 200

    def test_worker_token_as_bearer(self, client, gate_on, monkeypatch):
        monkeypatch.setenv("DUGOUT_WRITE_TOKEN", WRITE_TOKEN)
        r = client.get("/api/announcer/render-queue",
                       headers={"Authorization": f"Bearer {WRITE_TOKEN}"})
        assert r.status_code == 200

    def test_wrong_worker_token_still_locked(self, client, gate_on, monkeypatch):
        monkeypatch.setenv("DUGOUT_WRITE_TOKEN", WRITE_TOKEN)
        r = client.get("/api/announcer/render-queue", headers={"X-Dugout-Token": "wrong"})
        assert r.status_code == 401
        assert r.get_json() == {"error": "auth_required"}

    def test_worker_token_ignored_when_unconfigured(self, client, gate_on):
        r = client.get("/api/team", headers={"X-Dugout-Token": ""})
        assert r.status_code == 401

    def test_deploy_bearer_opens_sync_kick_status(self, client, gate_on, monkeypatch):
        monkeypatch.setenv("DEPLOY_WEBHOOK_TOKEN", DEPLOY_TOKEN)
        r = client.get("/api/sync/kick/status", headers={"Authorization": f"Bearer {DEPLOY_TOKEN}"})
        assert r.status_code == 200

    def test_wrong_deploy_bearer_still_locked(self, client, gate_on, monkeypatch):
        monkeypatch.setenv("DEPLOY_WEBHOOK_TOKEN", DEPLOY_TOKEN)
        r = client.get("/api/sync/kick/status", headers={"Authorization": "Bearer nope"})
        assert r.status_code == 401
        assert r.get_json() == {"error": "auth_required"}

    def test_deploy_route_keeps_its_own_auth(self, client, gate_on, monkeypatch):
        monkeypatch.setenv("DEPLOY_WEBHOOK_TOKEN", DEPLOY_TOKEN)
        r = client.post("/api/deploy", json={}, headers={"Authorization": "Bearer nope"})
        # Reaches the route (dormant 503 / 401 bad bearer), not the gate.
        assert r.get_json() != {"error": "auth_required"}

    def test_login_exempt_from_write_token(self, client, gate_on, monkeypatch):
        monkeypatch.setenv("DUGOUT_WRITE_TOKEN", WRITE_TOKEN)
        assert _login(client).status_code == 204

    def test_logout_exempt_from_write_token(self, client, gate_on, monkeypatch):
        monkeypatch.setenv("DUGOUT_WRITE_TOKEN", WRITE_TOKEN)
        r = client.post("/api/auth/logout", json={}, headers={"Origin": ORIGIN})
        assert r.status_code == 204

    def test_write_token_exempt_list(self):
        assert sd._write_token_exempt_path("/api/auth/login")
        assert sd._write_token_exempt_path("/api/auth/logout")
        assert not sd._write_token_exempt_path("/api/auth/verify")
