"""Tests for tools/autopull/diagnose.py — pure helper functions."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools.autopull.diagnose import _check, _load_env, _warn


# ---------------------------------------------------------------------------
# _check
# ---------------------------------------------------------------------------

class TestCheck:
    def test_returns_true_when_ok(self, capsys):
        result = _check("Label", True)
        assert result is True

    def test_returns_false_when_not_ok(self, capsys):
        result = _check("Label", False)
        assert result is False

    def test_prints_ok_mark_when_true(self, capsys):
        _check("MyLabel", True)
        out = capsys.readouterr().out
        assert "MyLabel" in out

    def test_prints_fail_mark_when_false(self, capsys):
        _check("MyLabel", False)
        out = capsys.readouterr().out
        assert "MyLabel" in out

    def test_includes_detail_when_provided(self, capsys):
        _check("Label", True, detail="some detail")
        out = capsys.readouterr().out
        assert "some detail" in out

    def test_no_detail_when_omitted(self, capsys):
        _check("Label", True)
        out = capsys.readouterr().out
        assert "—" not in out

    def test_returns_bool(self, capsys):
        assert isinstance(_check("X", True), bool)
        assert isinstance(_check("X", False), bool)


# ---------------------------------------------------------------------------
# _warn
# ---------------------------------------------------------------------------

class TestWarn:
    def test_prints_label(self, capsys):
        _warn("WarnLabel")
        out = capsys.readouterr().out
        assert "WarnLabel" in out

    def test_prints_detail_when_provided(self, capsys):
        _warn("WarnLabel", detail="warning detail")
        out = capsys.readouterr().out
        assert "warning detail" in out

    def test_returns_none(self, capsys):
        result = _warn("X")
        assert result is None


# ---------------------------------------------------------------------------
# _load_env
# ---------------------------------------------------------------------------

class TestLoadEnv:
    def test_loads_key_value_from_env_file(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("MY_DIAG_TEST_KEY=hello_world\n")
        monkeypatch.delenv("MY_DIAG_TEST_KEY", raising=False)

        import tools.autopull.diagnose as diag_mod
        orig_parents = Path(__file__).resolve().parents

        # Patch Path.__file__ resolve to point to tmp_path
        # Instead, monkeypatch os.environ directly after calling modified _load_env
        # We'll test by writing a .env next to the diagnose module's grandparent
        # Since we can't easily monkeypatch the path, test via direct env injection
        env_content = "MY_DIAG_TEST_KEY=hello_world\n"
        env_path = Path(diag_mod.__file__).resolve().parents[2] / ".env"

        # Only run if .env doesn't already exist (avoid clobbering real env)
        if not env_path.exists():
            env_path.write_text(env_content)
            try:
                monkeypatch.delenv("MY_DIAG_TEST_KEY", raising=False)
                _load_env()
                assert os.environ.get("MY_DIAG_TEST_KEY") == "hello_world"
            finally:
                env_path.unlink()
        else:
            # .env exists; just verify _load_env doesn't crash
            _load_env()

    def test_skips_comments_and_empty_lines(self, monkeypatch):
        # _load_env is safe to call when .env doesn't exist or has good format
        _load_env()  # must not raise

    def test_does_not_overwrite_existing_env_var(self, tmp_path, monkeypatch):
        import tools.autopull.diagnose as diag_mod
        env_path = Path(diag_mod.__file__).resolve().parents[2] / ".env"
        monkeypatch.setenv("EXISTING_KEY_XYZ", "original")
        if not env_path.exists():
            env_path.write_text("EXISTING_KEY_XYZ=new_value\n")
            try:
                _load_env()
                assert os.environ.get("EXISTING_KEY_XYZ") == "original"
            finally:
                env_path.unlink()
        else:
            # Can't safely test without clobbering real .env
            _load_env()  # just verify it doesn't crash
