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
    DEFAULT_NAMESPACE,
    MemoryEngine,
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


# ===========================================================================
# MemoryEngine — init-time guard tests (no real API needed)
# ===========================================================================

class TestMemoryEngineInit:
    def test_raises_when_pinecone_key_missing(self, monkeypatch):
        monkeypatch.delenv("PINECONE_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        with pytest.raises(ValueError, match="PINECONE_API_KEY"):
            MemoryEngine()

    def test_raises_when_gemini_key_missing_but_pinecone_set(self, monkeypatch):
        monkeypatch.setenv("PINECONE_API_KEY", "fake-pinecone-key")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        with pytest.raises(ValueError, match="GEMINI_API_KEY"):
            MemoryEngine()

    def test_raises_value_error_not_other_exception(self, monkeypatch):
        monkeypatch.delenv("PINECONE_API_KEY", raising=False)
        try:
            MemoryEngine()
        except ValueError:
            pass  # expected
        except Exception as e:
            pytest.fail(f"Expected ValueError, got {type(e).__name__}: {e}")


# ===========================================================================
# MemoryEngine — method tests with fully mocked external APIs
# ===========================================================================

def _make_engine(monkeypatch) -> "MemoryEngine":
    """Create a MemoryEngine with mocked external APIs."""
    monkeypatch.setenv("PINECONE_API_KEY", "fake-pc-key")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    fake_vector = [0.1] * 768

    # Patch genai.embed_content to return the expected structure
    genai_mock = sys.modules["google.generativeai"]
    genai_mock.embed_content = mock.MagicMock(return_value={"embedding": fake_vector})
    genai_mock.configure = mock.MagicMock()

    # Patch Pinecone and its Index
    pc_instance = mock.MagicMock()
    index_instance = mock.MagicMock()
    pc_instance.Index.return_value = index_instance
    sys.modules["pinecone"].Pinecone.return_value = pc_instance

    engine = MemoryEngine()
    engine._fake_vector = fake_vector
    engine._index_mock = index_instance
    return engine


class TestMemoryEngineInitSuccess:
    def test_successful_init_configures_genai(self, monkeypatch):
        """Lines 60-64: successful __init__ calls genai.configure and Pinecone."""
        engine = _make_engine(monkeypatch)
        genai_mock = sys.modules["google.generativeai"]
        genai_mock.configure.assert_called_once()
        assert engine.namespace == DEFAULT_NAMESPACE

    def test_successful_init_uses_custom_index(self, monkeypatch):
        monkeypatch.setenv("PINECONE_API_KEY", "pk")
        monkeypatch.setenv("GEMINI_API_KEY", "gk")
        sys.modules["google.generativeai"].configure = mock.MagicMock()
        sys.modules["google.generativeai"].embed_content = mock.MagicMock(
            return_value={"embedding": [0.0] * 768})
        pc_instance = mock.MagicMock()
        pc_instance.Index.return_value = mock.MagicMock()
        sys.modules["pinecone"].Pinecone.return_value = pc_instance
        engine = MemoryEngine(index_name="my-index", namespace="my-ns")
        assert engine.namespace == "my-ns"
        pc_instance.Index.assert_called_once_with("my-index")


class TestEmbed:
    def test_embed_returns_vector(self, monkeypatch):
        """Lines 67-75: _embed returns a list of floats from genai response."""
        engine = _make_engine(monkeypatch)
        result = engine._embed("some text", task_type="retrieval_document")
        assert result == engine._fake_vector

    def test_embed_truncates_text(self, monkeypatch):
        engine = _make_engine(monkeypatch)
        long_text = "x" * 20000
        engine._embed(long_text, task_type="retrieval_document")
        genai_mock = sys.modules["google.generativeai"]
        call_args = genai_mock.embed_content.call_args
        content_arg = call_args[1].get("content") or call_args[0][1]
        assert len(content_arg) <= 12000

    def test_embed_empty_string_uses_placeholder(self, monkeypatch):
        engine = _make_engine(monkeypatch)
        engine._embed("", task_type="retrieval_document")
        genai_mock = sys.modules["google.generativeai"]
        call_args = genai_mock.embed_content.call_args
        content_arg = call_args[1].get("content") or call_args[0][1]
        assert content_arg == "empty"

    def test_embed_raises_when_no_embedding_key(self, monkeypatch):
        engine = _make_engine(monkeypatch)
        sys.modules["google.generativeai"].embed_content = mock.MagicMock(
            return_value={"no_embedding_here": []})
        with pytest.raises(RuntimeError, match="embedding"):
            engine._embed("text", task_type="retrieval_document")


class TestDocText:
    def test_doc_text_returns_canonical_json(self, monkeypatch):
        """Line 78: _doc_text wraps _canonical_json."""
        from memory_engine import _canonical_json
        engine = _make_engine(monkeypatch)
        data = {"z": 1, "a": 2}
        result = engine._doc_text(data)
        assert result == _canonical_json(data)


class TestUpsertGameData:
    def test_upsert_game_data_calls_index_upsert(self, monkeypatch):
        """Lines 82-95: upsert_game_data calls index.upsert."""
        engine = _make_engine(monkeypatch)
        doc_id = engine.upsert_game_data("game-001", {"innings": 7})
        assert doc_id == "game::game-001"
        engine._index_mock.upsert.assert_called_once()

    def test_upsert_game_data_includes_entity_type(self, monkeypatch):
        engine = _make_engine(monkeypatch)
        engine.upsert_game_data("g1", {"score": 5})
        call_kwargs = engine._index_mock.upsert.call_args[1]
        vectors = call_kwargs["vectors"]
        assert vectors[0]["metadata"]["entity_type"] == "game"


class TestUpsertDocument:
    def test_upsert_document_returns_safe_id(self, monkeypatch):
        """Lines 99-112: upsert_document returns safe doc_id."""
        engine = _make_engine(monkeypatch)
        result = engine.upsert_document("sharks/team.json", {"data": "val"})
        assert result == "sharks/team.json"
        engine._index_mock.upsert.assert_called_once()

    def test_upsert_document_merges_metadata(self, monkeypatch):
        engine = _make_engine(monkeypatch)
        engine.upsert_document("doc1", {"x": 1},
                               metadata={"scope": "sharks"})
        call_kwargs = engine._index_mock.upsert.call_args[1]
        vectors = call_kwargs["vectors"]
        assert "scope" in vectors[0]["metadata"]


class TestBatchUpsertDocuments:
    def test_returns_count_of_upserted_docs(self, monkeypatch):
        """Lines 119-147: batch_upsert_documents returns total count."""
        engine = _make_engine(monkeypatch)
        engine._index_mock.upsert.return_value = None
        docs = [
            {"id": "doc1", "data": {"val": 1}},
            {"id": "doc2", "data": {"val": 2}},
        ]
        count = engine.batch_upsert_documents(docs, batch_size=10)
        assert count == 2

    def test_skips_non_dict_items(self, monkeypatch):
        engine = _make_engine(monkeypatch)
        docs = ["not a dict", None, {"id": "d1", "data": {"x": 1}}]
        count = engine.batch_upsert_documents(docs)
        assert count == 1

    def test_skips_items_missing_id_or_data(self, monkeypatch):
        engine = _make_engine(monkeypatch)
        docs = [
            {"data": {"x": 1}},  # missing id
            {"id": "d1"},         # missing data
            {"id": "d2", "data": {"y": 2}},
        ]
        count = engine.batch_upsert_documents(docs)
        assert count == 1

    def test_batching_flushes_at_batch_size(self, monkeypatch):
        engine = _make_engine(monkeypatch)
        docs = [{"id": f"d{i}", "data": {"i": i}} for i in range(5)]
        engine.batch_upsert_documents(docs, batch_size=2)
        # 5 docs, batch_size=2 → 2 upserts of 2, 1 upsert of 1 = 3 calls
        assert engine._index_mock.upsert.call_count == 3

    def test_empty_input_returns_zero(self, monkeypatch):
        engine = _make_engine(monkeypatch)
        count = engine.batch_upsert_documents([])
        assert count == 0

    def test_optional_metadata_merged(self, monkeypatch):
        engine = _make_engine(monkeypatch)
        docs = [{"id": "d1", "data": {"x": 1},
                 "metadata": {"scope": "sharks"}}]
        engine.batch_upsert_documents(docs)
        call_kwargs = engine._index_mock.upsert.call_args[1]
        assert "scope" in call_kwargs["vectors"][0]["metadata"]


class TestSearchHistory:
    def test_returns_list_of_matches(self, monkeypatch):
        """Lines 151-168: search_history returns match dicts."""
        engine = _make_engine(monkeypatch)
        fake_match = mock.MagicMock()
        fake_match.id = "doc1"
        fake_match.score = 0.95
        fake_match.metadata = {"entity_type": "game"}
        engine._index_mock.query.return_value = mock.MagicMock(
            matches=[fake_match])
        results = engine.search_history("how did we do last week?")
        assert len(results) == 1
        assert results[0]["id"] == "doc1"
        assert results[0]["score"] == pytest.approx(0.95)

    def test_returns_empty_list_when_no_matches(self, monkeypatch):
        engine = _make_engine(monkeypatch)
        engine._index_mock.query.return_value = mock.MagicMock(matches=[])
        results = engine.search_history("no match query")
        assert results == []

    def test_uses_top_k_parameter(self, monkeypatch):
        engine = _make_engine(monkeypatch)
        engine._index_mock.query.return_value = mock.MagicMock(matches=[])
        engine.search_history("query", top_k=3)
        call_kwargs = engine._index_mock.query.call_args[1]
        assert call_kwargs["top_k"] == 3


class TestSyncLocalFiles:
    def test_returns_zero_when_no_files_exist(self, tmp_path, monkeypatch):
        """Lines 175-214: sync_local_files returns 0 when files missing."""
        engine = _make_engine(monkeypatch)
        count = engine.sync_local_files(str(tmp_path))
        assert count == 0

    def test_indexes_json_files(self, tmp_path, monkeypatch):
        engine = _make_engine(monkeypatch)
        engine._index_mock.upsert.return_value = None
        (tmp_path / "team.json").write_text('{"team": "sharks"}')
        count = engine.sync_local_files(str(tmp_path))
        assert count == 1

    def test_indexes_txt_files(self, tmp_path, monkeypatch):
        engine = _make_engine(monkeypatch)
        engine._index_mock.upsert.return_value = None
        (tmp_path / "next_practice.txt").write_text("Warmup: stretch 10min")
        count = engine.sync_local_files(str(tmp_path))
        assert count == 1

    def test_skips_invalid_json_file(self, tmp_path, monkeypatch, capsys):
        engine = _make_engine(monkeypatch)
        (tmp_path / "team.json").write_text("{bad json}")
        count = engine.sync_local_files(str(tmp_path))
        assert count == 0
        out = capsys.readouterr().out
        assert "Error" in out

    def test_multiple_files_all_indexed(self, tmp_path, monkeypatch):
        engine = _make_engine(monkeypatch)
        engine._index_mock.upsert.return_value = None
        (tmp_path / "team.json").write_text('{"x": 1}')
        (tmp_path / "lineups.json").write_text('{"y": 2}')
        count = engine.sync_local_files(str(tmp_path))
        assert count == 2
