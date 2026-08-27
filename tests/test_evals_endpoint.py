"""Tests for the /api/evals endpoint in tools/sync_daemon.py."""
from __future__ import annotations

import json

import pytest

import sync_daemon

ALLOWED_ORIGIN = "http://localhost:3000"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(sync_daemon, "SHARKS_DIR", tmp_path)
    (tmp_path / "team.json").write_text(json.dumps({
        "team_name": "The Sharks",
        "roster": [{
            "first": "Riley", "last": "Vega", "number": "7", "core": True,
            "batting": {"pa": 20, "avg": 0.350, "sb": 5},
            "fielding": {"tc": 30, "po": 20, "a": 8, "fpct": 0.933, "e": 2, "dp": 1},
        }],
    }))
    sync_daemon.app.config["TESTING"] = True
    return sync_daemon.app.test_client()


class TestGetEvals:
    def test_returns_drills_and_fits(self, client, tmp_path):
        res = client.get("/api/evals")
        assert res.status_code == 200
        data = res.get_json()
        assert data["team_name"] == "The Sharks"
        assert len(data["drills"]) > 0
        assert "P" in data["fits"]["positions"]
        assert data["records"] == []
        # static fallback persisted for nginx
        assert (tmp_path / "evals.json").exists()

    def test_includes_existing_records(self, client, tmp_path):
        (tmp_path / "eval_records.json").write_text(json.dumps([
            {"player": "Riley Vega", "drill_id": "of_pop_flies", "made": 7, "attempts": 10},
        ]))
        data = client.get("/api/evals").get_json()
        assert len(data["records"]) == 1
        lf = {e["name"]: e for e in data["fits"]["positions"]["LF"]}
        assert lf["Riley Vega"]["drills_logged"] == 1


class TestPostEvals:
    def test_write_records_roundtrip(self, client, tmp_path):
        res = client.post(
            "/api/evals",
            json={"records": [
                {"player": "Riley Vega", "drill_id": "of_pop_flies", "made": 7, "attempts": 10},
                {"player": "Riley Vega", "drill_id": "home_to_first", "value": 4.2},
            ]},
            headers={"Origin": ALLOWED_ORIGIN},
        )
        assert res.status_code == 200
        data = res.get_json()
        assert len(data["records"]) == 2
        stored = json.loads((tmp_path / "eval_records.json").read_text())
        assert stored[0]["made"] == 7

    def test_invalid_record_rejected(self, client, tmp_path):
        res = client.post(
            "/api/evals",
            json={"records": [{"player": "Riley Vega", "drill_id": "of_pop_flies", "made": 99, "attempts": 10}]},
            headers={"Origin": ALLOWED_ORIGIN},
        )
        assert res.status_code == 400
        assert res.get_json()["error"] == "invalid_records"
        assert not (tmp_path / "eval_records.json").exists()

    def test_disallowed_origin_blocked(self, client, tmp_path):
        res = client.post(
            "/api/evals",
            json={"records": []},
            headers={"Origin": "https://evil.example.com"},
        )
        assert res.status_code == 403
        assert not (tmp_path / "eval_records.json").exists()

    def test_missing_origin_blocked(self, client):
        res = client.post("/api/evals", json={"records": []})
        assert res.status_code == 403

    def test_non_json_rejected(self, client):
        res = client.post("/api/evals", data="records", headers={"Origin": ALLOWED_ORIGIN})
        assert res.status_code == 415
