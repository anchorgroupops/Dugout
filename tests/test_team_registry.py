"""Tests for tools.team_registry."""
from __future__ import annotations
from pathlib import Path
import pytest
from tools import team_registry as tr


def _yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "teams.yaml"
    p.write_text(content, encoding="utf-8")
    return p


def test_loads_single_team(tmp_path):
    path = _yaml(tmp_path, """
teams:
  - id: abc123
    season_slug: 2026-spring-sharks
    name: The Sharks
    data_slug: sharks
    league: PCLL
    is_own_team: true
    active: true
""")
    teams = tr.load(path)
    assert len(teams) == 1
    assert teams[0].name == "The Sharks"
    assert teams[0].stats_url == "https://web.gc.com/teams/abc123/2026-spring-sharks/season-stats"


def test_load_active_filters(tmp_path):
    path = _yaml(tmp_path, """
teams:
  - id: a
    season_slug: s1
    name: A
    data_slug: a
    active: true
  - id: b
    season_slug: s2
    name: B
    data_slug: b
    active: false
""")
    assert [t.data_slug for t in tr.load_active(path)] == ["a"]
    assert [t.data_slug for t in tr.load(path)] == ["a", "b"]


def test_duplicate_data_slug_raises(tmp_path):
    path = _yaml(tmp_path, """
teams:
  - id: a
    season_slug: s
    name: A
    data_slug: dup
    active: true
  - id: b
    season_slug: s2
    name: B
    data_slug: dup
    active: true
""")
    with pytest.raises(tr.RegistryError, match="duplicate data_slug"):
        tr.load(path)


def test_duplicate_id_raises(tmp_path):
    path = _yaml(tmp_path, """
teams:
  - id: same
    season_slug: s
    name: A
    data_slug: a
    active: true
  - id: same
    season_slug: s2
    name: B
    data_slug: b
    active: true
""")
    with pytest.raises(tr.RegistryError, match="duplicate id"):
        tr.load(path)


def test_bad_data_slug_format_raises(tmp_path):
    path = _yaml(tmp_path, """
teams:
  - id: a
    season_slug: s
    name: A
    data_slug: "Has Spaces!"
    active: true
""")
    with pytest.raises(tr.RegistryError, match="data_slug"):
        tr.load(path)


def test_missing_file_uses_env_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("GC_TEAM_ID", "fallback_id")
    monkeypatch.setenv("GC_SEASON_SLUG", "fallback_season")
    teams = tr.load(tmp_path / "nope.yaml")
    assert len(teams) == 1
    assert teams[0].id == "fallback_id"
    assert teams[0].data_slug == "sharks"


def test_require_by_slug(tmp_path):
    path = _yaml(tmp_path, """
teams:
  - id: a
    season_slug: s
    name: A
    data_slug: a_slug
    active: true
""")
    team = tr.require_by_slug("a_slug", path)
    assert team.id == "a"
    with pytest.raises(tr.RegistryError, match="unknown team"):
        tr.require_by_slug("does_not_exist", path)


def test_defaults_optional_fields(tmp_path):
    path = _yaml(tmp_path, """
teams:
  - id: a
    season_slug: s
    name: A
    data_slug: a
    active: true
""")
    teams = tr.load(path)
    assert teams[0].league == ""
    assert teams[0].is_own_team is True


def test_empty_teams_list_raises(tmp_path):
    path = _yaml(tmp_path, "teams: []\n")
    with pytest.raises(tr.RegistryError, match="non-empty"):
        tr.load(path)


def test_missing_required_field_raises(tmp_path):
    path = _yaml(tmp_path, """
teams:
  - id: a
    season_slug: s
    name: A
    data_slug: a
    # 'active' field is missing
""")
    with pytest.raises(tr.RegistryError, match="active"):
        tr.load(path)


def test_non_mapping_team_entry_raises(tmp_path):
    path = _yaml(tmp_path, "teams:\n  - just_a_string\n")
    with pytest.raises(tr.RegistryError):
        tr.load(path)


def test_env_fallback_raises_when_no_vars(tmp_path, monkeypatch):
    monkeypatch.delenv("GC_TEAM_ID", raising=False)
    monkeypatch.delenv("GC_SEASON_SLUG", raising=False)
    with pytest.raises(tr.RegistryError):
        tr.load(tmp_path / "nope.yaml")


def test_env_fallback_raises_when_only_team_id_set(tmp_path, monkeypatch):
    monkeypatch.setenv("GC_TEAM_ID", "some_id")
    monkeypatch.delenv("GC_SEASON_SLUG", raising=False)
    with pytest.raises(tr.RegistryError):
        tr.load(tmp_path / "nope.yaml")


def test_is_own_team_defaults_true(tmp_path):
    path = _yaml(tmp_path, """
teams:
  - id: x
    season_slug: s
    name: X
    data_slug: x
    active: true
""")
    assert tr.load(path)[0].is_own_team is True


def test_multiple_teams_loaded(tmp_path):
    path = _yaml(tmp_path, """
teams:
  - id: a
    season_slug: s1
    name: A
    data_slug: a
    active: true
  - id: b
    season_slug: s2
    name: B
    data_slug: b
    active: true
""")
    teams = tr.load(path)
    assert len(teams) == 2
    assert {t.data_slug for t in teams} == {"a", "b"}


def test_require_by_slug_raises_for_unknown(tmp_path):
    path = _yaml(tmp_path, """
teams:
  - id: a
    season_slug: s
    name: A
    data_slug: a
    active: true
""")
    with pytest.raises(tr.RegistryError, match="unknown team"):
        tr.require_by_slug("z", path)


def test_team_stats_url_format():
    team = tr.Team(id="abc", season_slug="2026-spring", name="X", data_slug="x")
    assert team.stats_url == "https://web.gc.com/teams/abc/2026-spring/season-stats"


def test_empty_id_raises(tmp_path):
    path = _yaml(tmp_path, """
teams:
  - id: ""
    season_slug: s
    name: A
    data_slug: a
    active: true
""")
    with pytest.raises(tr.RegistryError, match="non-empty"):
        tr.load(path)


def test_missing_top_level_teams_key_raises(tmp_path):
    """YAML file with no 'teams' key should raise RegistryError."""
    path = _yaml(tmp_path, "other_key: value\n")
    with pytest.raises(tr.RegistryError, match="teams"):
        tr.load(path)


def test_yaml_import_error_raises_registry_error(tmp_path, monkeypatch):
    """If PyYAML is not importable, RegistryError should be raised."""
    import builtins
    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("no yaml")
        return real_import(name, *args, **kwargs)

    path = _yaml(tmp_path, "teams:\n  - {id: a, season_slug: s, name: A, data_slug: a, active: true}\n")
    monkeypatch.setattr(builtins, "__import__", mock_import)
    with pytest.raises(tr.RegistryError, match="PyYAML"):
        tr.load(path)
