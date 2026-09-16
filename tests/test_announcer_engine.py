"""Tests for tools/announcer_engine.py — pure logic, security helpers, MockTTS."""
from __future__ import annotations

import re
import json
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import tools.announcer_engine as ae_mod
from tools.announcer_engine import (
    EdgeTTSProvider,
    MockTTS,
    _apply_phonetics,
    _bootstrap_roster_from_team,
    _number_to_word,
    _sanitize_player_id,
    build_situational_announcement,
    get_default_voice_profile,
    get_player_by_id,
    get_tts_provider,
    get_quick_tts_provider,
    load_announcer_roster,
    load_voice_profiles,
    save_announcer_roster,
    update_player,
)


# ---------------------------------------------------------------------------
# _sanitize_player_id — path-traversal prevention
# ---------------------------------------------------------------------------

class TestSanitizePlayerId:
    def test_normal_id_lowercase(self):
        assert _sanitize_player_id("7-Jane-Smith") == "7-jane-smith"

    def test_spaces_become_hyphens(self):
        assert _sanitize_player_id("jane smith") == "jane-smith"

    def test_path_traversal_stripped(self):
        result = _sanitize_player_id("../../../etc/passwd")
        assert ".." not in result
        assert "/" not in result

    def test_leading_dots_removed(self):
        result = _sanitize_player_id("...hidden")
        assert not result.startswith(".")

    def test_leading_dashes_removed(self):
        result = _sanitize_player_id("---abc")
        assert not result.startswith("-")

    def test_all_whitespace_returns_unknown(self):
        assert _sanitize_player_id("   ") == "unknown"

    def test_empty_string_returns_unknown(self):
        assert _sanitize_player_id("") == "unknown"

    def test_only_special_chars_returns_unknown(self):
        assert _sanitize_player_id("!@#$%^&*()") == "unknown"

    def test_length_capped_at_100(self):
        long_id = "a" * 200
        result = _sanitize_player_id(long_id)
        assert len(result) == 100

    def test_uppercase_lowercased(self):
        assert _sanitize_player_id("JANE-SMITH") == "jane-smith"

    def test_disallowed_chars_removed(self):
        result = _sanitize_player_id("hello<world>foo")
        assert "<" not in result
        assert ">" not in result

    def test_hyphens_and_underscores_preserved(self):
        result = _sanitize_player_id("player_id-123")
        assert result == "player_id-123"

    def test_numbers_preserved(self):
        result = _sanitize_player_id("42abc")
        assert result == "42abc"


# ---------------------------------------------------------------------------
# _number_to_word — jersey number to spoken word
# ---------------------------------------------------------------------------

class TestNumberToWord:
    @pytest.mark.parametrize("num,expected", [
        ("0",  "zero"),
        ("1",  "one"),
        ("7",  "seven"),
        ("10", "ten"),
        ("11", "eleven"),
        ("20", "twenty"),
        ("21", "twenty-one"),
        ("30", "thirty"),
        ("99", "ninety-nine"),
        ("00", "double-zero"),
    ])
    def test_known_numbers(self, num, expected):
        assert _number_to_word(num) == expected

    def test_unknown_number_returns_raw(self):
        assert _number_to_word("42") == "42"

    def test_strips_whitespace(self):
        assert _number_to_word("  7  ") == "seven"

    def test_int_input(self):
        assert _number_to_word(5) == "five"


# ---------------------------------------------------------------------------
# build_situational_announcement — TTS script generation
# ---------------------------------------------------------------------------

class TestBuildSituationalAnnouncement:
    def _player(self, number="7", first="Sofia", last="Smith", phonetic_hint="", tts_instruction=""):
        return {
            "number": number, "first": first, "last": last,
            "phonetic_hint": phonetic_hint,
            "tts_instruction": tts_instruction,
        }

    def test_default_script_contains_now_batting(self):
        script = build_situational_announcement(self._player())
        assert "batting" in script.lower()

    def test_player_name_in_script(self):
        script = build_situational_announcement(self._player(first="Sofia", last="Smith"))
        assert "Sofia" in script or "sofia" in script.lower()

    def test_number_word_in_script(self):
        script = build_situational_announcement(self._player(number="7"))
        assert "seven" in script.lower()

    def test_phonetic_hint_overrides_name(self):
        player = self._player(first="Aoife", last="Murphy", phonetic_hint="EE-fah Murphy")
        script = build_situational_announcement(player)
        assert "EE-fah" in script

    def test_bases_loaded_two_outs_high_stakes_script(self):
        ctx = {"bases": [True, True, True], "outs": 2, "score_us": 3, "score_them": 3}
        script = build_situational_announcement(self._player(), game_context=ctx)
        assert "game on the line" in script.lower() or "bases loaded" in script.lower()

    def test_trailing_with_bases_loaded_mentions_game_on_line(self):
        ctx = {"bases": [True, True, True], "outs": 2, "score_us": 1, "score_them": 4}
        script = build_situational_announcement(self._player(), game_context=ctx)
        assert "game on the line" in script.lower()

    def test_bases_loaded_not_two_outs(self):
        ctx = {"bases": [True, True, True], "outs": 1, "score_us": 2, "score_them": 2}
        script = build_situational_announcement(self._player(), game_context=ctx)
        assert "bases loaded" in script.lower()

    def test_halo_triple_rbi_achievement(self):
        ctx = {"achievement": "triple_rbi"}
        script = build_situational_announcement(self._player(), game_context=ctx)
        assert "hat trick" in script.lower() or "three runs" in script.lower()

    def test_halo_grand_slam_achievement(self):
        ctx = {"achievement": "grand_slam"}
        script = build_situational_announcement(self._player(), game_context=ctx)
        assert "grand" in script.lower()

    def test_halo_5_strikeouts(self):
        ctx = {"achievement": "5_strikeouts"}
        script = build_situational_announcement(self._player(), game_context=ctx)
        assert "untouchable" in script.lower() or "five" in script.lower()

    def test_no_context_gives_default_script(self):
        script = build_situational_announcement(self._player(), game_context=None)
        assert "NUMBEEEER" in script or "batting" in script.lower()

    def test_tts_instruction_prepended_without_achievement(self):
        player = self._player(tts_instruction="Speak slowly")
        script = build_situational_announcement(player, game_context={})
        assert script.startswith("Speak slowly")

    def test_tts_instruction_not_added_when_achievement_present(self):
        player = self._player(tts_instruction="Speak slowly")
        ctx = {"achievement": "grand_slam"}
        script = build_situational_announcement(player, game_context=ctx)
        assert not script.startswith("Speak slowly")

    def test_unknown_achievement_falls_through_to_default(self):
        ctx = {"achievement": "nonexistent_achievement"}
        script = build_situational_announcement(self._player(), game_context=ctx)
        assert "batting" in script.lower()


# ---------------------------------------------------------------------------
# MockTTS — generates valid WAV bytes without any API keys
# ---------------------------------------------------------------------------

class TestMockTTS:
    def test_synthesize_returns_bytes(self):
        provider = MockTTS()
        result = provider.synthesize("Hello, world!", voice_config={})
        assert isinstance(result, bytes)

    def test_synthesize_returns_nonempty(self):
        provider = MockTTS()
        result = provider.synthesize("Test", voice_config={})
        assert len(result) > 0

    def test_output_is_wav_format(self):
        provider = MockTTS()
        result = provider.synthesize("Test", voice_config={})
        assert result[:4] == b"RIFF"

    def test_name_property(self):
        assert MockTTS().name == "mock"


# ---------------------------------------------------------------------------
# get_tts_provider / get_quick_tts_provider — fall through to mock
# ---------------------------------------------------------------------------

class TestGetTtsProvider:
    def test_returns_mock_when_no_env_vars(self, monkeypatch):
        monkeypatch.delenv("LOCAL_TTS_URL", raising=False)
        monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        monkeypatch.delenv("ANNOUNCER_VOICE_REF_URL", raising=False)
        # Pin availability: edge-tts is an optional install, and the point of this
        # test is chain order, not whether the package is present on this machine.
        monkeypatch.setattr(EdgeTTSProvider, "available", lambda self: True)
        provider = get_tts_provider()
        # EdgeTTS is the first credential-free provider in the chain
        assert isinstance(provider, EdgeTTSProvider)

    def test_quick_returns_mock_when_no_env_vars(self, monkeypatch):
        monkeypatch.delenv("LOCAL_TTS_URL", raising=False)
        monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        monkeypatch.delenv("ANNOUNCER_VOICE_REF_URL", raising=False)
        # Pin availability: edge-tts is an optional install, and the point of this
        # test is chain order, not whether the package is present on this machine.
        monkeypatch.setattr(EdgeTTSProvider, "available", lambda self: True)
        provider = get_quick_tts_provider()
        # EdgeTTS is the first credential-free provider in the chain
        assert isinstance(provider, EdgeTTSProvider)


# ---------------------------------------------------------------------------
# _apply_phonetics — name substitution map
# ---------------------------------------------------------------------------

class TestApplyPhonetics:
    def test_empty_map_returns_text_unchanged(self, monkeypatch):
        import tools.announcer_engine as ae
        monkeypatch.setattr(ae, "_PHONETIC_MAP", {})
        assert ae._apply_phonetics("Hello Sofia") == "Hello Sofia"

    def test_known_word_replaced(self, monkeypatch):
        import tools.announcer_engine as ae
        monkeypatch.setattr(ae, "_PHONETIC_MAP", {"Sofia": "SOH-fee-ah"})
        result = ae._apply_phonetics("Now batting: Sofia")
        assert "SOH-fee-ah" in result

    def test_replacement_case_insensitive(self, monkeypatch):
        import tools.announcer_engine as ae
        monkeypatch.setattr(ae, "_PHONETIC_MAP", {"sofia": "SOH-fee-ah"})
        result = ae._apply_phonetics("SOFIA is up next")
        assert "SOH-fee-ah" in result

    def test_multiple_replacements(self, monkeypatch):
        import tools.announcer_engine as ae
        monkeypatch.setattr(ae, "_PHONETIC_MAP", {"Jane": "JAYN", "Doe": "DOH"})
        result = ae._apply_phonetics("Jane Doe")
        assert "JAYN" in result
        assert "DOH" in result

    def test_non_matching_word_untouched(self, monkeypatch):
        import tools.announcer_engine as ae
        monkeypatch.setattr(ae, "_PHONETIC_MAP", {"Alice": "AL-iss"})
        result = ae._apply_phonetics("Now batting: Bob")
        assert "Bob" in result
        assert "AL-iss" not in result

    def test_returns_string(self, monkeypatch):
        import tools.announcer_engine as ae
        monkeypatch.setattr(ae, "_PHONETIC_MAP", {})
        assert isinstance(ae._apply_phonetics("test"), str)


# ---------------------------------------------------------------------------
# _atomic_write_json — file creation and atomicity
# ---------------------------------------------------------------------------

