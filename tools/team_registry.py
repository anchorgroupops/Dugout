"""Team registry — single source of truth for team metadata.

Teams are defined in `config/teams.yaml`. When that file is missing,
`load()` falls back to a synthetic single-team list seeded from legacy
env vars (GC_TEAM_ID, GC_SEASON_SLUG) so Phase 1 can ship without
requiring a `teams.yaml` to exist.
"""
from __future__ import annotations
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SLUG_RE = re.compile(r"^[a-z0-9_-]+$")
_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "teams.yaml"


class RegistryError(RuntimeError):
    """Raised on malformed or inconsistent team registry data."""


@dataclass(frozen=True)
class Team:
    id: str
    season_slug: str
    name: str
    data_slug: str
    league: str = ""
    is_own_team: bool = True
    active: bool = True

    @property
    def stats_url(self) -> str:
        # GC's web URL is /season-stats (not /stats as of 2026-04).
        return f"https://web.gc.com/teams/{self.id}/{self.season_slug}/season-stats"


def load(path: Path | None = None) -> list[Team]:
    path = Path(path) if path else _DEFAULT_PATH
    if not path.exists():
        return _env_fallback()

    try:
        import yaml
    except ImportError as e:
        raise RegistryError("PyYAML is required to read teams.yaml") from e

    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    if not isinstance(data, dict) or "teams" not in data:
        raise RegistryError(f"{path}: top-level key 'teams' missing")

    raw = data["teams"]
    if not isinstance(raw, list) or not raw:
        raise RegistryError(f"{path}: 'teams' must be a non-empty list")

    teams: list[Team] = []
    seen_ids: set[str] = set()
    seen_slugs: set[str] = set()
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise RegistryError(f"{path}[{idx}]: each team must be a mapping")
        team = _parse_team(entry, source=f"{path}[{idx}]")
        if team.id in seen_ids:
            raise RegistryError(f"{path}: duplicate id {team.id!r}")
        if team.data_slug in seen_slugs:
            raise RegistryError(f"{path}: duplicate data_slug {team.data_slug!r}")
        seen_ids.add(team.id)
        seen_slugs.add(team.data_slug)
        teams.append(team)

    return teams


def load_active(path: Path | None = None) -> list[Team]:
    return [t for t in load(path) if t.active]


def require_by_slug(slug: str, path: Path | None = None) -> Team:
    for t in load(path):
        if t.data_slug == slug:
            return t
    raise RegistryError(f"unknown team: {slug!r}")


def _parse_team(entry: dict[str, Any], *, source: str) -> Team:
    required = ("id", "season_slug", "name", "data_slug", "active")
    for key in required:
        if key not in entry:
            raise RegistryError(f"{source}: missing required field {key!r}")

    data_slug = str(entry["data_slug"])
    if not _SLUG_RE.match(data_slug):
        raise RegistryError(
            f"{source}: data_slug {data_slug!r} must match [a-z0-9_-]+"
        )
    team_id = str(entry["id"]).strip()
    if not team_id:
        raise RegistryError(f"{source}: id must be non-empty")

    return Team(
        id=team_id,
        season_slug=str(entry["season_slug"]),
        name=str(entry["name"]),
        data_slug=data_slug,
        league=str(entry.get("league", "")),
        is_own_team=bool(entry.get("is_own_team", True)),
        active=bool(entry["active"]),
    )


def _env_fallback() -> list[Team]:
    team_id = os.getenv("GC_TEAM_ID", "").strip()
    season = os.getenv("GC_SEASON_SLUG", "").strip()
    if not team_id or not season:
        raise RegistryError(
            "No teams.yaml and GC_TEAM_ID/GC_SEASON_SLUG not set"
        )
    return [Team(
        id=team_id,
        season_slug=season,
        name="The Sharks",
        data_slug="sharks",
        league="PCLL",
        is_own_team=True,
        active=True,
    )]
