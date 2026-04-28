"""Tests for tools/announcer_engine.py — pure logic, security helpers, MockTTS."""
from __future__ import annotations

import os

import pytest

from tools.announcer_engine import (
    MockTTS,
    _apply_phonetics,
    _number_to_word,
    _sanitize_player_id,
    build_situational_announcement,
    get_tts_provider,
    get_quick_tts_provider,
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
