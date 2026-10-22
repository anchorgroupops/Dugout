"""Regression tests for tools/gc_web_mobile_scraper.py hardening:
  - _fetch_public_games must retry transient HTTP failures (429/5xx/timeout)
    with backoff instead of raising on the first hiccup.
  - Box-score JSON must be written atomically so a crash mid-write can't
    leave a half-written game file for the API/dashboard to read.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import gc_web_mobile_scraper as gwm


class _FakeResp:
    def __init__(self, status_code, body=None, headers=None):
        self.status_code = status_code
        self._body = body if body is not None else []
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._body


def test_fetch_public_games_retries_429_then_succeeds(monkeypatch):
    calls = []

    def fake_get(url, timeout=30):
        calls.append(url)
        if len(calls) == 1:
            return _FakeResp(429, headers={"Retry-After": "0"})
        return _FakeResp(200, body=[{"id": "1"}])

    monkeypatch.setattr(gwm.requests, "get", fake_get)
    monkeypatch.setattr(gwm.time, "sleep", lambda s: None)
    result = gwm._fetch_public_games("team")
    assert len(calls) == 2
    assert result == [{"id": "1"}]


def test_fetch_public_games_retries_timeout_then_raises_after_exhaustion(monkeypatch):
    calls = []

    def fake_get(url, timeout=30):
        calls.append(url)
        raise requests.exceptions.Timeout("slow")

    monkeypatch.setattr(gwm.requests, "get", fake_get)
    monkeypatch.setattr(gwm.time, "sleep", lambda s: None)
    with pytest.raises(requests.exceptions.Timeout):
        gwm._fetch_public_games("team")
    assert len(calls) == 3


def test_fetch_public_games_does_not_retry_client_error(monkeypatch):
    calls = []

    def fake_get(url, timeout=30):
        calls.append(url)
        return _FakeResp(404)

    monkeypatch.setattr(gwm.requests, "get", fake_get)
    monkeypatch.setattr(gwm.time, "sleep", lambda s: None)
    with pytest.raises(requests.exceptions.HTTPError):
        gwm._fetch_public_games("team")
    assert len(calls) == 1


def test_atomic_write_json_leaves_no_partial_file_on_crash(tmp_path, monkeypatch):
    target = tmp_path / "game.json"

    def boom_dump(*a, **k):
        raise RuntimeError("simulated crash mid-write")

    monkeypatch.setattr(gwm.json, "dump", boom_dump)
    with pytest.raises(RuntimeError):
        gwm._atomic_write_json(target, {"a": 1})

    assert not target.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_json_writes_full_valid_json(tmp_path):
    target = tmp_path / "game.json"
    gwm._atomic_write_json(target, {"a": 1, "b": [1, 2, 3]})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1, "b": [1, 2, 3]}


def test_fetch_public_games_http_date_retry_after_does_not_crash(monkeypatch):
    calls, sleeps = [], []

    def fake_get(url, timeout=30):
        calls.append(url)
        if len(calls) == 1:
            return _FakeResp(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
        return _FakeResp(200, body=[{"id": "1"}])

    monkeypatch.setattr(gwm.requests, "get", fake_get)
    monkeypatch.setattr(gwm.time, "sleep", sleeps.append)
    assert gwm._fetch_public_games("team") == [{"id": "1"}]
    assert sleeps == [1]


def test_fetch_public_games_retry_after_is_capped(monkeypatch):
    calls, sleeps = [], []

    def fake_get(url, timeout=30):
        calls.append(url)
        if len(calls) == 1:
            return _FakeResp(429, headers={"Retry-After": "86400"})
        return _FakeResp(200, body=[])

    monkeypatch.setattr(gwm.requests, "get", fake_get)
    monkeypatch.setattr(gwm.time, "sleep", sleeps.append)
    gwm._fetch_public_games("team")
    assert max(sleeps) <= 60.0


# --- Fall 2026 data fixes -------------------------------------------------

def _row(number):
    return {"number": number, "name": f"Player {number}", "pos": "", "batting": {}}


class _FakePage:
    def __init__(self, body):
        self._body = body

    def goto(self, *a, **k):
        pass

    def wait_for_timeout(self, *a):
        pass

    def inner_text(self, _sel):
        return self._body


class _FakePlaywright:
    """Stands in for sync_playwright(): one page whose body text is fixed."""

    def __init__(self, body=""):
        page = _FakePage(body)
        context = type("Ctx", (), {"new_page": lambda s: page, "close": lambda s: None})()
        browser = type("Br", (), {"new_context": lambda s, **k: context, "close": lambda s: None})()
        self.chromium = type("Ch", (), {"launch": lambda s, **k: browser})()

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _game(gid="g1", side="away", team=15, opp=8, opponent="Riptide", ts="2026-10-14T23:00:00Z"):
    return {"id": gid, "game_status": "completed", "start_ts": ts, "home_away": side,
            "opponent_team": {"name": opponent}, "score": {"team": team, "opponent_team": opp}}


def _run(monkeypatch, tmp_path, games, sharks_rows, opp_rows, force=False):
    monkeypatch.setattr(gwm, "GAMES_DIR", tmp_path)
    monkeypatch.setattr(gwm, "_fetch_public_games", lambda team_id: games)
    monkeypatch.setattr(gwm, "sync_playwright", _FakePlaywright())
    monkeypatch.setattr(gwm, "_parse_boxscore_text",
                        lambda body, sharks_side: (sharks_rows, opp_rows, "Riptide"))
    return gwm.sync_recent_games(team_id="T", season_slug="2026-fall-sharks", force=force)


def test_score_team_is_always_the_sharks_even_when_away():
    # GC's public feed reports score.team as the queried team's runs on both sides.
    assert gwm._sharks_score(_game(side="away", team=15, opp=8)) == (15, 8)
    assert gwm._sharks_score(_game(side="home", team=11, opp=9)) == (11, 9)


def test_identical_rosters_still_write_score_but_drop_batting(monkeypatch, tmp_path):
    same = [_row("4"), _row("8")]
    result = _run(monkeypatch, tmp_path, [_game(side="away", team=15, opp=8)], same, list(same))
    assert result["saved"] == 1 and result["failed"] == 0
    data = json.loads(Path(result["outputs"][0]).read_text(encoding="utf-8"))
    assert data["score"] == {"sharks": 15, "opponent": 8}
    assert data["sharks_batting"] == [] and data["opponent_batting"] == []
    assert data["batting_unparsed"] is True


def test_distinct_rosters_are_kept(monkeypatch, tmp_path):
    result = _run(monkeypatch, tmp_path, [_game()], [_row("4")], [_row("7")])
    data = json.loads(Path(result["outputs"][0]).read_text(encoding="utf-8"))
    assert [r["number"] for r in data["sharks_batting"]] == ["4"]
    assert [r["number"] for r in data["opponent_batting"]] == ["7"]
    assert "batting_unparsed" not in data


def test_existing_file_matched_by_gc_game_id_despite_name_drift(monkeypatch, tmp_path):
    old = tmp_path / "2026-10-14_palm_coast_riptide.json"
    old.write_text(json.dumps({"gc_game_id": "g1", "date": "2026-10-14",
                               "opponent": "Palm Coast Riptide", "source": "gc_web_mobile_boxscore"}))
    result = _run(monkeypatch, tmp_path, [_game(gid="g1", opponent="Riptide")], [_row("4")], [_row("7")])
    assert result["outputs"] == [str(old)]
    assert sorted(p.name for p in tmp_path.glob("*.json")) == [old.name]
    assert json.loads(old.read_text(encoding="utf-8"))["game_id"] == old.stem


def test_scorebook_file_is_still_skipped(monkeypatch, tmp_path):
    (tmp_path / "2026-10-14_riptide.json").write_text(json.dumps(
        {"date": "2026-10-14", "opponent": "Riptide", "source": "scorebook_pdf"}))
    result = _run(monkeypatch, tmp_path, [_game()], [_row("4")], [_row("7")])
    assert result["skipped_existing"] == 1 and result["saved"] == 0


def test_doubleheader_writes_two_files(monkeypatch, tmp_path):
    games = [_game(gid="g1", ts="2026-10-14T21:00:00Z", team=3, opp=2),
             _game(gid="g2", ts="2026-10-14T23:00:00Z", team=5, opp=9)]
    result = _run(monkeypatch, tmp_path, games, [_row("4")], [_row("7")])
    assert result["saved"] == 2
    by_id = {json.loads(p.read_text(encoding="utf-8"))["gc_game_id"]: p for p in tmp_path.glob("*.json")}
    assert sorted(by_id) == ["g1", "g2"]
    assert json.loads(by_id["g1"].read_text(encoding="utf-8"))["score"] == {"sharks": 3, "opponent": 2}

    # A re-sync updates each game in place rather than cross-matching by (date, opponent).
    result = _run(monkeypatch, tmp_path, games, [_row("4")], [_row("7")])
    assert len(list(tmp_path.glob("*.json"))) == 2
    assert sorted(result["outputs"]) == sorted(str(p) for p in by_id.values())


def test_force_does_not_replace_scorebook_with_unparsed_batting(monkeypatch, tmp_path):
    book = tmp_path / "2026-10-14_riptide.json"
    original = {"date": "2026-10-14", "opponent": "Riptide", "source": "scorebook_pdf",
                "sharks_batting": [_row("4")]}
    book.write_text(json.dumps(original))
    same = [_row("4"), _row("8")]
    result = _run(monkeypatch, tmp_path, [_game()], same, list(same), force=True)
    assert result["skipped_existing"] == 1 and result["saved"] == 0
    assert json.loads(book.read_text(encoding="utf-8")) == original


def test_defaults_come_from_registry_not_spring(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(gwm, "current_gc_ids", lambda: ("FALL", "2026-fall-sharks"))
    monkeypatch.setattr(gwm, "GAMES_DIR", tmp_path)
    monkeypatch.setattr(gwm, "sync_playwright", _FakePlaywright())
    monkeypatch.setattr(gwm, "_fetch_public_games", lambda team_id: seen.setdefault("team", team_id) and [])
    gwm.sync_recent_games()
    assert seen["team"] == "FALL"


def test_missing_team_ids_fail_loudly(monkeypatch):
    monkeypatch.setattr(gwm, "current_gc_ids", lambda: ("", ""))
    monkeypatch.setattr(gwm, "sync_playwright", _FakePlaywright())
    with pytest.raises(RuntimeError, match="team"):
        gwm.sync_recent_games()


def test_cli_defaults_come_from_registry(monkeypatch):
    seen = {}
    monkeypatch.setattr(gwm, "current_gc_ids", lambda: ("FALL", "2026-fall-sharks"))
    monkeypatch.setattr(gwm, "sync_recent_games", lambda **k: seen.update(k) or {"saved": 1})
    monkeypatch.setattr(sys, "argv", ["gc_web_mobile_scraper.py"])
    assert gwm.main() == 0
    assert (seen["team_id"], seen["season_slug"]) == ("FALL", "2026-fall-sharks")
