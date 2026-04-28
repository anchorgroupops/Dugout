"""Tests for tools/registry_manager.py — in-memory notebook registry operations."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.registry_manager import (
    add_source_to_registry,
    find_notebook,
    get_all_owned,
    get_managed_notebooks,
    get_source_urls,
    load,
    mark_stale,
    save,
    sync_from_live,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def base_registry():
    return {
        "notebooks": [
            {
                "id": "nb-1",
                "title": "Sharks Stats",
                "ownership": "owned",
                "status": "active",
                "config": {"auto_add": True},
                "sources": [
                    {"url": "https://example.com/source1", "title": "Source 1",
                     "type": "web", "is_stale": False, "is_duplicate": False},
                ],
            },
            {
                "id": "nb-2",
                "title": "Training Videos",
                "ownership": "owned",
                "status": "active",
                "config": {"auto_add": False},
                "sources": [],
            },
            {
                "id": "nb-3",
                "title": "Opponent Research",
                "ownership": "shared",
                "status": "active",
                "config": {"auto_add": True},
                "sources": [],
            },
            {
                "id": "nb-4",
                "title": "Deleted Notebook",
                "ownership": "owned",
                "status": "deleted",
                "config": {"auto_add": True},
                "sources": [],
            },
        ]
    }


# ---------------------------------------------------------------------------
# load / save — filesystem round-trip
# ---------------------------------------------------------------------------

class TestLoadSave:
    def test_load_raises_when_missing(self, tmp_path, monkeypatch):
        import tools.registry_manager as rm
        monkeypatch.setattr(rm, "REGISTRY_PATH", tmp_path / "notebooks.json")
        with pytest.raises(FileNotFoundError):
            load()

    def test_save_and_load_round_trip(self, tmp_path, monkeypatch):
        import tools.registry_manager as rm
        monkeypatch.setattr(rm, "REGISTRY_PATH", tmp_path / "notebooks.json")
        data = {"notebooks": [{"id": "x", "title": "Test"}]}
        save(data)
        assert (tmp_path / "notebooks.json").exists()
        loaded = load()
        assert loaded == data

    def test_save_is_atomic_via_tmp(self, tmp_path, monkeypatch):
        import tools.registry_manager as rm
        monkeypatch.setattr(rm, "REGISTRY_PATH", tmp_path / "notebooks.json")
        data = {"notebooks": []}
        save(data)
        # No .tmp file should be left behind
        assert not (tmp_path / "notebooks.tmp").exists()


# ---------------------------------------------------------------------------
# get_managed_notebooks
# ---------------------------------------------------------------------------

class TestGetManagedNotebooks:
    def test_returns_owned_auto_add_active(self, base_registry):
        result = get_managed_notebooks(base_registry)
        ids = [nb["id"] for nb in result]
        assert "nb-1" in ids

    def test_excludes_auto_add_false(self, base_registry):
        result = get_managed_notebooks(base_registry)
        ids = [nb["id"] for nb in result]
        assert "nb-2" not in ids

    def test_excludes_shared(self, base_registry):
        result = get_managed_notebooks(base_registry)
        ids = [nb["id"] for nb in result]
        assert "nb-3" not in ids

    def test_excludes_deleted(self, base_registry):
        result = get_managed_notebooks(base_registry)
        ids = [nb["id"] for nb in result]
        assert "nb-4" not in ids

    def test_empty_registry(self):
        assert get_managed_notebooks({"notebooks": []}) == []


# ---------------------------------------------------------------------------
# get_all_owned
# ---------------------------------------------------------------------------

class TestGetAllOwned:
    def test_returns_all_owned(self, base_registry):
        result = get_all_owned(base_registry)
        ids = {nb["id"] for nb in result}
        assert ids == {"nb-1", "nb-2", "nb-4"}

    def test_excludes_shared(self, base_registry):
        result = get_all_owned(base_registry)
        ids = {nb["id"] for nb in result}
        assert "nb-3" not in ids


# ---------------------------------------------------------------------------
# find_notebook
# ---------------------------------------------------------------------------

class TestFindNotebook:
    def test_finds_by_id(self, base_registry):
        nb = find_notebook(base_registry, "nb-2")
        assert nb is not None
        assert nb["title"] == "Training Videos"

    def test_returns_none_when_not_found(self, base_registry):
        assert find_notebook(base_registry, "nonexistent") is None

    def test_returns_first_match(self, base_registry):
        nb = find_notebook(base_registry, "nb-1")
        assert nb["id"] == "nb-1"


# ---------------------------------------------------------------------------
# get_source_urls
# ---------------------------------------------------------------------------

class TestGetSourceUrls:
    def test_returns_url_set(self, base_registry):
        nb = find_notebook(base_registry, "nb-1")
        urls = get_source_urls(nb)
        assert "https://example.com/source1" in urls

    def test_empty_sources(self, base_registry):
        nb = find_notebook(base_registry, "nb-2")
        assert get_source_urls(nb) == set()

    def test_sources_without_url_excluded(self):
        nb = {"sources": [{"title": "No URL", "type": "web"}]}
        assert get_source_urls(nb) == set()

    def test_returns_set_not_list(self, base_registry):
        nb = find_notebook(base_registry, "nb-1")
        assert isinstance(get_source_urls(nb), set)


# ---------------------------------------------------------------------------
# add_source_to_registry
# ---------------------------------------------------------------------------

class TestAddSourceToRegistry:
    def test_source_appended(self, base_registry):
        nb = find_notebook(base_registry, "nb-2")
        add_source_to_registry(nb, url="https://new.com", title="New", source_type="web")
        assert len(nb["sources"]) == 1
        assert nb["sources"][0]["url"] == "https://new.com"

    def test_required_fields_present(self, base_registry):
        nb = find_notebook(base_registry, "nb-2")
        add_source_to_registry(nb, url="https://x.com", title="X", source_type="pdf")
        src = nb["sources"][0]
        for key in ("url", "title", "type", "added_at", "last_checked",
                    "is_stale", "is_duplicate", "added_externally"):
            assert key in src

    def test_is_stale_false_by_default(self, base_registry):
        nb = find_notebook(base_registry, "nb-2")
        add_source_to_registry(nb, url="https://x.com", title="X", source_type="web")
        assert nb["sources"][0]["is_stale"] is False

    def test_added_externally_false_by_default(self, base_registry):
        nb = find_notebook(base_registry, "nb-2")
        add_source_to_registry(nb, url="https://x.com", title="X", source_type="web")
        assert nb["sources"][0]["added_externally"] is False

    def test_source_id_stored(self, base_registry):
        nb = find_notebook(base_registry, "nb-2")
        add_source_to_registry(nb, url="https://x.com", title="X",
                               source_type="web", source_id="src-99")
        assert nb["sources"][0]["source_id"] == "src-99"

    def test_last_synced_updated(self, base_registry):
        nb = find_notebook(base_registry, "nb-2")
        add_source_to_registry(nb, url="https://x.com", title="X", source_type="web")
        assert "last_synced" in nb

    def test_initializes_sources_list_if_missing(self):
        nb = {"id": "new", "title": "Empty"}
        add_source_to_registry(nb, url="https://x.com", title="X", source_type="web")
        assert len(nb["sources"]) == 1


# ---------------------------------------------------------------------------
# mark_stale
# ---------------------------------------------------------------------------

class TestMarkStale:
    def test_marks_matching_url_as_stale(self, base_registry):
        nb = find_notebook(base_registry, "nb-1")
        mark_stale(nb, "https://example.com/source1")
        assert nb["sources"][0]["is_stale"] is True

    def test_non_matching_url_unchanged(self, base_registry):
        nb = find_notebook(base_registry, "nb-1")
        mark_stale(nb, "https://other.com/nothere")
        assert nb["sources"][0]["is_stale"] is False

    def test_last_checked_updated(self, base_registry):
        nb = find_notebook(base_registry, "nb-1")
        old_checked = nb["sources"][0].get("last_checked", "")
        mark_stale(nb, "https://example.com/source1")
        assert nb["sources"][0]["last_checked"] != "" or old_checked == ""

    def test_no_error_when_sources_empty(self, base_registry):
        nb = find_notebook(base_registry, "nb-2")
        mark_stale(nb, "https://anything.com")   # should not raise


# ---------------------------------------------------------------------------
# sync_from_live
# ---------------------------------------------------------------------------

class TestSyncFromLive:
    def test_externally_added_source_detected(self, base_registry):
        nb = find_notebook(base_registry, "nb-1")
        live = [
            {"url": "https://example.com/source1", "title": "Source 1", "type": "web"},
            {"url": "https://example.com/new-live", "title": "Live Only", "type": "web"},
        ]
        added, removed = sync_from_live(nb, live)
        assert "https://example.com/new-live" in added

    def test_added_externally_flag_set(self, base_registry):
        nb = find_notebook(base_registry, "nb-1")
        live = [
            {"url": "https://example.com/source1", "title": "Source 1"},
            {"url": "https://example.com/external", "title": "External"},
        ]
        sync_from_live(nb, live)
        external = next(s for s in nb["sources"] if s["url"] == "https://example.com/external")
        assert external["added_externally"] is True

    def test_removed_externally_detected(self, base_registry):
        nb = find_notebook(base_registry, "nb-1")
        live = []   # source1 is in registry but not in live
        _, removed = sync_from_live(nb, live)
        assert "https://example.com/source1" in removed

    def test_removed_source_marked_in_registry(self, base_registry):
        nb = find_notebook(base_registry, "nb-1")
        sync_from_live(nb, [])
        src = nb["sources"][0]
        assert src.get("status") == "removed"

    def test_no_change_when_live_matches_registry(self, base_registry):
        nb = find_notebook(base_registry, "nb-1")
        live = [{"url": "https://example.com/source1", "title": "Source 1", "type": "web"}]
        added, removed = sync_from_live(nb, live)
        assert added == []
        assert removed == []

    def test_empty_live_and_empty_registry(self):
        nb = {"id": "x", "title": "Empty", "sources": []}
        added, removed = sync_from_live(nb, [])
        assert added == []
        assert removed == []
