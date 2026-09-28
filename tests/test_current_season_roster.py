"""Only the current season's players reach the app.

Regression cover for Fall 2026: the sync daemon's local-CSV fallback globbed
"Sharks Spring 2026 Stats*.csv" every cycle and rewrote team.json with last
season's roster; team-file loaders took the first file that existed, so a
stale Spring team_enriched.json masked a fresh Fall team.json.
"""
from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import sync_daemon as sd
import tools.announcer_engine as ae_mod
from tools.gc_csv_ingest import build_team_json
from tools.team_registry import (
    Team, find_season_csv, is_season, pick_team_file, season_key, season_label,
)

FALL_SLUG = "2026-fall-sharks"
FALL = Team(id="LFdMZvC8bLpr", season_slug=FALL_SLUG, name="The Sharks", data_slug="sharks")

SPRING_ROSTER = [
    {"first": "Maylani", "last": "Nixon", "number": "1"},
    {"first": "Lexi", "last": "McKinney", "number": "99"},
]
FALL_ROSTER = [
    {"first": "Lexi", "last": "McKinney", "number": "99"},
    {"first": "Raelynne", "last": "Cotter", "number": "31"},
]


def _write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


# ---------------------------------------------------------------------------
# Season parsing
# ---------------------------------------------------------------------------

class TestSeasonKey:
    @pytest.mark.parametrize("value,expected", [
        ("Spring 2026", ("2026", "spring")),
        ("2026-fall-sharks", ("2026", "fall")),
        ("Sharks Fall 2026 Stats (3).csv", ("2026", "fall")),
        ("season_stats_20260928.csv", None),
        ("", None),
        (None, None),
    ])
    def test_parses_both_label_and_slug(self, value, expected):
        assert season_key(value) == expected

    def test_label_and_slug_are_the_same_season(self):
        assert is_season("Fall 2026", FALL_SLUG)
        assert not is_season("Spring 2026", FALL_SLUG)
        assert season_label(FALL_SLUG) == "Fall 2026"


# ---------------------------------------------------------------------------
# CSV discovery — Spring files present, Fall season selected
# ---------------------------------------------------------------------------

class TestFindSeasonCsv:
    def test_spring_only_finds_nothing(self, tmp_path):
        (tmp_path / "Sharks Spring 2026 Stats.csv").write_text("x")
        (tmp_path / "Sharks Spring 2026 Stats (12).csv").write_text("x")
        assert find_season_csv(tmp_path, FALL_SLUG) is None

    def test_spring_and_fall_picks_fall(self, tmp_path):
        (tmp_path / "Sharks Spring 2026 Stats.csv").write_text("x")
        fall = tmp_path / "Sharks Fall 2026 Stats.csv"
        fall.write_text("x")
        assert find_season_csv(tmp_path, FALL_SLUG) == fall

    def test_equal_mtimes_pick_highest_download_suffix(self, tmp_path):
        # A fresh checkout stamps every tracked export with the same mtime.
        for name in ("Stats.csv", "Stats (3).csv", "Stats (12).csv"):
            p = tmp_path / f"Sharks Fall 2026 {name}"
            p.write_text("x")
            os.utime(p, (1_000_000, 1_000_000))
        assert find_season_csv(tmp_path, FALL_SLUG).name == "Sharks Fall 2026 Stats (12).csv"

    def test_any_team_name_prefix(self, tmp_path):
        fall = tmp_path / "The Sharks Fall 2026 Stats.csv"
        fall.write_text("x")
        assert find_season_csv(tmp_path, FALL_SLUG) == fall

    def test_missing_dir(self, tmp_path):
        assert find_season_csv(tmp_path / "nope", FALL_SLUG) is None


