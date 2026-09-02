"""Tests for the DUGOUT_WRITE_TOKEN shared-secret gate and the
/api/music/ingest SSRF allow-list.

Covers:
- token unset  -> legacy Origin-only behaviour
- token set    -> 401 write_token_required / write_token_invalid
- X-Dugout-Token and Authorization: Bearer accepted (POST /api/auth/verify)
- /api/deploy still governed by DEPLOY_WEBHOOK_TOKEN only
- GET /api/health reports write_token_required and stays unauthenticated
- _is_ingest_url_allowed() / POST /api/music/ingest host allow-list
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import sync_daemon as sd


TOKEN = "s3cr3t-write-token"
ORIGIN = "https://dugout.joelycannoli.com"


@pytest.fixture
def client():
    sd.app.config["TESTING"] = True
    return sd.app.test_client()


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    """The in-app write throttle is process-global; reset it per test."""
    with sd._MUTATE_RATE_LOCK:
        sd._MUTATE_RATE_BUCKETS.clear()
    yield
    with sd._MUTATE_RATE_LOCK:
        sd._MUTATE_RATE_BUCKETS.clear()


@pytest.fixture
def token_set(monkeypatch):
    monkeypatch.setenv("DUGOUT_WRITE_TOKEN", TOKEN)


@pytest.fixture
def token_unset(monkeypatch):
    monkeypatch.delenv("DUGOUT_WRITE_TOKEN", raising=False)


# ---------------------------------------------------------------------------
# Token unset -> unchanged behaviour
# ---------------------------------------------------------------------------

class TestTokenUnset:
    def test_verify_passes_with_allowed_origin(self, client, token_unset):
        r = client.post("/api/auth/verify", json={}, headers={"Origin": ORIGIN})
        assert r.status_code == 200
        assert r.get_json() == {"ok": True}

    def test_origin_check_still_enforced(self, client, token_unset):
        r = client.post("/api/auth/verify", json={}, headers={"Origin": "https://evil.example"})
        assert r.status_code == 403
        assert r.get_json()["error"] == "forbidden_origin"

    def test_missing_origin_still_rejected(self, client, token_unset):
        r = client.post("/api/auth/verify", json={})
        assert r.status_code == 403
        assert r.get_json()["error"] == "origin_required"


# ---------------------------------------------------------------------------
# Token set -> shared secret required
# ---------------------------------------------------------------------------

class TestTokenSet:
    def test_missing_header_401(self, client, token_set):
        r = client.post("/api/auth/verify", json={}, headers={"Origin": ORIGIN})
        assert r.status_code == 401
        assert r.get_json()["error"] == "write_token_required"

    def test_wrong_token_401(self, client, token_set):
        r = client.post(
            "/api/auth/verify",
            json={},
            headers={"Origin": ORIGIN, "X-Dugout-Token": "nope"},
        )
        assert r.status_code == 401
        assert r.get_json()["error"] == "write_token_invalid"

    def test_correct_token_passes(self, client, token_set):
        r = client.post(
            "/api/auth/verify",
            json={},
            headers={"Origin": ORIGIN, "X-Dugout-Token": TOKEN},
        )
        assert r.status_code == 200
        assert r.get_json() == {"ok": True}

    def test_bearer_form_accepted(self, client, token_set):
        r = client.post(
            "/api/auth/verify",
            json={},
            headers={"Origin": ORIGIN, "Authorization": f"Bearer {TOKEN}"},
        )
        assert r.status_code == 200
        assert r.get_json() == {"ok": True}

    def test_origin_still_enforced_with_valid_token(self, client, token_set):
        r = client.post(
            "/api/auth/verify",
            json={},
            headers={"Origin": "https://evil.example", "X-Dugout-Token": TOKEN},
        )
        assert r.status_code == 403

    def test_other_mutating_route_gated(self, client, token_set):
        """The guard is central, so a route that never mentions the token is covered."""
        r = client.post("/api/availability", json={}, headers={"Origin": ORIGIN})
        assert r.status_code == 401
        assert r.get_json()["error"] == "write_token_required"

    def test_multipart_route_gated(self, client, token_set):
        """csv-import bypasses _guard_mutating_request (multipart) but not the gate."""
        r = client.post("/api/announcer/csv-import", headers={"Origin": ORIGIN})
        assert r.status_code == 401

    def test_get_requests_unaffected(self, client, token_set):
        r = client.get("/api/health")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Deploy / kick endpoints keep their own token
# ---------------------------------------------------------------------------

class TestDeployExempt:
    def test_deploy_uses_deploy_token_not_write_token(self, client, token_set, monkeypatch):
        monkeypatch.setenv("DEPLOY_WEBHOOK_ENABLED", "1")
        monkeypatch.setenv("DEPLOY_WEBHOOK_TOKEN", "deploy-tok")
        # Write token present but wrong -> still reaches the deploy-token check.
        r = client.post(
            "/api/deploy",
            json={},
            headers={"Origin": ORIGIN, "X-Dugout-Token": "wrong"},
        )
        assert r.status_code == 401
        assert r.get_json()["error"] == "Unauthorized"

    def test_kick_exempt_from_write_token(self, client, token_set, monkeypatch):
        monkeypatch.delenv("DEPLOY_WEBHOOK_TOKEN", raising=False)
        r = client.post("/api/sync/kick", headers={"Origin": ORIGIN})
        # 503 from _require_deploy_token, not 401 write_token_required.
        assert r.status_code == 503

    def test_exempt_path_helper(self):
        assert sd._write_token_exempt_path("/api/deploy")
        assert sd._write_token_exempt_path("/api/deploy/status")
        assert sd._write_token_exempt_path("/api/sync/kick")
        assert sd._write_token_exempt_path("/api/sync/kick/status")
        assert not sd._write_token_exempt_path("/api/sync/status")
        assert not sd._write_token_exempt_path("/api/availability")


# ---------------------------------------------------------------------------
# /api/health advertises the requirement
# ---------------------------------------------------------------------------

class TestHealthReportsTokenRequirement:
    def test_true_when_token_set(self, client, token_set):
        body = client.get("/api/health").get_json()
        assert body["write_token_required"] is True

    def test_false_when_token_unset(self, client, token_unset):
        body = client.get("/api/health").get_json()
        assert body["write_token_required"] is False


# ---------------------------------------------------------------------------
# SSRF allow-list on /api/music/ingest
# ---------------------------------------------------------------------------

BAD_URLS = [
    "http://127.0.0.1/x",
    "http://169.254.169.254/",
    "http://sharks_api/",
    "http://localhost:5000/x",
    "http://evil.example/track.mp3",
    "https://youtube.com.evil.example/watch?v=1",
    "file:///etc/passwd",
    "ftp://youtube.com/x",
    "http://redis.internal/x",
    "http://pi.local/x",
]


class TestIngestUrlAllowList:
    @pytest.mark.parametrize("url", BAD_URLS)
    def test_rejects(self, url):
        assert sd._is_ingest_url_allowed(url) is False

    @pytest.mark.parametrize("url", [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://music.youtube.com/watch?v=abc",
    ])
    def test_accepts_youtube(self, url, monkeypatch):
        monkeypatch.setattr(sd.socket, "getaddrinfo",
                            lambda *a, **k: [(2, 1, 6, "", ("142.250.72.14", 0))])
        assert sd._is_ingest_url_allowed(url) is True

    def test_rejects_allowlisted_host_resolving_private(self, monkeypatch):
        monkeypatch.setattr(sd.socket, "getaddrinfo",
                            lambda *a, **k: [(2, 1, 6, "", ("10.0.0.5", 0))])
        assert sd._is_ingest_url_allowed("https://youtu.be/abc") is False

    def test_rejects_when_dns_fails(self, monkeypatch):
        def boom(*a, **k):
            raise OSError("nxdomain")
        monkeypatch.setattr(sd.socket, "getaddrinfo", boom)
        assert sd._is_ingest_url_allowed("https://youtu.be/abc") is False


class TestMusicIngestEndpoint:
    @pytest.mark.parametrize("url", ["http://127.0.0.1/x", "http://169.254.169.254/",
                                     "http://sharks_api/", "http://evil.example/x"])
    def test_endpoint_rejects_bad_url(self, client, token_unset, url):
        r = client.post(
            "/api/music/ingest",
            json={"player_id": "p1", "url": url},
            headers={"Origin": ORIGIN},
        )
        assert r.status_code == 400
        assert r.get_json()["error"] == "url_not_allowed"

    def test_endpoint_accepts_youtube(self, client, token_unset, monkeypatch):
        monkeypatch.setattr(sd.socket, "getaddrinfo",
                            lambda *a, **k: [(2, 1, 6, "", ("142.250.72.14", 0))])
        import music_ingest

        monkeypatch.setattr(music_ingest, "has_yt_dlp", lambda: True)
        monkeypatch.setattr(music_ingest, "ffmpeg_available", lambda: True)
        monkeypatch.setattr(
            music_ingest, "ingest_url",
            lambda player_id, url, **kw: {"song_id": 7, "file_path": "/audio/music/p1/x-hook.mp3"},
        )

        r = client.post(
            "/api/music/ingest",
            json={"player_id": "p1", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            headers={"Origin": ORIGIN},
        )
        assert r.status_code == 201
        assert r.get_json()["song_id"] == 7


# ---------------------------------------------------------------------------
# CORS: never stamp ACAO on responses that carry no Origin
# ---------------------------------------------------------------------------

class TestCorsAlwaysSendOff:
    def test_no_origin_no_acao_header(self, client, token_unset):
        r = client.get("/api/sync/status")
        assert "Access-Control-Allow-Origin" not in r.headers

    def test_allowed_origin_echoed(self, client, token_unset):
        r = client.get("/api/sync/status", headers={"Origin": ORIGIN})
        assert r.headers.get("Access-Control-Allow-Origin") == ORIGIN

    def test_disallowed_origin_no_acao_header(self, client, token_unset):
        r = client.get("/api/sync/status", headers={"Origin": "https://evil.example"})
        assert "Access-Control-Allow-Origin" not in r.headers


# ---------------------------------------------------------------------------
# /api/health: CSV-first source resolution
# ---------------------------------------------------------------------------

class TestHealthSourceResolution:
    def test_team_falls_back_to_team_json(self, client, token_unset, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        (tmp_path / "team.json").write_text("{}")
        src = client.get("/api/health").get_json()["sources"]["team"]
        assert src["exists"] is True
        assert src["file"] == "team.json"
        assert src["required"] is True

    def test_team_prefers_enriched(self, client, token_unset, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        (tmp_path / "team.json").write_text("{}")
        (tmp_path / "team_merged.json").write_text("{}")
        (tmp_path / "team_enriched.json").write_text("{}")
        src = client.get("/api/health").get_json()["sources"]["team"]
        assert src["file"] == "team_enriched.json"

    def test_team_missing_entirely_is_stale(self, client, token_unset, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        data = client.get("/api/health").get_json()
        assert data["sources"]["team"]["exists"] is False
        assert "team" in data["stale_sources"]
        assert data["sources"]["team"]["file"] == "team_enriched.json"

    def test_pipeline_health_optional_when_live_scrape_off(self, client, token_unset,
                                                           monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "GC_LIVE_SCRAPE_ENABLED", False)
        data = client.get("/api/health").get_json()
        assert data["sources"]["pipeline_health"]["required"] is False
        assert "pipeline_health" not in data["stale_sources"]

    def test_pipeline_health_required_when_live_scrape_on(self, client, token_unset,
                                                          monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "GC_LIVE_SCRAPE_ENABLED", True)
        data = client.get("/api/health").get_json()
        assert data["sources"]["pipeline_health"]["required"] is True
        assert "pipeline_health" in data["stale_sources"]

    def test_shape_unchanged(self, client, token_unset, monkeypatch, tmp_path):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        data = client.get("/api/health").get_json()
        assert set(data) >= {"checked_at", "stale_sources", "sources"}
        for src in data["sources"].values():
            assert {"exists", "stale", "required"} <= set(src)


# ---------------------------------------------------------------------------
# Deploy webhook off by default (SIGN-007: Watchtower owns deploys)
# ---------------------------------------------------------------------------

class TestDeployWebhookDisabled:
    @pytest.fixture(autouse=True)
    def _disabled(self, monkeypatch):
        monkeypatch.delenv("DEPLOY_WEBHOOK_ENABLED", raising=False)
        monkeypatch.setenv("DEPLOY_WEBHOOK_TOKEN", "deploy-tok")

    def test_post_deploy_404(self, client):
        r = client.post("/api/deploy", headers={"Authorization": "Bearer deploy-tok"})
        assert r.status_code == 404
        assert r.get_json()["error"] == "deploy_webhook_disabled"

    def test_deploy_status_404(self, client):
        r = client.get("/api/deploy/status", headers={"Authorization": "Bearer deploy-tok"})
        assert r.status_code == 404
        assert r.get_json()["error"] == "deploy_webhook_disabled"

    def test_404_before_token_check(self, client):
        """No token at all still 404s (the disable gate runs first)."""
        r = client.post("/api/deploy")
        assert r.status_code == 404

    def test_sync_kick_unaffected(self, client):
        r = client.post("/api/sync/kick", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401

    def test_enabled_flag_restores_endpoint(self, client, monkeypatch):
        monkeypatch.setenv("DEPLOY_WEBHOOK_ENABLED", "1")
        r = client.post("/api/deploy", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401
