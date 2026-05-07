"""Tests for pure utility functions in tools/memory_engine.py.

The MemoryEngine class requires live API keys and is NOT instantiated here.
Only the four module-level helpers are tested:
  _safe_id, _canonical_json, _content_hash, _flatten_metadata
"""
from __future__ import annotations

import hashlib
import json
import sys
import unittest.mock as mock
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Import setup — patch heavy third-party modules before memory_engine loads
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
sys.modules.setdefault("google.generativeai", mock.MagicMock())
sys.modules.setdefault("pinecone", mock.MagicMock())

from memory_engine import (  # noqa: E402  (import after sys.modules patch)
    _canonical_json,
    _content_hash,
    _flatten_metadata,
    _safe_id,
)


# ===========================================================================
# TestSafeId
# ===========================================================================

class TestSafeId:
    def test_normal_alphanumeric_passes_through(self):
        assert _safe_id("game123") == "game123"

    def test_colons_kept(self):
        assert _safe_id("game::2024-05-01") == "game::2024-05-01"

    def test_hyphens_kept(self):
        assert _safe_id("sharks-vs-tigers") == "sharks-vs-tigers"

    def test_underscores_kept(self):
        assert _safe_id("player_jane_doe") == "player_jane_doe"

    def test_dots_kept(self):
        assert _safe_id("file.json") == "file.json"

    def test_forward_slash_kept(self):
        # forward slash is in the allowed set [a-zA-Z0-9:_\-./]
        assert _safe_id("path/to/file") == "path/to/file"

    def test_spaces_replaced_with_underscore(self):
        result = _safe_id("hello world")
        assert " " not in result
        assert "_" in result

    def test_special_chars_stripped(self):
        # @ # $ % are not in the allowed set
        result = _safe_id("game@2024#playoffs!")
        assert "@" not in result
        assert "#" not in result
        assert "!" not in result

    def test_empty_string_returns_unknown(self):
        assert _safe_id("") == "unknown"

    def test_none_returns_unknown(self):
        assert _safe_id(None) == "unknown"

    def test_whitespace_only_returns_unknown(self):
        # strip() turns "   " into "", then re.sub leaves it empty → "unknown"
        assert _safe_id("   ") == "unknown"

    def test_truncated_at_256_chars(self):
        long_input = "a" * 300
        result = _safe_id(long_input)
        assert len(result) == 256

    def test_exactly_256_chars_not_truncated(self):
        exact = "b" * 256
        result = _safe_id(exact)
        assert len(result) == 256
        assert result == exact

    def test_leading_dot_preserved(self):
        # dot is in the allowed set
        result = _safe_id(".hidden")
        assert result.startswith(".")

    def test_mixed_valid_and_invalid_chars(self):
        result = _safe_id("abc!def@ghi")
        # valid chars stay; invalid chars become underscore
        assert result == "abc_def_ghi"

    def test_all_special_chars_produces_underscores(self):
        result = _safe_id("!!!###")
        assert all(c == "_" for c in result)

    def test_all_special_chars_then_empty_after_strip_unknown(self):
        # If the raw value is only whitespace → stripped → empty → "unknown"
        assert _safe_id("   \t\n   ") == "unknown"


# ===========================================================================
# TestCanonicalJson
# ===========================================================================

class TestCanonicalJson:
    def test_keys_are_sorted(self):
        data = {"z": 1, "a": 2, "m": 3}
        result = _canonical_json(data)
        parsed = json.loads(result)
        assert list(parsed.keys()) == sorted(parsed.keys())

    def test_no_extra_whitespace(self):
        result = _canonical_json({"key": "value"})
        assert " " not in result

    def test_no_spaces_after_colon(self):
        result = _canonical_json({"k": "v"})
        assert ": " not in result

    def test_no_spaces_after_comma(self):
        result = _canonical_json({"a": 1, "b": 2})
        assert ", " not in result

    def test_nested_dict_is_stable(self):
        data = {"outer": {"z": 9, "a": 1}}
        result = _canonical_json(data)
        # Nested keys should also be sorted
        assert result == '{"outer":{"a":1,"z":9}}'

    def test_list_preserved_in_order(self):
        data = {"items": [3, 1, 2]}
        result = _canonical_json(data)
        assert '"items":[3,1,2]' in result

    def test_string_value_preserved(self):
        result = _canonical_json({"name": "sharks"})
        assert '"name":"sharks"' in result

    def test_integer_value_preserved(self):
        result = _canonical_json({"count": 42})
        assert '"count":42' in result

    def test_none_serialized_as_null(self):
        result = _canonical_json({"x": None})
        assert '"x":null' in result

    def test_boolean_values(self):
        result = _canonical_json({"flag": True, "off": False})
        assert '"flag":true' in result
        assert '"off":false' in result

    def test_same_data_same_output(self):
        data = {"b": 2, "a": 1}
        assert _canonical_json(data) == _canonical_json(data)

    def test_different_key_order_same_canonical(self):
        a = {"z": 1, "a": 2}
        b = {"a": 2, "z": 1}
        assert _canonical_json(a) == _canonical_json(b)

    def test_empty_dict(self):
        assert _canonical_json({}) == "{}"

    def test_empty_list(self):
        assert _canonical_json([]) == "[]"