class TestAtomicWriteJson:
    def test_creates_file_with_correct_content(self, tmp_path):
        from tools.announcer_engine import _atomic_write_json
        target = tmp_path / "test.json"
        data = {"key": "value", "num": 42}
        _atomic_write_json(target, data)
        import json
        assert json.loads(target.read_text()) == data

    def test_creates_parent_dirs_automatically(self, tmp_path):
        from tools.announcer_engine import _atomic_write_json
        target = tmp_path / "sub" / "deep" / "file.json"
        _atomic_write_json(target, {"x": 1})
        assert target.exists()

    def test_overwrites_existing_file(self, tmp_path):
        from tools.announcer_engine import _atomic_write_json
        import json
        target = tmp_path / "data.json"
        _atomic_write_json(target, {"v": 1})
        _atomic_write_json(target, {"v": 2})
        assert json.loads(target.read_text()) == {"v": 2}

    def test_writes_list(self, tmp_path):
        from tools.announcer_engine import _atomic_write_json
        import json
        target = tmp_path / "list.json"
        _atomic_write_json(target, [1, 2, 3])
        assert json.loads(target.read_text()) == [1, 2, 3]


# ---------------------------------------------------------------------------
# _read_json — filesystem JSON reader
# ---------------------------------------------------------------------------

class TestReadJson:
    def test_missing_file_returns_default(self, tmp_path):
        from tools.announcer_engine import _read_json
        result = _read_json(tmp_path / "absent.json", default={"fallback": True})
        assert result == {"fallback": True}

    def test_valid_json_parsed(self, tmp_path):
        from tools.announcer_engine import _read_json
        import json
        p = tmp_path / "data.json"
        p.write_text(json.dumps({"ok": True}))
        assert _read_json(p) == {"ok": True}

    def test_malformed_json_returns_default(self, tmp_path):
        from tools.announcer_engine import _read_json
        p = tmp_path / "bad.json"
        p.write_text("{INVALID")
        result = _read_json(p, default=None)
        assert result is None

    def test_none_default(self, tmp_path):
        from tools.announcer_engine import _read_json
        result = _read_json(tmp_path / "absent.json")
        assert result is None


# ---------------------------------------------------------------------------
# build_announcement_text — thin delegate
# ---------------------------------------------------------------------------

class TestBuildAnnouncementText:
    def test_delegates_to_situational(self):
        from tools.announcer_engine import build_announcement_text
        player = {"number": "7", "first": "Jane", "last": "Doe",
                  "phonetic_hint": "", "tts_instruction": ""}
        result = build_announcement_text(player)
        assert isinstance(result, str)
        assert "batting" in result.lower() or "Jane" in result

    def test_with_game_context(self):
        from tools.announcer_engine import build_announcement_text
        player = {"number": "7", "first": "Jane", "last": "Doe",
                  "phonetic_hint": "", "tts_instruction": ""}
        ctx = {"bases": [False, False, False], "outs": 0}
        result = build_announcement_text(player, game_context=ctx)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# load_voice_profiles / get_default_voice_profile
# ---------------------------------------------------------------------------

class TestVoiceProfiles:
    """Profiles are a fixed list in code; only the team default is persisted."""

    def test_halo_is_the_default_when_nothing_selected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ae_mod, "VOICE_SELECTION_FILE", tmp_path / "sel.json")
        assert get_default_voice_profile()["id"] == "halo"
        profiles = load_voice_profiles()
        assert [p["id"] for p in profiles if p["is_default"]] == ["halo"]
        assert len(profiles) >= 4

    def test_halo_profile_drops_pitch_and_uses_deep_voice(self):
        halo = ae_mod.get_voice_profile("halo")
        assert halo["pitch_semitones"] < 0
        assert halo["elevenlabs_voice_id"] == ae_mod.ANNOUNCER_ELEVENLABS_VOICE_ID
        assert halo["voice_settings"]["style"] >= 0.7

    def test_set_default_persists_and_reloads(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ae_mod, "VOICE_SELECTION_FILE", tmp_path / "sel.json")
        monkeypatch.setattr(ae_mod, "_ensure_dirs", lambda: None)
        ae_mod.set_default_voice_profile("callum")
        assert ae_mod.get_default_voice_profile_id() == "callum"
        assert get_default_voice_profile()["id"] == "callum"

    def test_set_default_rejects_unknown(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ae_mod, "VOICE_SELECTION_FILE", tmp_path / "sel.json")
        with pytest.raises(ValueError):
            ae_mod.set_default_voice_profile("nope")

    def test_corrupt_selection_falls_back_to_halo(self, tmp_path, monkeypatch):
        sel = tmp_path / "sel.json"
        sel.write_text('{"default_profile_id": "deleted-voice"}', encoding="utf-8")
        monkeypatch.setattr(ae_mod, "VOICE_SELECTION_FILE", sel)
        assert ae_mod.get_default_voice_profile_id() == "halo"

    def test_player_override_beats_team_default(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ae_mod, "VOICE_SELECTION_FILE", tmp_path / "sel.json")
        assert ae_mod.resolve_voice_profile({"voice_profile_id": "george"})["id"] == "george"
        assert ae_mod.resolve_voice_profile({"voice_profile_id": ""})["id"] == "halo"
        assert ae_mod.resolve_voice_profile({"voice_profile_id": "bogus"})["id"] == "halo"


class TestElevenLabsUsesProfile:
    def test_model_and_settings_come_from_profile(self, monkeypatch):
        captured = {}

        class _Resp:
            status_code = 200
            content = b"audio"
            headers = {}

        def _post(url, json=None, headers=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            return _Resp()

        monkeypatch.setattr(ae_mod.requests, "post", _post)
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el_fake")
        monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
        monkeypatch.delenv("ELEVENLABS_DEFAULT_VOICE_ID", raising=False)
        monkeypatch.setitem(sys.modules, "sync_daemon", None)
        profile = ae_mod.get_voice_profile("callum")
        ae_mod.ElevenLabsTTS().synthesize("hello", profile)
        assert profile["elevenlabs_voice_id"] in captured["url"]
        assert captured["json"]["model_id"] == profile["model_id"]
        assert captured["json"]["voice_settings"] == profile["voice_settings"]


class TestPitchDropInStadiumChain:
    def test_negative_semitones_add_resample_stage(self, tmp_path, monkeypatch):
        import shutil, subprocess
        if not shutil.which("ffmpeg"):
            pytest.skip("ffmpeg not installed")
        monkeypatch.setattr(ae_mod, "CLIPS_DIR", tmp_path / "clips")
        src = tmp_path / "in.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                        "-i", "sine=frequency=200:duration=1", str(src)], check=True)
        out = tmp_path / "shifted.mp3"
        _, mp3 = ae_mod.archive_and_transcode(src.read_bytes(), "p1", archive=False,
                                              pitch_semitones=-2.0, out_mp3=out)
        assert mp3 == out and out.stat().st_size > 0
        # Duration must survive the tempo correction: 1 s of source plus the
        # Stadium Wrap's ~0.45 s PA tail and codec padding — never the 1.12 s
        # stretch an uncorrected asetrate would leave on top of that.
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                    "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout)
        assert 1.30 < dur < 1.60


class TestRenderVoiceSample:
    def test_renders_once_then_serves_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ae_mod, "VOICE_SAMPLES_DIR", tmp_path / "samples")
        calls = []

        class _P(ae_mod.TTSProvider):
            name = "fake"
            def synthesize(self, text, voice_config):
                calls.append((text, voice_config["id"]))
                return b"x" * 2000

        monkeypatch.setattr(ae_mod, "get_tts_provider", lambda: _P())
        monkeypatch.setattr(ae_mod, "archive_and_transcode",
                            lambda audio, pid, **kw: (None, kw["out_mp3"].write_bytes(audio) and kw["out_mp3"]))
        p1 = ae_mod.render_voice_sample("george")
        p2 = ae_mod.render_voice_sample("george")
        assert p1 == p2 and p1.exists()
        assert len(calls) == 1 and calls[0][1] == "george"
        assert "[pause" not in calls[0][0]           # markup stripped for non-Edge providers

    def test_unknown_profile_raises(self):
        with pytest.raises(ValueError):
            ae_mod.render_voice_sample("nope")


# ---------------------------------------------------------------------------
# _bootstrap_roster_from_team
# ---------------------------------------------------------------------------

class TestBootstrapRosterFromTeam:
    def test_returns_empty_when_no_team_files(self, tmp_path, monkeypatch):
        sharks_dir = tmp_path / "sharks"
        sharks_dir.mkdir()
        monkeypatch.setattr(ae_mod, "DATA_DIR", tmp_path)
        result = _bootstrap_roster_from_team()
        assert result == []

    def test_builds_roster_from_team_json(self, tmp_path, monkeypatch):
        sharks_dir = tmp_path / "sharks"
        sharks_dir.mkdir()
        team = {
            "roster": [
                {"first": "Jane", "last": "Doe", "number": "7"},
                {"first": "Sara", "last": "Smith", "number": "12"},
            ]
        }
        (sharks_dir / "team.json").write_text(json.dumps(team))
        monkeypatch.setattr(ae_mod, "DATA_DIR", tmp_path)
        result = _bootstrap_roster_from_team()
        assert len(result) == 2

    def test_each_entry_has_required_fields(self, tmp_path, monkeypatch):
        sharks_dir = tmp_path / "sharks"
        sharks_dir.mkdir()
        team = {"roster": [{"first": "Jane", "last": "Doe", "number": "7"}]}
        (sharks_dir / "team.json").write_text(json.dumps(team))
        monkeypatch.setattr(ae_mod, "DATA_DIR", tmp_path)
        result = _bootstrap_roster_from_team()
        assert len(result) == 1
        entry = result[0]
        for key in ("id", "first", "last", "number", "status", "is_active"):
            assert key in entry

    def test_skips_player_without_first_name(self, tmp_path, monkeypatch):
        sharks_dir = tmp_path / "sharks"
        sharks_dir.mkdir()
        team = {"roster": [{"last": "NoFirst", "number": "99"}]}
        (sharks_dir / "team.json").write_text(json.dumps(team))
        monkeypatch.setattr(ae_mod, "DATA_DIR", tmp_path)
        result = _bootstrap_roster_from_team()
        assert result == []


# ---------------------------------------------------------------------------
# load_announcer_roster / save_announcer_roster / get_player_by_id / update_player
# ---------------------------------------------------------------------------

class TestLoadSaveAnnouncerRoster:
    def _setup(self, tmp_path, monkeypatch):
        sharks_dir = tmp_path / "sharks"
        announcer_dir = sharks_dir / "announcer"
        announcer_dir.mkdir(parents=True)
        monkeypatch.setattr(ae_mod, "DATA_DIR", tmp_path)
        monkeypatch.setattr(ae_mod, "ANNOUNCER_DIR", announcer_dir)
        monkeypatch.setattr(ae_mod, "ROSTER_FILE", announcer_dir / "roster.json")
        return announcer_dir

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        roster = [{"id": "7-jane-doe", "first": "Jane", "last": "Doe", "number": "7",
                   "status": "pending", "is_active": True}]
        save_announcer_roster(roster)
        loaded = load_announcer_roster()
        assert loaded[0]["id"] == "7-jane-doe"

    def test_load_returns_list(self, tmp_path, monkeypatch):
        sharks_dir = tmp_path / "sharks"
        announcer_dir = sharks_dir / "announcer"
        announcer_dir.mkdir(parents=True)
        monkeypatch.setattr(ae_mod, "DATA_DIR", tmp_path)
        monkeypatch.setattr(ae_mod, "ANNOUNCER_DIR", announcer_dir)
        monkeypatch.setattr(ae_mod, "ROSTER_FILE", announcer_dir / "roster.json")
        result = load_announcer_roster()
        assert isinstance(result, list)


