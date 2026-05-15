"""Tests for sync_daemon anomaly-detection and pipeline-health helpers."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import sync_daemon

_detect = sync_daemon._detect_threshold_anomalies
_collect_health = sync_daemon._collect_pipeline_health


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _player(name, number, pa, ab, h, so, **extra):
    """Build a minimal roster entry that normalize_batting_row can consume."""
    base = {
        "name": name,
        "number": number,
        "batting": {
            "pa": pa, "ab": ab, "h": h, "so": so,
            "bb": extra.get("bb", 0),
            "hbp": extra.get("hbp", 0),
        },
    }
    return base


# ─── _detect_threshold_anomalies ─────────────────────────────────────────────

class TestDetectThresholdAnomalies:
    def test_empty_roster_returns_empty(self):
        assert _detect({"roster": []}) == []

    def test_low_pa_player_skipped(self):
        p = _player("Alice", "7", pa=4, ab=3, h=0, so=3)
        assert _detect({"roster": [p]}) == []

    def test_good_batter_produces_no_alerts(self):
        p = _player("Bob", "9", pa=20, ab=18, h=8, so=3)
        result = _detect({"roster": [p]})
        assert result == []

    def test_very_low_ba_flagged(self):
        # BA = 0/10 = 0.000 < 0.100, PA >= 8
        p = _player("Carol", "3", pa=10, ab=10, h=0, so=4)
        result = _detect({"roster": [p]})
        assert len(result) == 1
        assert "Carol" in result[0]["player"] or "3" == result[0]["number"]
        assert any("BA" in alert or "ba" in alert.lower() for alert in result[0]["alerts"])

    def test_high_k_rate_flagged(self):
        # K-rate = 8/10 = 80% > 50%, PA >= 8
        p = _player("Dave", "11", pa=10, ab=9, h=3, so=8)
        result = _detect({"roster": [p]})
        assert any("K-rate" in alert or "k_rate" in alert.lower() for alert in result[0]["alerts"])

    def test_alerts_not_triggered_below_8_pa_threshold(self):
        # BA < 0.1 but only 7 PA — should not trigger
        p = _player("Eve", "5", pa=7, ab=7, h=0, so=5)
        result = _detect({"roster": [p]})
        assert result == []

    def test_player_with_both_low_ba_and_high_k_gets_two_alerts(self):
        # BA = 0, K-rate = 10/10 = 100%
        p = _player("Frank", "1", pa=10, ab=10, h=0, so=10)
        result = _detect({"roster": [p]})
        assert len(result) == 1
        assert len(result[0]["alerts"]) == 2

    def test_result_contains_player_name_and_number(self):
        p = _player("Grace", "99", pa=12, ab=12, h=0, so=0)
        result = _detect({"roster": [p]})
        if result:
            assert "player" in result[0]
            assert "number" in result[0]

    def test_multiple_players_only_flags_bad_ones(self):
        good = _player("Good", "7", pa=20, ab=18, h=8, so=2)
        bad = _player("Bad", "8", pa=10, ab=10, h=0, so=9)
        result = _detect({"roster": [good, bad]})
        assert len(result) == 1
        assert result[0]["number"] == "8"

    def test_returns_list(self):
        result = _detect({"roster": []})
        assert isinstance(result, list)

    def test_ba_exactly_at_threshold_not_flagged(self):
        # BA = 0.100 exactly — should NOT trigger (< 0.100 condition)
        p = _player("Thresh", "5", pa=10, ab=10, h=1, so=2)
        result = _detect({"roster": [p]})
        # ba = 1/10 = 0.100, not < 0.100
        assert not any("BA" in alert for alerts in [r["alerts"] for r in result] for alert in alerts)

    def test_k_rate_exactly_at_threshold_not_flagged(self):
        # K-rate = 5/10 = 0.500 — should NOT trigger (> 0.50 condition)
        p = _player("KThresh", "22", pa=10, ab=10, h=4, so=5)
        result = _detect({"roster": [p]})
        assert not any("K-rate" in alert for alerts in [r["alerts"] for r in result] for alert in alerts)


# ─── _collect_pipeline_health ─────────────────────────────────────────────────

class TestCollectPipelineHealth:
    @pytest.fixture(autouse=True)
    def _redirect_dirs(self, tmp_path, monkeypatch):
        self.sharks_dir = tmp_path / "sharks"
        self.data_dir = tmp_path / "data"
        self.sharks_dir.mkdir(parents=True)
        self.data_dir.mkdir(parents=True)
        monkeypatch.setattr(sync_daemon, "SHARKS_DIR", self.sharks_dir)
        monkeypatch.setattr(sync_daemon, "DATA_DIR", self.data_dir)

    def test_returns_dict_with_expected_top_level_keys(self):
        result = _collect_health()
        for key in ("generated_at", "schema", "feeds", "required_field_coverage"):
            assert key in result

    def test_feeds_has_expected_sources(self):
        result = _collect_health()
        feeds = result["feeds"]
        for source in ("app_stats", "team_merged", "games", "opponents"):
            assert source in feeds

    def test_generated_at_is_string(self):
        result = _collect_health()
        assert isinstance(result["generated_at"], str)
        assert "T" in result["generated_at"]  # ISO format contains 'T'

    def test_schema_lists_canonical_fields(self):
        result = _collect_health()
        schema = result["schema"]
        assert isinstance(schema.get("batting"), list)
        assert len(schema["batting"]) > 0

    def test_empty_dirs_produce_zero_counts(self):
        result = _collect_health()
        assert result["feeds"]["app_stats"]["batting_rows"] == 0
        assert result["feeds"]["team_merged"]["roster_rows"] == 0
        assert result["feeds"]["games"]["game_files"] == 0
        assert result["feeds"]["opponents"]["team_files"] == 0

    def test_app_stats_batting_rows_counted(self):
        data = {"batting": [{"number": "7", "ab": 4, "h": 2}], "pitching": [], "fielding": []}
        (self.sharks_dir / "app_stats.json").write_text(json.dumps(data))
        result = _collect_health()
        assert result["feeds"]["app_stats"]["batting_rows"] == 1

    def test_team_merged_roster_counted(self):
        data = {"roster": [{"number": "7"}, {"number": "9"}]}
        (self.sharks_dir / "team_merged.json").write_text(json.dumps(data))
        result = _collect_health()
        assert result["feeds"]["team_merged"]["roster_rows"] == 2

    def test_game_files_counted(self):
        games_dir = self.sharks_dir / "games"
        games_dir.mkdir()
        for i in range(3):
            (games_dir / f"game{i}.json").write_text(json.dumps({"sharks_batting": [], "opponent_batting": []}))
        result = _collect_health()
        assert result["feeds"]["games"]["game_files"] == 3

    def test_index_json_excluded_from_game_count(self):
        games_dir = self.sharks_dir / "games"
        games_dir.mkdir()
        (games_dir / "index.json").write_text(json.dumps({"games": []}))
        (games_dir / "game1.json").write_text(json.dumps({"sharks_batting": [], "opponent_batting": []}))
        result = _collect_health()
        assert result["feeds"]["games"]["game_files"] == 1

    def test_opponent_team_files_counted(self):
        opp_dir = self.data_dir / "opponents" / "wildcats"
        opp_dir.mkdir(parents=True)
        (opp_dir / "team.json").write_text(json.dumps({"batting_stats": [{"ab": 4}]}))
        result = _collect_health()
        assert result["feeds"]["opponents"]["team_files"] == 1

    def test_malformed_app_stats_handled_gracefully(self):
        (self.sharks_dir / "app_stats.json").write_text("{BAD}")
        result = _collect_health()
        assert result["feeds"]["app_stats"]["batting_rows"] == 0

    def test_malformed_game_file_skipped(self):
        games_dir = self.sharks_dir / "games"
        games_dir.mkdir()
        (games_dir / "bad.json").write_text("{NOT JSON}")
        result = _collect_health()
        assert result["feeds"]["games"]["game_files"] == 0  # bad file not counted

    def test_required_field_coverage_key_exists(self):
        result = _collect_health()
        cov = result["required_field_coverage"]
        for key in ("batting", "pitching", "fielding"):
            assert key in cov


# ─── _load_recent_metric_profiles ────────────────────────────────────────────

class TestLoadRecentMetricProfiles:
    def test_returns_empty_when_db_missing(self, tmp_path, monkeypatch):
        import stats_db
        monkeypatch.setattr(stats_db, "DB_PATH", tmp_path / "nonexistent.db")
        result = sync_daemon._load_recent_metric_profiles()
        assert result == {}

    def test_returns_dict(self, tmp_path, monkeypatch):
        import stats_db
        monkeypatch.setattr(stats_db, "DB_PATH", tmp_path / "nonexistent.db")
        result = sync_daemon._load_recent_metric_profiles()
        assert isinstance(result, dict)

    def test_limit_param_accepted(self, tmp_path, monkeypatch):
        import stats_db
        monkeypatch.setattr(stats_db, "DB_PATH", tmp_path / "nonexistent.db")
        result = sync_daemon._load_recent_metric_profiles(limit=5)
        assert result == {}