class TestLocalCsvFallback:
    """The every-cycle fallback must not re-ingest last season's export."""

    def _setup(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sd, "SCOREBOOKS_DIR", tmp_path)
        sharks = tmp_path / "sharks"
        sharks.mkdir()
        monkeypatch.setattr(sd, "SHARKS_DIR", sharks)
        monkeypatch.setattr(sd, "GC_SEASON_SLUG_DEFAULT", FALL_SLUG)
        (tmp_path / "Other docs").mkdir()
        fake = types.ModuleType("gc_csv_ingest")
        fake.parse_gc_csv = MagicMock(return_value=[{"first": "Raelynne", "number": "31"}])
        fake.build_team_json = MagicMock(return_value={"season": FALL_SLUG, "roster": []})
        fake.build_app_stats_json = MagicMock(return_value={})
        monkeypatch.setitem(sys.modules, "gc_csv_ingest", fake)
        return sharks, fake

    def test_spring_csv_is_not_ingested(self, tmp_path, monkeypatch):
        sharks, fake = self._setup(tmp_path, monkeypatch)
        (tmp_path / "Other docs" / "Sharks Spring 2026 Stats.csv").write_text("x")
        team_file = _write(sharks / "team.json", {"season": FALL_SLUG, "roster": FALL_ROSTER})
        sd._csv_ingest_from_local()
        fake.parse_gc_csv.assert_not_called()
        assert json.loads(team_file.read_text())["roster"] == FALL_ROSTER

    def test_fall_csv_is_ingested(self, tmp_path, monkeypatch):
        sharks, fake = self._setup(tmp_path, monkeypatch)
        (tmp_path / "Other docs" / "Sharks Spring 2026 Stats.csv").write_text("x")
        fall = tmp_path / "Other docs" / "Sharks Fall 2026 Stats.csv"
        fall.write_text("x")
        sd._csv_ingest_from_local()
        fake.parse_gc_csv.assert_called_once_with(fall)


# ---------------------------------------------------------------------------
# build_team_json — season comes from the registry, not the file it replaces
# ---------------------------------------------------------------------------

class TestBuildTeamJsonSeason:
    def test_stale_spring_metadata_is_replaced(self, tmp_path):
        _write(tmp_path / "team.json", {
            "team_name": "The Sharks", "league": "PCLL Majors",
            "season": "Spring 2026", "gc_team_id": "",
        })
        out = build_team_json([], Path("season_stats_20260928.csv"), team=FALL, team_dir=tmp_path)
        assert out["season"] == FALL_SLUG
        assert out["gc_team_id"] == FALL.id
        assert out["team_name"] == "The Sharks"

    def test_refuses_other_season_export(self, tmp_path):
        with pytest.raises(ValueError):
            build_team_json([], Path("Sharks Spring 2026 Stats.csv"), team=FALL, team_dir=tmp_path)

    def test_accepts_current_season_export(self, tmp_path):
        out = build_team_json([], Path("Sharks Fall 2026 Stats.csv"), team=FALL, team_dir=tmp_path)
        assert out["season"] == FALL_SLUG


# ---------------------------------------------------------------------------
# Team-file precedence — stale Spring derived file vs fresh Fall team.json
# ---------------------------------------------------------------------------

class TestPickTeamFile:
    def test_stale_enriched_does_not_mask_current_team_json(self, tmp_path):
        enriched = _write(tmp_path / "team_enriched.json", {"season": "Spring 2026", "roster": SPRING_ROSTER})
        team = _write(tmp_path / "team.json", {"season": FALL_SLUG, "roster": FALL_ROSTER})
        assert pick_team_file([enriched, team], FALL_SLUG) == (team, True)

    def test_current_enriched_keeps_precedence(self, tmp_path):
        enriched = _write(tmp_path / "team_enriched.json", {"season": FALL_SLUG, "roster": FALL_ROSTER})
        team = _write(tmp_path / "team.json", {"season": FALL_SLUG, "roster": FALL_ROSTER})
        assert pick_team_file([enriched, team], FALL_SLUG) == (enriched, True)

    def test_only_old_season_reports_mismatch(self, tmp_path):
        team = _write(tmp_path / "team.json", {"season": "Spring 2026", "roster": SPRING_ROSTER})
        assert pick_team_file([tmp_path / "team_enriched.json", team], FALL_SLUG) == (team, False)

    def test_file_without_season_is_accepted(self, tmp_path):
        team = _write(tmp_path / "team.json", {"roster": FALL_ROSTER})
        assert pick_team_file([team], FALL_SLUG) == (team, True)