class TestGetPlayerById:
    def _setup(self, tmp_path, monkeypatch, roster):
        sharks_dir = tmp_path / "sharks"
        announcer_dir = sharks_dir / "announcer"
        announcer_dir.mkdir(parents=True)
        (announcer_dir / "roster.json").write_text(json.dumps(roster))
        monkeypatch.setattr(ae_mod, "DATA_DIR", tmp_path)
        monkeypatch.setattr(ae_mod, "ANNOUNCER_DIR", announcer_dir)
        monkeypatch.setattr(ae_mod, "ROSTER_FILE", announcer_dir / "roster.json")

    def test_returns_player_when_found(self, tmp_path, monkeypatch):
        roster = [{"id": "7-jane-doe", "first": "Jane", "last": "Doe"}]
        self._setup(tmp_path, monkeypatch, roster)
        result = get_player_by_id("7-jane-doe")
        assert result is not None
        assert result["first"] == "Jane"

    def test_returns_none_when_not_found(self, tmp_path, monkeypatch):
        roster = [{"id": "7-jane-doe", "first": "Jane", "last": "Doe"}]
        self._setup(tmp_path, monkeypatch, roster)
        result = get_player_by_id("99-nobody")
        assert result is None


class TestUpdatePlayer:
    def _setup(self, tmp_path, monkeypatch, roster):
        sharks_dir = tmp_path / "sharks"
        announcer_dir = sharks_dir / "announcer"
        announcer_dir.mkdir(parents=True)
        (announcer_dir / "roster.json").write_text(json.dumps(roster))
        monkeypatch.setattr(ae_mod, "DATA_DIR", tmp_path)
        monkeypatch.setattr(ae_mod, "ANNOUNCER_DIR", announcer_dir)
        monkeypatch.setattr(ae_mod, "ROSTER_FILE", announcer_dir / "roster.json")

    def test_returns_updated_player(self, tmp_path, monkeypatch):
        roster = [{"id": "7-jane-doe", "first": "Jane", "status": "pending"}]
        self._setup(tmp_path, monkeypatch, roster)
        result = update_player("7-jane-doe", {"status": "done"})
        assert result["status"] == "done"

    def test_returns_none_when_player_not_found(self, tmp_path, monkeypatch):
        roster = [{"id": "7-jane-doe", "first": "Jane"}]
        self._setup(tmp_path, monkeypatch, roster)
        result = update_player("99-nobody", {"status": "done"})
        assert result is None

    def test_persists_update_to_file(self, tmp_path, monkeypatch):
        roster = [{"id": "7-jane-doe", "first": "Jane", "status": "pending"}]
        self._setup(tmp_path, monkeypatch, roster)
        update_player("7-jane-doe", {"status": "done"})
        loaded = load_announcer_roster()
        assert loaded[0]["status"] == "done"


# ---------------------------------------------------------------------------
# _get_phonetic_map — ImportError branch (lines 48-49)
# ---------------------------------------------------------------------------

class TestGetPhoneticMapImportError:
    def test_import_error_returns_empty_dict(self, monkeypatch):
        """Lines 48-49: when sync_daemon import fails, _PHONETIC_MAP = {}."""
        monkeypatch.setattr(ae_mod, "_PHONETIC_MAP", None)
        monkeypatch.setitem(sys.modules, "sync_daemon", None)
        result = ae_mod._get_phonetic_map()
        assert result == {}
        # restore
        monkeypatch.setattr(ae_mod, "_PHONETIC_MAP", None)


# ---------------------------------------------------------------------------
# _resolve_secret (lines 66, 70-71)
# ---------------------------------------------------------------------------

class TestResolveSecret:
    def test_returns_env_var_when_set(self, monkeypatch):
        """Line 66: env var non-empty → returns immediately without sync_daemon."""
        monkeypatch.setenv("_TEST_SECRET_KEY", "my_secret_value")
        result = ae_mod._resolve_secret("_TEST_SECRET_KEY")
        assert result == "my_secret_value"

    def test_falls_back_to_sync_daemon(self, monkeypatch):
        """Lines 70-71: env var empty, sync_daemon has _resolve_secret."""
        monkeypatch.delenv("_FAKE_SD_KEY", raising=False)
        fake_sd = types.ModuleType("sync_daemon")
        fake_sd._resolve_secret = lambda name, default="": f"sd:{name}"
        monkeypatch.setitem(sys.modules, "sync_daemon", fake_sd)
        result = ae_mod._resolve_secret("_FAKE_SD_KEY", "default")
        assert result == "sd:_FAKE_SD_KEY"

    def test_returns_default_when_no_env_and_no_sync_daemon(self, monkeypatch):
        monkeypatch.delenv("_MISSING_KEY", raising=False)
        monkeypatch.setitem(sys.modules, "sync_daemon", None)
        result = ae_mod._resolve_secret("_MISSING_KEY", "fallback")
        assert result == "fallback"


# ---------------------------------------------------------------------------
# _atomic_write_json exception handler (lines 89-94)
# ---------------------------------------------------------------------------

class TestAtomicWriteJsonException:
    def test_exception_cleans_up_tmp_and_reraises(self, tmp_path, monkeypatch):
        """Lines 89-94: json.dump failure → tmp removed, exception re-raised."""
        from tools.announcer_engine import _atomic_write_json
        monkeypatch.setattr(ae_mod.json, "dump",
                            lambda *a, **kw: (_ for _ in ()).throw(ValueError("encode error")))
        target = tmp_path / "atomic.json"
        with pytest.raises(ValueError, match="encode error"):
            _atomic_write_json(target, {"key": "val"})
        # no .tmp files should linger
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_unlink_oserrror_in_cleanup_swallowed(self, tmp_path, monkeypatch):
        """Lines 92-93: json.dump fails AND os.unlink fails → OSError swallowed."""
        from tools.announcer_engine import _atomic_write_json
        monkeypatch.setattr(ae_mod.json, "dump",
                            lambda *a, **kw: (_ for _ in ()).throw(ValueError("encode error")))
        monkeypatch.setattr(ae_mod.os, "unlink",
                            lambda *a, **kw: (_ for _ in ()).throw(OSError("already gone")))
        target = tmp_path / "atomic.json"
        # ValueError re-raised, OSError swallowed (lines 92-93)
        with pytest.raises(ValueError, match="encode error"):
            _atomic_write_json(target, {"key": "val"})


# ---------------------------------------------------------------------------
# LocalVLLMTTS (lines 141, 144-162)
# ---------------------------------------------------------------------------

class TestLocalVLLMTTS:
    def test_name_property(self):
        """Line 141: name returns 'local_vllm'."""
        assert ae_mod.LocalVLLMTTS().name == "local_vllm"

    def test_synthesize_returns_content_on_200(self, monkeypatch):
        """Lines 159-162: successful POST returns audio bytes."""
        monkeypatch.setenv("LOCAL_TTS_URL", "http://local:8080")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"audio_data"
        monkeypatch.setattr(ae_mod.requests, "post", lambda *a, **kw: mock_resp)
        result = ae_mod.LocalVLLMTTS().synthesize("Hello", {})
        assert result == b"audio_data"

    def test_synthesize_raises_when_not_200(self, monkeypatch):
        """Line 161: non-200 response → RuntimeError."""
        monkeypatch.setenv("LOCAL_TTS_URL", "http://local:8080")
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "server error"
        monkeypatch.setattr(ae_mod.requests, "post", lambda *a, **kw: mock_resp)
        with pytest.raises(RuntimeError, match="Local TTS returned 500"):
            ae_mod.LocalVLLMTTS().synthesize("Hello", {})

    def test_synthesize_raises_when_url_not_set(self, monkeypatch):
        """Line 146: no LOCAL_TTS_URL → RuntimeError."""
        monkeypatch.delenv("LOCAL_TTS_URL", raising=False)
        with pytest.raises(RuntimeError, match="LOCAL_TTS_URL not set"):
            ae_mod.LocalVLLMTTS().synthesize("Hello", {})

    def test_synthesize_passes_reference_audio(self, monkeypatch):
        """Lines 156-158: voice_config reference fields are included in payload."""
        monkeypatch.setenv("LOCAL_TTS_URL", "http://local:8080")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"x"
        captured = {}
        def fake_post(url, json=None, **kw):
            captured["payload"] = json
            return mock_resp
        monkeypatch.setattr(ae_mod.requests, "post", fake_post)
        ae_mod.LocalVLLMTTS().synthesize("Hi", {
            "reference_audio_url": "http://ref.mp3",
            "reference_transcript": "Now batting",
        })
        assert captured["payload"]["reference_audio_url"] == "http://ref.mp3"


# ---------------------------------------------------------------------------
# ReplicateTTS properties + synthesize (lines 173-174, 182, 185-242, 245-253)
# ---------------------------------------------------------------------------

class TestReplicateTTSProperties:
    def test_api_url_uses_default_model(self, monkeypatch):
        """Lines 173-174: _api_url property uses default model slug."""
        monkeypatch.delenv("REPLICATE_BEST_MODEL_ID", raising=False)
        provider = ae_mod.ReplicateTTS()
        assert "qwen2.5-tts-3b" in provider._api_url

    def test_api_url_uses_env_override(self, monkeypatch):
        """Line 173: REPLICATE_BEST_MODEL_ID env var overrides default slug."""
        monkeypatch.setenv("REPLICATE_BEST_MODEL_ID", "custom/model-id")
        provider = ae_mod.ReplicateTTS()
        assert "custom/model-id" in provider._api_url

    def test_name_property(self):
        """Line 182: name returns 'replicate_qwen25_tts_3b'."""
        assert ae_mod.ReplicateTTS().name == "replicate_qwen25_tts_3b"


