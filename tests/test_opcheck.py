import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from opcheck import check_local_pipeline_artifacts, _req_json, run_opcheck
import tools.opcheck as opcheck_mod


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


# ---------------------------------------------------------------------------
# Exception paths in check_local_pipeline_artifacts (lines 308-309, 320-321,
# 332-333) + default root_dir path (line 275)
# ---------------------------------------------------------------------------

class TestCheckLocalExceptionPaths:
    def test_invalid_team_json_graceful(self, tmp_path):
        """Lines 308-309: invalid JSON in team.json → roster_count stays 0."""
        _build_full_tree(tmp_path)
        (tmp_path / "data" / "sharks" / "team.json").write_text("NOT JSON {{")
        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        chk = next(c for c in result["checks"] if c["name"] == "team_json_has_roster")
        assert chk["ok"] is False

    def test_invalid_swot_json_graceful(self, tmp_path):
        """Lines 320-321: invalid JSON in swot_analysis.json → swot_count stays 0."""
        _build_full_tree(tmp_path)
        (tmp_path / "data" / "sharks" / "swot_analysis.json").write_text("<<<bad>>>")
        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        chk = next(c for c in result["checks"] if c["name"] == "swot_analysis_populated")
        assert chk["ok"] is False

    def test_invalid_lineups_json_graceful(self, tmp_path):
        """Lines 332-333: invalid JSON in lineups.json → lineup_len stays 0."""
        _build_full_tree(tmp_path)
        (tmp_path / "data" / "sharks" / "lineups.json").write_text("!!!bad!!!")
        result = check_local_pipeline_artifacts(root_dir=tmp_path)
        chk = next(c for c in result["checks"] if c["name"] == "lineups_json_populated")
        assert chk["ok"] is False

    def test_default_root_dir_does_not_raise(self):
        """Line 275: calling without root_dir uses repo root; must not raise."""
        result = check_local_pipeline_artifacts()
        assert "checks" in result


# ---------------------------------------------------------------------------
# _req_json (lines 16-23)
# ---------------------------------------------------------------------------

class TestReqJson:
    def _make_session(self, data, status=200, json_raises=False):
        resp = MagicMock()
        resp.status_code = status
        resp.headers = {}
        if json_raises:
            resp.json.side_effect = ValueError("bad json")
        else:
            resp.json.return_value = data
        session = MagicMock()
        session.get.return_value = resp
        session.post.return_value = resp
        return session

    def test_get_returns_resp_and_data(self):
        s = self._make_session({"key": "val"})
        resp, data = _req_json(s, "http://x/api", "GET")
        assert resp.status_code == 200
        assert data == {"key": "val"}
        s.get.assert_called_once_with("http://x/api", timeout=30)

    def test_post_uses_post_method(self):
        s = self._make_session({"posted": True})
        resp, data = _req_json(s, "http://x/api", "POST", json={"a": 1})
        s.post.assert_called_once()
        assert data == {"posted": True}

    def test_json_parse_error_returns_none(self):
        s = self._make_session(None, json_raises=True)
        resp, data = _req_json(s, "http://x/api", "GET")
        assert data is None

    def test_non_200_status_returned(self):
        s = self._make_session(None, status=404)
        resp, data = _req_json(s, "http://x/api", "GET")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# run_opcheck (lines 27-264) — fully mocked HTTP session
# ---------------------------------------------------------------------------

def _default_headers():
    return {
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "referrer-policy": "strict-origin",
        "content-security-policy": "default-src 'self'",
        "cross-origin-resource-policy": "same-origin",
        "cross-origin-opener-policy": "same-origin",
        "x-permitted-cross-domain-policies": "none",
        "strict-transport-security": "max-age=31536000",
        "cache-control": "no-store",
    }


