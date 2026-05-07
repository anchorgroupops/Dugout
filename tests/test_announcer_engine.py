"""Tests for tools/announcer_engine.py — pure logic, security helpers, MockTTS."""
from __future__ import annotations

import json
import os

import pytest

import tools.announcer_engine as ae_mod
from tools.announcer_engine import (
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
        provider = get_tts_provider()
        assert isinstance(provider, MockTTS)

    def test_quick_returns_mock_when_no_env_vars(self, monkeypatch):
        monkeypatch.delenv("LOCAL_TTS_URL", raising=False)
        monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        monkeypatch.delenv("ANNOUNCER_VOICE_REF_URL", raising=False)
        provider = get_quick_tts_provider()
        assert isinstance(provider, MockTTS)


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

class TestLoadVoiceProfiles:
    def test_returns_list_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ae_mod, "VOICE_PROFILES_FILE", tmp_path / "vp.json")
        result = load_voice_profiles()
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_returns_default_when_file_empty(self, tmp_path, monkeypatch):
        vp_file = tmp_path / "vp.json"
        vp_file.write_text("[]")
        monkeypatch.setattr(ae_mod, "VOICE_PROFILES_FILE", vp_file)
        result = load_voice_profiles()
        assert isinstance(result, list)

    def test_returns_profiles_from_file(self, tmp_path, monkeypatch):
        profiles = [{"name": "Custom", "is_default": True}]
        vp_file = tmp_path / "vp.json"
        vp_file.write_text(json.dumps(profiles))
        monkeypatch.setattr(ae_mod, "VOICE_PROFILES_FILE", vp_file)
        result = load_voice_profiles()
        assert result[0]["name"] == "Custom"


class TestGetDefaultVoiceProfile:
    def test_returns_dict(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ae_mod, "VOICE_PROFILES_FILE", tmp_path / "vp.json")
        result = get_default_voice_profile()
        assert isinstance(result, dict)

    def test_returns_profile_marked_default(self, tmp_path, monkeypatch):
        profiles = [
            {"name": "NonDefault", "is_default": False},
            {"name": "TheDefault", "is_default": True},
        ]
        vp_file = tmp_path / "vp.json"
        vp_file.write_text(json.dumps(profiles))
        monkeypatch.setattr(ae_mod, "VOICE_PROFILES_FILE", vp_file)
        result = get_default_voice_profile()
        assert result["name"] == "TheDefault"

    def test_fallback_when_no_default_marked(self, tmp_path, monkeypatch):
        profiles = [{"name": "NoDefault", "is_default": False}]
        vp_file = tmp_path / "vp.json"
        vp_file.write_text(json.dumps(profiles))
        monkeypatch.setattr(ae_mod, "VOICE_PROFILES_FILE", vp_file)
        result = get_default_voice_profile()
        assert isinstance(result, dict)


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