class TestReplicateTTSSynthesize:
    def _make_provider(self, monkeypatch, token="r8_faketoken"):
        monkeypatch.setenv("REPLICATE_API_TOKEN", token)
        monkeypatch.delenv("LOCAL_TTS_URL", raising=False)
        return ae_mod.ReplicateTTS()

    def test_raises_when_no_token(self, monkeypatch):
        """Line 187: missing token → RuntimeError."""
        monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
        monkeypatch.setitem(sys.modules, "sync_daemon", None)
        with pytest.raises(RuntimeError, match="REPLICATE_API_TOKEN"):
            ae_mod.ReplicateTTS().synthesize("Hi", {})

    def test_succeeded_immediately(self, monkeypatch):
        """Lines 222-223: status == 'succeeded' on initial POST → downloads."""
        provider = self._make_provider(monkeypatch)
        audio_data = b"mp3_audio"
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {
            "status": "succeeded",
            "output": "https://cdn.replicate.com/out.mp3",
        }
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.content = audio_data

        monkeypatch.setattr(ae_mod.requests, "post", lambda *a, **kw: post_resp)
        monkeypatch.setattr(ae_mod.requests, "get", lambda *a, **kw: get_resp)
        result = provider.synthesize("Hello pitcher", {})
        assert result == audio_data

    def test_polls_until_succeeded(self, monkeypatch):
        """Lines 230-237: polling loop terminates on 'succeeded' poll."""
        provider = self._make_provider(monkeypatch)
        monkeypatch.setattr(ae_mod.time, "sleep", lambda n: None)

        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {
            "status": "processing",
            "urls": {"get": "https://api.replicate.com/v1/predictions/xyz"},
        }
        poll_calls = [0]
        def fake_get(url, **kw):
            if "predictions" in url:
                poll_calls[0] += 1
                if poll_calls[0] < 2:
                    r = MagicMock(); r.json.return_value = {"status": "processing"}; return r
                r = MagicMock()
                r.json.return_value = {
                    "status": "succeeded",
                    "output": ["https://cdn.replicate.com/out.mp3"],
                }
                return r
            # audio download
            r = MagicMock(); r.status_code = 200; r.content = b"audio"; return r

        monkeypatch.setattr(ae_mod.requests, "post", lambda *a, **kw: post_resp)
        monkeypatch.setattr(ae_mod.requests, "get", fake_get)
        result = provider.synthesize("Hello", {})
        assert result == b"audio"
        assert poll_calls[0] == 2

    def test_poll_failed_status_raises(self, monkeypatch):
        """Lines 238-240: 'failed' poll status → RuntimeError."""
        provider = self._make_provider(monkeypatch)
        monkeypatch.setattr(ae_mod.time, "sleep", lambda n: None)

        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {
            "status": "processing",
            "urls": {"get": "https://api.replicate.com/v1/predictions/xyz"},
        }
        poll_resp = MagicMock()
        poll_resp.json.return_value = {"status": "failed", "error": "model crash"}

        monkeypatch.setattr(ae_mod.requests, "post", lambda *a, **kw: post_resp)
        monkeypatch.setattr(ae_mod.requests, "get", lambda *a, **kw: poll_resp)
        with pytest.raises(RuntimeError, match="model crash"):
            provider.synthesize("Hello", {})

    def test_no_poll_url_raises(self, monkeypatch):
        """Line 228: missing poll URL → RuntimeError."""
        provider = self._make_provider(monkeypatch)
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"status": "processing", "urls": {}}
        monkeypatch.setattr(ae_mod.requests, "post", lambda *a, **kw: post_resp)
        with pytest.raises(RuntimeError, match="No poll URL"):
            provider.synthesize("Hello", {})

    def test_non_200_post_raises(self, monkeypatch):
        """Lines 215-216: Replicate POST returns non-200 → RuntimeError."""
        provider = self._make_provider(monkeypatch)
        post_resp = MagicMock()
        post_resp.status_code = 422
        post_resp.text = "invalid input"
        monkeypatch.setattr(ae_mod.requests, "post", lambda *a, **kw: post_resp)
        with pytest.raises(RuntimeError, match="Replicate returned 422"):
            provider.synthesize("Hello", {})

    def test_clone_mode_when_ref_audio_set(self, monkeypatch):
        """Lines 205-208: voice_config with ref audio → mode='clone'."""
        provider = self._make_provider(monkeypatch)
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {
            "status": "succeeded",
            "output": "https://cdn/out.mp3",
        }
        get_resp = MagicMock(); get_resp.status_code = 200; get_resp.content = b"x"
        captured = {}
        def fake_post(url, json=None, **kw):
            captured["payload"] = json
            return post_resp
        monkeypatch.setattr(ae_mod.requests, "post", fake_post)
        monkeypatch.setattr(ae_mod.requests, "get", lambda *a, **kw: get_resp)
        provider.synthesize("Hi", {
            "reference_audio_url": "https://ref/clip.mp3",
            "reference_transcript": "Now batting",
        })
        assert captured["payload"]["input"]["mode"] == "clone"

    def test_timeout_raises(self, monkeypatch):
        """Line 242: polling exceeds MAX_POLL_SECONDS → RuntimeError."""
        provider = self._make_provider(monkeypatch)
        provider.MAX_POLL_SECONDS = 0  # instant timeout
        monkeypatch.setattr(ae_mod.time, "sleep", lambda n: None)

        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {
            "status": "processing",
            "urls": {"get": "https://api.replicate.com/v1/predictions/xyz"},
        }
        poll_resp = MagicMock()
        poll_resp.json.return_value = {"status": "processing"}
        monkeypatch.setattr(ae_mod.requests, "post", lambda *a, **kw: post_resp)
        monkeypatch.setattr(ae_mod.requests, "get", lambda *a, **kw: poll_resp)
        with pytest.raises(RuntimeError, match="timed out"):
            provider.synthesize("Hello", {})


class TestReplicateTTSDownloadOutput:
    def test_raises_when_no_output(self):
        """Lines 247-248: no 'output' key → RuntimeError."""
        with pytest.raises(RuntimeError, match="no output"):
            ae_mod.ReplicateTTS()._download_output({"output": None})

    def test_downloads_from_url_string(self, monkeypatch):
        """Lines 249-253: output is URL string → GET and return content."""
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.content = b"audio_bytes"
        monkeypatch.setattr(ae_mod.requests, "get", lambda *a, **kw: get_resp)
        result = ae_mod.ReplicateTTS()._download_output({"output": "https://cdn/out.mp3"})
        assert result == b"audio_bytes"

    def test_downloads_from_url_list(self, monkeypatch):
        """Line 249: output is list → use first element."""
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.content = b"list_audio"
        monkeypatch.setattr(ae_mod.requests, "get", lambda *a, **kw: get_resp)
        result = ae_mod.ReplicateTTS()._download_output({"output": ["https://cdn/out.mp3"]})
        assert result == b"list_audio"

    def test_raises_when_download_fails(self, monkeypatch):
        """Lines 251-252: non-200 download → RuntimeError."""
        get_resp = MagicMock()
        get_resp.status_code = 403
        monkeypatch.setattr(ae_mod.requests, "get", lambda *a, **kw: get_resp)
        with pytest.raises(RuntimeError, match="Failed to download"):
            ae_mod.ReplicateTTS()._download_output({"output": "https://cdn/out.mp3"})


# ---------------------------------------------------------------------------
# Replicate06bTTS (lines 268-272, 278)
# ---------------------------------------------------------------------------

class TestReplicate06bTTS:
    def test_api_url_uses_default_06b_slug(self, monkeypatch):
        """Lines 268-272: uses the 0.6B model slug by default."""
        monkeypatch.delenv("REPLICATE_06B_MODEL_ID", raising=False)
        provider = ae_mod.Replicate06bTTS()
        assert "qwen3-tts-0.6b" in provider._api_url

    def test_api_url_uses_env_override(self, monkeypatch):
        """Line 268: REPLICATE_06B_MODEL_ID overrides default."""
        monkeypatch.setenv("REPLICATE_06B_MODEL_ID", "custom/06b-model")
        provider = ae_mod.Replicate06bTTS()
        assert "custom/06b-model" in provider._api_url

    def test_name_property(self):
        """Line 278: name returns the 0.6B identifier."""
        assert ae_mod.Replicate06bTTS().name == "replicate_qwen3_tts_0.6b"

    def test_max_poll_seconds_is_30(self):
        """Line 274: 0.6B has shorter timeout than 3B."""
        assert ae_mod.Replicate06bTTS.MAX_POLL_SECONDS == 30


# ---------------------------------------------------------------------------
# ElevenLabsTTS (lines 286, 289-320)
# ---------------------------------------------------------------------------

class TestElevenLabsTTS:
    def test_name_property(self):
        """Line 286: name returns 'elevenlabs'."""
        assert ae_mod.ElevenLabsTTS().name == "elevenlabs"

    def test_synthesize_returns_audio_on_200(self, monkeypatch):
        """Lines 317-320: successful POST returns audio bytes."""
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el_fakekey")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"el_audio"
        monkeypatch.setattr(ae_mod.requests, "post", lambda *a, **kw: mock_resp)
        result = ae_mod.ElevenLabsTTS().synthesize("Hello", {})
        assert result == b"el_audio"

    def test_synthesize_raises_when_no_key(self, monkeypatch):
        """Line 299: no ELEVENLABS_API_KEY → RuntimeError."""
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        monkeypatch.setitem(sys.modules, "sync_daemon", None)
        with pytest.raises(RuntimeError, match="ELEVENLABS_API_KEY"):
            ae_mod.ElevenLabsTTS().synthesize("Hello", {})

    def test_synthesize_raises_when_not_200(self, monkeypatch):
        """Lines 318-319: non-200 → RuntimeError."""
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el_fakekey")
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "rate limited"
        monkeypatch.setattr(ae_mod.requests, "post", lambda *a, **kw: mock_resp)
        with pytest.raises(RuntimeError, match="ElevenLabs returned 429"):
            ae_mod.ElevenLabsTTS().synthesize("Hello", {})

    def test_voice_id_from_voice_config(self, monkeypatch):
        """Lines 290-294: voice_config elevenlabs_voice_id takes precedence."""
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el_fakekey")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"x"
        captured = {}
        def fake_post(url, **kw):
            captured["url"] = url
            return mock_resp
        monkeypatch.setattr(ae_mod.requests, "post", fake_post)
        ae_mod.ElevenLabsTTS().synthesize("Hi", {"elevenlabs_voice_id": "custom_vid"})
        assert "custom_vid" in captured["url"]


# ---------------------------------------------------------------------------
# get_tts_provider branches (lines 361, 363, 365)
# get_quick_tts_provider branches (lines 379, 381, 383)
# ---------------------------------------------------------------------------

class TestGetTtsProviderBranches:
    def test_returns_local_vllm_when_url_set(self, monkeypatch):
        """Line 361: LOCAL_TTS_URL → LocalVLLMTTS."""
        monkeypatch.setenv("LOCAL_TTS_URL", "http://local:8080")
        assert isinstance(ae_mod.get_tts_provider(), ae_mod.LocalVLLMTTS)

    def test_returns_replicate_when_token_and_ref_url(self, monkeypatch):
        """Line 363: REPLICATE_API_TOKEN + ANNOUNCER_VOICE_REF_URL → ReplicateTTS."""
        monkeypatch.delenv("LOCAL_TTS_URL", raising=False)
        monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_faketoken")
        monkeypatch.setenv("ANNOUNCER_VOICE_REF_URL", "https://ref/clip.mp3")
        assert isinstance(ae_mod.get_tts_provider(), ae_mod.ReplicateTTS)

    def test_returns_elevenlabs_when_only_el_key(self, monkeypatch):
        """With ELEVENLABS_API_KEY set, ElevenLabs wins — it outranks the style-less free providers."""
        monkeypatch.delenv("LOCAL_TTS_URL", raising=False)
        monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
        monkeypatch.delenv("ANNOUNCER_VOICE_REF_URL", raising=False)
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el_fakekey")
        monkeypatch.setitem(sys.modules, "sync_daemon", None)
        assert isinstance(ae_mod.get_tts_provider(), ae_mod.ElevenLabsTTS)


