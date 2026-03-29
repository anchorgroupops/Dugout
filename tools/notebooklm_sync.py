"""
notebooklm_sync.py — Rich data payload builder for NotebookLM.

Reads team.json, all game JSONs, and all player JSONs, then builds a
comprehensive Markdown document covering full batting/pitching/fielding stats,
game-by-game results with both teams' stats, and opponent scouting data.

Output: data/notebooklm_payload.md

Usage:
  python notebooklm_sync.py
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
TEAM_DIR = DATA_DIR / os.getenv("TEAM_SLUG", "sharks")
PLAYERS_DIR = TEAM_DIR / "players"
PAYLOAD_FILE = DATA_DIR / "notebooklm_payload.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _fmt(val, decimals: int = 3) -> str:
    if val is None or val == "" or val == "-":
        return "-"
    try:
        fval = float(str(val).replace(",", ""))
        return f"{fval:.{decimals}f}"
    except (TypeError, ValueError):
        return str(val)


def _int(val) -> str:
    if val is None or val == "" or val == "-":
        return "-"
    try:
        return str(int(float(str(val))))
    except (TypeError, ValueError):
        return str(val)


def _player_name(p: dict) -> str:
    name = p.get("name") or f"{p.get('first', '')} {p.get('last', '')}".strip()
    return name or "Unknown"


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _batting_std_table(players: list[dict], section_name: str = "Batting — Standard") -> str:
    if not players:
        return f"### {section_name}\n_No data_\n\n"

    header = "| # | Player | GP | PA | AB | AVG | OBP | OPS | H | 1B | 2B | 3B | HR | RBI | R | BB | SO | SB |"
    sep    = "|---|--------|----|----|----|----|-----|-----|---|----|----|----|----|-----|---|----|----|-----|"
    rows = [header, sep]

    for p in players:
        b = p.get("batting") or p
        num = _int(p.get("number", ""))
        name = _player_name(p)
        rows.append(
            f"| {num} | {name} | {_int(b.get('gp','-'))} | {_int(b.get('pa','-'))} | "
            f"{_int(b.get('ab','-'))} | {_fmt(b.get('avg','-'))} | {_fmt(b.get('obp','-'))} | "
            f"{_fmt(b.get('ops','-'))} | {_int(b.get('h','-'))} | {_int(b.get('singles',b.get('1b','-')))} | "
            f"{_int(b.get('doubles',b.get('2b','-')))} | {_int(b.get('triples',b.get('3b','-')))} | "
            f"{_int(b.get('hr','-'))} | {_int(b.get('rbi','-'))} | {_int(b.get('r','-'))} | "
            f"{_int(b.get('bb','-'))} | {_int(b.get('so','-'))} | {_int(b.get('sb','-'))} |"
        )

    return f"### {section_name}\n" + "\n".join(rows) + "\n\n"


def _batting_adv_table(players: list[dict]) -> str:
    if not players:
        return "### Batting — Advanced\n_No data_\n\n"

    header = "| # | Player | PA | QAB | QAB% | BB/K | C% | HHB | LD% | GB% | FB% | BABIP | BA/RISP |"
    sep    = "|---|--------|----|-----|------|------|----|-----|-----|-----|-----|-------|---------|"
    rows = [header, sep]

    for p in players:
        b = p.get("batting_advanced") or p.get("batting") or p
        num = _int(p.get("number", ""))
        name = _player_name(p)
        rows.append(
            f"| {num} | {name} | {_int(b.get('pa','-'))} | {_int(b.get('qab','-'))} | "
            f"{_fmt(b.get('qab_pct','-'),2)} | {_fmt(b.get('bb_k',b.get('bb_per_k','-')),3)} | "
            f"{_fmt(b.get('c_pct','-'),2)} | {_int(b.get('hhb','-'))} | "
            f"{_fmt(b.get('ld_pct','-'),2)} | {_fmt(b.get('gb_pct','-'),2)} | "
            f"{_fmt(b.get('fb_pct','-'),2)} | {_fmt(b.get('babip','-'))} | "
            f"{_fmt(b.get('ba_risp','-'))} |"
        )

    return "### Batting — Advanced\n" + "\n".join(rows) + "\n\n"


def _pitching_std_table(players: list[dict]) -> str:
    if not players:
        return "### Pitching — Standard\n_No data_\n\n"

    header = "| # | Player | GP | GS | W | L | SV | IP | H | R | ER | BB | SO | ERA | WHIP |"
    sep    = "|---|--------|----|----|-|-|----|----|---|---|----|----|----|----|------|"
    rows = [header, sep]

    for p in players:
        pit = p.get("pitching") or p
        if not any(pit.get(k) for k in ("ip", "gp", "w", "l", "er", "so")):
            continue
        num = _int(p.get("number", ""))
        name = _player_name(p)
        rows.append(
            f"| {num} | {name} | {_int(pit.get('gp','-'))} | {_int(pit.get('gs','-'))} | "
            f"{_int(pit.get('w','-'))} | {_int(pit.get('l','-'))} | {_int(pit.get('sv','-'))} | "
            f"{pit.get('ip','-')} | {_int(pit.get('h','-'))} | {_int(pit.get('r','-'))} | "
            f"{_int(pit.get('er','-'))} | {_int(pit.get('bb','-'))} | {_int(pit.get('so','-'))} | "
            f"{_fmt(pit.get('era','-'),2)} | {_fmt(pit.get('whip','-'),2)} |"
        )

    if len(rows) <= 2:
        return "### Pitching — Standard\n_No pitchers with data_\n\n"
    return "### Pitching — Standard\n" + "\n".join(rows) + "\n\n"


def _fielding_std_table(players: list[dict]) -> str:
    if not players:
        return "### Fielding — Standard\n_No data_\n\n"

    header = "| # | Player | TC | PO | A | E | FPCT | DP |"
    sep    = "|---|--------|----|----|---|---|------|-----|"
    rows = [header, sep]

    for p in players:
        fld = p.get("fielding") or p
        if not any(fld.get(k) for k in ("po", "a", "e", "tc")):
            continue
        num = _int(p.get("number", ""))
        name = _player_name(p)
        rows.append(
            f"| {num} | {name} | {_int(fld.get('tc','-'))} | {_int(fld.get('po','-'))} | "
            f"{_int(fld.get('a','-'))} | {_int(fld.get('e','-'))} | "
            f"{_fmt(fld.get('fpct','-'))} | {_int(fld.get('dp','-'))} |"
        )

    if len(rows) <= 2:
        return "### Fielding — Standard\n_No fielding data_\n\n"
    return "### Fielding — Standard\n" + "\n".join(rows) + "\n\n"


def _game_section(game: dict) -> str:
    date = game.get("date", "Unknown date")
    opp = game.get("opponent", "Unknown")
    result = game.get("result", "")
    score = game.get("score", {})
    sharks_score = score.get("sharks")
    opp_score = score.get("opponent")

    score_str = ""
    if sharks_score is not None and opp_score is not None:
        score_str = f" ({sharks_score}-{opp_score})"
        if not result:
            result = "W" if sharks_score > opp_score else ("L" if sharks_score < opp_score else "T")

    title = f"### {date} vs {opp}"
    if result or score_str:
        title += f" — {result}{score_str}"

    lines = [title, ""]

    # Sharks stats
    sharks_data = game.get("sharks", {})
    opp_data = game.get("opponent_stats", game.get("opponent_batting", []))

    # Handle legacy format (flat sharks_batting list)
    if "sharks_batting" in game and not sharks_data:
        sharks_batting = game.get("sharks_batting", [])
        if sharks_batting:
            lines.append("#### Sharks Batting")
            lines.append(_batting_std_table(sharks_batting, "").replace("### Batting — Standard\n", ""))
    elif isinstance(sharks_data, dict) and sharks_data:
        lines.append("#### Sharks Batting")
        if "batting" in sharks_data:
            lines.append(_batting_std_table(sharks_data["batting"], "").replace("### Batting — Standard\n", ""))
        if "pitching" in sharks_data:
            lines.append("#### Sharks Pitching")
            lines.append(_pitching_std_table(sharks_data["pitching"]).replace("### Pitching — Standard\n", ""))

    # Opponent stats
    opp_label = f"#### {opp} Batting"
    if isinstance(opp_data, list) and opp_data:
        lines.append(opp_label)
        lines.append(_batting_std_table(opp_data, "").replace("### Batting — Standard\n", ""))
    elif isinstance(opp_data, dict) and opp_data.get("batting"):
        lines.append(opp_label)
        lines.append(_batting_std_table(opp_data["batting"], "").replace("### Batting — Standard\n", ""))
        if opp_data.get("pitching"):
            lines.append(f"#### {opp} Pitching")
            lines.append(_pitching_std_table(opp_data["pitching"]).replace("### Pitching — Standard\n", ""))

    return "\n".join(lines) + "\n\n"


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def prepare_notebooklm_payload() -> Path:
    """Build the full Markdown payload and write to data/notebooklm_payload.md."""
    today = datetime.now(ET).strftime("%B %d, %Y")
    lines = [f"# Sharks Spring 2026 — Full Data Sync ({today})", ""]

    # ------------------------------------------------------------------ #
    # 1. Season Stats (from team.json or team_web.json)
    # ------------------------------------------------------------------ #
    team_file = TEAM_DIR / "team_web.json"
    if not team_file.exists():
        team_file = TEAM_DIR / "team_enriched.json"
    if not team_file.exists():
        team_file = TEAM_DIR / "team_merged.json"
    if not team_file.exists():
        team_file = TEAM_DIR / "team.json"

    team_data = _read_json(team_file, {})
    roster = team_data.get("roster", [])

    if roster:
        team_name = team_data.get("team_name", "The Sharks")
        record = team_data.get("record", "")
        season = team_data.get("season", "Spring 2026")
        lines.append(f"## {team_name} — {season} {record}")
        lines.append(f"_Source: {team_file.name}_")
        lines.append("")

        lines.append("## Season Stats — Batting (Standard)")
        lines.append(_batting_std_table(roster, "Batting Standard"))

        lines.append("## Season Stats — Batting (Advanced)")
        lines.append(_batting_adv_table(roster))

        lines.append("## Season Stats — Pitching")
        lines.append(_pitching_std_table(roster))

        lines.append("## Season Stats — Fielding")
        lines.append(_fielding_std_table(roster))

    # Also check for team_web.json stat arrays (from GCFullScraper)
    web_data = _read_json(TEAM_DIR / "team_web.json", {})
    for stat_key, label in [
        ("batting", "Season Batting (Web Scraped)"),
        ("pitching", "Season Pitching (Web Scraped)"),
        ("fielding", "Season Fielding (Web Scraped)"),
    ]:
        if stat_key in web_data and web_data[stat_key]:
            lines.append(f"## {label}")
            if stat_key == "batting":
                lines.append(_batting_std_table(web_data[stat_key], label))
            elif stat_key == "pitching":
                lines.append(_pitching_std_table(web_data[stat_key]))
            elif stat_key == "fielding":
                lines.append(_fielding_std_table(web_data[stat_key]))

    # ------------------------------------------------------------------ #
    # 2. Game Log
    # ------------------------------------------------------------------ #
    games_dir = TEAM_DIR / "games"
    game_files = sorted(games_dir.glob("*.json")) if games_dir.exists() else []
    game_files = [f for f in game_files if f.name != "index.json"]

    if game_files:
        lines.append("## Game Log")
        lines.append("")
        for gf in game_files:
            game = _read_json(gf, {})
            if not game:
                continue
            # Skip empty/future games: no date AND no batting data
            sharks_data = game.get("sharks", {})
            legacy_batting = game.get("sharks_batting", [])
            has_batting = (
                (isinstance(sharks_data, dict) and sharks_data.get("batting"))
                or legacy_batting
            )
            has_date = bool(game.get("date", "").strip())
            if not has_batting and not has_date:
                continue
            try:
                lines.append(_game_section(game))
            except Exception as e:
                lines.append(f"### {gf.name}\n_Error reading game: {e}_\n\n")

    # ------------------------------------------------------------------ #
    # 3. Per-Player Game Logs
    # ------------------------------------------------------------------ #
    player_files = sorted(PLAYERS_DIR.glob("*.json")) if PLAYERS_DIR.exists() else []
    if player_files:
        lines.append("## Player Game-by-Game Logs")
        lines.append("")
        for pf in player_files:
            player = _read_json(pf, {})
            if not player or not player.get("games"):
                continue
            name = player.get("name", pf.stem)
            number = player.get("number", "")
            lines.append(f"### #{number} {name}")
            lines.append("")
            header = "| Date | Opponent | AB | H | BB | RBI | R | SB | AVG |"
            sep    = "|------|----------|----|---|-----|-----|---|-----|-----|"
            prows = [header, sep]
            for g in player.get("games", []):
                b = g.get("batting", {})
                prows.append(
                    f"| {g.get('date','-')} | {g.get('opponent','-')} | "
                    f"{_int(b.get('ab','-'))} | {_int(b.get('h','-'))} | "
                    f"{_int(b.get('bb','-'))} | {_int(b.get('rbi','-'))} | "
                    f"{_int(b.get('r','-'))} | {_int(b.get('sb','-'))} | "
                    f"{_fmt(b.get('avg','-'))} |"
                )
            lines.append("\n".join(prows))
            lines.append("")

    # ------------------------------------------------------------------ #
    # 4. Opponent Scouting
    # ------------------------------------------------------------------ #
    opponents_dir = DATA_DIR / "opponents"
    opp_files = sorted(opponents_dir.glob("*.json")) if opponents_dir.exists() else []

    # Also aggregate opponent data from game files
    opp_agg: dict[str, list] = {}
    for gf in game_files:
        game = _read_json(gf, {})
        if not game:
            continue
        opp_name = game.get("opponent", "Unknown")
        opp_batting = (
            game.get("opponent_stats", {}).get("batting")
            or game.get("opponent_batting")
            or []
        )
        if opp_batting:
            opp_agg.setdefault(opp_name, []).extend(opp_batting)

    if opp_agg or opp_files:
        lines.append("## Opponent Scouting")
        lines.append("")

        for opp_name, players in opp_agg.items():
            if players:
                lines.append(f"### {opp_name}")
                lines.append(_batting_std_table(players, "").replace("### Batting — Standard\n", ""))

        for opp_file in opp_files:
            opp_data = _read_json(opp_file, {})
            if not opp_data:
                continue
            opp_name = opp_data.get("team_name") or opp_file.stem.replace("_", " ").title()
            if opp_name in opp_agg:
                continue  # Already included from game files
            batting = opp_data.get("batting") or opp_data.get("roster") or []
            if batting:
                lines.append(f"### {opp_name} (from opponents dir)")
                lines.append(_batting_std_table(batting, "").replace("### Batting — Standard\n", ""))

    # ------------------------------------------------------------------ #
    # 5. SWOT Analysis (if available)
    # ------------------------------------------------------------------ #
    swot_file = TEAM_DIR / "swot_analysis.json"
    if swot_file.exists():
        swot = _read_json(swot_file, {})
        if swot:
            lines.append("## SWOT Analysis")
            lines.append("")
            for category in ("strengths", "weaknesses", "opportunities", "threats"):
                items = swot.get(category, [])
                if items:
                    lines.append(f"### {category.title()}")
                    for item in items:
                        if isinstance(item, dict):
                            lines.append(f"- **{item.get('title','')}**: {item.get('description','')}")
                        else:
                            lines.append(f"- {item}")
                    lines.append("")

    # ------------------------------------------------------------------ #
    # Write output
    # ------------------------------------------------------------------ #
    payload_content = "\n".join(lines)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PAYLOAD_FILE.write_text(payload_content, encoding="utf-8")

    print(f"[NotebookLM] Payload written to {PAYLOAD_FILE} ({len(payload_content):,} chars)")
    print(
        "[NotebookLM] To update NotebookLM: drag-and-drop 'notebooklm_payload.md' "
        "into your PCLL notebook, or use the notebooklm MCP tool."
    )
    return PAYLOAD_FILE


if __name__ == "__main__":
    prepare_notebooklm_payload()