# ---------------------------------------------------------------------------
# Announcer — mixed-season roster, only current-season players active
# ---------------------------------------------------------------------------

class TestAnnouncerCurrentSeason:
    def _setup(self, tmp_path, monkeypatch, roster):
        sharks = tmp_path / "sharks"
        announcer = sharks / "announcer"
        announcer.mkdir(parents=True)
        roster_file = _write(announcer / "roster.json", roster)
        monkeypatch.setattr(ae_mod, "DATA_DIR", tmp_path)
        monkeypatch.setattr(ae_mod, "ANNOUNCER_DIR", announcer)
        monkeypatch.setattr(ae_mod, "ROSTER_FILE", roster_file)
        monkeypatch.setattr(ae_mod, "_current_season", lambda: FALL_SLUG)
        return sharks

    def _spring_announcer_roster(self):
        return [
            {"id": "1-maylani-nixon", "first": "Maylani", "last": "Nixon", "number": "1",
             "status": "ready", "is_active": True, "phonetic_hint": "May-lah-nee"},
            {"id": "99-lexi-mckinney", "first": "Lexi", "last": "McKinney", "number": "99",
             "status": "ready", "is_active": True},
        ]

    def test_only_fall_players_active(self, tmp_path, monkeypatch):
        sharks = self._setup(tmp_path, monkeypatch, self._spring_announcer_roster())
        # Stale Spring enriched file must lose to the Fall team.json.
        _write(sharks / "team_enriched.json", {"season": "Spring 2026", "roster": SPRING_ROSTER})
        _write(sharks / "team.json", {"season": FALL_SLUG, "roster": FALL_ROSTER})

        roster = {p["id"]: p for p in ae_mod.load_announcer_roster()}

        active = {pid for pid, p in roster.items() if p.get("is_active", True)}
        assert active == {"99-lexi-mckinney", "31-raelynne-cotter"}
        # Spring player is deactivated, not deleted — hint survives.
        assert roster["1-maylani-nixon"]["is_active"] is False
        assert roster["1-maylani-nixon"]["phonetic_hint"] == "May-lah-nee"

    def test_old_season_team_data_leaves_roster_alone(self, tmp_path, monkeypatch):
        sharks = self._setup(tmp_path, monkeypatch, self._spring_announcer_roster())
        _write(sharks / "team.json", {"season": "Spring 2026", "roster": [SPRING_ROSTER[0]]})
        roster = ae_mod.load_announcer_roster()
        assert ae_mod._bootstrap_roster_from_team() == []
        assert [p["is_active"] for p in roster] == [True, True]


# ---------------------------------------------------------------------------
# /api/roster reports which season it is serving
# ---------------------------------------------------------------------------

class TestRosterEndpointSeason:
    def _client(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sd, "SHARKS_DIR", tmp_path)
        monkeypatch.setattr(sd, "GC_SEASON_SLUG_DEFAULT", FALL_SLUG)
        sd.app.config["TESTING"] = True
        return sd.app.test_client()

    def test_serves_current_season_over_stale_enriched(self, tmp_path, monkeypatch):
        _write(tmp_path / "team_enriched.json", {"season": "Spring 2026", "roster": SPRING_ROSTER})
        _write(tmp_path / "team.json", {"season": FALL_SLUG, "roster": FALL_ROSTER})
        body = self._client(tmp_path, monkeypatch).get("/api/roster").get_json()
        assert body["season"] == FALL_SLUG
        assert body["season_current"] is True
        assert body["current_season"] == FALL_SLUG
        assert [p["first"] for p in body["roster"]] == ["Lexi", "Raelynne"]

    def test_flags_old_season_data(self, tmp_path, monkeypatch):
        _write(tmp_path / "team.json", {"season": "Spring 2026", "roster": SPRING_ROSTER})
        body = self._client(tmp_path, monkeypatch).get("/api/roster").get_json()
        assert body["season"] == "Spring 2026"
        assert body["season_current"] is False