class TestGetQuickTtsProviderBranches:
    def test_returns_local_vllm_when_url_set(self, monkeypatch):
        """Line 379: LOCAL_TTS_URL → LocalVLLMTTS for quick renders."""
        monkeypatch.setenv("LOCAL_TTS_URL", "http://local:8080")
        assert isinstance(ae_mod.get_quick_tts_provider(), ae_mod.LocalVLLMTTS)

    def test_returns_replicate06b_when_token_and_ref_url(self, monkeypatch):
        """Line 381: REPLICATE_API_TOKEN + ref URL → Replicate06bTTS for quick."""
        monkeypatch.delenv("LOCAL_TTS_URL", raising=False)
        monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_faketoken")
        monkeypatch.setenv("ANNOUNCER_VOICE_REF_URL", "https://ref/clip.mp3")
        assert isinstance(ae_mod.get_quick_tts_provider(), ae_mod.Replicate06bTTS)

    def test_returns_elevenlabs_when_only_el_key(self, monkeypatch):
        """With ELEVENLABS_API_KEY set, ElevenLabs wins — it outranks the style-less free providers."""
        monkeypatch.delenv("LOCAL_TTS_URL", raising=False)
        monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
        monkeypatch.delenv("ANNOUNCER_VOICE_REF_URL", raising=False)
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el_fakekey")
        monkeypatch.setitem(sys.modules, "sync_daemon", None)
        assert isinstance(ae_mod.get_quick_tts_provider(), ae_mod.ElevenLabsTTS)


# ---------------------------------------------------------------------------
# check_provider_health (lines 390-425)
# ---------------------------------------------------------------------------

class TestCheckProviderHealth:
    def test_returns_dict_with_all_keys(self, monkeypatch):
        """Result always has edge_tts and mock keys (provider names); mock is always True."""
        monkeypatch.delenv("LOCAL_TTS_URL", raising=False)
        monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        monkeypatch.setitem(sys.modules, "sync_daemon", None)
        result = ae_mod.check_provider_health()
        assert "edge_tts" in result and "mock" in result

    def test_mock_always_true(self, monkeypatch):
        """Line 391: mock field is always True."""
        monkeypatch.delenv("LOCAL_TTS_URL", raising=False)
        monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        monkeypatch.setitem(sys.modules, "sync_daemon", None)
        assert ae_mod.check_provider_health()["mock"] is True

    def test_local_tts_healthy(self, monkeypatch):
        """LOCAL_TTS_URL set, /health returns 200 → local_tts_ping True."""
        monkeypatch.setenv("LOCAL_TTS_URL", "http://local:8080")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        monkeypatch.setattr(ae_mod.requests, "get", lambda *a, **kw: mock_resp)
        result = ae_mod.check_provider_health()
        assert result["local_tts_ping"] is True

    def test_local_tts_unhealthy_when_non_200(self, monkeypatch):
        """Non-200 response → local_tts_ping False."""
        monkeypatch.setenv("LOCAL_TTS_URL", "http://local:8080")
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        monkeypatch.setattr(ae_mod.requests, "get", lambda *a, **kw: mock_resp)
        result = ae_mod.check_provider_health()
        assert result["local_tts_ping"] is False

    def test_local_tts_exception_swallowed(self, monkeypatch):
        """Request exception → local_tts_ping False (not re-raised)."""
        monkeypatch.setenv("LOCAL_TTS_URL", "http://local:8080")
        monkeypatch.setattr(ae_mod.requests, "get",
                            lambda *a, **kw: (_ for _ in ()).throw(ConnectionError("refused")))
        result = ae_mod.check_provider_health()
        assert result["local_tts_ping"] is False

    def test_replicate_healthy(self, monkeypatch):
        """REPLICATE_API_TOKEN set, account check returns 200 → replicate_ping True."""
        monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_fake")
        monkeypatch.delenv("LOCAL_TTS_URL", raising=False)
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        monkeypatch.setattr(ae_mod.requests, "get", lambda *a, **kw: mock_resp)
        result = ae_mod.check_provider_health()
        assert result["replicate_ping"] is True

    def test_elevenlabs_healthy(self, monkeypatch):
        """Lines 413-423: ELEVENLABS_API_KEY set, user check returns 200."""
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el_fake")
        monkeypatch.delenv("LOCAL_TTS_URL", raising=False)
        monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
        monkeypatch.setitem(sys.modules, "sync_daemon", None)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        monkeypatch.setattr(ae_mod.requests, "get", lambda *a, **kw: mock_resp)
        result = ae_mod.check_provider_health()
        assert result["elevenlabs"] is True

    def test_replicate_exception_swallowed(self, monkeypatch):
        """Replicate GET raises → replicate_ping False (exception swallowed)."""
        monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_fake")
        monkeypatch.delenv("LOCAL_TTS_URL", raising=False)
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        monkeypatch.setitem(sys.modules, "sync_daemon", None)
        monkeypatch.setattr(ae_mod.requests, "get",
                            lambda *a, **kw: (_ for _ in ()).throw(ConnectionError("refused")))
        result = ae_mod.check_provider_health()
        assert result["replicate_ping"] is False

    def test_elevenlabs_exception_swallowed(self, monkeypatch):
        """ElevenLabs GET raises → elevenlabs_ping False (exception swallowed)."""
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el_fake")
        monkeypatch.delenv("LOCAL_TTS_URL", raising=False)
        monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
        monkeypatch.setitem(sys.modules, "sync_daemon", None)
        monkeypatch.setattr(ae_mod.requests, "get",
                            lambda *a, **kw: (_ for _ in ()).throw(ConnectionError("refused")))
        result = ae_mod.check_provider_health()
        assert result["elevenlabs_ping"] is False


# ---------------------------------------------------------------------------
# _bootstrap_roster_from_team edge cases (lines 575, 580)
# ---------------------------------------------------------------------------

class TestBootstrapRosterEdgeCases:
    def test_returns_empty_when_roster_not_list(self, tmp_path, monkeypatch):
        """Line 575: team["roster"] is not a list → return []."""
        sharks_dir = tmp_path / "sharks"
        sharks_dir.mkdir()
        (sharks_dir / "team.json").write_text(json.dumps({"roster": "bad_type"}))
        monkeypatch.setattr(ae_mod, "DATA_DIR", tmp_path)
        result = ae_mod._bootstrap_roster_from_team()
        assert result == []

    def test_skips_non_dict_roster_entries(self, tmp_path, monkeypatch):
        """Line 580: non-dict entries in roster list → skipped via continue."""
        sharks_dir = tmp_path / "sharks"
        sharks_dir.mkdir()
        team = {"roster": [
            "not_a_dict",
            {"first": "Jane", "last": "Doe", "number": "7"},
        ]}
        (sharks_dir / "team.json").write_text(json.dumps(team))
        monkeypatch.setattr(ae_mod, "DATA_DIR", tmp_path)
        result = ae_mod._bootstrap_roster_from_team()
        assert len(result) == 1
        assert result[0]["first"] == "Jane"


# ---------------------------------------------------------------------------
# load_announcer_roster bootstrap path (lines 618-619)
# ---------------------------------------------------------------------------

class TestLoadAnnouncerRosterBootstrap:
    def test_bootstrap_writes_roster_when_no_file(self, tmp_path, monkeypatch):
        """Lines 618-619: no roster file + team.json → bootstrap + atomic write."""
        sharks_dir = tmp_path / "sharks"
        announcer_dir = sharks_dir / "announcer"
        announcer_dir.mkdir(parents=True)
        clips_dir = announcer_dir / "clips"
        clips_dir.mkdir()
        archive_dir = announcer_dir / "archive"
        archive_dir.mkdir()
        roster_file = announcer_dir / "roster.json"

        monkeypatch.setattr(ae_mod, "DATA_DIR", tmp_path)
        monkeypatch.setattr(ae_mod, "ANNOUNCER_DIR", announcer_dir)
        monkeypatch.setattr(ae_mod, "CLIPS_DIR", clips_dir)
        monkeypatch.setattr(ae_mod, "ARCHIVE_DIR", archive_dir)
        monkeypatch.setattr(ae_mod, "ROSTER_FILE", roster_file)

        team = {"roster": [{"first": "Jane", "last": "Doe", "number": "7"}]}
        (sharks_dir / "team.json").write_text(json.dumps(team))

        result = ae_mod.load_announcer_roster()
        assert len(result) == 1
        assert roster_file.exists()


# ---------------------------------------------------------------------------
# archive_and_transcode (lines 659-730) — subprocess mocked
# ---------------------------------------------------------------------------

class TestArchiveAndTranscode:
    def _setup(self, tmp_path, monkeypatch):
        announcer_dir = tmp_path / "announcer"
        archive_dir = announcer_dir / "archive"
        clips_dir = announcer_dir / "clips"
        archive_dir.mkdir(parents=True)
        clips_dir.mkdir(parents=True)
        monkeypatch.setattr(ae_mod, "ANNOUNCER_DIR", announcer_dir)
        monkeypatch.setattr(ae_mod, "ARCHIVE_DIR", archive_dir)
        monkeypatch.setattr(ae_mod, "CLIPS_DIR", clips_dir)
        return archive_dir, clips_dir

    def test_raises_when_ffmpeg_flac_fails(self, tmp_path, monkeypatch):
        """Lines 689-693: FLAC encode non-zero returncode → RuntimeError."""
        self._setup(tmp_path, monkeypatch)
        bad_result = MagicMock()
        bad_result.returncode = 1
        bad_result.stderr = b"error msg"
        with patch("subprocess.run", return_value=bad_result):
            with pytest.raises(RuntimeError, match="FFmpeg FLAC encode failed"):
                ae_mod.archive_and_transcode(b"fake_audio", "7-jane-doe")

    def test_raises_when_ffmpeg_mp3_fails(self, tmp_path, monkeypatch):
        """Lines 716-719: MP3 encode non-zero returncode → RuntimeError."""
        archive_dir, clips_dir = self._setup(tmp_path, monkeypatch)
        call_count = [0]
        def fake_run(*args, **kwargs):
            call_count[0] += 1
            r = MagicMock()
            if call_count[0] == 1:
                r.returncode = 0
                cmd = args[0] if args else kwargs.get("args", [])
                for s in cmd:
                    if str(s).endswith(".flac"):
                        Path(str(s)).write_bytes(b"fake flac")
            else:
                r.returncode = 1
                r.stderr = b"mp3 error"
            return r
        with patch("subprocess.run", side_effect=fake_run):
            with pytest.raises(RuntimeError, match="FFmpeg Stadium Wrap failed"):
                ae_mod.archive_and_transcode(b"fake_audio", "7-jane-doe")

    def test_returns_flac_and_mp3_paths_on_success(self, tmp_path, monkeypatch):
        """Lines 726-730: successful encode returns (flac_path, mp3_path)."""
        archive_dir, clips_dir = self._setup(tmp_path, monkeypatch)
        def fake_run(*args, **kwargs):
            r = MagicMock(); r.returncode = 0
            cmd = args[0] if args else []
            for s in cmd:
                p = Path(str(s))
                if p.suffix in (".flac", ".mp3"):
                    p.write_bytes(b"fake output")
            return r
        with patch("subprocess.run", side_effect=fake_run):
            flac_path, mp3_path = ae_mod.archive_and_transcode(b"fake_audio", "7-jane-doe")
        assert flac_path.suffix == ".flac"
        assert mp3_path.suffix == ".mp3"

    def test_detects_mp3_input_from_magic_bytes(self, tmp_path, monkeypatch):
        """Line 674: ID3-prefixed audio → suffix='.mp3' for temp file."""
        archive_dir, clips_dir = self._setup(tmp_path, monkeypatch)
        def fake_run(*args, **kwargs):
            r = MagicMock(); r.returncode = 0
            for s in (args[0] if args else []):
                p = Path(str(s))
                if p.suffix in (".flac", ".mp3"):
                    p.write_bytes(b"fake")
            return r
        with patch("subprocess.run", side_effect=fake_run):
            mp3_input = b"ID3\x03\x00\x00" + b"\x00" * 100
            ae_mod.archive_and_transcode(mp3_input, "7-jane-doe")

    def test_finally_oserrror_on_tmp_unlink_swallowed(self, tmp_path, monkeypatch):
        """Lines 723-724: tmp_path.unlink() raises OSError in finally → swallowed."""
        archive_dir, clips_dir = self._setup(tmp_path, monkeypatch)
        def fake_run(*args, **kwargs):
            r = MagicMock(); r.returncode = 0
            for s in (args[0] if args else []):
                p = Path(str(s))
                if p.suffix in (".flac", ".mp3"):
                    p.write_bytes(b"fake")
            return r
        # Patch Path.unlink to raise OSError (simulates already-deleted temp file)
        original_unlink = Path.unlink
        calls = [0]
        def patched_unlink(self_, *args, **kwargs):
            calls[0] += 1
            if calls[0] == 1:
                raise OSError("no such file")
            return original_unlink(self_, *args, **kwargs)
        with patch("subprocess.run", side_effect=fake_run):
            with patch.object(Path, "unlink", patched_unlink):
                # Should NOT raise — OSError swallowed in finally
                ae_mod.archive_and_transcode(b"fake_audio", "7-jane-doe")


