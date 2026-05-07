import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from opcheck import check_local_pipeline_artifacts


def _check_by_name(result: dict, name: str) -> dict:
    for c in result["checks"]:
        if c["name"] == name:
            return c
    raise KeyError(f"Check not found: {name}")


def _build_full_tree(root: Path) -> None:
    tools_dir = root / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    (tools_dir / "gc_ingest_pipeline.py").write_text("# stub")
    (tools_dir / "scorebook_ocr.py").write_text("# stub")

    sharks_dir = root / "data" / "sharks"
    sharks_dir.mkdir(parents=True, exist_ok=True)

    (sharks_dir / "season_stats.csv").write_text("player,pa\nJane Doe,10\n")

    team = {"roster": [{"number": "7", "name": "Jane Doe"}]}
    (sharks_dir / "team.json").write_text(json.dumps(team))

    swot = {"player_analyses": [{"player": "Jane Doe", "strengths": []}]}
    (sharks_dir / "swot_analysis.json").write_text(json.dumps(swot))

    lineups = {"balanced": {"lineup": [{"name": "Jane Doe", "pa": 5}]}}
    (sharks_dir / "lineups.json").write_text(json.dumps(lineups))

    (sharks_dir / "next_practice.txt").write_text("Drill: hitting practice\n")
    (sharks_dir / "gc_report.json").write_text(json.dumps({"generated": True}))
    (sharks_dir / "stats_history.db").write_bytes(b"SQLite format 3\x00")


