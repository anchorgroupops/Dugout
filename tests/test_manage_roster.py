"""
Tests for tools/manage_roster.py
"""
import sys
import json
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
import manage_roster as mr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_team(players):
    """Build a team dict from a list of (first, last, number[, core]) tuples."""
    return {
        "roster": [
            {
                "first": p[0],
                "last": p[1],
                "number": p[2],
                "core": p[3] if len(p) > 3 else False,
            }
            for p in players
        ]
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_files(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "TEAM_FILE", tmp_path / "team_merged.json")
    monkeypatch.setattr(mr, "AVAILABILITY_FILE", tmp_path / "availability.json")
    monkeypatch.setattr(mr, "SHARKS_DIR", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# TestLoadTeam
# ---------------------------------------------------------------------------

class TestLoadTeam:
    def test_returns_parsed_json_when_file_exists(self, tmp_files):
        team = make_team([("Alice", "Smith", "7"), ("Bob", "Jones", "3")])
        (tmp_files / "team_merged.json").write_text(json.dumps(team))

        result = mr.load_team()

        assert result is not None
        assert len(result["roster"]) == 2
        assert result["roster"][0]["first"] == "Alice"

    def test_falls_back_to_team_json_when_team_merged_missing(self, tmp_files):
        fallback_team = make_team([("Carol", "Lee", "11")])
        # Write fallback only; TEAM_FILE (team_merged.json) does NOT exist.
        (tmp_files / "team.json").write_text(json.dumps(fallback_team))

        result = mr.load_team()

        assert result is not None
        assert result["roster"][0]["first"] == "Carol"

    def test_returns_none_when_neither_file_exists(self, tmp_files, capsys):
        # Neither team_merged.json nor team.json present.
        result = mr.load_team()

        assert result is None
        captured = capsys.readouterr()
        assert "Error" in captured.out


# ---------------------------------------------------------------------------
# TestLoadAvailability
# ---------------------------------------------------------------------------

class TestLoadAvailability:
    def test_returns_empty_dict_when_file_missing(self, tmp_files):
        result = mr.load_availability()

        assert result == {}

    def test_returns_parsed_dict_when_file_exists(self, tmp_files):
        data = {"Alice Smith": True, "Bob Jones": False}
        (tmp_files / "availability.json").write_text(json.dumps(data))

        result = mr.load_availability()

        assert result == data


# ---------------------------------------------------------------------------
# TestSaveAndLoadAvailabilityRoundTrip
# ---------------------------------------------------------------------------

class TestSaveAndLoadAvailabilityRoundTrip:
    def test_round_trip_preserves_data(self, tmp_files):
        data = {"Alice Smith": True, "Bob Jones": False, "Carol Lee": True}

        mr.save_availability(data)
        loaded = mr.load_availability()

        assert loaded == data

    def test_round_trip_empty_dict(self, tmp_files):
        mr.save_availability({})
        loaded = mr.load_availability()

        assert loaded == {}

    def test_overwrite_updates_values(self, tmp_files):
        initial = {"Alice Smith": True}
        mr.save_availability(initial)

        updated = {"Alice Smith": False, "Bob Jones": True}
        mr.save_availability(updated)
        loaded = mr.load_availability()

        assert loaded == updated


# ---------------------------------------------------------------------------
# TestListPlayers
# ---------------------------------------------------------------------------

class TestListPlayers:
    def test_does_not_crash_with_empty_roster(self, capsys):
        team = {"roster": []}
        mr.list_players(team, {})
        # Should print headers without error.
        captured = capsys.readouterr()
        assert "Name" in captured.out

    def test_shows_x_for_available_player(self, capsys):
        team = make_team([("Alice", "Smith", "7")])
        availability = {"Alice Smith": True}

        mr.list_players(team, availability)

        captured = capsys.readouterr()
        assert "[X]" in captured.out

    def test_shows_empty_bracket_for_unavailable_player(self, capsys):
        team = make_team([("Bob", "Jones", "3")])
        availability = {"Bob Jones": False}

        mr.list_players(team, availability)

        captured = capsys.readouterr()
        assert "[ ]" in captured.out

    def test_default_status_is_available_when_not_in_availability(self, capsys):
        team = make_team([("Carol", "Lee", "11")])

        mr.list_players(team, {})

        captured = capsys.readouterr()
        assert "[X]" in captured.out

    def test_shows_asterisk_for_core_player(self, capsys):
        team = make_team([("Dana", "Park", "5", True)])

        mr.list_players(team, {})

        captured = capsys.readouterr()
        assert "*" in captured.out

    def test_no_asterisk_for_non_core_player(self, capsys):
        team = make_team([("Eve", "Moss", "9", False)])

        mr.list_players(team, {})

        captured = capsys.readouterr()
        # Header line has no asterisk; player line should have none either.
        lines = [l for l in captured.out.splitlines() if "Eve" in l]
        assert lines, "Player line not found"
        assert "*" not in lines[0]

    def test_multiple_players_show_correct_statuses(self, capsys):
        team = make_team([
            ("Alice", "Smith", "7"),
            ("Bob", "Jones", "3"),
        ])
        availability = {"Alice Smith": True, "Bob Jones": False}

        mr.list_players(team, availability)

        captured = capsys.readouterr()
        assert "[X]" in captured.out
        assert "[ ]" in captured.out


# ---------------------------------------------------------------------------
# TestTogglePlayer
# ---------------------------------------------------------------------------

class TestTogglePlayer:
    def _team(self):
        return make_team([
            ("Alice", "Smith", "7"),
            ("Bob", "Jones", "3"),
        ])

    def test_toggles_true_to_false(self):
        team = self._team()
        availability = {"Alice Smith": True}

        result = mr.toggle_player(team, availability, 1)

        assert result is True
        assert availability["Alice Smith"] is False

    def test_toggles_false_to_true(self):
        team = self._team()
        availability = {"Bob Jones": False}

        result = mr.toggle_player(team, availability, 2)

        assert result is True
        assert availability["Bob Jones"] is True

    def test_default_true_toggled_to_false_when_not_in_availability(self):
        team = self._team()
        availability = {}

        result = mr.toggle_player(team, availability, 1)

        assert result is True
        assert availability["Alice Smith"] is False

    def test_modifies_availability_dict_in_place(self):
        team = self._team()
        availability = {"Alice Smith": True}
        original_ref = availability

        mr.toggle_player(team, availability, 1)

        assert availability is original_ref
        assert "Alice Smith" in availability

    def test_returns_false_for_index_zero(self, capsys):
        team = self._team()
        availability = {}

        result = mr.toggle_player(team, availability, 0)

        assert result is False

    def test_returns_false_for_index_greater_than_roster_size(self, capsys):
        team = self._team()
        availability = {}

        result = mr.toggle_player(team, availability, 99)

        assert result is False

    def test_returns_false_for_negative_index(self, capsys):
        team = self._team()
        availability = {}

        result = mr.toggle_player(team, availability, -1)

        assert result is False

    def test_invalid_index_prints_message(self, capsys):
        team = self._team()
        availability = {}

        mr.toggle_player(team, availability, 0)

        captured = capsys.readouterr()
        assert "Invalid" in captured.out

    def test_toggle_last_valid_index(self):
        team = self._team()
        availability = {"Bob Jones": True}

        result = mr.toggle_player(team, availability, 2)

        assert result is True
        assert availability["Bob Jones"] is False

    def test_sequential_toggles_return_to_original(self):
        team = self._team()
        availability = {"Alice Smith": True}

        mr.toggle_player(team, availability, 1)
        assert availability["Alice Smith"] is False

        mr.toggle_player(team, availability, 1)
        assert availability["Alice Smith"] is True


# ---------------------------------------------------------------------------
# TestMain — CLI command-line mode
# ---------------------------------------------------------------------------

class TestMain:
    """Tests for manage_roster.main() CLI mode (non-interactive)."""

    def _setup(self, tmp_files):
        team = make_team([("Alice", "Smith", 1), ("Bob", "Jones", 2)])
        (tmp_files / "team_merged.json").write_text(
            __import__("json").dumps(team))

    def test_list_command_runs_without_error(self, tmp_files, monkeypatch, capsys):
        self._setup(tmp_files)
        monkeypatch.setattr("sys.argv", ["manage_roster.py", "list"])
        mr.main()
        out = capsys.readouterr().out
        assert "Alice" in out

    def test_toggle_command_updates_availability(self, tmp_files, monkeypatch):
        self._setup(tmp_files)
        monkeypatch.setattr("sys.argv", ["manage_roster.py", "toggle", "1"])
        mr.main()
        import json as _json
        data = _json.loads((tmp_files / "availability.json").read_text())
        assert data["Alice Smith"] is False

    def test_toggle_invalid_index_string_prints_message(self, tmp_files, monkeypatch, capsys):
        self._setup(tmp_files)
        monkeypatch.setattr("sys.argv", ["manage_roster.py", "toggle", "notanumber"])
        mr.main()
        out = capsys.readouterr().out
        assert "integer" in out.lower()

    def test_set_all_true_marks_all_active(self, tmp_files, monkeypatch, capsys):
        self._setup(tmp_files)
        monkeypatch.setattr("sys.argv", ["manage_roster.py", "set-all", "true"])
        mr.main()
        import json as _json
        data = _json.loads((tmp_files / "availability.json").read_text())
        assert all(v is True for v in data.values())

    def test_set_all_false_marks_all_inactive(self, tmp_files, monkeypatch, capsys):
        self._setup(tmp_files)
        monkeypatch.setattr("sys.argv", ["manage_roster.py", "set-all", "false"])
        mr.main()
        import json as _json
        data = _json.loads((tmp_files / "availability.json").read_text())
        assert all(v is False for v in data.values())

    def test_main_exits_early_when_team_missing(self, tmp_files, monkeypatch):
        monkeypatch.setattr("sys.argv", ["manage_roster.py", "list"])
        mr.main()  # should not raise even with no team file


# ---------------------------------------------------------------------------
# TestInteractiveMode — interactive while-loop (lines 91-114)
# ---------------------------------------------------------------------------

class TestInteractiveMode:
    """Tests for the interactive mode reached when no CLI args are given."""

    def _setup(self, tmp_files):
        team = make_team([("Alice", "Smith", 1), ("Bob", "Jones", 2)])
        (tmp_files / "team_merged.json").write_text(
            __import__("json").dumps(team))

    def test_quit_immediately(self, tmp_files, monkeypatch, capsys):
        self._setup(tmp_files)
        monkeypatch.setattr("sys.argv", ["manage_roster.py"])
        monkeypatch.setattr("builtins.input", lambda _: "q")
        mr.main()  # should exit cleanly after first 'q'

    def test_all_active_then_quit(self, tmp_files, monkeypatch):
        self._setup(tmp_files)
        monkeypatch.setattr("sys.argv", ["manage_roster.py"])
        inputs = iter(["a", "q"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        mr.main()
        import json as _json
        data = _json.loads((tmp_files / "availability.json").read_text())
        assert all(v is True for v in data.values())

    def test_all_inactive_then_quit(self, tmp_files, monkeypatch):
        self._setup(tmp_files)
        monkeypatch.setattr("sys.argv", ["manage_roster.py"])
        inputs = iter(["n", "q"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        mr.main()
        import json as _json
        data = _json.loads((tmp_files / "availability.json").read_text())
        assert all(v is False for v in data.values())

    def test_toggle_by_index_then_quit(self, tmp_files, monkeypatch):
        self._setup(tmp_files)
        monkeypatch.setattr("sys.argv", ["manage_roster.py"])
        inputs = iter(["1", "q"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        mr.main()
        import json as _json
        data = _json.loads((tmp_files / "availability.json").read_text())
        assert data.get("Alice Smith") is False

    def test_unknown_command_prints_message_then_quit(self, tmp_files, monkeypatch, capsys):
        self._setup(tmp_files)
        monkeypatch.setattr("sys.argv", ["manage_roster.py"])
        inputs = iter(["?bad?", "q"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        mr.main()
        out = capsys.readouterr().out
        assert "Unknown command" in out