# ---------------------------------------------------------------------------
# render_player_audio (lines 736-794)
# ---------------------------------------------------------------------------

def _setup_render_env(tmp_path, monkeypatch):
    """Set up a minimal announcer roster environment for render tests."""
    announcer_dir = tmp_path / "announcer"
    archive_dir = announcer_dir / "archive"
    clips_dir = announcer_dir / "clips"
    for d in (archive_dir, clips_dir):
        d.mkdir(parents=True)
    roster_file = announcer_dir / "roster.json"
    roster = [{
        "id": "7-jane-doe", "first": "Jane", "last": "Doe",
        "number": "7", "phonetic_hint": "", "tts_instruction": "",
        "status": "pending", "is_active": True,
        "announcer_audio_url": "", "rendered_at": "", "error_message": "",
    }]
    roster_file.write_text(json.dumps(roster))
    monkeypatch.setattr(ae_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ae_mod, "ANNOUNCER_DIR", announcer_dir)
    monkeypatch.setattr(ae_mod, "CLIPS_DIR", clips_dir)
    monkeypatch.setattr(ae_mod, "ARCHIVE_DIR", archive_dir)
    monkeypatch.setattr(ae_mod, "ROSTER_FILE", roster_file)
    return roster_file


class TestRenderPlayerAudio:
    def test_raises_when_player_not_found(self, tmp_path, monkeypatch):
        """Line 738: unknown player_id → ValueError."""
        _setup_render_env(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="not found"):
            ae_mod.render_player_audio("99-nobody")

    def test_quick_render_saves_raw_mp3(self, tmp_path, monkeypatch):
        """Lines 768-775: quality='quick' saves raw bytes, no archive."""
        _setup_render_env(tmp_path, monkeypatch)
        mock_provider = MagicMock()
        mock_provider.synthesize.return_value = b"raw_audio"
        mock_provider.name = "mock"
        monkeypatch.setattr(ae_mod, "get_quick_tts_provider", lambda: mock_provider)
        monkeypatch.setattr(ae_mod, "get_tts_provider", lambda: mock_provider)
        result = ae_mod.render_player_audio("7-jane-doe", quality="quick")
        assert result["status"] == "ready"
        assert "/announcer-clips/" in result["announcer_audio_url"]

    def test_best_render_falls_back_when_ffmpeg_absent(self, tmp_path, monkeypatch):
        """Lines 757-766: best quality + archive fails → raw bytes saved."""
        _setup_render_env(tmp_path, monkeypatch)
        mock_provider = MagicMock()
        mock_provider.synthesize.return_value = b"best_audio"
        mock_provider.name = "mock"
        monkeypatch.setattr(ae_mod, "get_tts_provider", lambda: mock_provider)
        monkeypatch.setattr(ae_mod, "archive_and_transcode",
                            MagicMock(side_effect=RuntimeError("ffmpeg not found")))
        result = ae_mod.render_player_audio("7-jane-doe", quality="best")
        assert result["status"] == "ready"

    def test_best_render_with_archive_success(self, tmp_path, monkeypatch):
        """Lines 752-756: best quality + archive succeeds → mp3_path used."""
        _setup_render_env(tmp_path, monkeypatch)
        mock_provider = MagicMock()
        mock_provider.synthesize.return_value = b"best_audio"
        mock_provider.name = "mock"
        fake_mp3 = tmp_path / "out.mp3"
        fake_mp3.write_bytes(b"mp3")
        monkeypatch.setattr(ae_mod, "get_tts_provider", lambda: mock_provider)
        monkeypatch.setattr(ae_mod, "archive_and_transcode",
                            MagicMock(return_value=(tmp_path / "out.flac", fake_mp3)))
        result = ae_mod.render_player_audio("7-jane-doe", quality="best")
        assert result["status"] == "ready"

    def test_synthesize_exception_sets_error_status(self, tmp_path, monkeypatch):
        """Lines 788-794: synthesize raises → player status='error', re-raised."""
        _setup_render_env(tmp_path, monkeypatch)
        mock_provider = MagicMock()
        mock_provider.synthesize.side_effect = RuntimeError("TTS boom")
        mock_provider.name = "mock"
        monkeypatch.setattr(ae_mod, "get_tts_provider", lambda: mock_provider)
        with pytest.raises(RuntimeError, match="TTS boom"):
            ae_mod.render_player_audio("7-jane-doe", quality="best")
        # player should be marked error
        roster = json.loads(ae_mod.ROSTER_FILE.read_text())
        assert roster[0]["status"] == "error"

    def test_oversized_audio_raises(self, tmp_path, monkeypatch):
        """Lines 748-749: audio > MAX_TTS_OUTPUT_BYTES → RuntimeError."""
        _setup_render_env(tmp_path, monkeypatch)
        mock_provider = MagicMock()
        # Return bytes larger than the 10MB cap
        mock_provider.synthesize.return_value = b"x" * (ae_mod.MAX_TTS_OUTPUT_BYTES + 1)
        mock_provider.name = "mock"
        monkeypatch.setattr(ae_mod, "get_tts_provider", lambda: mock_provider)
        with pytest.raises(RuntimeError, match="TTS output too large"):
            ae_mod.render_player_audio("7-jane-doe", quality="best")


# ---------------------------------------------------------------------------
# render_all_pending (lines 799-811)
# ---------------------------------------------------------------------------

class TestRenderAllPending:
    def test_returns_empty_summary_when_no_active(self, tmp_path, monkeypatch):
        """Lines 800-801: no active players → total=0."""
        _setup_render_env(tmp_path, monkeypatch)
        # Mark the player as already ready
        ae_mod.update_player("7-jane-doe", {"status": "ready", "wrap_version": ae_mod.STADIUM_WRAP_VERSION})
        result = ae_mod.render_all_pending()
        assert result["total"] == 0
        assert result["success"] == 0

    def test_counts_success_and_failures(self, tmp_path, monkeypatch):
        """Lines 803-809: success incremented on success, failed on exception."""
        roster_file = _setup_render_env(tmp_path, monkeypatch)
        # Add a second player
        roster = json.loads(roster_file.read_text())
        roster.append({
            "id": "8-sara-smith", "first": "Sara", "last": "Smith",
            "number": "8", "phonetic_hint": "", "tts_instruction": "",
            "status": "pending", "is_active": True,
            "announcer_audio_url": "", "rendered_at": "", "error_message": "",
        })
        roster_file.write_text(json.dumps(roster))

        call_n = [0]
        def fake_render(player_id, game_context=None, quality="best"):
            call_n[0] += 1
            if player_id == "8-sara-smith":
                raise RuntimeError("render failed")
            ae_mod.update_player(player_id, {"status": "ready"})
            return ae_mod.get_player_by_id(player_id)

        monkeypatch.setattr(ae_mod, "render_player_audio", fake_render)
        result = ae_mod.render_all_pending()
        assert result["total"] == 2
        assert result["success"] == 1
        assert result["failed"] == 1
        assert len(result["errors"]) == 1


# ---------------------------------------------------------------------------
# get_roster_stats (lines 816-823)
# ---------------------------------------------------------------------------

class TestGetRosterStats:
    def test_returns_correct_counts(self, tmp_path, monkeypatch):
        """Lines 816-823: summary counts match roster state."""
        _setup_render_env(tmp_path, monkeypatch)
        # roster has one pending player
        result = ae_mod.get_roster_stats()
        assert isinstance(result, dict)
        assert result["total"] == 1
        assert result["pending"] == 1
        assert result["ready"] == 0
        assert result["error"] == 0

    def test_inactive_player_excluded(self, tmp_path, monkeypatch):
        """Line 817: is_active=False → excluded from counts."""
        roster_file = _setup_render_env(tmp_path, monkeypatch)
        roster = json.loads(roster_file.read_text())
        roster[0]["is_active"] = False
        roster_file.write_text(json.dumps(roster))
        result = ae_mod.get_roster_stats()
        assert result["total"] == 0


# ---------------------------------------------------------------------------
# Council 2026-09-15 — regressions for the Fall 2026 announcer hardening
# ---------------------------------------------------------------------------

class TestAnnouncerVoiceDefault:
    def test_default_voice_is_not_the_female_premade(self):
        """EXAVITQu4vr4xnSDxMaL is ElevenLabs "Sarah" — wrong for a stadium announcer."""
        assert ae_mod.ANNOUNCER_ELEVENLABS_VOICE_ID != "EXAVITQu4vr4xnSDxMaL"

    def test_elevenlabs_outranks_style_less_providers(self, monkeypatch):
        monkeypatch.delenv("LOCAL_TTS_URL", raising=False)
        monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
        monkeypatch.delenv("ANNOUNCER_VOICE_REF_URL", raising=False)
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el_fakekey")
        monkeypatch.setitem(sys.modules, "sync_daemon", None)
        chain = [p.name for p in ae_mod._build_provider_chain()]
        assert chain.index("elevenlabs") < chain.index("edge_tts")


