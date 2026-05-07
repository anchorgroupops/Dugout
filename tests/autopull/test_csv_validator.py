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


# ---------------------------------------------------------------------------
# _overlap — schema drift metric
# ---------------------------------------------------------------------------

def test_rejects_utf8_decode_error(tmp_path):
    p = tmp_path / "bad_encoding.csv"
    p.write_bytes(b"\xff\xfe Player,AB\r\n")  # UTF-16 BOM — not valid UTF-8
    result = cv.validate(p, known_columns=None)
    assert result.accepted is False
    assert "utf" in result.reason.lower() or "decode" in result.reason.lower()


def test_rejects_empty_header_columns(tmp_path):
    # File with a header row of only whitespace/commas — no non-empty column names
    p = _write(tmp_path / "blank_header.csv", "  ,  ,  \nx,y,z\n")
    result = cv.validate(p, known_columns=None)
    assert result.accepted is False
    assert "column" in result.reason.lower()


def test_stop_iteration_on_empty_csv_reader(tmp_path, monkeypatch):
    """csv.reader yields nothing (StopIteration) for a non-empty file — line 45."""
    p = tmp_path / "nonempty.csv"
    p.write_text("x", encoding="utf-8")  # size > 0 bypasses early-exit
    monkeypatch.setattr(cv.csv, "reader", lambda *a, **kw: iter([]))
    result = cv.validate(p, known_columns=None)
    assert result.accepted is False
    assert "empty" in result.reason.lower()


def test_csv_error_during_parse(tmp_path, monkeypatch):
    """csv.reader raises csv.Error — lines 49-50."""
    import csv as _csv
    p = tmp_path / "bad.csv"
    p.write_text("some,content\n", encoding="utf-8")

    def _error_reader(*a, **kw):
        def _gen():
            raise _csv.Error("bad line format")
            yield  # noqa: unreachable — makes it a generator
        return _gen()

    monkeypatch.setattr(cv.csv, "reader", _error_reader)
    result = cv.validate(p, known_columns=None)
    assert result.accepted is False
    assert "csv" in result.reason.lower() or "parse" in result.reason.lower()


class TestOverlap:
    def test_full_overlap(self):
        assert cv._overlap(["a", "b", "c"], ["a", "b", "c"]) == 1.0

    def test_empty_known_cols_returns_one(self):
        assert cv._overlap(["a", "b"], []) == 1.0

    def test_zero_overlap(self):
        assert cv._overlap(["x", "y"], ["a", "b"]) == 0.0

    def test_partial_overlap(self):
        result = cv._overlap(["a", "b", "x", "y"], ["a", "b", "c", "d"])
        assert abs(result - 0.5) < 1e-9

    def test_extra_csv_cols_dont_reduce_overlap(self):
        # CSV has extra col "extra" not in known; known cols fully covered
        result = cv._overlap(["a", "b", "extra"], ["a", "b"])
        assert result == 1.0

    def test_returns_float(self):
        result = cv._overlap(["a"], ["a"])
        assert isinstance(result, float)

    def test_single_missing_known_col(self):
        result = cv._overlap(["a", "b"], ["a", "b", "c"])
        assert abs(result - 2 / 3) < 1e-9
