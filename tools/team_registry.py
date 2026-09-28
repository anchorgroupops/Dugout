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


# ---------------------------------------------------------------------------
# Current-season helpers
#
# Season values in the data files are mixed: GC CSV filenames and old
# team.json files say "Spring 2026", the registry and newer files say
# "2026-fall-sharks". season_key() reduces both to ("2026", "fall") so a file
# from last season can be told apart from this one.
# ---------------------------------------------------------------------------

_TERM_RE = re.compile(r"(spring|summer|fall|autumn|winter)", re.IGNORECASE)
_YEAR_RE = re.compile(r"(20\d\d)")


def season_key(value: str | None) -> tuple[str, str] | None:
    """("2026", "fall") from "Fall 2026" or "2026-fall-sharks"; None if unparseable."""
    text = str(value or "")
    year, term = _YEAR_RE.search(text), _TERM_RE.search(text)
    if not year or not term:
        return None
    t = term.group(1).lower()
    return year.group(1), ("fall" if t == "autumn" else t)


def season_label(value: str | None) -> str:
    """"Fall 2026" — the form GameChanger uses in CSV export filenames."""
    key = season_key(value)
    return f"{key[1].capitalize()} {key[0]}" if key else ""


def is_season(value: str | None, season: str | None) -> bool:
    """True when both parse and name the same season."""
    a, b = season_key(value), season_key(season)
    return a is not None and a == b


def find_season_csv(search_dir: Path, season: str) -> Path | None:
    """Newest "Sharks <Season> Stats*.csv" export for `season`, or None.

    Only the given season is considered. Returning another season's export
    here is how Spring 2026 kept overwriting the Fall roster. "Newest" is by
    mtime, not name: sorted() put "Stats.csv" after "Stats (12).csv".
    """
    label = season_label(season)
    if not label or not search_dir.exists():
        return None
    candidates = list(search_dir.glob(f"Sharks {label} Stats*.csv"))
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def own_team(path: Path | None = None) -> Team:
    """The Sharks' current registry entry (current GC team id + season slug)."""
    return require_by_slug("sharks", path)


def current_gc_ids() -> tuple[str, str]:
    """(team_id, season_slug): GC_TEAM_ID+GC_SEASON_SLUG env if both set, else teams.yaml.

    Replaces the old hard-coded Spring 2026 fallbacks, which sent every run on
    a box without a .env to last season's team page.
    """
    team_id = os.getenv("GC_TEAM_ID", "").strip()
    season = os.getenv("GC_SEASON_SLUG", "").strip()
    if team_id and season:
        return team_id, season
    try:
        t = own_team()
    except RegistryError:
        return team_id, season
    return t.id, t.season_slug  # never mix an env id with a registry season


def pick_team_file(candidates, season: str) -> tuple[Path | None, bool]:
    """First existing candidate that is not from another season.

    A file is skipped only when its `season` names a different season; files
    with no parseable season (or an unparseable `season` argument) are taken
    as-is. Returns (path, current). When
    every existing file is from another season, returns the first one with
    current=False so callers can report the mismatch instead of silently
    presenting last season as this one.
    """
    import json

    first = None
    for p in candidates:
        p = Path(p)
        if not p.exists():
            continue
        first = first or p
        try:
            with p.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        file_season = data.get("season") if isinstance(data, dict) else None
        if season_key(season) is None or season_key(file_season) is None \
                or is_season(file_season, season):
            return p, True
    return first, False