class TestNumberToWord:
    @pytest.mark.parametrize("raw,spoken", [
        ("0", "zero"), ("00", "double-zero"), ("7", "seven"), ("13", "thirteen"),
        ("15", "fifteen"), ("18", "eighteen"), ("25", "twenty-five"),
        ("31", "thirty-one"), ("67", "sixty-seven"), ("99", "ninety-nine"),
        ("20", "twenty"), ("40", "forty"),
    ])
    def test_every_live_jersey_number_is_spoken(self, raw, spoken):
        assert ae_mod._number_to_word(raw) == spoken

    @pytest.mark.parametrize("raw", ["", "TBD", "100"])
    def test_non_jersey_input_passes_through(self, raw):
        assert ae_mod._number_to_word(raw) == raw


class TestStadiumWrapFiltergraph:
    def test_filtergraph_is_accepted_by_ffmpeg(self, tmp_path):
        """The graph used to carry two syntax errors, so every best-quality
        render silently fell back to unprocessed bytes."""
        import shutil, subprocess
        if not shutil.which("ffmpeg"):
            pytest.skip("ffmpeg not installed")
        src = tmp_path / "in.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
             "-i", "sine=frequency=200:duration=1", str(src)], check=True)
        flac, mp3 = ae_mod.archive_and_transcode(src.read_bytes(), "test-player")
        assert flac.exists() and mp3.exists()
        assert mp3.stat().st_size > 0


class TestReconcileRosterWithTeam:
    def test_adds_new_players_and_deactivates_departed(self, monkeypatch):
        team = [
            {"id": "1-new-player", "first": "New", "last": "Player", "number": "1",
             "phonetic_hint": "", "tts_instruction": "", "walkup_song_url": "",
             "intro_timestamp": 5.0, "announcer_audio_url": "", "status": "pending",
             "is_active": True, "rendered_at": "", "error_message": ""},
        ]
        monkeypatch.setattr(ae_mod, "_bootstrap_roster_from_team", lambda: team)
        existing = [{"id": "9-old-player", "is_active": True, "status": "ready",
                     "phonetic_hint": "OLD-ee", "announcer_audio_url": "/clip.mp3"}]
        roster, changed = ae_mod.reconcile_roster_with_team(existing)
        assert changed
        by_id = {p["id"]: p for p in roster}
        assert by_id["1-new-player"]["is_active"] is True
        assert by_id["9-old-player"]["is_active"] is False
        # departed players keep their work — deactivated, never deleted
        assert by_id["9-old-player"]["phonetic_hint"] == "OLD-ee"
        assert by_id["9-old-player"]["announcer_audio_url"] == "/clip.mp3"

    def test_no_team_data_leaves_roster_untouched(self, monkeypatch):
        monkeypatch.setattr(ae_mod, "_bootstrap_roster_from_team", lambda: [])
        existing = [{"id": "9-old-player", "is_active": True}]
        roster, changed = ae_mod.reconcile_roster_with_team(existing)
        assert changed is False
        assert roster == existing


class TestConcurrentRosterUpdates:
    def test_parallel_updates_do_not_lose_writes(self, tmp_path, monkeypatch):
        """Unlocked read-modify-write dropped statuses under --concurrency 2-4."""
        from concurrent.futures import ThreadPoolExecutor
        roster_file = tmp_path / "roster.json"
        players = [{"id": f"p{i}", "is_active": True, "status": "pending"} for i in range(10)]
        roster_file.write_text(json.dumps(players), encoding="utf-8")
        monkeypatch.setattr(ae_mod, "ROSTER_FILE", roster_file)
        monkeypatch.setattr(ae_mod, "_bootstrap_roster_from_team", lambda: [])
        monkeypatch.setattr(ae_mod, "_ensure_dirs", lambda: None)

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda p: ae_mod.update_player(
                p["id"], {"status": "ready", "wrap_version": ae_mod.STADIUM_WRAP_VERSION}), players))

        final = json.loads(roster_file.read_text(encoding="utf-8"))
        assert [p["status"] for p in final] == ["ready"] * 10


# ---------------------------------------------------------------------------
# Second pass 2026-09-15 — web render path (gunicorn, 2 workers)
# ---------------------------------------------------------------------------

class TestRosterLockCrossProcess:
    def test_lock_is_reentrant(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ae_mod, "ROSTER_FILE", tmp_path / "roster.json")
        with ae_mod._ROSTER_LOCK:
            with ae_mod._ROSTER_LOCK:
                pass  # must not deadlock

    def test_lock_blocks_a_second_process(self, tmp_path, monkeypatch):
        """A thread lock alone let two gunicorn workers clobber roster.json."""
        import subprocess, time
        roster = tmp_path / "roster.json"
        sentinel = tmp_path / "held"
        monkeypatch.setattr(ae_mod, "ROSTER_FILE", roster)
        repo = str(Path(ae_mod.__file__).resolve().parents[1])
        child = subprocess.Popen([sys.executable, "-c", (
            "import sys, time, pathlib\n"
            f"sys.path.insert(0, {repo!r})\n"
            "import tools.announcer_engine as ae\n"
            f"ae.ROSTER_FILE = pathlib.Path({str(roster)!r})\n"
            "with ae._ROSTER_LOCK:\n"
            f"    pathlib.Path({str(sentinel)!r}).write_text('held')\n"
            "    time.sleep(1.5)\n"
        )])
        try:
            deadline = time.monotonic() + 10
            while not sentinel.exists():
                assert time.monotonic() < deadline, "child never took the lock"
                time.sleep(0.05)
            t0 = time.monotonic()
            with ae_mod._ROSTER_LOCK:
                waited = time.monotonic() - t0
        finally:
            child.wait(timeout=10)
        assert waited >= 0.8, f"parent acquired the lock after only {waited:.2f}s — not held across processes"


class TestQuickRenderGetsStadiumWrap:
    def _setup(self, tmp_path, monkeypatch):
        roster = tmp_path / "roster.json"
        roster.write_text(json.dumps([{"id": "p1", "first": "A", "last": "B", "number": "1",
                                       "is_active": True, "status": "pending"}]), encoding="utf-8")
        monkeypatch.setattr(ae_mod, "ROSTER_FILE", roster)
        monkeypatch.setattr(ae_mod, "CLIPS_DIR", tmp_path / "clips")
        monkeypatch.setattr(ae_mod, "_bootstrap_roster_from_team", lambda: [])
        monkeypatch.setattr(ae_mod, "_ensure_dirs", lambda: None)
        monkeypatch.setattr(ae_mod, "get_quick_tts_provider", lambda: MockTTS())
        monkeypatch.setattr(ae_mod, "get_tts_provider", lambda: MockTTS())
        wrap = MagicMock(return_value=(None, tmp_path / "clips" / "p1" / "x.mp3"))
        monkeypatch.setattr(ae_mod, "archive_and_transcode", wrap)
        return wrap

    def test_quick_wraps_without_archive(self, tmp_path, monkeypatch):
        wrap = self._setup(tmp_path, monkeypatch)
        ae_mod.render_player_audio("p1", quality="quick")
        wrap.assert_called_once()
        assert wrap.call_args.kwargs["archive"] is False

    def test_best_wraps_with_archive(self, tmp_path, monkeypatch):
        wrap = self._setup(tmp_path, monkeypatch)
        ae_mod.render_player_audio("p1", quality="best")
        assert wrap.call_args.kwargs["archive"] is True

    def test_archive_false_writes_no_flac(self, tmp_path, monkeypatch):
        import shutil, subprocess
        if not shutil.which("ffmpeg"):
            pytest.skip("ffmpeg not installed")
        monkeypatch.setattr(ae_mod, "CLIPS_DIR", tmp_path / "clips")
        monkeypatch.setattr(ae_mod, "ARCHIVE_DIR", tmp_path / "archive")
        src = tmp_path / "in.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                        "-i", "sine=frequency=200:duration=1", str(src)], check=True)
        flac, mp3 = ae_mod.archive_and_transcode(src.read_bytes(), "p1", archive=False)
        assert flac is None
        assert mp3.exists() and mp3.stat().st_size > 0
        assert not (tmp_path / "archive").exists()


# ---------------------------------------------------------------------------
# Halo-quality pass: ElevenLabs pauses, Stadium Wrap v2, stale-render marking
# ---------------------------------------------------------------------------

