"""Tests for tools/gc_ingest_pipeline.py — auto-discovery and report assembly."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import tools.gc_ingest_pipeline as pipeline_mod
from tools.gc_ingest_pipeline import _assemble_report, _auto_discover_csv


# ---------------------------------------------------------------------------
# _auto_discover_csv — filesystem glob discovery
# ---------------------------------------------------------------------------

class TestAutoDiscoverCsv:
    def test_returns_none_when_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pipeline_mod, "_ROOT_DIR", tmp_path)
        assert _auto_discover_csv() is None

    def test_returns_none_when_no_matching_csvs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pipeline_mod, "_ROOT_DIR", tmp_path)
        target = tmp_path / "Scorebooks" / "Other docs"
        target.mkdir(parents=True)
        (target / "unrelated.csv").write_text("data")
        assert _auto_discover_csv() is None

    def test_returns_matching_csv(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pipeline_mod, "_ROOT_DIR", tmp_path)
        target = tmp_path / "Scorebooks" / "Other docs"
        target.mkdir(parents=True)
        csv_path = target / "Sharks Spring 2026 Stats (1).csv"
        csv_path.write_text("data")
        result = _auto_discover_csv()
        assert result == csv_path

    def test_returns_last_when_multiple_match(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pipeline_mod, "_ROOT_DIR", tmp_path)
        target = tmp_path / "Scorebooks" / "Other docs"
        target.mkdir(parents=True)
        for i in (1, 2, 3):
            (target / f"Sharks Spring 2026 Stats ({i}).csv").write_text("data")
        result = _auto_discover_csv()
        assert result is not None
        assert "Stats (3)" in result.name


# ---------------------------------------------------------------------------
# _assemble_report — schema validation and field population
# ---------------------------------------------------------------------------

class TestAssembleReport:
    def _call(self, tmp_path: Path, **overrides):
        defaults = {
            "csv_path": Path("export.csv"),
            "scorebook_path": None,
            "roster": [],
            "stages": {
                "csv_ingest": {"status": "ok", "detail": "0 players"},
                "sqlite_snapshot": {"status": "ok", "detail": "snapshot_id=1"},
                "scorebook_ocr": {"status": "skipped", "detail": ""},
                "swot_analysis": {"status": "ok", "detail": ""},
                "lineup_optimization": {"status": "ok", "detail": ""},
                "practice_plan": {"status": "ok", "detail": ""},
            },
            "swot_result": None,
            "snapshot_id": None,
            "scorebook_data": None,
        }
        defaults.update(overrides)
        # Patch SHARKS_DIR to an empty tmp dir so no real files are read
        with patch.object(pipeline_mod, "SHARKS_DIR", tmp_path):
            return _assemble_report(**defaults)

    def test_schema_version_present(self, tmp_path):
        report = self._call(tmp_path)
        assert report["schema_version"] == "1.0"

    def test_pipeline_version_present(self, tmp_path):
        report = self._call(tmp_path)
        assert report["pipeline_version"] == "gc_ingest_pipeline:1.0"

    def test_csv_source_from_path(self, tmp_path):
        report = self._call(tmp_path, csv_path=Path("my_export.csv"))
        assert report["csv_source"] == "my_export.csv"

    def test_scorebook_source_none_when_not_provided(self, tmp_path):
        report = self._call(tmp_path, scorebook_path=None)
        assert report["scorebook_source"] is None

    def test_scorebook_source_name_when_provided(self, tmp_path):
        report = self._call(tmp_path, scorebook_path=Path("game1.pdf"))
        assert report["scorebook_source"] == "game1.pdf"

    def test_stages_passed_through(self, tmp_path):
        stages = {"csv_ingest": {"status": "ok", "detail": "5 players"}}
        report = self._call(tmp_path, stages=stages)
        assert report["stages"] == stages

    def test_snapshot_id_passed_through(self, tmp_path):
        report = self._call(tmp_path, snapshot_id=42)
        assert report["snapshot_id"] == 42

    def test_scorebook_data_passed_through(self, tmp_path):
        sb_data = {"method": "pdfplumber", "innings": []}
        report = self._call(tmp_path, scorebook_data=sb_data)
        assert report["scorebook_data"] == sb_data

    def test_team_summary_roster_size(self, tmp_path):
        roster = [{"first": "A"}, {"first": "B"}, {"first": "C"}]
        report = self._call(tmp_path, roster=roster)
        assert report["team_summary"]["roster_size"] == 3

    def test_generated_at_is_string(self, tmp_path):
        report = self._call(tmp_path)
        assert isinstance(report["generated_at"], str)
        assert "T" in report["generated_at"]  # ISO format

    def test_drill_priorities_empty_without_swot(self, tmp_path):
        report = self._call(tmp_path, swot_result=None)
        assert report["drill_priorities"] == []

    def test_game_strategy_notes_empty_without_swot(self, tmp_path):
        report = self._call(tmp_path, swot_result=None)
        assert report["game_strategy_notes"] == []

    def test_swot_summary_empty_without_swot(self, tmp_path):
        report = self._call(tmp_path, swot_result=None)
        assert report["swot_summary"] == {}

    def test_lineup_snapshot_has_required_keys(self, tmp_path):
        report = self._call(tmp_path)
        snap = report["lineup_snapshot"]
        assert "recommended_strategy" in snap
        assert "top_5" in snap
        assert isinstance(snap["top_5"], list)

    def test_lineup_snapshot_defaults_to_balanced(self, tmp_path):
        report = self._call(tmp_path)
        assert report["lineup_snapshot"]["recommended_strategy"] == "balanced"

    def test_lineup_snapshot_loads_from_file(self, tmp_path):
        lineups = {
            "recommended_strategy": "power",
            "power": {
                "lineup": [
                    {"slot": 1, "role": "leadoff", "name": "Jane Smith",
                     "number": "7", "obp": 0.450, "pa": 30}
                ],
                "simulated_runs_per_game": 4.2,
            },
        }
        lineups_file = tmp_path / "lineups.json"
        lineups_file.write_text(json.dumps(lineups))
        with patch.object(pipeline_mod, "SHARKS_DIR", tmp_path):
            report = _assemble_report(
                csv_path=Path("x.csv"), scorebook_path=None,
                roster=[], stages={}, swot_result=None,
                snapshot_id=None, scorebook_data=None,
            )
        assert report["lineup_snapshot"]["recommended_strategy"] == "power"
        assert report["lineup_snapshot"]["simulated_runs_per_game"] == pytest.approx(4.2)
        assert len(report["lineup_snapshot"]["top_5"]) == 1

    def test_team_meta_loaded_from_team_json(self, tmp_path):
        team_data = {
            "team_name": "The Sharks",
            "league": "PCLL Majors",
            "season": "Spring 2026",
            "record": "5-2 (7 GP)",
            "roster": [],
        }
        (tmp_path / "team.json").write_text(json.dumps(team_data))
        with patch.object(pipeline_mod, "SHARKS_DIR", tmp_path):
            report = _assemble_report(
                csv_path=Path("x.csv"), scorebook_path=None,
                roster=[], stages={}, swot_result=None,
                snapshot_id=None, scorebook_data=None,
            )
        assert report["team_summary"]["team_name"] == "The Sharks"
        assert report["team_summary"]["record"] == "5-2 (7 GP)"

    def test_swot_summary_populated_from_swot_result(self, tmp_path):
        swot = {
            "team_swot": {
                "strengths": ["Good OBP"],
                "weaknesses": ["Low power"],
                "opportunities": ["Opponent weak pitching"],
                "threats": ["Weather"],
            },
            "player_analyses": [],
        }
        report = self._call(tmp_path, swot_result=swot)
        summary = report["swot_summary"]
        assert summary["team_strengths"] == ["Good OBP"]
        assert summary["team_weaknesses"] == ["Low power"]

    def test_game_strategy_notes_from_swot(self, tmp_path):
        swot = {
            "team_swot": {
                "strengths": ["Strong defense"],
                "weaknesses": ["Strikeouts"],
                "opportunities": [],
                "threats": [],
            },
            "player_analyses": [],
        }
        report = self._call(tmp_path, swot_result=swot)
        notes = report["game_strategy_notes"]
        assert any("Strikeouts" in n for n in notes)
        assert any("Strong defense" in n for n in notes)
