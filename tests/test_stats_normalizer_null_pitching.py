"""Regression tests for the 2026-04-09 production enrichment freeze.

stats_normalizer.normalize_pitching_row used `row.get("pitching", row or {})`
as a fallback, which returns None (not the default) when the key exists with
an explicit null value. With 10/16 production roster entries shaped like
`{"pitching": None, ...}`, normalize_pitching_row then called `_pick(None,
"ip")`, which did `"ip" in None` → TypeError. Caught by the local try/except
at sync_daemon.py:1137, the failure was silent — team_enriched.json and
stats_anomalies.json stopped being written, and pipeline_health.json froze
because the same bug fired again inside _collect_pipeline_health via
count_populated_fields.
"""
from __future__ import annotations

import stats_normalizer


def test_normalize_pitching_row_handles_explicit_null_pitching():
    player = {"name": "Tester", "number": "42", "pitching": None}
    out = stats_normalizer.normalize_pitching_row(player)
    assert isinstance(out, dict)
    assert out.get("ip", 0) == 0
    assert out.get("er", 0) == 0
    assert out.get("so", 0) == 0


def test_normalize_fielding_row_handles_explicit_null_fielding():
    player = {"name": "Tester", "number": "42", "fielding": None}
    out = stats_normalizer.normalize_fielding_row(player)
    assert isinstance(out, dict)
    assert out.get("po", 0) == 0
    assert out.get("a", 0) == 0
    assert out.get("e", 0) == 0


def test_normalize_pitching_row_flat_row_still_works():
    """If a row has no nested 'pitching' key, the whole row is the pitching source."""
    flat = {"ip": "5.1", "er": 2, "so": 7, "bb": 1, "h": 3}
    out = stats_normalizer.normalize_pitching_row(flat)
    assert out["so"] == 7
    assert out["er"] == 2


def test_normalize_pitching_row_nested_dict_still_works():
    nested = {"name": "Tester", "pitching": {"ip": "5.0", "er": 1, "so": 4}}
    out = stats_normalizer.normalize_pitching_row(nested)
    assert out["so"] == 4
    assert out["er"] == 1


def test_normalize_pitching_row_handles_none_row():
    out = stats_normalizer.normalize_pitching_row(None)
    assert isinstance(out, dict)


def test_pick_handles_non_dict_input():
    assert stats_normalizer._pick(None, "x") is None
    assert stats_normalizer._pick("string", "x") is None
    assert stats_normalizer._pick([], "x") is None


def test_pick_still_returns_value_on_dict():
    assert stats_normalizer._pick({"x": "hello"}, "x") == "hello"
    assert stats_normalizer._pick({"y": "hi"}, "x", "y") == "hi"
    assert stats_normalizer._pick({"x": ""}, "x") is None
    assert stats_normalizer._pick({"x": "-"}, "x") is None