# ===========================================================================
# TestContentHash
# ===========================================================================

class TestContentHash:
    def test_same_data_same_hash(self):
        data = {"player": "Jane", "hits": 3}
        assert _content_hash(data) == _content_hash(data)

    def test_different_data_different_hash(self):
        assert _content_hash({"x": 1}) != _content_hash({"x": 2})

    def test_returns_40_char_hex_string(self):
        result = _content_hash({"key": "value"})
        assert isinstance(result, str)
        assert len(result) == 40
        assert all(c in "0123456789abcdef" for c in result)

    def test_order_independent_for_dict_keys(self):
        # Dict with different key insertion order → same canonical JSON → same hash
        a = {"z": 9, "a": 1}
        b = {"a": 1, "z": 9}
        assert _content_hash(a) == _content_hash(b)

    def test_matches_manual_sha1(self):
        data = {"game": "2024-05-01"}
        canonical = _canonical_json(data)
        expected = hashlib.sha1(canonical.encode("utf-8")).hexdigest()
        assert _content_hash(data) == expected

    def test_empty_dict_consistent(self):
        assert _content_hash({}) == _content_hash({})

    def test_nested_dict_stable(self):
        a = {"stats": {"ab": 4, "h": 2}}
        b = {"stats": {"h": 2, "ab": 4}}
        assert _content_hash(a) == _content_hash(b)

    def test_different_types_differ(self):
        # integer 1 vs string "1" must differ
        assert _content_hash({"v": 1}) != _content_hash({"v": "1"})

    def test_list_order_matters(self):
        # Lists are ordered; different order → different hash
        assert _content_hash({"l": [1, 2, 3]}) != _content_hash({"l": [3, 2, 1]})


# ===========================================================================
# TestFlattenMetadata
# ===========================================================================

class TestFlattenMetadata:
    # --- scalar pass-through ---

    def test_string_passed_through(self):
        result = _flatten_metadata({"name": "sharks"})
        assert result["name"] == "sharks"

    def test_integer_passed_through(self):
        result = _flatten_metadata({"score": 7})
        assert result["score"] == 7

    def test_float_passed_through(self):
        result = _flatten_metadata({"avg": 0.375})
        assert result["avg"] == 0.375

    def test_bool_true_passed_through(self):
        result = _flatten_metadata({"active": True})
        assert result["active"] is True

    def test_bool_false_passed_through(self):
        result = _flatten_metadata({"active": False})
        assert result["active"] is False

    def test_none_value_passed_through(self):
        result = _flatten_metadata({"missing": None})
        assert result["missing"] is None

    # --- complex values serialized ---

    def test_list_serialized_to_json_string(self):
        result = _flatten_metadata({"positions": ["SS", "3B"]})
        assert isinstance(result["positions"], str)
        assert json.loads(result["positions"]) == ["SS", "3B"]

    def test_nested_dict_serialized_to_json_string(self):
        result = _flatten_metadata({"stats": {"ab": 4, "h": 2}})
        assert isinstance(result["stats"], str)
        assert json.loads(result["stats"]) == {"ab": 4, "h": 2}

    # --- key truncation ---

    def test_long_key_truncated_to_64_chars(self):
        long_key = "k" * 100
        result = _flatten_metadata({long_key: "value"})
        truncated = "k" * 64
        assert truncated in result
        assert long_key not in result

    def test_key_exactly_64_chars_not_truncated(self):
        key = "x" * 64
        result = _flatten_metadata({key: "v"})
        assert key in result

    def test_key_65_chars_truncated_to_64(self):
        key = "y" * 65
        result = _flatten_metadata({key: "v"})
        assert "y" * 64 in result
        assert key not in result

    # --- edge cases ---

    def test_none_input_returns_empty_dict(self):
        assert _flatten_metadata(None) == {}

    def test_empty_dict_returns_empty_dict(self):
        assert _flatten_metadata({}) == {}

    def test_multiple_keys_all_processed(self):
        result = _flatten_metadata({"a": 1, "b": "two", "c": [3, 4]})
        assert result["a"] == 1
        assert result["b"] == "two"
        assert isinstance(result["c"], str)

    def test_output_is_new_dict_not_mutated(self):
        original = {"key": "value"}
        result = _flatten_metadata(original)
        result["key"] = "changed"
        assert original["key"] == "value"

    def test_serialized_list_value_is_string(self):
        result = _flatten_metadata({"tags": ["a", "b", "c"]})
        val = result["tags"]
        assert isinstance(val, str)
        # must be valid JSON
        parsed = json.loads(val)
        assert parsed == ["a", "b", "c"]

    def test_normal_length_key_preserved_exactly(self):
        result = _flatten_metadata({"short_key": 42})
        assert "short_key" in result
