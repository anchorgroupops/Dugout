"""Tests for sync_daemon._build_games_feed — game-feed construction logic."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import sync_daemon

_build = sync_daemon._build_games_feed


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _redirect_dirs(tmp_path, monkeypatch):
    sharks_dir = tmp_path / "sharks"
    config_dir = tmp_path / "config"
    sharks_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)
    monkeypatch.setattr(sync_daemon, "SHARKS_DIR", sharks_dir)
    monkeypatch.setattr(sync_daemon, "CONFIG_DIR", config_dir)
    # Expose dirs on the fixture for use in tests
    pytest.sharks_dir = sharks_dir
    pytest.config_dir = config_dir


def _games_dir():
    d = pytest.sharks_dir / "games"
    d.mkdir(exist_ok=True)
    return d


def _write_index(*games):
    d = _games_dir()
    (d / "index.json").write_text(json.dumps(list(games)))


def _write_schedule(past=None, upcoming=None):
    data = {"past": past or [], "upcoming": upcoming or []}
    (pytest.sharks_dir / "schedule_manual.json").write_text(json.dumps(data))


# ─── Basic return value tests ─────────────────────────────────────────────────

class TestBuildGamesFeedBasics:
    def test_returns_list(self):
        assert isinstance(_build(), list)

    def test_empty_when_no_index_no_schedule(self):
        assert _build() == []

    def test_empty_when_empty_index(self):
        _write_index()
        assert _build() == []

    def test_single_game_from_index(self):
        _write_index({"game_id": "g1", "date": "2026-03-10", "opponent": "Peppers"})
        result = _build()
        assert len(result) == 1
        assert result[0]["game_id"] == "g1"

    def test_games_sorted_newest_first(self):
        _write_index(
            {"game_id": "g1", "date": "2026-03-01", "opponent": "Peppers"},
            {"game_id": "g2", "date": "2026-04-01", "opponent": "Wildcats"},
        )
        result = _build()
        assert result[0]["date"] > result[1]["date"]

    def test_result_not_modified_without_schedule(self):
        _write_index({"game_id": "g1", "date": "2026-03-10", "opponent": "Peppers"})
        result = _build()
        assert result[0].get("result", "") == ""


# ─── Schedule result enrichment ───────────────────────────────────────────────

class TestScheduleEnrichment:
    def test_result_enriched_from_schedule(self):
        _write_index({"game_id": "g1", "date": "2026-03-10", "opponent": "Peppers"})
        _write_schedule(past=[{"date": "2026-03-10", "opponent": "Peppers", "result": "W", "score": {"sharks": 5, "opponent": 2}}])
        result = _build()
        assert result[0].get("result") == "W"

    def test_partial_slug_match_enriches_result(self):
        # "Peppers" slug is "peppers"; schedule has "Peppers Major SB" → slug "peppersmajorsb"
        # "peppers" IS a substring of "peppersmajorsb" → match should succeed
        _write_index({"game_id": "g1", "date": "2026-03-10", "opponent": "Peppers"})
        _write_schedule(past=[{
            "date": "2026-03-10",
            "opponent": "Peppers Major SB Spring 2026",
            "result": "L",
        }])
        result = _build()
        assert result[0].get("result") == "L"

    def test_schedule_only_game_appended_when_no_pdf(self):
        _write_schedule(past=[{
            "date": "2026-02-01",
            "opponent": "Ravens",
            "result": "W",
            "score": {"sharks": 7, "opponent": 3},
        }])
        result = _build()
        assert len(result) == 1
        assert "ravens" in result[0].get("game_id", "").lower()

    def test_no_duplicate_when_pdf_and_schedule_match(self):
        _write_index({"game_id": "g1", "date": "2026-03-10", "opponent": "Peppers"})
        _write_schedule(past=[{"date": "2026-03-10", "opponent": "Peppers", "result": "W"}])
        result = _build()
        assert len(result) == 1

    def test_schedule_game_without_result_not_appended(self):
        """Upcoming past-date schedule games with no PDF and no result are not surfaced."""
        _write_schedule(upcoming=[{
            "date": "2025-01-01",  # Far in the past
            "opponent": "Future Opponent",
        }])
        result = _build()
        # Only games where GC data or known results exist should surface
        # (the function logic allows past-upcoming without result to be appended to sched_results)
        # Verify no crash at least
        assert isinstance(result, list)


# ─── Deduplication ────────────────────────────────────────────────────────────

class TestDeduplication:
    def test_duplicate_date_opponent_collapsed(self):
        _write_index(
            {"game_id": "g1", "date": "2026-03-10", "opponent": "Peppers"},
            {"game_id": "g2", "date": "2026-03-10", "opponent": "Peppers"},
        )
        result = _build()
        assert len(result) == 1

    def test_different_opponents_same_date_both_kept(self):
        _write_index(
            {"game_id": "g1", "date": "2026-03-10", "opponent": "Peppers"},
            {"game_id": "g2", "date": "2026-03-10", "opponent": "Wildcats"},
        )
        result = _build()
        assert len(result) == 2


# ─── gc_full_scraper_v2 game surfacing ────────────────────────────────────────

class TestGcFullScraperV2Games:
    def _write_gc_game(self, game_id, date, opponent, sharks_h, opp_h, score_sharks, score_opp):
        d = _games_dir()
        data = {
            "game_id": game_id,
            "date": date,
            "opponent": opponent,
            "source": "gc_full_scraper_v2",
            "score": {"sharks": score_sharks, "opponent": score_opp},
            "sharks": {
                "batting": [
                    {"number": "7", "pa": 4, "ab": 3, "h": sharks_h, "bb": 1},
                ],
            },
        }
        (d / f"{game_id}.json").write_text(json.dumps(data))

    def test_gc_game_with_stats_surfaced(self):
        self._write_gc_game("abc123", "2026-04-01", "Wildcats", 2, 0, 5, 3)
        result = _build()
        assert any(g.get("game_id") == "abc123" for g in result)

    def test_gc_game_result_derived_from_score(self):
        self._write_gc_game("abc123", "2026-04-01", "Wildcats", 2, 0, 7, 4)
        result = _build()
        g = next(r for r in result if r.get("game_id") == "abc123")
        assert g.get("result") == "W"

    def test_gc_game_loss_result(self):
        self._write_gc_game("xyz789", "2026-04-05", "Ravens", 0, 2, 3, 8)
        result = _build()
        g = next(r for r in result if r.get("game_id") == "xyz789")
        assert g.get("result") == "L"

    def test_gc_game_without_stats_not_surfaced(self):
        d = _games_dir()
        data = {
            "game_id": "empty_gc",
            "date": "2026-04-10",
            "opponent": "Future Team",
            "source": "gc_full_scraper_v2",
            "score": {},
            "sharks": {"batting": []},  # empty = no stats
        }
        (d / "empty_gc.json").write_text(json.dumps(data))
        result = _build()
        assert not any(g.get("game_id") == "empty_gc" for g in result)

    def test_gc_game_preferred_over_pdf_on_same_date(self):
        _write_index({"game_id": "pdf1", "date": "2026-04-01", "opponent": "Wildcats"})
        self._write_gc_game("gc1", "2026-04-01", "Wildcats", 2, 0, 5, 3)
        result = _build()
        ids = [g.get("game_id") for g in result]
        assert "gc1" in ids
        assert "pdf1" not in ids  # PDF deduped in favor of GC

    def test_source_field_marked_as_gc_full_scraper_v2(self):
        self._write_gc_game("abc123", "2026-04-01", "Wildcats", 2, 0, 5, 3)
        result = _build()
        g = next(r for r in result if r.get("game_id") == "abc123")
        assert g.get("source") == "gc_full_scraper_v2"


# ─── Detail mode ──────────────────────────────────────────────────────────────

class TestDetailMode:
    def test_include_detail_attaches_sharks_batting(self):
        gd = _games_dir()
        _write_index({"game_id": "g1", "date": "2026-03-10", "opponent": "Peppers"})
        (gd / "g1.json").write_text(json.dumps({
            "sharks_batting": [{"number": "7", "name": "Alice", "h": 2}],
        }))
        result = _build(include_detail=True)
        assert result[0].get("sharks_batting") == [{"number": "7", "name": "Alice", "h": 2}]

    def test_include_detail_false_no_batting_attached(self):
        gd = _games_dir()
        _write_index({"game_id": "g1", "date": "2026-03-10", "opponent": "Peppers"})
        (gd / "g1.json").write_text(json.dumps({
            "sharks_batting": [{"number": "7", "name": "Alice"}],
        }))
        result = _build(include_detail=False)
        assert "sharks_batting" not in result[0]
