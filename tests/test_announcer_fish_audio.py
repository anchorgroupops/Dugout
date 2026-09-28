"""fish.audio voices: provider request shape, profile → provider routing,
custom catalogue voices, the catalogue search proxy and render-all in a voice.

No test reaches the network: every fish.audio / ElevenLabs call is a fake, and
keys are controlled by patching `_resolve_secret` so a key added to the host
environment later can't turn a test into a billed call.
"""
from __future__ import annotations

import json

import pytest

import announcer_engine as ae
import sync_daemon as sd

ORIGIN = "https://test.example.com"
STEITZER = "86126c4c4dad4911979556b4569802cd"


class _Resp:
    def __init__(self, status=200, content=b"", payload=None):
        self.status_code, self.content, self._payload = status, content, payload
        self.text = json.dumps(payload) if payload is not None else content.decode("latin-1")

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _keys(monkeypatch, **present):
    """Only the named secrets resolve; everything else reads as unset."""
    monkeypatch.setattr(ae, "_resolve_secret", lambda name, default="": present.get(name, default))


def _no_network(*a, **k):
    raise AssertionError("unexpected network call")


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ae, "VOICE_PROFILES_CUSTOM_FILE", tmp_path / "voice_profiles_custom.json")
    monkeypatch.setattr(ae, "VOICE_SELECTION_FILE", tmp_path / "voice_selection.json")
    monkeypatch.setattr(ae, "_ensure_dirs", lambda: None)
    monkeypatch.setattr(ae.requests, "post", _no_network)
    monkeypatch.setattr(ae.requests, "get", _no_network)
    monkeypatch.delenv("FISH_AUDIO_MODEL", raising=False)


# ── provider ────────────────────────────────────────────────────────────────

class TestFishAudioTTS:
    def test_request_shape(self, monkeypatch):
        _keys(monkeypatch, FISH_AUDIO_API_KEY="fish_test")
        seen = {}

        def _post(url, json=None, headers=None, timeout=None):
            seen.update(url=url, json=json, headers=headers, timeout=timeout)
            return _Resp(200, b"ID3mp3bytes")

        monkeypatch.setattr(ae.requests, "post", _post)
        audio = ae.FishAudioTTS().synthesize("Now batting", {"fish_reference_id": STEITZER, "speed": 0.9})
        assert audio == b"ID3mp3bytes"
        assert seen["url"] == "https://api.fish.audio/v1/tts"
        assert seen["headers"]["Authorization"] == "Bearer fish_test"
        assert seen["headers"]["model"] == "s2.1-pro"
        assert seen["timeout"] == 60
        assert seen["json"] == {
            "text": "Now batting", "reference_id": STEITZER, "format": "mp3", "mp3_bitrate": 128,
            "normalize": True, "latency": "normal", "prosody": {"speed": 0.9, "volume": 0},
        }

    def test_model_from_env_and_no_reference_without_profile_id(self, monkeypatch):
        _keys(monkeypatch, FISH_AUDIO_API_KEY="k")
        monkeypatch.setenv("FISH_AUDIO_MODEL", "s1")
        seen = {}
        monkeypatch.setattr(ae.requests, "post",
                            lambda url, json=None, headers=None, timeout=None:
                            seen.update(json=json, headers=headers) or _Resp(200, b"a"))
        ae.FishAudioTTS().synthesize("hi", {})
        assert seen["headers"]["model"] == "s1"
        assert "reference_id" not in seen["json"]
        assert seen["json"]["prosody"]["speed"] == 1.0

    @pytest.mark.parametrize("status,body,expected", [
        (402, {"status": 402, "message": "Insufficient balance", "reason": "payment_required"},
         r"402: Insufficient balance \(payment_required\)"),
        (401, {"status": 401, "message": "Invalid api key"}, r"401: Invalid api key"),
        (503, None, r"503"),
    ])
    def test_errors_carry_the_api_message(self, monkeypatch, status, body, expected):
        _keys(monkeypatch, FISH_AUDIO_API_KEY="k")
        monkeypatch.setattr(ae.requests, "post", lambda *a, **k: _Resp(status, b"busy", body))
        with pytest.raises(RuntimeError, match=expected):
            ae.FishAudioTTS().synthesize("hi", {"fish_reference_id": STEITZER})

    def test_availability_follows_the_key(self, monkeypatch):
        _keys(monkeypatch)
        assert ae.FishAudioTTS().available() is False
        with pytest.raises(RuntimeError, match="FISH_AUDIO_API_KEY not set"):
            ae.FishAudioTTS().synthesize("hi", {})
        _keys(monkeypatch, FISH_AUDIO_API_KEY="k")
        assert ae.FishAudioTTS().available() is True

    def test_gets_plain_text(self):
        assert ae.text_for_provider(ae.FishAudioTTS(), "Now [pause:0.5s] batting [breath]") == "Now batting"

    def test_in_chain_after_elevenlabs(self, monkeypatch):
        for var in ("LOCAL_TTS_URL", "REPLICATE_API_TOKEN", "ANNOUNCER_VOICE_REF_URL"):
            monkeypatch.delenv(var, raising=False)
        _keys(monkeypatch, ELEVENLABS_API_KEY="el", FISH_AUDIO_API_KEY="k")
        names = [p.name for p in ae._build_provider_chain()]
        assert names.index("fish_audio") == names.index("elevenlabs") + 1

    def test_probe_lists_fish_audio(self, monkeypatch):
        _keys(monkeypatch, FISH_AUDIO_API_KEY="k")
        fish = next(p for p in ae.probe_tts_providers() if p["name"] == "fish_audio")
        assert fish["available"] is True

    def test_provider_health_pings_catalogue(self, monkeypatch):
        _keys(monkeypatch, FISH_AUDIO_API_KEY="k")
        monkeypatch.delenv("LOCAL_TTS_URL", raising=False)
        seen = {}

        def _get(url, params=None, headers=None, timeout=None):
            seen.update(url=url, params=params, headers=headers)
            return _Resp(200, payload={"items": []})

        monkeypatch.setattr(ae.requests, "get", _get)
        assert ae.check_provider_health()["fish_audio_ping"] is True
        assert seen["url"] == "https://api.fish.audio/model"
        assert seen["params"] == {"page_size": 1}
        assert seen["headers"]["Authorization"] == "Bearer k"