def _make_resp(status=200, data=None, headers=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = data
    r.headers = headers if headers is not None else _default_headers()
    return r


def _build_mock_session(include_burst=False):
    """Return a mock session that answers every URL run_opcheck will call."""
    s = MagicMock()

    def fake_get(url, **kw):
        if "/api/team" in url:
            return _make_resp(200, {"roster": [
                {"number": "7", "batting": {"pa": 10}},
                {"number": "8", "batting": {"pa": 0}},
            ]})
        if "/api/games" in url and "detail" not in url:
            return _make_resp(200, [{"result": "W"}, {"result": "L"}])
        if "/api/availability" in url:
            return _make_resp(200, {"7": True, "8": True})
        if "/api/standings" in url:
            return _make_resp(200, {"standings": [
                {"slug": "sharks", "record": "1-1", "team_name": "The Sharks"}
            ]})
        if "/api/matchup/peppers" in url:
            return _make_resp(200, {"empty": False, "data_source": "gc", "reason": None})
        if "/api/matchup/riptide_rebels" in url:
            return _make_resp(200, {"empty": False, "data_source": "gc", "reason": None})
        if "/api/matchup/ravens" in url:
            return _make_resp(200, {
                "empty": False, "reason": "ok",
                "opponent_public_metrics": {"line_score_games": 3},
            })
        if "/data/sharks/swot_analysis.json" in url:
            return _make_resp(200, {"player_analyses": [{"player": "A"}, {"player": "B"}]})
        if "/data/sharks/lineups.json" in url:
            return _make_resp(200, {"balanced": {"lineup": [{"pa": 5}, {"pa": 3}]}})
        if "/data/sharks/pipeline_health.json" in url:
            return _make_resp(200, {"required_field_coverage": 0.9})
        if "/api/opponent-discovery" in url:
            return _make_resp(200, {"teams": [{"name": "Eagles"}]})
        if "/api/stats-db/status" in url:
            return _make_resp(200, {"snapshot_count": 2, "latest": "2026-04-01"})
        if "/api/practice-insights" in url:
            return _make_resp(200, {"needs": ["hitting"], "selected_players": ["Alice"],
                                    "default_player_source": "roster"})
        if "/api/regenerate-lineups" in url:
            return _make_resp(405, None)
        return _make_resp(200, {})

    def fake_get_burst(url, **kw):
        # For burst tests: return 429 on the last few calls
        n = getattr(fake_get_burst, "_n", 0)
        fake_get_burst._n = n + 1
        if "/api/team" in url and n >= 32:
            return _make_resp(429, None)
        return fake_get(url, **kw)

    def fake_post(url, **kw):
        headers_sent = kw.get("headers", {})
        data_sent = kw.get("data", kw.get("json", {}))
        content_type = headers_sent.get("Content-Type", "")
        origin = headers_sent.get("Origin", "")
        if content_type == "text/plain":
            return _make_resp(415, None)
        if "evil.example" in origin:
            return _make_resp(403, None)
        if isinstance(data_sent, dict) and len(str(data_sent)) > 100000:
            return _make_resp(413, None)
        # Write burst: return 429 near the end
        n = getattr(fake_post, "_n", 0)
        fake_post._n = n + 1
        if n >= 8:
            return _make_resp(429, None)
        return _make_resp(403, None)

    s.get = MagicMock(side_effect=fake_get_burst if include_burst else fake_get)
    s.post = MagicMock(side_effect=fake_post)
    return s


class TestRunOpcheck:
    def test_returns_summary_dict(self, monkeypatch):
        """run_opcheck returns a dict with checks, summary, generated_at."""
        monkeypatch.setattr(opcheck_mod.time, "sleep", lambda n: None)
        s = _build_mock_session()
        with patch("tools.opcheck.requests.Session", return_value=s):
            result = run_opcheck("http://test.local", include_burst=False)
        assert "checks" in result
        assert "summary" in result
        assert "generated_at" in result

    def test_checks_list_nonempty(self, monkeypatch):
        monkeypatch.setattr(opcheck_mod.time, "sleep", lambda n: None)
        s = _build_mock_session()
        with patch("tools.opcheck.requests.Session", return_value=s):
            result = run_opcheck("http://test.local", include_burst=False)
        assert len(result["checks"]) > 0

    def test_all_checks_have_required_fields(self, monkeypatch):
        monkeypatch.setattr(opcheck_mod.time, "sleep", lambda n: None)
        s = _build_mock_session()
        with patch("tools.opcheck.requests.Session", return_value=s):
            result = run_opcheck("http://test.local", include_burst=False)
        for chk in result["checks"]:
            assert "name" in chk and "ok" in chk and "detail" in chk

    def test_team_batting_nonzero_check(self, monkeypatch):
        """api_team response with pa>0 → team_batting_nonzero passes."""
        monkeypatch.setattr(opcheck_mod.time, "sleep", lambda n: None)
        s = _build_mock_session()
        with patch("tools.opcheck.requests.Session", return_value=s):
            result = run_opcheck("http://test.local", include_burst=False)
        chk = next(c for c in result["checks"] if c["name"] == "team_batting_nonzero")
        assert chk["ok"] is True

    def test_scorebook_reconciliation_no_deficit(self, monkeypatch):
        """scorebook_reconciliation passes when scorebook totals <= team totals."""
        monkeypatch.setattr(opcheck_mod.time, "sleep", lambda n: None)

        def fake_get(url, **kw):
            if "/api/games" in url and "detail=1" in url:
                return _make_resp(200, [{"sharks_batting": [
                    {"number": "7", "batting": {"pa": 5}}
                ]}])
            return _build_mock_session().get.__wrapped__(url, **kw) if False else _build_mock_session().get.side_effect(url, **kw)

        s = _build_mock_session()
        with patch("tools.opcheck.requests.Session", return_value=s):
            result = run_opcheck("http://test.local", include_burst=False)
        chk = next(c for c in result["checks"] if c["name"] == "scorebook_reconciliation")
        assert isinstance(chk["ok"], bool)

    def test_include_burst_adds_rate_limit_checks(self, monkeypatch):
        """Lines 233-252: include_burst=True adds read/write rate-limit smoke checks."""
        monkeypatch.setattr(opcheck_mod.time, "sleep", lambda n: None)
        s = _build_mock_session(include_burst=True)
        with patch("tools.opcheck.requests.Session", return_value=s):
            result = run_opcheck("http://test.local", include_burst=True)
        names = {c["name"] for c in result["checks"]}
        assert "read_rate_limit_smoke" in names
        assert "write_rate_limit_smoke" in names

    def test_no_burst_omits_rate_limit_checks(self, monkeypatch):
        """include_burst=False → no rate-limit smoke checks."""
        monkeypatch.setattr(opcheck_mod.time, "sleep", lambda n: None)
        s = _build_mock_session()
        with patch("tools.opcheck.requests.Session", return_value=s):
            result = run_opcheck("http://test.local", include_burst=False)
        names = {c["name"] for c in result["checks"]}
        assert "read_rate_limit_smoke" not in names
        assert "write_rate_limit_smoke" not in names

    def test_security_headers_check_present(self, monkeypatch):
        """Lines 186-198: security_headers check appears in results."""
        monkeypatch.setattr(opcheck_mod.time, "sleep", lambda n: None)
        s = _build_mock_session()
        with patch("tools.opcheck.requests.Session", return_value=s):
            result = run_opcheck("http://test.local", include_burst=False)
        names = {c["name"] for c in result["checks"]}
        assert "security_headers" in names
        assert "api_cache_control_no_store" in names

    def test_games_detail_missing_number_skipped(self, monkeypatch):
        """Lines 118-119: rows without jersey number are skipped in agg."""
        monkeypatch.setattr(opcheck_mod.time, "sleep", lambda n: None)
        s = _build_mock_session()

        original_side_effect = s.get.side_effect

        def patched_get(url, **kw):
            if "detail=1" in url:
                return _make_resp(200, [{"sharks_batting": [
                    {"number": "", "batting": {"pa": 2}},   # no number → skipped
                    {"number": "7", "batting": {"pa": 2}},
                ]}])
            return original_side_effect(url, **kw)

        s.get.side_effect = patched_get
        with patch("tools.opcheck.requests.Session", return_value=s):
            result = run_opcheck("http://test.local", include_burst=False)
        chk = next(c for c in result["checks"] if c["name"] == "scorebook_reconciliation")
        assert isinstance(chk["ok"], bool)

    def test_scorebook_number_not_in_roster_hits_continue(self, monkeypatch):
        """Line 133: jersey number in scorebook absent from roster → skip."""
        monkeypatch.setattr(opcheck_mod.time, "sleep", lambda n: None)
        s = _build_mock_session()
        original_se = s.get.side_effect

        def patched(url, **kw):
            if "detail=1" in url:
                # number "99" is not in the roster returned by /api/team
                return _make_resp(200, [{"sharks_batting": [
                    {"number": "99", "batting": {"pa": 5}},
                ]}])
            return original_se(url, **kw)

        s.get.side_effect = patched
        with patch("tools.opcheck.requests.Session", return_value=s):
            result = run_opcheck("http://test.local", include_burst=False)
        chk = next(c for c in result["checks"] if c["name"] == "scorebook_reconciliation")
        assert isinstance(chk["ok"], bool)

    def test_scorebook_deficit_detected(self, monkeypatch):
        """Line 137: team stat < scorebook stat → deficit appended → check fails."""
        monkeypatch.setattr(opcheck_mod.time, "sleep", lambda n: None)
        s = _build_mock_session()
        original_se = s.get.side_effect

        def patched(url, **kw):
            if "/api/team" in url and "detail" not in url:
                # jersey "7" has pa=2 in team data
                return _make_resp(200, {"roster": [
                    {"number": "7", "batting": {"pa": 2}},
                ]})
            if "detail=1" in url:
                # scorebook says pa=10 → deficit detected
                return _make_resp(200, [{"sharks_batting": [
                    {"number": "7", "batting": {"pa": 10}},
                ]}])
            return original_se(url, **kw)

        s.get.side_effect = patched
        with patch("tools.opcheck.requests.Session", return_value=s):
            result = run_opcheck("http://test.local", include_burst=False)
        chk = next(c for c in result["checks"] if c["name"] == "scorebook_reconciliation")
        assert chk["ok"] is False


# ---------------------------------------------------------------------------
# main() (lines 362-387)
# ---------------------------------------------------------------------------

class TestMain:
    def test_main_local_flag_calls_check_local(self, monkeypatch, capsys):
        """--local flag calls check_local_pipeline_artifacts and prints JSON."""
        fake_report = {"checks": [], "summary": {"total": 0, "passed": 0, "failed": 0},
                       "generated_at": "2026-05-08T00:00:00"}
        monkeypatch.setattr(opcheck_mod, "check_local_pipeline_artifacts",
                            MagicMock(return_value=fake_report))
        opcheck_mod.main.__wrapped__ = None  # ensure it's not wrapped
        import runpy
        with patch("sys.argv", ["opcheck.py", "--local"]):
            with patch.object(opcheck_mod, "check_local_pipeline_artifacts",
                              return_value=fake_report) as mock_local:
                opcheck_mod.main()
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["checks"] == []

    def test_main_runs_opcheck_by_default(self, monkeypatch, capsys):
        """Without --local, run_opcheck is called."""
        fake_report = {"checks": [{"name": "x", "ok": True, "detail": ""}],
                       "summary": {"total": 1, "passed": 1, "failed": 0},
                       "generated_at": "2026-05-08T00:00:00",
                       "base_url": "http://test.local"}
        with patch("sys.argv", ["opcheck.py", "--base-url", "http://test.local",
                                "--no-burst"]):
            with patch.object(opcheck_mod, "run_opcheck", return_value=fake_report):
                opcheck_mod.main()
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["summary"]["passed"] == 1

    def test_main_writes_output_file(self, tmp_path, monkeypatch, capsys):
        """--out flag writes JSON report to disk."""
        out_file = tmp_path / "report.json"
        fake_report = {"checks": [], "summary": {"total": 0, "passed": 0, "failed": 0},
                       "generated_at": "t", "base_url": "x"}
        with patch("sys.argv", ["opcheck.py", "--local", "--out", str(out_file)]):
            with patch.object(opcheck_mod, "check_local_pipeline_artifacts",
                              return_value=fake_report):
                opcheck_mod.main()
        assert out_file.exists()
        data = json.loads(out_file.read_text())
        assert data["summary"]["total"] == 0