class TestElevenLabsPauses:
    def test_pause_tags_become_break_elements(self):
        out = ae_mod._tags_to_elevenlabs("[breath] Now batting... [pause:0.7s] NUMBEEEER seven... [pause:0.5s] Ember!")
        assert out == 'Now batting... <break time="0.7s" /> NUMBEEEER seven... <break time="0.5s" /> Ember!'

    def test_breaks_are_capped_at_three_seconds_and_unknown_tags_dropped(self):
        out = ae_mod._tags_to_elevenlabs("[pause:9s] go [whatever] now")
        assert out == '<break time="3.0s" /> go now'

    def test_text_for_provider_routes_by_provider(self):
        raw = "[breath] Now... [pause:0.7s] seven"
        assert ae_mod.text_for_provider(ae_mod.EdgeTTSProvider(), raw) == raw
        assert "<break" in ae_mod.text_for_provider(ae_mod.ElevenLabsTTS(), raw)
        plain = ae_mod.text_for_provider(ae_mod.MockTTS(), raw)
        assert "[" not in plain and "<" not in plain

    def test_render_sends_breaks_to_elevenlabs(self, tmp_path, monkeypatch):
        """The walk-up script's beats must reach ElevenLabs as <break/> tags,
        not be stripped to nothing."""
        monkeypatch.setattr(ae_mod, "ROSTER_FILE", tmp_path / "roster.json")
        monkeypatch.setattr(ae_mod, "CLIPS_DIR", tmp_path / "clips")
        monkeypatch.setattr(ae_mod, "ARCHIVE_DIR", tmp_path / "archive")
        monkeypatch.setattr(ae_mod, "ANNOUNCER_DIR", tmp_path)
        monkeypatch.setattr(ae_mod, "_bootstrap_roster_from_team", lambda: [])
        ae_mod._atomic_write_json(tmp_path / "roster.json", [
            {"id": "7-ember-h", "first": "Ember", "last": "H", "number": "7",
             "is_active": True, "status": "pending"},
        ])
        captured = {}

        class _EL(ae_mod.ElevenLabsTTS):
            def synthesize(self, text, voice_config):
                captured["text"] = text
                return b"\xff\xfb" + b"\x00" * 100

        monkeypatch.setattr(ae_mod, "get_tts_provider", lambda: _EL())
        monkeypatch.setattr(ae_mod, "archive_and_transcode",
                            lambda audio, pid, **kw: (None, (tmp_path / "clips" / pid).mkdir(parents=True, exist_ok=True) or (tmp_path / "clips" / pid / "x.mp3")))
        (tmp_path / "clips" / "7-ember-h").mkdir(parents=True, exist_ok=True)
        (tmp_path / "clips" / "7-ember-h" / "x.mp3").write_bytes(b"x")
        updated = ae_mod.render_player_audio("7-ember-h")
        assert '<break time="0.7s" />' in captured["text"]
        assert '<break time="0.5s" />' in captured["text"]
        assert "[pause" not in captured["text"] and "[breath]" not in captured["text"]
        assert updated["wrap_version"] == ae_mod.STADIUM_WRAP_VERSION

    def test_output_format_is_requested(self, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_API_KEY", "el_fake")
        monkeypatch.setenv("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_192")
        captured = {}

        class _Resp:
            status_code = 200
            content = b"a"
            headers = {}

        def _post(url, json=None, headers=None, timeout=None):
            captured["url"] = url
            return _Resp()

        monkeypatch.setattr(ae_mod.requests, "post", _post)
        ae_mod.ElevenLabsTTS().synthesize("hi", {})
        assert captured["url"].endswith("?output_format=mp3_44100_192")


class TestStaleRenderMarking:
    def _roster(self):
        return [
            {"id": "a", "status": "ready", "is_active": True, "announcer_audio_url": "/c/a.mp3"},
            {"id": "b", "status": "ready", "is_active": True, "wrap_version": ae_mod.STADIUM_WRAP_VERSION},
            {"id": "c", "status": "ready", "is_active": False},
            {"id": "d", "status": "error", "is_active": True},
        ]

    def test_only_active_ready_clips_from_older_chain_go_pending(self):
        roster = self._roster()
        assert ae_mod._mark_stale_renders(roster) is True
        by = {p["id"]: p for p in roster}
        assert by["a"]["status"] == "pending"
        assert by["a"]["announcer_audio_url"] == "/c/a.mp3"   # playback keeps working
        assert by["b"]["status"] == "ready"
        assert by["c"]["status"] == "ready"
        assert by["d"]["status"] == "error"

    def test_idempotent_once_current(self):
        roster = [{"id": "b", "status": "ready", "is_active": True, "wrap_version": ae_mod.STADIUM_WRAP_VERSION}]
        assert ae_mod._mark_stale_renders(roster) is False

    def test_load_roster_persists_the_flag_and_counts_as_pending(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ae_mod, "ROSTER_FILE", tmp_path / "roster.json")
        monkeypatch.setattr(ae_mod, "ANNOUNCER_DIR", tmp_path)
        monkeypatch.setattr(ae_mod, "CLIPS_DIR", tmp_path / "clips")
        monkeypatch.setattr(ae_mod, "ARCHIVE_DIR", tmp_path / "archive")
        monkeypatch.setattr(ae_mod, "_bootstrap_roster_from_team", lambda: [])
        ae_mod._atomic_write_json(tmp_path / "roster.json", [
            {"id": "a", "status": "ready", "is_active": True, "announcer_audio_url": "/c/a.mp3"},
        ])
        roster = ae_mod.load_announcer_roster()
        assert roster[0]["status"] == "pending"
        assert ae_mod._read_json(tmp_path / "roster.json")[0]["status"] == "pending"
        assert ae_mod.get_roster_stats()["pending"] == 1

    def test_voice_sample_cache_is_versioned(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ae_mod, "VOICE_SAMPLES_DIR", tmp_path / "samples")
        (tmp_path / "samples").mkdir()
        (tmp_path / "samples" / "halo.mp3").write_bytes(b"old" * 1000)   # v1 cache must not be served
        calls = []

        class _P(ae_mod.TTSProvider):
            name = "fake"
            def synthesize(self, text, voice_config):
                calls.append(text)
                return b"x" * 2000

        monkeypatch.setattr(ae_mod, "get_tts_provider", lambda: _P())
        monkeypatch.setattr(ae_mod, "archive_and_transcode",
                            lambda audio, pid, **kw: (None, kw["out_mp3"].write_bytes(audio) and kw["out_mp3"]))
        out = ae_mod.render_voice_sample("halo")
        assert out.name == f"halo.v{ae_mod.STADIUM_WRAP_VERSION}.mp3"
        assert len(calls) == 1


class TestStadiumWrapQuality:
    """Measured contract for the chain: stereo tail, kept dynamics, fixed
    loudness, 192 kbps.  v1 failed the first three; v2 failed the stereo one
    in production (it passed here only because CI had no ffmpeg to run it)."""

    def _measure(self, mp3):
        import json, subprocess
        probe = json.loads(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=bit_rate:stream=channels",
             "-of", "json", str(mp3)], capture_output=True, text=True).stdout)
        log = subprocess.run(
            ["ffmpeg", "-v", "info", "-i", str(mp3), "-af", "ebur128", "-f", "null", "-"],
            capture_output=True, text=True).stderr
        summary = log[log.rfind("Summary"):]
        lufs = float(re.search(r"I:\s+(-?[\d.]+) LUFS", summary).group(1))
        lra = float(re.search(r"LRA:\s+([\d.]+) LU", summary).group(1))
        pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp3), "-f", "s16le", "-ac", "2", "-"],
                             capture_output=True).stdout
        import struct
        n = len(pcm) // 4
        side = 0
        for i in range(0, n * 4, 4 * 50):
            l, r = struct.unpack_from("<hh", pcm, i)
            side += abs(l - r)
        return {"channels": probe["streams"][0]["channels"],
                "bit_rate": int(probe["format"]["bit_rate"]),
                "lufs": lufs, "lra": lra, "side": side}

    def test_chain_output_meets_the_contract(self, tmp_path, monkeypatch):
        import shutil, subprocess
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            pytest.skip("ffmpeg not installed")
        monkeypatch.setattr(ae_mod, "CLIPS_DIR", tmp_path / "clips")
        monkeypatch.setattr(ae_mod, "ARCHIVE_DIR", tmp_path / "archive")
        src = tmp_path / "in.wav"
        # Speech-like source: a voiced tone that alternates loud and quiet in
        # 3 s blocks (EBU LRA is measured over 3 s windows), so there is
        # dynamic range for the chain to preserve.
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
             "aevalsrc=sin(2*PI*180*t)*(0.12+0.85*mod(floor(t/3)\\,2)):d=12:s=44100",
             str(src)], check=True)
        _, mp3 = ae_mod.archive_and_transcode(src.read_bytes(), "contract", archive=False,
                                              pitch_semitones=-2.0, out_mp3=tmp_path / "out.mp3")
        m = self._measure(mp3)
        assert m["channels"] == 2
        assert m["bit_rate"] >= 180_000, m
        assert -18.0 <= m["lufs"] <= -14.0, m       # loudnorm target -16 LUFS
        assert m["lra"] >= 2.5, m                    # dynamics survive (v1: 1.0 LU)
        assert m["side"] > 0, m                      # a real stereo tail (v1: mono)



# ---------------------------------------------------------------------------
# v3: no amix in the chain, spoken names, players with no jersey number
# ---------------------------------------------------------------------------

class TestChainNeverMixesMono:
    """amix negotiates one channel layout across its inputs, so a mono leg
    drags the whole mix to mono and silently throws away the stereo built
    upstream.  That is how v2 shipped mono clips to the Pi."""

    def _filtergraph(self, monkeypatch, tmp_path, **kw):
        captured = {}

        class _Res:
            returncode = 0
            stderr = b""

        def _run(cmd, **kwargs):
            if "-filter_complex" in cmd:
                captured["graph"] = cmd[cmd.index("-filter_complex") + 1]
            out = Path(cmd[-1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"x" * 64)
            return _Res()

        monkeypatch.setattr(ae_mod.subprocess if hasattr(ae_mod, "subprocess") else __import__("subprocess"),
                            "run", _run, raising=False)
        import subprocess as _sp
        monkeypatch.setattr(_sp, "run", _run)
        monkeypatch.setattr(ae_mod, "CLIPS_DIR", tmp_path / "clips")
        monkeypatch.setattr(ae_mod, "ARCHIVE_DIR", tmp_path / "archive")
        ae_mod.archive_and_transcode(b"RIFFfake", "p", archive=False,
                                     out_mp3=tmp_path / "o.mp3", **kw)
        return captured["graph"]

    def test_graph_contains_no_amix(self, monkeypatch, tmp_path):
        graph = self._filtergraph(monkeypatch, tmp_path)
        assert "amix" not in graph, graph

    def test_graph_joins_two_legs_into_stereo(self, monkeypatch, tmp_path):
        graph = self._filtergraph(monkeypatch, tmp_path)
        assert "join=inputs=2:channel_layout=stereo" in graph
        # The two legs must differ, or join produces two identical channels
        # and the output is mono in everything but the channel count.
        left = graph.split("[la]")[1].split("[left]")[0]
        right = graph.split("[ra]")[1].split("[right]")[0]
        assert left != right, (left, right)

    def test_pitch_stage_still_applied(self, monkeypatch, tmp_path):
        graph = self._filtergraph(monkeypatch, tmp_path, pitch_semitones=-2.0)
        assert "asetrate=" in graph and "atempo=" in graph


class TestSpokenName:
    @pytest.mark.parametrize("first,last,expected", [
        ("Ava", "W", "Ava"),              # GameChanger privacy abbreviation
        ("Addy", "A", "Addy"),
        ("Brielle", "P.", "Brielle"),     # initial with a full stop
        ("Ember", "Hourahan", "Ember Hourahan"),
        ("Leila", "VanDeusen", "Leila VanDeusen"),
        ("Amelia", "", "Amelia"),
        ("", "Hourahan", "Hourahan"),
    ])
    def test_initials_are_dropped_real_surnames_kept(self, first, last, expected):
        assert ae_mod._spoken_name(first, last) == expected

    def test_phonetic_hint_still_wins(self):
        player = {"first": "Ava", "last": "W", "number": "28",
                  "phonetic_hint": "AY-vuh Dubs"}
        assert "AY-vuh Dubs" in ae_mod.build_announcement_text(player)


class TestPlayerWithNoJerseyNumber:
    """A blank number used to render the word "NUMBEEEER" followed by nothing."""

    def _say(self, player, ctx=None):
        return ae_mod._tags_to_elevenlabs(ae_mod.build_announcement_text(player, ctx))

    def test_standard_walkup_omits_the_number_call(self):
        said = self._say({"first": "Amelia", "last": "", "number": ""})
        assert "NUMBEEEER" not in said
        assert said.endswith("Amelia!")

    def test_numbered_player_still_gets_the_number_call(self):
        said = self._say({"first": "Lexi", "last": "McKinney", "number": "99"})
        assert "NUMBEEEER ninety-nine" in said

    def test_bases_loaded_and_high_stakes_omit_it_too(self):
        p = {"first": "Amelia", "last": "", "number": ""}
        loaded = self._say(p, {"bases": [True, True, True], "outs": 1})
        clutch = self._say(p, {"bases": [True, True, True], "outs": 2})
        assert "NUMBEEEER" not in loaded and loaded.endswith("Amelia!")
        assert "NUMBEEEER" not in clutch and clutch.endswith("Amelia!")

    def test_achievement_call_omits_the_number_credit(self):
        said = self._say({"first": "Amelia", "last": "", "number": ""},
                         {"achievement": "grand_slam"})
        assert "number" not in said.lower()
        assert said.endswith("Amelia!")

    def test_achievement_call_keeps_it_when_numbered(self):
        said = self._say({"first": "Ruby", "last": "VanDeusen", "number": "67"},
                         {"achievement": "grand_slam"})
        assert "number sixty-seven" in said
