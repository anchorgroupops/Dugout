"""Shared fixtures for autopull tests."""
from __future__ import annotations
import sqlite3
from pathlib import Path
import pytest


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """Returns a path for a fresh SQLite DB in a temp dir."""
    return tmp_path / "autopull_state.db"


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """Returns a temp data dir with staging and quarantine subdirs."""
    d = tmp_path / "autopull"
    (d / "staging").mkdir(parents=True)
    (d / "quarantine").mkdir(parents=True)
    return d


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    """Write a small valid season stats CSV to disk, return the path."""
    p = tmp_path / "season_stats_sample.csv"
    p.write_text(
        "Player,AB,H,BB,K,HBP,RBI,BA,OBP,SLG\n"
        "Alice Smith,20,8,3,4,1,6,0.400,0.500,0.600\n"
        "Bob Jones,18,5,2,5,0,3,0.278,0.350,0.389\n",
        encoding="utf-8",
    )
    return p
