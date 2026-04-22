"""Tests for tools.autopull.csv_validator."""
from __future__ import annotations
from pathlib import Path
import pytest
from tools.autopull import csv_validator as cv


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_accepts_valid_csv(tmp_path, sample_csv):
    result = cv.validate(sample_csv, known_columns=["Player", "AB", "H", "BB", "K"])
    assert result.accepted is True
    assert result.row_count == 2
    assert set(result.columns) >= {"Player", "AB"}


def test_rejects_non_csv_extension(tmp_path):
    p = _write(tmp_path / "not.txt", "Player,AB\nx,1\n")
    result = cv.validate(p, known_columns=None)
    assert result.accepted is False
    assert "extension" in result.reason.lower()


def test_rejects_empty_file(tmp_path):
    p = _write(tmp_path / "empty.csv", "")
    result = cv.validate(p, known_columns=None)
    assert result.accepted is False
    assert "empty" in result.reason.lower()


def test_rejects_header_only(tmp_path):
    p = _write(tmp_path / "no_rows.csv", "Player,AB\n")
    result = cv.validate(p, known_columns=None)
    assert result.accepted is False
    assert "no data rows" in result.reason.lower()


def test_schema_overlap_below_threshold_critical(tmp_path):
    p = _write(tmp_path / "drifted.csv",
               "Name,Foo,Bar\nA,1,2\nB,3,4\n")
    result = cv.validate(p, known_columns=["Player", "AB", "H", "BB", "K"])
    assert result.accepted is False
    assert result.drift_severity == "critical"


def test_schema_overlap_advisory(tmp_path):
    # 4 of 5 known columns present → 80% overlap
    p = _write(tmp_path / "advisory.csv",
               "Player,AB,H,BB,NEW\nx,1,2,3,4\n")
    result = cv.validate(p, known_columns=["Player", "AB", "H", "BB", "K"])
    assert result.accepted is True
    assert result.drift_severity == "advisory"


def test_quarantine_moves_file(tmp_path, tmp_data_dir):
    p = _write(tmp_path / "bad.csv", "")
    result = cv.validate(p, known_columns=None)
    moved = cv.quarantine(p, result, quarantine_root=tmp_data_dir / "quarantine")
    assert moved.exists()
    assert not p.exists()
    assert "bad.csv" in moved.name
