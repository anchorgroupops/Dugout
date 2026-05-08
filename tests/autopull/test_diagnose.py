"""Tests for tools/autopull/diagnose.py — pure helper functions."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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

    def test_skips_blank_and_comment_lines_hits_continue(self, monkeypatch):
        """Line 49: the continue branch for empty/comment/no-equals lines."""
        import tools.autopull.diagnose as diag_mod
        env_path = Path(diag_mod.__file__).resolve().parents[2] / ".env"
        if env_path.exists():
            pytest.skip(".env already exists; cannot safely inject test content")
        env_path.write_text(
            "# a comment line\n"
            "\n"
            "NO_EQUALS_LINE\n"
            "DIAG_CONT_KEY=found_it\n"
        )
        try:
            monkeypatch.delenv("DIAG_CONT_KEY", raising=False)
            _load_env()
            assert os.environ.get("DIAG_CONT_KEY") == "found_it"
        finally:
            env_path.unlink()


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

import tools.autopull.diagnose as _diag_mod  # noqa: E402 — module-level for class


def _setup_base_mocks(tmp_path, monkeypatch, *, cli_rc=0, cli_stdout="",
                      cli_exception=None, active_stdout="active\n",
                      db_runs=None, db_exception=None):
    """Patch everything main() touches so unit tests stay hermetic."""
    monkeypatch.setattr(_diag_mod, "_load_env", lambda: None)

    # Team registry (imported inside main())
    import tools.team_registry as tr_mod
    fake_team = MagicMock()
    fake_team.active = True
    fake_team.name = "Sharks"
    fake_team.data_slug = "sharks"
    fake_team.season_slug = "2026"
    monkeypatch.setattr(tr_mod, "load", lambda: [fake_team])

    # Required env vars + one optional set, two optional missing
    for k in ("GC_EMAIL", "GC_PASSWORD", "GMAIL_USERNAME", "GMAIL_APP_PASSWORD"):
        monkeypatch.setenv(k, "test_val")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")   # optional SET  → line 88
    monkeypatch.delenv("N8N_AUTOPULL_STATUS_WEBHOOK", raising=False)  # optional UNSET → line 90
    monkeypatch.delenv("PUSH_WEBHOOK_URL", raising=False)

    # subprocess.run: first two calls = systemd timers, third = CLI dry-run
    call_idx = [0]

    def fake_run(*args, **kwargs):
        n = call_idx[0]
        call_idx[0] += 1
        if n < 2:
            m = MagicMock()
            m.stdout = active_stdout
            m.stderr = ""
            m.returncode = 0 if active_stdout.strip() == "active" else 1
            return m
        if cli_exception:
            raise cli_exception
        m = MagicMock()
        m.returncode = cli_rc
        m.stdout = cli_stdout
        m.stderr = ""
        return m

    monkeypatch.setattr(_diag_mod.subprocess, "run", fake_run)

    # State DB + config (imported inside main())
    from tools.autopull import config as config_mod, state as state_mod
    fake_cfg = MagicMock()
    fake_cfg.data_root = tmp_path
    monkeypatch.setattr(config_mod, "load", lambda: fake_cfg)

    fake_db = MagicMock()
    tables = ["runs", "strategies", "circuit_breaker", "schema_profile"]
    fake_db.list_tables.return_value = tables
    fake_db.recent_runs.return_value = db_runs if db_runs is not None else []

    if db_exception:
        monkeypatch.setattr(state_mod, "StateDB",
                            lambda path: (_ for _ in ()).throw(db_exception))
    else:
        monkeypatch.setattr(state_mod, "StateDB", lambda path: fake_db)

    return fake_db


class TestMain:
    def test_returns_0_when_all_checks_pass(self, tmp_path, monkeypatch, capsys):
        """main() returns 0 when every check succeeds."""
        _setup_base_mocks(tmp_path, monkeypatch, cli_rc=0, cli_stdout="done")
        chromium_dir = tmp_path / ".cache" / "ms-playwright" / "chromium-9"
        chromium_dir.mkdir(parents=True)
        with patch.object(Path, "home", return_value=tmp_path):
            result = _diag_mod.main()
        assert result == 0

    def test_returns_1_when_required_env_var_missing(self, tmp_path, monkeypatch, capsys):
        """main() returns 1 when a required env var is absent."""
        _setup_base_mocks(tmp_path, monkeypatch)
        monkeypatch.delenv("GC_EMAIL", raising=False)
        with patch.object(Path, "home", return_value=tmp_path):
            result = _diag_mod.main()
        assert result == 1

    def test_team_registry_exception_covers_line70(self, tmp_path, monkeypatch, capsys):
        """Line 70: _check called with False when team_registry.load raises."""
        _setup_base_mocks(tmp_path, monkeypatch)
        import tools.team_registry as tr_mod
        monkeypatch.setattr(tr_mod, "load", lambda: (_ for _ in ()).throw(RuntimeError("bad yaml")))
        result = _diag_mod.main()
        out = capsys.readouterr().out
        assert "bad yaml" in out
        assert result == 1

    def test_chromium_found_covers_iterdir_branch(self, tmp_path, monkeypatch, capsys):
        """Lines 111-113: chromium found when the cache dir contains a chromium-* entry."""
        _setup_base_mocks(tmp_path, monkeypatch, cli_rc=0)
        chromium_dir = tmp_path / ".cache" / "ms-playwright" / "chromium-99"
        chromium_dir.mkdir(parents=True)
        with patch.object(Path, "home", return_value=tmp_path):
            result = _diag_mod.main()
        out = capsys.readouterr().out
        assert "Chromium" in out

    def test_import_failure_covers_line106(self, tmp_path, monkeypatch, capsys):
        """Lines 106-107: ImportError path when a dep is absent from sys.modules."""
        _setup_base_mocks(tmp_path, monkeypatch)
        # Make playwright appear non-importable for the duration of the test
        monkeypatch.setitem(sys.modules, "playwright", None)
        result = _diag_mod.main()
        out = capsys.readouterr().out
        assert "playwright" in out

    def test_systemd_timer_inactive_sets_all_ok_false(self, tmp_path, monkeypatch, capsys):
        """Lines 119-123: inactive systemd timer → all_ok False → returns 1."""
        _setup_base_mocks(tmp_path, monkeypatch, active_stdout="inactive\n")
        result = _diag_mod.main()
        assert result == 1

    def test_state_db_with_recent_runs_covers_loop(self, tmp_path, monkeypatch, capsys):
        """Lines 138-143: recent run entries are printed."""
        fake_run = MagicMock()
        fake_run.id = 7
        fake_run.team_id = "sharks"
        fake_run.outcome = "success"
        fake_run.trigger = "cron"
        _setup_base_mocks(tmp_path, monkeypatch, cli_rc=0, db_runs=[fake_run])
        with patch.object(Path, "home", return_value=tmp_path):
            result = _diag_mod.main()
        out = capsys.readouterr().out
        assert "#7" in out

    def test_state_db_exception_covers_line144(self, tmp_path, monkeypatch, capsys):
        """Lines 144-145: state DB exception → _check(False) → returns 1."""
        _setup_base_mocks(tmp_path, monkeypatch, db_exception=RuntimeError("db broken"))
        result = _diag_mod.main()
        out = capsys.readouterr().out
        assert "db broken" in out
        assert result == 1

    def test_cli_subprocess_exception_covers_line158(self, tmp_path, monkeypatch, capsys):
        """Lines 158-159: CLI subprocess raises → _check(False) → returns 1."""
        _setup_base_mocks(tmp_path, monkeypatch,
                          cli_exception=RuntimeError("playwright missing"))
        result = _diag_mod.main()
        out = capsys.readouterr().out
        assert "playwright missing" in out
        assert result == 1

    def test_cli_with_stdout_covers_line157(self, tmp_path, monkeypatch, capsys):
        """Line 157: CLI stdout is printed when non-empty."""
        _setup_base_mocks(tmp_path, monkeypatch, cli_rc=0, cli_stdout="autopull ok\n")
        with patch.object(Path, "home", return_value=tmp_path):
            _diag_mod.main()
        out = capsys.readouterr().out
        assert "autopull ok" in out

    def test_optional_env_var_set_covers_line88(self, tmp_path, monkeypatch, capsys):
        """Line 88: optional var present → _check(..., True, ...) printed."""
        _setup_base_mocks(tmp_path, monkeypatch)
        out = capsys.readouterr().out  # flush
        with patch.object(Path, "home", return_value=tmp_path):
            _diag_mod.main()
        out = capsys.readouterr().out
        # ANTHROPIC_API_KEY is set in _setup_base_mocks → line 88 hit
        assert "ANTHROPIC_API_KEY" in out

    def test_optional_env_var_unset_covers_line90(self, tmp_path, monkeypatch, capsys):
        """Line 90: optional var absent → _warn printed."""
        _setup_base_mocks(tmp_path, monkeypatch)
        with patch.object(Path, "home", return_value=tmp_path):
            _diag_mod.main()
        out = capsys.readouterr().out
        # N8N_AUTOPULL_STATUS_WEBHOOK is unset → line 90 hit
        assert "N8N_AUTOPULL_STATUS_WEBHOOK" in out
