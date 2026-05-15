"""Tests for tools/bootstrap_data.py.

modal is not installed in the CI/test environment, so we inject a fake
modal module into sys.modules before importing bootstrap_data, making
both the module-level decorator calls and the function body testable.
"""
from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Fake modal module — must be injected before bootstrap_data is imported
# ---------------------------------------------------------------------------

def _make_fake_modal():
    fake_app = MagicMock()
    # app.function(...) returns an identity decorator so the original function
    # is preserved (not replaced by a MagicMock call result).
    fake_app.function = lambda *a, **kw: (lambda f: f)
    fake_app.local_entrypoint = lambda *a, **kw: (lambda f: f)

    fake_vol = MagicMock()

    fake_modal = types.ModuleType("modal")
    fake_modal.App = MagicMock(return_value=fake_app)
    fake_modal.Volume = MagicMock()
    fake_modal.Volume.from_name = MagicMock(return_value=fake_vol)
    return fake_modal, fake_vol


def _import_bsd():
    """Import (or reload) bootstrap_data with fake modal in place."""
    sys.modules.pop("tools.bootstrap_data", None)
    fake_modal, fake_vol = _make_fake_modal()
    sys.modules["modal"] = fake_modal
    try:
        import tools.bootstrap_data as bsd
        importlib.reload(bsd)
    finally:
        # Don't leave the fake modal; subsequent imports of modal elsewhere
        # should fail naturally (it isn't installed).
        sys.modules.pop("modal", None)
    # Reattach the fake vol so tests can control vol.commit()
    bsd._test_vol = fake_vol
    return bsd


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBootstrap:
    def _get_bsd_with_redirect(self, tmp_path):
        """Return bsd module + a Path factory that redirects /vol → tmp_path."""
        bsd = _import_bsd()
        orig_Path = Path

        def redirected(p):
            s = str(p)
            if s.startswith("/vol"):
                return orig_Path(tmp_path) / s.lstrip("/")
            return orig_Path(p)

        return bsd, redirected

    def test_bootstrap_writes_team_enriched(self, tmp_path, monkeypatch):
        """bootstrap() writes team_enriched.json with roster data."""
        bsd, redirected = self._get_bsd_with_redirect(tmp_path)
        monkeypatch.setattr(bsd, "Path", redirected)
        result = bsd.bootstrap()
        team_path = tmp_path / "vol" / "softball-gc" / "sharks" / "team_enriched.json"
        assert team_path.exists()
        data = json.loads(team_path.read_text())
        assert data["team_name"] == "The Sharks"

    def test_bootstrap_writes_team_json(self, tmp_path, monkeypatch):
        """bootstrap() writes team.json for backwards compatibility."""
        bsd, redirected = self._get_bsd_with_redirect(tmp_path)
        monkeypatch.setattr(bsd, "Path", redirected)
        bsd.bootstrap()
        team_json = tmp_path / "vol" / "softball-gc" / "sharks" / "team.json"
        assert team_json.exists()

    def test_bootstrap_writes_schedule_json(self, tmp_path, monkeypatch):
        """bootstrap() writes schedule.json with past/upcoming games."""
        bsd, redirected = self._get_bsd_with_redirect(tmp_path)
        monkeypatch.setattr(bsd, "Path", redirected)
        bsd.bootstrap()
        sched = tmp_path / "vol" / "softball-gc" / "sharks" / "schedule.json"
        assert sched.exists()
        data = json.loads(sched.read_text())
        assert "past" in data and "upcoming" in data

    def test_bootstrap_writes_schedule_manual_json(self, tmp_path, monkeypatch):
        """bootstrap() writes schedule_manual.json for sync_daemon compatibility."""
        bsd, redirected = self._get_bsd_with_redirect(tmp_path)
        monkeypatch.setattr(bsd, "Path", redirected)
        bsd.bootstrap()
        sched_manual = tmp_path / "vol" / "softball-gc" / "sharks" / "schedule_manual.json"
        assert sched_manual.exists()

    def test_bootstrap_returns_status_ok(self, tmp_path, monkeypatch):
        """bootstrap() returns {"status": "ok", "files": [...]}."""
        bsd, redirected = self._get_bsd_with_redirect(tmp_path)
        monkeypatch.setattr(bsd, "Path", redirected)
        result = bsd.bootstrap()
        assert result["status"] == "ok"
        assert "team_enriched.json" in result["files"]

    def test_bootstrap_calls_vol_commit(self, tmp_path, monkeypatch):
        """bootstrap() calls vol.commit() to persist data to the volume."""
        bsd, redirected = self._get_bsd_with_redirect(tmp_path)
        monkeypatch.setattr(bsd, "Path", redirected)
        bsd.bootstrap()
        bsd.vol.commit.assert_called_once()

    def test_bootstrap_clears_auth_cooldown_when_present(self, tmp_path, monkeypatch):
        """Lines 98-100: cooldown file is deleted when it exists."""
        bsd, redirected = self._get_bsd_with_redirect(tmp_path)
        monkeypatch.setattr(bsd, "Path", redirected)
        # Create the cooldown file so the conditional branch is taken
        cooldown = tmp_path / "vol" / "softball-gc" / "auth" / ".auth_cooldown"
        cooldown.parent.mkdir(parents=True, exist_ok=True)
        cooldown.write_text("")
        bsd.bootstrap()
        assert not cooldown.exists()

    def test_bootstrap_skips_cooldown_unlink_when_absent(self, tmp_path, monkeypatch):
        """Lines 98-100: no error when cooldown file doesn't exist."""
        bsd, redirected = self._get_bsd_with_redirect(tmp_path)
        monkeypatch.setattr(bsd, "Path", redirected)
        # cooldown does NOT exist — should not raise
        bsd.bootstrap()

    def test_main_calls_bootstrap_remote(self, tmp_path, monkeypatch, capsys):
        """main() calls bootstrap.remote() and prints the result."""
        bsd, _ = self._get_bsd_with_redirect(tmp_path)
        mock_remote = MagicMock(return_value={"status": "ok"})
        monkeypatch.setattr(bsd.bootstrap, "remote", mock_remote, raising=False)
        bsd.main()
        mock_remote.assert_called_once()
        out = capsys.readouterr().out
        assert "Bootstrapping" in out

    def test_team_data_constant_has_roster(self):
        """TEAM_DATA contains a non-empty roster list."""
        bsd = _import_bsd()
        assert isinstance(bsd.TEAM_DATA["roster"], list)
        assert len(bsd.TEAM_DATA["roster"]) > 0

    def test_schedule_data_constant_has_past_and_upcoming(self):
        """SCHEDULE_DATA contains past and upcoming game lists."""
        bsd = _import_bsd()
        assert isinstance(bsd.SCHEDULE_DATA["past"], list)
        assert isinstance(bsd.SCHEDULE_DATA["upcoming"], list)
