"""Coach-supplied announcer audio and the manual batting order.

Uploaded walk-up songs and calls, the soundboard (built-in synthesised
effects plus uploads), and PUT/DELETE of the coach's batting order. FFmpeg
tests skip when it isn't installed; the no-FFmpeg path is tested by turning
it off.
"""
from __future__ import annotations

import io
import json
import math
import shutil
import struct
import wave

import pytest

import announcer_engine as ae
import announcer_media as am
import music_ingest as mi
import sync_daemon as sd

ORIGIN = "https://test.example.com"
HAS_FFMPEG = bool(shutil.which("ffmpeg"))
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")


def _wav(seconds=0.5, rate=22050, channels=1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate))) * channels
            for i in range(int(seconds * rate))
        )
        w.writeframes(frames)
    return buf.getvalue()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Temp roster, clip, music and soundboard dirs, and a test client."""
    roster_file = tmp_path / "announcer" / "roster.json"
    roster_file.parent.mkdir(parents=True)
    monkeypatch.setattr(ae, "ROSTER_FILE", roster_file)
    monkeypatch.setattr(ae, "CLIPS_DIR", tmp_path / "announcer" / "clips")
    monkeypatch.setattr(ae, "_ensure_dirs", lambda: None)
    monkeypatch.setattr(ae, "reconcile_roster_with_team", lambda r: (r, False))
    monkeypatch.setattr(ae, "_mark_stale_renders", lambda r: False)
    monkeypatch.setattr(mi, "CLIPS_DIR", tmp_path / "music" / "clips")
    monkeypatch.setattr(am, "SOUNDBOARD_DIR", tmp_path / "announcer" / "soundboard")
    monkeypatch.setattr(am, "SOUNDBOARD_FILE", tmp_path / "announcer" / "soundboard.json")
    monkeypatch.setattr(am, "BATTING_ORDER_FILE", tmp_path / "announcer" / "batting_order.json")
    monkeypatch.setattr(sd, "WRITE_ORIGINS", [ORIGIN])
    monkeypatch.setattr(sd, "_load_roster_players", lambda: [])
    monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path / "sharks")
    monkeypatch.setattr(sd, "_MUTATE_RATE_BUCKETS", {})  # 12 writes/min/path would trip across tests
    pool_rows = []

    class _Adb:  # keeps the real announcer.db out of it
        @staticmethod
        def add_player_song(**kw):
            pool_rows.append(kw)
            return []

    monkeypatch.setattr(sd, "_announcer_db", lambda: _Adb)
    monkeypatch.delenv("DUGOUT_WRITE_TOKEN", raising=False)
    monkeypatch.delenv("DUGOUT_APP_PASSWORD", raising=False)
    sd.app.config["TESTING"] = True

    class E:
        tmp = tmp_path
        pool = pool_rows

        @staticmethod
        def write(players):
            roster_file.write_text(json.dumps(players))

        @staticmethod
        def get(pid):
            return next(p for p in json.loads(roster_file.read_text()) if p["id"] == pid)

    E.write([
        {"id": "07-jane", "first": "Jane", "last": "Doe", "number": "7", "status": "pending", "is_active": True},
        {"id": "12-mia", "first": "Mia", "last": "Park", "number": "12", "status": "ready", "is_active": True},
    ])
    with sd.app.test_client() as c:
        E.client = c
        yield E


def _upload(client, path, data, filename="Walk Up.wav", headers=None, **form):
    return client.post(path, data={"file": (io.BytesIO(data), filename), **form},
                       content_type="multipart/form-data",
                       headers={"Origin": ORIGIN} if headers is None else headers)


def _no_ffmpeg(monkeypatch):
    monkeypatch.setattr(am, "ffmpeg_available", lambda: False)


# ── sniffing ───────────────────────────────────────────────────────────────

class TestSniff:
    def test_known_headers(self):
        assert am.sniff_audio(b"ID3\x04\x00") == "mp3"
        assert am.sniff_audio(b"\xff\xfb\x90\x00") == "mp3"
        assert am.sniff_audio(_wav()[:16]) == "wav"
        assert am.sniff_audio(b"\x00\x00\x00\x20ftypM4A ") == "m4a"

    def test_aac_adts_and_text_are_not_mp3(self):
        assert am.sniff_audio(b"\xff\xf1\x50\x80") is None  # ADTS: layer bits 00
        assert am.sniff_audio(b"<html>") is None
        assert am.sniff_audio(b"") is None


# ── walk-up songs ──────────────────────────────────────────────────────────

class TestSongUpload:
    @needs_ffmpeg
    def test_wav_becomes_a_normalised_mp3_song_that_plays(self, env):
        resp = _upload(env.client, "/api/announcer/songs/07-jane/upload", _wav(1.0))
        assert resp.status_code == 201, resp.get_json()
        song = resp.get_json()["song"]
        assert song["start"] == 0 and song["label"] == "Walk Up"
        assert song["url"].startswith("/audio/music/07-jane/walk-up-") and song["url"].endswith(".mp3")
        stem = song["url"].rsplit("/", 1)[-1][:-4]
        assert len(stem.rsplit("-", 1)[-1]) == 8
        assert [s["url"] for s in env.get("07-jane")["songs"]] == [song["url"]]
        assert env.pool == [{"player_id": "07-jane", "song_url": song["url"], "song_label": "Walk Up",
                             "source": "upload", "source_id": song["id"], "optimal_start_ms": 0,
                             "file_path": song["url"]}]
        assert env.get("07-jane")["walkup_song_url"] == song["url"]
        served = env.client.get(song["url"])
        assert served.status_code == 200 and served.mimetype == "audio/mpeg"
        assert am.sniff_audio(served.data[:16]) == "mp3"

    @needs_ffmpeg
    def test_label_field_wins_over_filename(self, env):
        resp = _upload(env.client, "/api/announcer/songs/07-jane/upload", _wav(), label="Sweet Tune")
        assert resp.get_json()["song"]["label"] == "Sweet Tune"

    def test_without_ffmpeg_the_file_is_stored_as_is(self, env, monkeypatch):
        _no_ffmpeg(monkeypatch)
        data = _wav()
        resp = _upload(env.client, "/api/announcer/songs/07-jane/upload", data)
        assert resp.status_code == 201
        url = resp.get_json()["song"]["url"]
        assert url.endswith(".wav")
        served = env.client.get(url)
        assert served.status_code == 200 and served.mimetype == "audio/wav" and served.data == data

    def test_not_audio_is_415(self, env):
        resp = _upload(env.client, "/api/announcer/songs/07-jane/upload", b"<html>nope</html>", "x.mp3")
        assert resp.status_code == 415 and resp.get_json()["error"] == "unsupported_audio"
        assert not mi.CLIPS_DIR.exists() or not any(mi.CLIPS_DIR.rglob("*.mp3"))

    @needs_ffmpeg
    def test_audio_header_with_garbage_is_422(self, env):
        bad = b"RIFF\x24\x00\x00\x00WAVE" + b"\x13" * 4000
        resp = _upload(env.client, "/api/announcer/songs/07-jane/upload", bad)
        assert resp.status_code == 422 and resp.get_json()["error"] == "audio_unreadable"
        assert env.get("07-jane").get("songs") in (None, [])

    def test_file_over_the_cap_is_413(self, env, monkeypatch):
        monkeypatch.setattr(am, "MAX_UPLOAD_BYTES", 1000)
        resp = _upload(env.client, "/api/announcer/songs/07-jane/upload", _wav())
        assert resp.status_code == 413 and resp.get_json()["error"] == "file_too_large"

    def test_a_20_mb_file_gets_through_the_raised_body_cap(self, env, monkeypatch):
        _no_ffmpeg(monkeypatch)
        big = _wav(0.1)[:44] + b"\x00" * (20 * 1024 * 1024)
        resp = _upload(env.client, "/api/announcer/songs/07-jane/upload", big)
        assert resp.status_code == 201, resp.get_json()

    def test_a_body_just_over_the_real_cap_is_413(self, env, monkeypatch):
        _no_ffmpeg(monkeypatch)
        big = _wav(0.1)[:44] + b"\x00" * sd.MAX_MEDIA_UPLOAD_BYTES
        resp = _upload(env.client, "/api/announcer/songs/07-jane/upload", big)
        assert resp.status_code == 413 and resp.get_json()["error"] == "payload_too_large"
        assert env.get("07-jane").get("songs") in (None, [])

    def test_body_over_the_gate_is_413_before_the_route(self, env, monkeypatch):
        monkeypatch.setattr(sd, "MAX_MEDIA_UPLOAD_BYTES", 2000)
        resp = _upload(env.client, "/api/announcer/songs/07-jane/upload", _wav())
        assert resp.status_code == 413 and resp.get_json()["error"] == "payload_too_large"

    def test_a_full_song_list_is_409_and_writes_nothing(self, env, monkeypatch):
        _no_ffmpeg(monkeypatch)
        env.write([{"id": "07-jane", "first": "Jane", "songs": [
            {"id": f"s{i}", "url": f"https://x.test/{i}.mp3", "start": 0} for i in range(ae.MAX_SONGS)]}])
        resp = _upload(env.client, "/api/announcer/songs/07-jane/upload", _wav())
        assert resp.status_code == 409 and resp.get_json()["error"] == "songs_full"
        assert not mi.CLIPS_DIR.exists()

    def test_unknown_player_is_404(self, env):
        resp = _upload(env.client, "/api/announcer/songs/99-nobody/upload", _wav())
        assert resp.status_code == 404

    def test_missing_file_is_400(self, env):
        resp = env.client.post("/api/announcer/songs/07-jane/upload", data={}, content_type="multipart/form-data",
                               headers={"Origin": ORIGIN})
        assert resp.status_code == 400 and resp.get_json()["error"] == "file_required"

    def test_no_origin_is_refused(self, env):
        resp = _upload(env.client, "/api/announcer/songs/07-jane/upload", _wav(), headers={})
        assert resp.status_code == 403 and resp.get_json()["error"] == "origin_required"

    def test_foreign_origin_is_refused(self, env):
        resp = _upload(env.client, "/api/announcer/songs/07-jane/upload", _wav(), headers={"Origin": "https://evil.test"})
        assert resp.status_code == 403 and resp.get_json()["error"] == "forbidden_origin"

    def test_write_token_is_required_when_set(self, env, monkeypatch):
        monkeypatch.setenv("DUGOUT_WRITE_TOKEN", "t0k3n")
        resp = _upload(env.client, "/api/announcer/songs/07-jane/upload", _wav())
        assert resp.status_code == 401 and resp.get_json()["error"] == "write_token_required"
        _no_ffmpeg(monkeypatch)
        ok = _upload(env.client, "/api/announcer/songs/07-jane/upload", _wav(),
                     headers={"Origin": ORIGIN, "X-Dugout-Token": "t0k3n"})
        assert ok.status_code == 201

    def test_saving_songs_keeps_an_uploaded_song_and_its_label(self, env, monkeypatch):
        _no_ffmpeg(monkeypatch)
        song = _upload(env.client, "/api/announcer/songs/07-jane/upload", _wav()).get_json()["song"]
        resp = env.client.post("/api/announcer/phonetics/07-jane", headers={"Origin": ORIGIN}, json={"songs": [
            {"id": song["id"], "url": song["url"], "start": 3, "label": song["label"]},
            {"url": "https://x.test/b.mp3", "start": 0},
        ]})
        assert resp.status_code == 200, resp.get_json()
        saved = env.get("07-jane")["songs"]
        assert saved[0] == {"id": song["id"], "url": song["url"], "start": 3.0, "label": "Walk Up"}
        assert "label" not in saved[1]

    def test_phonetics_still_refuses_other_relative_paths(self, env):
        for url in ("/etc/passwd", "/audio/music/../x.mp3", "javascript:alert(1)"):
            resp = env.client.post("/api/announcer/phonetics/07-jane", headers={"Origin": ORIGIN},
                                   json={"songs": [{"url": url}]})
            assert resp.status_code == 400, url


# ── calls ──────────────────────────────────────────────────────────────────

class TestCallUpload:
    def test_first_call_makes_the_player_ready(self, env, monkeypatch):
        _no_ffmpeg(monkeypatch)
        resp = _upload(env.client, "/api/announcer/calls/07-jane/upload", b"ID3" + b"\x00" * 500, "call.mp3")
        assert resp.status_code == 201, resp.get_json()
        clip = resp.get_json()["clip_url"]
        assert clip.startswith("/announcer-clips/07-jane/upload-") and clip.endswith(".mp3")
        p = env.get("07-jane")
        assert p["status"] == "ready" and p["wrap_version"] == ae.STADIUM_WRAP_VERSION
        assert [(i["voice"], i["clip_url"], i["draft"]) for i in p["intros"]] == [("upload", clip, False)]
        assert (ae.CLIPS_DIR / "07-jane" / clip.rsplit("/", 1)[-1]).is_file()

    @needs_ffmpeg
    def test_wav_call_is_transcoded(self, env):
        resp = _upload(env.client, "/api/announcer/calls/07-jane/upload", _wav())
        clip = resp.get_json()["clip_url"]
        assert clip.endswith(".mp3")
        assert am.sniff_audio((ae.CLIPS_DIR / "07-jane" / clip.rsplit("/", 1)[-1]).read_bytes()[:16]) == "mp3"

    def test_an_in_flight_render_keeps_its_status(self, env, monkeypatch):
        _no_ffmpeg(monkeypatch)
        env.write([{"id": "07-jane", "first": "Jane", "status": "rendering",
                    "render_started_at": ae._now_iso(), "render_job_id": "j1"}])
        assert _upload(env.client, "/api/announcer/calls/07-jane/upload", _wav()).status_code == 201
        p = env.get("07-jane")
        assert p["status"] == "rendering" and p["render_job_id"] == "j1" and len(p["intros"]) == 1

    def test_existing_calls_keep_their_status(self, env, monkeypatch):
        _no_ffmpeg(monkeypatch)
        env.write([{"id": "07-jane", "first": "Jane", "status": "pending",
                    "intros": [{"id": "a1", "voice": "halo", "clip_url": "/announcer-clips/07-jane/a.mp3"}]}])
        _upload(env.client, "/api/announcer/calls/07-jane/upload", _wav())
        p = env.get("07-jane")
        assert p["status"] == "pending" and [i["voice"] for i in p["intros"]] == ["halo", "upload"]

    def test_not_audio_is_415(self, env):
        resp = _upload(env.client, "/api/announcer/calls/07-jane/upload", b"hello", "x.wav")
        assert resp.status_code == 415


# ── soundboard ─────────────────────────────────────────────────────────────

class TestSoundboard:
    @needs_ffmpeg
    def test_builtins_are_synthesised_once_and_served(self, env):
        sounds = env.client.get("/api/announcer/soundboard").get_json()["sounds"]
        assert [s["id"] for s in sounds] == [b[0] for b in am.BUILTIN_SOUNDS]
        assert all(s["builtin"] for s in sounds)
        first = env.client.get(sounds[0]["url"])
        assert first.status_code == 200 and first.mimetype == "audio/mpeg"
        assert am.sniff_audio(first.data[:16]) == "mp3"
        mtime = (am.SOUNDBOARD_DIR / am.builtin_filename(sounds[0]["id"])).stat().st_mtime_ns
        env.client.get("/api/announcer/soundboard")
        assert (am.SOUNDBOARD_DIR / am.builtin_filename(sounds[0]["id"])).stat().st_mtime_ns == mtime

    def test_without_ffmpeg_there_are_no_builtins_but_the_list_works(self, env, monkeypatch):
        _no_ffmpeg(monkeypatch)
        resp = env.client.get("/api/announcer/soundboard")
        assert resp.status_code == 200 and resp.get_json()["sounds"] == []

    def test_upload_list_serve_and_remove(self, env, monkeypatch):
        _no_ffmpeg(monkeypatch)
        resp = _upload(env.client, "/api/announcer/soundboard/upload", _wav(), "rally_cry.wav", label="Rally!")
        assert resp.status_code == 201, resp.get_json()
        sound = resp.get_json()["sound"]
        assert sound["label"] == "Rally!" and sound["builtin"] is False and sound["url"].startswith("/audio/soundboard/")
        listed = env.client.get("/api/announcer/soundboard").get_json()["sounds"]
        assert [s["id"] for s in listed] == [sound["id"]]
        assert env.client.get(sound["url"]).status_code == 200

        gone = env.client.delete(f"/api/announcer/soundboard/{sound['id']}", json={}, headers={"Origin": ORIGIN})
        assert gone.status_code == 200
        assert env.client.get("/api/announcer/soundboard").get_json()["sounds"] == []
        assert env.client.get(sound["url"]).status_code == 404

    def test_label_defaults_to_the_filename_and_is_capped(self, env, monkeypatch):
        _no_ffmpeg(monkeypatch)
        sound = _upload(env.client, "/api/announcer/soundboard/upload", _wav(),
                        "a_very_long_sound_effect_name_indeed.wav").get_json()["sound"]
        assert sound["label"] == "a very long sound effect"[:am.SOUND_LABEL_MAX]

    def test_builtins_cannot_be_removed(self, env):
        resp = env.client.delete("/api/announcer/soundboard/air-horn", json={}, headers={"Origin": ORIGIN})
        assert resp.status_code == 400 and resp.get_json()["error"] == "builtin_sound"

    def test_unknown_sound_is_404(self, env):
        resp = env.client.delete("/api/announcer/soundboard/nope-12345678", json={}, headers={"Origin": ORIGIN})
        assert resp.status_code == 404

    def test_delete_needs_json_and_origin(self, env):
        assert env.client.delete("/api/announcer/soundboard/x", headers={"Origin": ORIGIN}).status_code == 415
        assert env.client.delete("/api/announcer/soundboard/x", json={}).status_code == 403

    def test_upload_needs_origin(self, env):
        resp = _upload(env.client, "/api/announcer/soundboard/upload", _wav(), headers={})
        assert resp.status_code == 403

    def test_serving_refuses_bad_names(self, env, monkeypatch):
        _no_ffmpeg(monkeypatch)
        am.SOUNDBOARD_DIR.mkdir(parents=True)
        (am.SOUNDBOARD_DIR.parent / "secret.mp3").write_bytes(b"ID3x")
        for name in ("..%2Fsecret.mp3", "secret.txt", ".hidden.mp3"):
            assert env.client.get(f"/audio/soundboard/{name}").status_code == 404, name

    def test_a_full_board_refuses_more(self, env, monkeypatch):
        _no_ffmpeg(monkeypatch)
        monkeypatch.setattr(am, "MAX_SOUNDS", 1)
        assert _upload(env.client, "/api/announcer/soundboard/upload", _wav()).status_code == 201
        resp = _upload(env.client, "/api/announcer/soundboard/upload", _wav())
        assert resp.status_code == 409 and resp.get_json()["error"] == "sounds_full"


# ── batting order ──────────────────────────────────────────────────────────

class TestBattingOrder:
    def _put(self, env, body):
        return env.client.put("/api/announcer/batting-order", json=body, headers={"Origin": ORIGIN})

    def test_lineup_has_no_manual_order_by_default(self, env):
        body = env.client.get("/api/announcer/game-lineup").get_json()
        assert body["manual_order"] == [] and body["source"] == "none"

    def test_put_saves_and_the_lineup_reports_it(self, env):
        resp = self._put(env, {"order": ["12-mia", "07-jane", "12-mia", "99-gone"]})
        assert resp.status_code == 200
        assert resp.get_json()["order"] == ["12-mia", "07-jane"]  # repeats and unknown ids dropped
        body = env.client.get("/api/announcer/game-lineup").get_json()
        assert body["manual_order"] == ["12-mia", "07-jane"] and body["manual_updated_at"]

    def test_active_players_the_order_leaves_out_are_appended(self, env):
        resp = self._put(env, {"order": ["12-mia"]})
        assert resp.get_json()["order"] == ["12-mia", "07-jane"]

    def test_inactive_players_are_dropped(self, env):
        env.write([
            {"id": "07-jane", "first": "Jane", "is_active": True},
            {"id": "12-mia", "first": "Mia", "is_active": True},
            {"id": "03-old", "first": "Olga", "is_active": False},
        ])
        resp = self._put(env, {"order": ["03-old", "12-mia", "07-jane"]})
        assert resp.get_json()["order"] == ["12-mia", "07-jane"]
        assert self._put(env, {"order": ["03-old"]}).status_code == 400

    def test_delete_resets_to_the_gamechanger_order(self, env):
        self._put(env, {"order": ["12-mia"]})
        resp = env.client.delete("/api/announcer/batting-order", json={}, headers={"Origin": ORIGIN})
        assert resp.status_code == 200
        assert env.client.get("/api/announcer/game-lineup").get_json()["manual_order"] == []

    @pytest.mark.parametrize("body", [{}, {"order": "07-jane"}, {"order": [1, 2]}, {"order": ["../x"]},
                                      {"order": []}, {"order": ["99-gone"]}])
    def test_bad_orders_are_400(self, env, body):
        resp = self._put(env, body)
        assert resp.status_code == 400 and resp.get_json()["error"] == "order_invalid"

    def test_put_needs_json_and_origin(self, env):
        assert env.client.put("/api/announcer/batting-order", data="x", headers={"Origin": ORIGIN}).status_code == 415
        assert env.client.put("/api/announcer/batting-order", json={"order": ["07-jane"]}).status_code == 403

    def test_a_corrupt_order_file_never_breaks_the_lineup(self, env):
        am.BATTING_ORDER_FILE.write_text("{not json")
        body = env.client.get("/api/announcer/game-lineup").get_json()
        assert body["manual_order"] == []


def test_batting_order_rejects_non_object_body(env):
    # A bare JSON list used to raise inside the route (500); it is a 400 now.
    r = env.client.put("/api/announcer/batting-order", data="[1,2]",
                       headers={"Origin": ORIGIN, "Content-Type": "application/json"})
    assert r.status_code == 400
    assert r.get_json() == {"error": "bad_request"}


# ── song gap ───────────────────────────────────────────────────────────────

class TestSongGap:
    """The seconds between a call ending and the song starting, per player."""

    def _post(self, env, body):
        return env.client.post("/api/announcer/phonetics/07-jane", headers={"Origin": ORIGIN}, json=body)

    def test_gap_is_saved_and_comes_back_on_the_roster_the_pwa_loads(self, env):
        assert self._post(env, {"song_gap": 1.5}).status_code == 200
        roster = env.client.get("/api/announcer/roster").get_json()["roster"]
        assert next(p for p in roster if p["id"] == "07-jane")["song_gap"] == 1.5

    def test_gap_is_clamped_to_three_seconds_either_way(self, env):
        assert self._post(env, {"song_gap": 9}).status_code == 200
        assert env.get("07-jane")["song_gap"] == 3.0
        assert self._post(env, {"song_gap": -9}).status_code == 200
        assert env.get("07-jane")["song_gap"] == -3.0

    def test_a_gap_that_is_not_a_number_is_refused_and_nothing_changes(self, env):
        self._post(env, {"song_gap": -1})
        resp = self._post(env, {"song_gap": "soon"})
        assert resp.status_code == 400 and resp.get_json()["error"] == "song_gap_invalid"
        assert env.get("07-jane")["song_gap"] == -1.0

    def test_saving_a_gap_does_not_make_the_calls_stale(self, env):
        assert self._post(env, {"song_gap": 0}).status_code == 200
        assert env.get("12-mia")["status"] == "ready"
        self._post(env, {"song_gap": 0})
        assert env.get("07-jane")["status"] == "pending"  # was pending already; unchanged