# ── profiles honour their provider ──────────────────────────────────────────

def _roster(tmp_path, monkeypatch, players):
    roster_file = tmp_path / "roster.json"
    roster_file.write_text(json.dumps(players))
    monkeypatch.setattr(ae, "ROSTER_FILE", roster_file)
    monkeypatch.setattr(ae, "reconcile_roster_with_team", lambda r: (r, False))
    monkeypatch.setattr(ae, "_mark_stale_renders", lambda r: False)
    return roster_file


class TestProfilesHonourProvider:
    def test_six_fish_profiles_with_ids(self):
        fish = {p["id"]: p for p in ae.VOICE_PROFILES if p.get("provider") == "fish_audio"}
        assert set(fish) == {"steitzer", "optimus", "smash", "spongebob", "patrick", "mortal_kombat"}
        assert fish["steitzer"]["fish_reference_id"] == STEITZER
        for p in fish.values():
            assert ae._FISH_ID_RE.match(p["fish_reference_id"])
            assert p["qwen_instruct"] and p["pitch_semitones"] == 0.0
        assert all(p.get("provider") for p in ae.VOICE_PROFILES)

    def test_load_reports_availability(self, monkeypatch):
        _keys(monkeypatch, ELEVENLABS_API_KEY="el")
        by_id = {p["id"]: p for p in ae.load_voice_profiles()}
        assert by_id["halo"]["available"] is True and by_id["halo"]["provider"] == "elevenlabs"
        assert by_id["steitzer"]["available"] is False
        assert by_id["steitzer"]["unavailable_reason"] == "FISH_AUDIO_API_KEY not set"

    def test_fish_profile_renders_through_fish_audio(self, tmp_path, monkeypatch):
        _keys(monkeypatch, FISH_AUDIO_API_KEY="k")
        _roster(tmp_path, monkeypatch, [{"id": "7-jane", "first": "Jane", "last": "Doe", "number": "7",
                                         "status": "ready", "is_active": True}])
        monkeypatch.setattr(ae, "CLIPS_DIR", tmp_path / "clips")
        seen = {}
        monkeypatch.setattr(ae.requests, "post",
                            lambda url, json=None, headers=None, timeout=None:
                            seen.update(url=url, json=json) or _Resp(200, b"ID3" + b"\0" * 50))
        monkeypatch.setattr(ae, "archive_and_transcode", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no ffmpeg")))
        p = ae.render_player_audio("7-jane", voice_id="steitzer")
        assert seen["url"].endswith("/v1/tts") and seen["json"]["reference_id"] == STEITZER
        assert p["status"] == "ready" and p["voice_rendered"] == "steitzer"

    def test_missing_key_fails_clearly_instead_of_edge(self, tmp_path, monkeypatch):
        _keys(monkeypatch)
        roster_file = _roster(tmp_path, monkeypatch, [{"id": "7-jane", "first": "Jane", "last": "Doe",
                                                       "number": "7", "status": "ready", "is_active": True}])
        monkeypatch.setattr(ae, "get_tts_provider", lambda: pytest.fail("fell back to the chain"))
        with pytest.raises(RuntimeError, match="FISH_AUDIO_API_KEY not set"):
            ae.render_player_audio("7-jane", voice_id="steitzer")
        row = json.loads(roster_file.read_text())[0]
        assert row["status"] == "error" and row["error_message"] == "FISH_AUDIO_API_KEY not set"

    def test_elevenlabs_profile_without_key_errors(self, monkeypatch):
        _keys(monkeypatch)
        with pytest.raises(RuntimeError, match="ELEVENLABS_API_KEY not set"):
            ae.provider_for_voice(ae.get_voice_profile("halo"))

    def test_profile_without_provider_keeps_the_chain(self, monkeypatch):
        sentinel = ae.MockTTS()
        monkeypatch.setattr(ae, "get_tts_provider", lambda: sentinel)
        monkeypatch.setattr(ae, "get_quick_tts_provider", lambda: sentinel)
        assert ae.provider_for_voice({"id": "x"}) is sentinel
        assert ae.provider_for_voice({"id": "x"}, "quick") is sentinel

    def test_voice_sample_uses_profile_provider(self, tmp_path, monkeypatch):
        _keys(monkeypatch)
        monkeypatch.setattr(ae, "VOICE_SAMPLES_DIR", tmp_path / "samples")
        with pytest.raises(RuntimeError, match="FISH_AUDIO_API_KEY not set"):
            ae.render_voice_sample("spongebob")


# ── custom catalogue voices ─────────────────────────────────────────────────

REF = "0123456789abcdef0123456789abcdef"


class TestCustomProfiles:
    def test_add_with_name_needs_no_lookup(self):
        p = ae.add_custom_voice_profile(REF, "Coach Bob")
        assert p["id"] == "fish_01234567" and p["provider"] == "fish_audio" and p["custom"] is True
        assert ae.get_voice_profile("fish_01234567")["fish_reference_id"] == REF
        assert "fish_01234567" in [x["id"] for x in ae.load_voice_profiles()]

    def test_add_without_name_looks_up_the_title(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(ae.requests, "get", lambda url, timeout=None: seen.update(url=url) or _Resp(
            200, payload={"title": "Announcer Guy", "type": "tts", "state": "trained",
                          "like_count": 5, "author": {"nickname": "sam"}}))
        p = ae.add_custom_voice_profile(REF)
        assert seen["url"] == f"https://api.fish.audio/model/{REF}"
        assert p["name"] == "Announcer Guy" and "sam" in p["tagline"]

    def test_lookup_404_is_voice_not_found(self, monkeypatch):
        monkeypatch.setattr(ae.requests, "get", lambda *a, **k: _Resp(404, payload={}))
        with pytest.raises(ae.VoiceProfileError) as e:
            ae.add_custom_voice_profile(REF)
        assert (e.value.code, e.value.status) == ("voice_not_found", 404)

    @pytest.mark.parametrize("ref", ["", "xyz", REF[:-1], REF + "0", "../" + REF[:29], "g" * 32])
    def test_rejects_bad_reference_ids(self, ref):
        with pytest.raises(ae.VoiceProfileError, match="invalid_fish_reference_id"):
            ae.add_custom_voice_profile(ref, "x")

    def test_duplicates_refused(self):
        ae.add_custom_voice_profile(REF, "One")
        with pytest.raises(ae.VoiceProfileError, match="voice_already_added"):
            ae.add_custom_voice_profile(REF, "Two")
        with pytest.raises(ae.VoiceProfileError, match="voice_already_added"):
            ae.add_custom_voice_profile(STEITZER, "Built-in again")

    def test_delete_custom_and_protect_builtins(self):
        ae.add_custom_voice_profile(REF, "One")
        ae.delete_custom_voice_profile("fish_01234567")
        assert ae.get_voice_profile("fish_01234567") is None
        with pytest.raises(ae.VoiceProfileError) as e:
            ae.delete_custom_voice_profile("steitzer")
        assert (e.value.code, e.value.status) == ("builtin_voice", 409)
        with pytest.raises(ae.VoiceProfileError, match="unknown_profile"):
            ae.delete_custom_voice_profile("fish_deadbeef")


# ── routes ──────────────────────────────────────────────────────────────────

class _NoRunThread:
    started = []

    def __init__(self, target=None, daemon=None):
        self.target = target

    def start(self):
        _NoRunThread.started.append(self.target)


@pytest.fixture
def client(monkeypatch):
    import threading
    monkeypatch.setattr(sd, "WRITE_ORIGINS", [ORIGIN])
    monkeypatch.delenv("DUGOUT_WRITE_TOKEN", raising=False)
    monkeypatch.setattr(threading, "Thread", _NoRunThread)
    _NoRunThread.started = []
    sd._MUTATE_RATE_BUCKETS.clear()
    sd.app.config["TESTING"] = True
    with sd.app.test_client() as c:
        yield c


def _post(client, path, body=None):
    return client.post(path, json=body or {}, headers={"Origin": ORIGIN})


class TestVoiceLibrarySearch:
    def test_proxies_public_search(self, client, monkeypatch):
        seen = {}
        items = [
            {"_id": STEITZER, "title": "Jeff", "type": "tts", "state": "trained", "like_count": 900,
             "author": {"nickname": "halo_fan"}},
            {"_id": "bad", "title": "Broken"},
            {"_id": REF, "title": "Gone", "type": "tts", "state": "trained", "dmca_taken_down": True},
        ]

        def _get(url, params=None, timeout=None):
            seen.update(url=url, params=params, timeout=timeout)
            return _Resp(200, payload={"items": items})

        monkeypatch.setattr(ae.requests, "get", _get)
        resp = client.get("/api/announcer/voice-library/search?q=halo")
        assert resp.status_code == 200
        assert resp.get_json()["results"] == [{"id": STEITZER, "title": "Jeff", "likes": 900, "author": "halo_fan"}]
        assert seen["url"] == "https://api.fish.audio/model"
        assert seen["params"] == {"title": "halo", "language": "en", "sort_by": "score", "page_size": 12}
        assert seen["timeout"] == 10

    @pytest.mark.parametrize("q", ["", "a", "x" * 61])
    def test_query_length_enforced(self, client, q):
        assert client.get(f"/api/announcer/voice-library/search?q={q}").status_code == 400

    def test_upstream_failure_is_502(self, client, monkeypatch):
        monkeypatch.setattr(ae.requests, "get", lambda *a, **k: _Resp(500, payload={}))
        resp = client.get("/api/announcer/voice-library/search?q=halo")
        assert resp.status_code == 502 and resp.get_json()["error"] == "voice_search_failed"


class TestCustomVoiceRoutes:
    def test_add_list_delete(self, client):
        resp = _post(client, "/api/announcer/voice-profiles", {"fish_reference_id": REF, "name": "Coach Bob"})
        assert resp.status_code == 201 and resp.get_json()["profile"]["id"] == "fish_01234567"
        ids = [p["id"] for p in client.get("/api/announcer/voice-profiles").get_json()["profiles"]]
        assert "fish_01234567" in ids and "steitzer" in ids
        resp = client.delete("/api/announcer/voice-profiles/fish_01234567", json={}, headers={"Origin": ORIGIN})
        assert resp.status_code == 200
        ids = [p["id"] for p in client.get("/api/announcer/voice-profiles").get_json()["profiles"]]
        assert "fish_01234567" not in ids

    def test_validation_and_builtin_protection(self, client):
        assert _post(client, "/api/announcer/voice-profiles", {"fish_reference_id": "nope"}).status_code == 400
        resp = client.delete("/api/announcer/voice-profiles/steitzer", json={}, headers={"Origin": ORIGIN})
        assert resp.status_code == 409 and resp.get_json()["error"] == "builtin_voice"

    def test_mutations_need_the_guard(self, client):
        resp = client.post("/api/announcer/voice-profiles", json={"fish_reference_id": REF, "name": "x"})
        assert resp.status_code == 403  # no Origin
        resp = client.delete("/api/announcer/voice-profiles/fish_01234567", headers={"Origin": ORIGIN})
        assert resp.status_code == 415  # JSON-only, like every mutating route


class TestRenderAllInVoice:
    @pytest.fixture
    def roster(self, tmp_path, monkeypatch):
        return _roster(tmp_path, monkeypatch, [
            {"id": "a", "status": "ready", "is_active": True},
            {"id": "b", "status": "pending", "is_active": True},
            {"id": "c", "status": "rendering", "is_active": True, "render_started_at": ae._now_iso()},
            {"id": "d", "status": "ready", "is_active": False},
        ])

    def test_claims_every_active_player_and_renders_in_that_voice(self, client, roster, monkeypatch):
        _keys(monkeypatch, FISH_AUDIO_API_KEY="k")
        resp = _post(client, "/api/announcer/render-all", {"voice_id": "spongebob"})
        assert resp.status_code == 202
        body = resp.get_json()
        assert body["player_ids"] == ["a", "b"] and body["voice_id"] == "spongebob"
        rows = {p["id"]: p for p in json.loads(roster.read_text())}
        assert rows["a"]["status"] == "rendering" and rows["d"]["status"] == "ready"
        calls = []
        monkeypatch.setattr(ae, "render_player_audio", lambda pid, **kw: calls.append((pid, kw)))
        _NoRunThread.started[0]()
        assert calls == [("a", {"voice_id": "spongebob"}), ("b", {"voice_id": "spongebob"})]

    def test_unavailable_voice_refused_before_claiming(self, client, roster, monkeypatch):
        _keys(monkeypatch)
        resp = _post(client, "/api/announcer/render-all", {"voice_id": "spongebob"})
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "voice_unavailable", "reason": "FISH_AUDIO_API_KEY not set"}
        assert json.loads(roster.read_text())[0]["status"] == "ready"
        assert _NoRunThread.started == []

    def test_unknown_voice_is_400(self, client, roster):
        assert _post(client, "/api/announcer/render-all", {"voice_id": "nope"}).status_code == 400

    def test_default_behaviour_unchanged(self, client, roster, monkeypatch):
        resp = _post(client, "/api/announcer/render-all")
        assert resp.get_json()["player_ids"] == ["b"]
        calls = []
        monkeypatch.setattr(ae, "render_player_audio", lambda pid, **kw: calls.append((pid, kw)))
        _NoRunThread.started[0]()
        assert calls == [("b", {})]

    def test_team_voice_refuses_unavailable_voice(self, client, roster, monkeypatch):
        _keys(monkeypatch)
        resp = _post(client, "/api/announcer/voice-profiles/default", {"profile_id": "optimus"})
        assert resp.status_code == 409 and resp.get_json()["error"] == "voice_unavailable"
