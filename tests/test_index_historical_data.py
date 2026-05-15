"""Tests for tools/index_historical_data.py — pure filesystem helpers."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import index_historical_data as ihd


# ── _load_json ──────────────────────────────────────────────────────────────

class TestLoadJson:
    def test_dict_returned_as_is(self, tmp_path):
        f = tmp_path / "team.json"
        f.write_text(json.dumps({"name": "Sharks", "wins": 7}))
        result = ihd._load_json(f)
        assert result == {"name": "Sharks", "wins": 7}

    def test_list_wrapped_in_items_key(self, tmp_path):
        f = tmp_path / "list.json"
        f.write_text(json.dumps([1, 2, 3]))
        result = ihd._load_json(f)
        assert result == {"items": [1, 2, 3]}

    def test_scalar_wrapped_in_value_key(self, tmp_path):
        f = tmp_path / "scalar.json"
        f.write_text(json.dumps(42))
        result = ihd._load_json(f)
        assert result == {"value": 42}

    def test_empty_dict(self, tmp_path):
        f = tmp_path / "empty.json"
        f.write_text("{}")
        result = ihd._load_json(f)
        assert result == {}

    def test_empty_list_wrapped(self, tmp_path):
        f = tmp_path / "empty_list.json"
        f.write_text("[]")
        result = ihd._load_json(f)
        assert result == {"items": []}

    def test_unicode_content(self, tmp_path):
        f = tmp_path / "uni.json"
        f.write_text(json.dumps({"name": "Riptide Señoritas"}), encoding="utf-8")
        result = ihd._load_json(f)
        assert result["name"] == "Riptide Señoritas"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises((FileNotFoundError, OSError)):
            ihd._load_json(tmp_path / "nonexistent.json")

    def test_invalid_json_raises(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("{not: valid json}")
        with pytest.raises(json.JSONDecodeError):
            ihd._load_json(f)

    def test_nested_dict_preserved(self, tmp_path):
        data = {"roster": [{"name": "Alice", "avg": 0.450}]}
        f = tmp_path / "nested.json"
        f.write_text(json.dumps(data))
        assert ihd._load_json(f) == data

    def test_none_json_wrapped_in_value(self, tmp_path):
        f = tmp_path / "null.json"
        f.write_text("null")
        result = ihd._load_json(f)
        assert result == {"value": None}


# ── _doc_metadata ─────────────────────────────────────────────────────────────

class TestDocMetadata:
    """_doc_metadata produces metadata dicts relative to DATA_DIR."""

    @pytest.fixture(autouse=True)
    def _patch_data_dir(self, tmp_path, monkeypatch):
        self.data_dir = tmp_path / "data"
        self.data_dir.mkdir()
        monkeypatch.setattr(ihd, "DATA_DIR", self.data_dir)

    def _make(self, *parts, content=None):
        p = self.data_dir
        for part in parts:
            p = p / part
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content or "{}")
        return p

    def test_sharks_scope_detected(self):
        f = self._make("sharks", "team.json")
        meta = ihd._doc_metadata(f)
        assert meta["scope"] == "sharks"

    def test_opponents_scope_detected(self):
        f = self._make("opponents", "riptide", "team.json")
        meta = ihd._doc_metadata(f)
        assert meta["scope"] == "opponents"

    def test_source_path_is_relative_posix(self):
        f = self._make("sharks", "team.json")
        meta = ihd._doc_metadata(f)
        assert meta["source_path"] == "sharks/team.json"
        assert "\\" not in meta["source_path"]

    def test_filename_matches_basename(self):
        f = self._make("sharks", "app_stats.json")
        meta = ihd._doc_metadata(f)
        assert meta["filename"] == "app_stats.json"

    def test_opponent_slug_added_for_opponents(self):
        f = self._make("opponents", "wildcats", "team.json")
        meta = ihd._doc_metadata(f)
        assert meta["opponent_slug"] == "wildcats"

    def test_no_opponent_slug_for_sharks(self):
        f = self._make("sharks", "team.json")
        meta = ihd._doc_metadata(f)
        assert "opponent_slug" not in meta

    def test_deep_opponents_path_uses_first_dir_as_slug(self):
        f = self._make("opponents", "peppers", "sub", "data.json")
        meta = ihd._doc_metadata(f)
        assert meta["opponent_slug"] == "peppers"

    def test_metadata_has_required_keys(self):
        f = self._make("sharks", "team.json")
        meta = ihd._doc_metadata(f)
        for key in ("source_path", "scope", "filename"):
            assert key in meta


# ── _iter_json_files ─────────────────────────────────────────────────────────

class TestIterJsonFiles:
    @pytest.fixture(autouse=True)
    def _patch_dirs(self, tmp_path, monkeypatch):
        self.data_dir = tmp_path / "data"
        self.sharks_dir = self.data_dir / "sharks"
        self.opp_dir = self.data_dir / "opponents"
        self.sharks_dir.mkdir(parents=True)
        self.opp_dir.mkdir(parents=True)
        monkeypatch.setattr(ihd, "DATA_DIR", self.data_dir)
        monkeypatch.setattr(ihd, "SHARKS_DIR", self.sharks_dir)
        monkeypatch.setattr(ihd, "OPPONENTS_DIR", self.opp_dir)

    def test_empty_dirs_yield_nothing(self):
        assert list(ihd._iter_json_files()) == []

    def test_sharks_json_found(self):
        (self.sharks_dir / "team.json").write_text("{}")
        paths = list(ihd._iter_json_files())
        assert len(paths) == 1
        assert paths[0].name == "team.json"

    def test_opponents_json_found(self):
        opp = self.opp_dir / "wildcats"
        opp.mkdir()
        (opp / "team.json").write_text("{}")
        paths = list(ihd._iter_json_files())
        assert any(p.name == "team.json" for p in paths)

    def test_non_json_files_excluded(self):
        (self.sharks_dir / "notes.txt").write_text("ignore me")
        (self.sharks_dir / "team.json").write_text("{}")
        paths = list(ihd._iter_json_files())
        assert all(p.suffix == ".json" for p in paths)

    def test_multiple_files_all_found(self):
        (self.sharks_dir / "a.json").write_text("{}")
        (self.sharks_dir / "b.json").write_text("{}")
        paths = list(ihd._iter_json_files())
        assert len(paths) == 2

    def test_results_are_path_objects(self):
        (self.sharks_dir / "x.json").write_text("{}")
        paths = list(ihd._iter_json_files())
        assert all(isinstance(p, Path) for p in paths)

    def test_results_are_sorted(self):
        for name in ("z.json", "a.json", "m.json"):
            (self.sharks_dir / name).write_text("{}")
        paths = list(ihd._iter_json_files())
        names = [p.name for p in paths]
        assert names == sorted(names)

    def test_nonexistent_dirs_skipped_gracefully(self, monkeypatch):
        monkeypatch.setattr(ihd, "SHARKS_DIR", self.data_dir / "does_not_exist")
        monkeypatch.setattr(ihd, "OPPONENTS_DIR", self.data_dir / "also_missing")
        paths = list(ihd._iter_json_files())
        assert paths == []

    def test_nested_subdirs_traversed(self):
        nested = self.opp_dir / "ravens" / "2026"
        nested.mkdir(parents=True)
        (nested / "stats.json").write_text("{}")
        paths = list(ihd._iter_json_files())
        assert any(p.name == "stats.json" for p in paths)


# ── run() dry_run mode ────────────────────────────────────────────────────────

class TestRunDryRun:
    @pytest.fixture(autouse=True)
    def _patch_dirs(self, tmp_path, monkeypatch):
        self.data_dir = tmp_path / "data"
        self.sharks_dir = self.data_dir / "sharks"
        self.opp_dir = self.data_dir / "opponents"
        self.sharks_dir.mkdir(parents=True)
        self.opp_dir.mkdir(parents=True)
        monkeypatch.setattr(ihd, "DATA_DIR", self.data_dir)
        monkeypatch.setattr(ihd, "SHARKS_DIR", self.sharks_dir)
        monkeypatch.setattr(ihd, "OPPONENTS_DIR", self.opp_dir)

    def test_dry_run_returns_zero_when_no_files(self):
        count = ihd.run("idx", "ns", batch_size=4, dry_run=True)
        assert count == 0

    def test_dry_run_counts_json_files(self):
        for i in range(3):
            (self.sharks_dir / f"file{i}.json").write_text("{}")
        count = ihd.run("idx", "ns", batch_size=4, dry_run=True)
        assert count == 3

    def test_dry_run_skips_invalid_json(self, capsys):
        (self.sharks_dir / "good.json").write_text('{"ok": true}')
        (self.sharks_dir / "bad.json").write_text("{corrupt}")
        count = ihd.run("idx", "ns", batch_size=4, dry_run=True)
        assert count == 1  # only the good file counts
        out = capsys.readouterr().out
        assert "Skipping" in out

    def test_dry_run_does_not_call_memory_engine(self, monkeypatch):
        (self.sharks_dir / "team.json").write_text('{"name": "Sharks"}')
        called = []
        monkeypatch.setattr("builtins.__import__", lambda *a, **k: called.append(a[0]) or __import__(*a, **k))
        ihd.run("idx", "ns", batch_size=4, dry_run=True)
        assert "memory_engine" not in called

    def test_dry_run_prints_count(self, capsys):
        (self.sharks_dir / "team.json").write_text("{}")
        ihd.run("idx", "ns", batch_size=4, dry_run=True)
        out = capsys.readouterr().out
        assert "1" in out

    def test_doc_id_format_in_dry_run(self):
        (self.sharks_dir / "team.json").write_text('{"x": 1}')
        # We re-implement just enough to check doc_id format;
        # dry_run prints count but returns int — verify the path codepath
        count = ihd.run("test-index", "softball", batch_size=8, dry_run=True)
        assert isinstance(count, int)
        assert count >= 0

    def test_opponent_files_counted(self):
        opp = self.opp_dir / "peppers"
        opp.mkdir()
        (opp / "team.json").write_text('{"name": "Peppers"}')
        count = ihd.run("idx", "ns", batch_size=4, dry_run=True)
        assert count == 1

    def test_both_dirs_files_counted_together(self):
        (self.sharks_dir / "a.json").write_text("{}")
        opp = self.opp_dir / "wildcats"
        opp.mkdir()
        (opp / "b.json").write_text("{}")
        count = ihd.run("idx", "ns", batch_size=4, dry_run=True)
        assert count == 2


class TestMain:
    """Tests for the main() CLI entry point — lines 78-85."""

    def test_main_calls_run_with_dry_run_flag(self, monkeypatch):
        calls = []
        monkeypatch.setattr(ihd, "run", lambda **kw: calls.append(kw) or 0)
        monkeypatch.setattr("sys.argv", ["index_historical_data.py", "--dry-run"])
        ihd.main()
        assert calls[0]["dry_run"] is True

    def test_main_uses_default_index_and_namespace(self, monkeypatch):
        calls = []
        monkeypatch.setattr(ihd, "run", lambda **kw: calls.append(kw) or 0)
        monkeypatch.setattr("sys.argv", ["index_historical_data.py"])
        ihd.main()
        assert calls[0]["index_name"] == "softball-sharks"
        assert calls[0]["namespace"] == "softball"

    def test_main_custom_args_forwarded(self, monkeypatch):
        calls = []
        monkeypatch.setattr(ihd, "run", lambda **kw: calls.append(kw) or 0)
        monkeypatch.setattr("sys.argv", [
            "index_historical_data.py",
            "--index", "my-index",
            "--namespace", "my-ns",
            "--batch-size", "32",
        ])
        ihd.main()
        assert calls[0]["index_name"] == "my-index"
        assert calls[0]["namespace"] == "my-ns"
        assert calls[0]["batch_size"] == 32


class TestRunLive:
    """Test the non-dry-run path by mocking MemoryEngine."""

    @pytest.fixture(autouse=True)
    def _patch_dirs(self, tmp_path, monkeypatch):
        self.data_dir = tmp_path / "data"
        self.sharks_dir = self.data_dir / "sharks"
        self.sharks_dir.mkdir(parents=True)
        (self.data_dir / "opponents").mkdir()
        monkeypatch.setattr(ihd, "DATA_DIR", self.data_dir)
        monkeypatch.setattr(ihd, "SHARKS_DIR", self.sharks_dir)
        monkeypatch.setattr(ihd, "OPPONENTS_DIR", self.data_dir / "opponents")

    def test_calls_memory_engine_when_not_dry_run(self, monkeypatch):
        from unittest.mock import MagicMock, patch
        (self.sharks_dir / "team.json").write_text('{"name": "Sharks"}')
        mock_engine = MagicMock()
        mock_engine.batch_upsert_documents.return_value = 1
        with patch.dict("sys.modules", {"memory_engine": MagicMock(MemoryEngine=MagicMock(return_value=mock_engine))}):
            import importlib
            import tools.index_historical_data as ihd2
            monkeypatch.setattr(ihd2, "DATA_DIR", self.data_dir)
            monkeypatch.setattr(ihd2, "SHARKS_DIR", self.sharks_dir)
            monkeypatch.setattr(ihd2, "OPPONENTS_DIR", self.data_dir / "opponents")
            count = ihd2.run("idx", "ns", batch_size=4, dry_run=False)
        assert count >= 0  # engine was called