class TestCheckLocalPipelineArtifacts:
    def test_empty_directory_all_checks_fail(self, tmp_path):
        result = check_local_pipeline_artifacts(root_dir=tmp_path)

        assert "checks" in result
        assert "summary" in result
        for check in result["checks"]:
            assert check["ok"] is False, f"Expected {check['name']} to fail in empty dir"

    def test_happy_path_all_checks_pass(self, tmp_path):
        _build_full_tree(tmp_path)
        result = check_local_pipeline_artifacts(root_dir=tmp_path)

        for check in result["checks"]:
            assert check["ok"] is True, (
                f"Expected {check['name']} to pass; detail: {check['detail']}"
            )

    def test_gc_ingest_pipeline_exists_check(self, tmp_path):
        _build_full_tree(tmp_path)
        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        assert _check_by_name(result, "gc_ingest_pipeline_exists")["ok"] is True

        (tmp_path / "tools" / "gc_ingest_pipeline.py").unlink()
        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        assert _check_by_name(result, "gc_ingest_pipeline_exists")["ok"] is False

    def test_scorebook_ocr_exists_check(self, tmp_path):
        _build_full_tree(tmp_path)
        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        assert _check_by_name(result, "scorebook_ocr_exists")["ok"] is True

        (tmp_path / "tools" / "scorebook_ocr.py").unlink()
        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        assert _check_by_name(result, "scorebook_ocr_exists")["ok"] is False

    def test_csv_source_ingested_check(self, tmp_path):
        _build_full_tree(tmp_path)
        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        assert _check_by_name(result, "csv_source_ingested")["ok"] is True

        (tmp_path / "data" / "sharks" / "season_stats.csv").unlink()
        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        assert _check_by_name(result, "csv_source_ingested")["ok"] is False

    def test_team_json_has_roster_passes_with_roster(self, tmp_path):
        _build_full_tree(tmp_path)
        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        assert _check_by_name(result, "team_json_has_roster")["ok"] is True

    def test_team_json_has_roster_fails_when_roster_is_empty(self, tmp_path):
        _build_full_tree(tmp_path)
        team_file = tmp_path / "data" / "sharks" / "team.json"
        team_file.write_text(json.dumps({"roster": []}))

        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        assert _check_by_name(result, "team_json_has_roster")["ok"] is False

    def test_team_json_has_roster_fails_when_file_missing(self, tmp_path):
        _build_full_tree(tmp_path)
        (tmp_path / "data" / "sharks" / "team.json").unlink()

        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        assert _check_by_name(result, "team_json_has_roster")["ok"] is False

    def test_swot_analysis_populated_passes_with_analyses(self, tmp_path):
        _build_full_tree(tmp_path)
        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        assert _check_by_name(result, "swot_analysis_populated")["ok"] is True

    def test_swot_analysis_populated_fails_when_player_analyses_is_empty(self, tmp_path):
        _build_full_tree(tmp_path)
        swot_file = tmp_path / "data" / "sharks" / "swot_analysis.json"
        swot_file.write_text(json.dumps({"player_analyses": []}))

        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        assert _check_by_name(result, "swot_analysis_populated")["ok"] is False

    def test_swot_analysis_populated_fails_when_file_missing(self, tmp_path):
        _build_full_tree(tmp_path)
        (tmp_path / "data" / "sharks" / "swot_analysis.json").unlink()

        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        assert _check_by_name(result, "swot_analysis_populated")["ok"] is False

    def test_lineups_json_populated_passes_with_balanced_lineup(self, tmp_path):
        _build_full_tree(tmp_path)
        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        assert _check_by_name(result, "lineups_json_populated")["ok"] is True

    def test_lineups_json_populated_fails_when_balanced_lineup_is_empty(self, tmp_path):
        _build_full_tree(tmp_path)
        lineups_file = tmp_path / "data" / "sharks" / "lineups.json"
        lineups_file.write_text(json.dumps({"balanced": {"lineup": []}}))

        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        assert _check_by_name(result, "lineups_json_populated")["ok"] is False

    def test_lineups_json_populated_fails_when_file_missing(self, tmp_path):
        _build_full_tree(tmp_path)
        (tmp_path / "data" / "sharks" / "lineups.json").unlink()

        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        assert _check_by_name(result, "lineups_json_populated")["ok"] is False

    def test_practice_plan_generated_passes_with_nonempty_file(self, tmp_path):
        _build_full_tree(tmp_path)
        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        assert _check_by_name(result, "practice_plan_generated")["ok"] is True

    def test_practice_plan_generated_fails_when_file_is_empty(self, tmp_path):
        _build_full_tree(tmp_path)
        (tmp_path / "data" / "sharks" / "next_practice.txt").write_text("")

        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        assert _check_by_name(result, "practice_plan_generated")["ok"] is False

    def test_practice_plan_generated_fails_when_file_missing(self, tmp_path):
        _build_full_tree(tmp_path)
        (tmp_path / "data" / "sharks" / "next_practice.txt").unlink()

        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        assert _check_by_name(result, "practice_plan_generated")["ok"] is False

    def test_gc_report_exists_check(self, tmp_path):
        _build_full_tree(tmp_path)
        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        assert _check_by_name(result, "gc_report_exists")["ok"] is True

        (tmp_path / "data" / "sharks" / "gc_report.json").unlink()
        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        assert _check_by_name(result, "gc_report_exists")["ok"] is False

    def test_sqlite_db_exists_check(self, tmp_path):
        _build_full_tree(tmp_path)
        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        assert _check_by_name(result, "sqlite_db_exists")["ok"] is True

        (tmp_path / "data" / "sharks" / "stats_history.db").unlink()
        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        assert _check_by_name(result, "sqlite_db_exists")["ok"] is False

    def test_summary_counts_match_check_results(self, tmp_path):
        _build_full_tree(tmp_path)
        result = check_local_pipeline_artifacts(root_dir=tmp_path)

        checks = result["checks"]
        summary = result["summary"]
        passed = sum(1 for c in checks if c["ok"])
        failed = sum(1 for c in checks if not c["ok"])

        assert summary["total"] == len(checks)
        assert summary["passed"] == passed
        assert summary["failed"] == failed
        assert summary["total"] == summary["passed"] + summary["failed"]

    def test_summary_counts_match_check_results_partial(self, tmp_path):
        _build_full_tree(tmp_path)
        (tmp_path / "data" / "sharks" / "gc_report.json").unlink()
        (tmp_path / "data" / "sharks" / "stats_history.db").unlink()

        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        checks = result["checks"]
        summary = result["summary"]

        passed = sum(1 for c in checks if c["ok"])
        failed = sum(1 for c in checks if not c["ok"])

        assert summary["total"] == len(checks)
        assert summary["passed"] == passed
        assert summary["failed"] == failed
        assert summary["failed"] == 2

    def test_result_has_required_top_level_keys(self, tmp_path):
        result = check_local_pipeline_artifacts(root_dir=tmp_path)

        assert "checks" in result
        assert "summary" in result
        assert "generated_at" in result
        assert isinstance(result["checks"], list)
        assert isinstance(result["summary"], dict)

    def test_each_check_has_required_fields(self, tmp_path):
        result = check_local_pipeline_artifacts(root_dir=tmp_path)

        for check in result["checks"]:
            assert "name" in check
            assert "ok" in check
            assert "detail" in check
            assert isinstance(check["ok"], bool)

    def test_expected_check_names_all_present(self, tmp_path):
        expected_names = {
            "gc_ingest_pipeline_exists",
            "scorebook_ocr_exists",
            "csv_source_ingested",
            "team_json_has_roster",
            "swot_analysis_populated",
            "lineups_json_populated",
            "practice_plan_generated",
            "gc_report_exists",
            "sqlite_db_exists",
        }
        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        found_names = {c["name"] for c in result["checks"]}

        assert expected_names.issubset(found_names)
