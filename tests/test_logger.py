"""Tests for tools/logger.py — deterministic decision audit log."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def isolated_logger(tmp_path, monkeypatch):
    """Run logger with CWD = tmp_path so logs/ is written there, not in the repo."""
    monkeypatch.chdir(tmp_path)
    import importlib
    import sys
    if "tools.logger" in sys.modules:
        del sys.modules["tools.logger"]
    from tools import logger
    yield logger, tmp_path


class TestLogDecision:
    def test_creates_logs_dir_and_writes_entry(self, isolated_logger):
        logger, tmp = isolated_logger
        logger.log_decision("swot_analysis", {"team": "Sharks"}, {"out": "data"}, "test rationale")
        log_file = tmp / "logs" / "audit_trail.json"
        assert log_file.exists()
        history = json.loads(log_file.read_text())
        assert len(history) == 1
        entry = history[0]
        assert entry["category"] == "swot_analysis"
        assert entry["input"] == {"team": "Sharks"}
        assert entry["output"] == {"out": "data"}
        assert entry["rationale"] == "test rationale"
        assert "timestamp" in entry

    def test_appends_to_existing_history(self, isolated_logger):
        logger, tmp = isolated_logger
        logger.log_decision("a", {}, {}, "first")
        logger.log_decision("b", {}, {}, "second")
        history = json.loads((tmp / "logs" / "audit_trail.json").read_text())
        assert len(history) == 2
        assert history[0]["rationale"] == "first"
        assert history[1]["rationale"] == "second"

    def test_timestamp_is_eastern_iso(self, isolated_logger):
        logger, tmp = isolated_logger
        logger.log_decision("x", {}, {}, "rat")
        entry = json.loads((tmp / "logs" / "audit_trail.json").read_text())[0]
        # ISO format with timezone offset
        assert "T" in entry["timestamp"]
        assert entry["timestamp"].endswith(tuple(["-04:00", "-05:00"]))  # ET offsets

    def test_bad_write_path_fails_gracefully(self, isolated_logger, capsys):
        logger, tmp = isolated_logger
        # Make audit_trail.json unwritable by writing garbage first so json.load fails,
        # then patch open to raise on write
        (tmp / "logs").mkdir(exist_ok=True)
        (tmp / "logs" / "audit_trail.json").write_text("garbage json{")
        logger.log_decision("x", {}, {}, "rat")
        output = capsys.readouterr().out
        assert "Failed to log decision" in output
