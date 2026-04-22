"""Shared pytest fixtures for dugout.

Fixture scope conventions:
- Pure-data fixtures are session-scoped (immutable) or function-scoped (mutable copies).
- Any fixture that touches the filesystem or env vars is function-scoped.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))


@pytest.fixture
def sample_batting_row():
    return {
        "pa": 10, "ab": 8, "h": 3, "1b": 2, "2b": 1, "3b": 0, "hr": 0,
        "bb": 1, "hbp": 0, "so": 2, "rbi": 1, "sb": 0, "r": 1, "sac": 1,
        "avg": 0.375, "obp": 0.444, "slg": 0.500, "ops": 0.944,
    }


@pytest.fixture
def sample_pitching_row():
    return {
        "ip": "4.2", "er": 2, "bb": 1, "h": 5, "so": 6,
    }


@pytest.fixture
def sample_player():
    return {
        "number": "7",
        "first": "Jane",
        "last": "Doe",
        "name": "Jane Doe",
        "batting": {
            "pa": 10, "ab": 8, "h": 3, "1b": 2, "2b": 1, "3b": 0, "hr": 0,
            "bb": 1, "hbp": 0, "so": 2, "rbi": 1, "sb": 0, "r": 1, "sac": 1,
        },
        "pitching": {"ip": "4.2", "er": 2, "bb": 1, "h": 5, "so": 6},
        "fielding": {"po": 10, "a": 3, "e": 1},
    }


@pytest.fixture
def sample_roster(sample_player):
    return [
        sample_player,
        {"number": "3", "first": "Alex", "last": "Smith", "name": "Alex Smith",
         "batting": {"pa": 20, "ab": 18, "h": 6, "bb": 2, "so": 4, "2b": 2, "hr": 1, "rbi": 5}},
        {"number": "12", "first": "Kim", "last": "Lee", "name": "Kim Lee",
         "batting": {"pa": 15, "ab": 14, "h": 4, "bb": 1, "so": 5, "1b": 3, "2b": 1, "rbi": 2}},
    ]


@pytest.fixture
def clean_env(monkeypatch):
    """Strip env vars that could influence tests (API keys, feature flags)."""
    for var in [
        "OPENAI_API_KEY", "GEMINI_API_KEY", "PINECONE_API_KEY",
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
        "CF_API_TOKEN", "CF_ZONE_ID",
        "DATA_DIR", "LOG_DIR",
    ]:
        monkeypatch.delenv(var, raising=False)
    yield monkeypatch


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """Isolated DATA_DIR for tests that write to disk."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    yield data_dir
