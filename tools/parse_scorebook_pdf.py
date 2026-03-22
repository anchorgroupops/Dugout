"""
Parse GC mobile app scorebook PDFs into per-game JSON files.

Each PDF has 2 pages (away team, home team). We extract per-player
batting stats by reading at-bat outcome codes from the scorebook grid.

Outputs: data/sharks/games/<date>_<opponent_slug>.json
"""
import json
import re
import sys
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    print("ERROR: pdfplumber not installed. Run: pip install pdfplumber")
    sys.exit(1)

ROOT_DIR = Path(__file__).resolve().parent.parent
SCOREBOOKS_DIR = ROOT_DIR / "Scorebooks"
GAMES_DIR = ROOT_DIR / "data" / "sharks" / "games"
SHARKS_NAMES = {"sharks", "the sharks"}

# ---- At-bat outcome classification ----
# Whitelist of valid at-bat outcomes (everything else is noise)
HITS = {"1B", "2B", "3B", "HR"}
WALKS = {"BB", "IBB"}
HBP_SET = {"HBP"}
# Strikeout variants
STRIKEOUT_VARIANTS = {"K", "KL", "KD", "KD3", "KD1", "KD2"}
# Out variants
GROUNDOUT = {"G"}
FLYOUT = {"F"}
LINEOUT = {"L"}
DOUBLE_PLAY = {"DP", "GDP"}
TRIPLE_PLAY = {"TP"}
ERROR_SET = {"E", "E+E", "E + E", "ROE"}
FC_SET = {"FC"}
SAC_SET = {"SAC", "SH", "SF", "SF1", "SF2"}

# Normalise outcome string to canonical form
def _norm(raw: str) -> str:
    v = raw.strip().upper().replace(" ", "").replace("\n", "")
    # Collapse error variants
    if v.startswith("E+E") or v.startswith("E+"):
        return "E"
    if v.startswith("KD"):
        return "K"
    return v


def classify(raw: str):
    """Return (stat_key, is_ab) for a raw at-bat outcome string, or None if noise."""
    v = _norm(raw)
    if v in {"1B"}:
        return "singles", True
    if v in {"2B"}:
        return "doubles", True
    if v in {"3B"}:
        return "triples", True
    if v in {"HR"}:
        return "hr", True
    if v in WALKS:
        return "bb", False
    if v in HBP_SET:
        return "hbp", False
    if v in STRIKEOUT_VARIANTS:
        return "so", True
    if v in GROUNDOUT | FLYOUT | LINEOUT | DOUBLE_PLAY | TRIPLE_PLAY | ERROR_SET | FC_SET:
        return "out", True
    if v in SAC_SET:
        return "sac", False
    # Anything else is scorebook noise (SB, PB, WP, pitch indicators, base numbers, etc.)
    return None


def stats_from_at_bats(at_bats: list[str]) -> dict:
    """Convert a list of raw at-bat outcome strings into a batting stat dict."""
    stats = {
        "pa": 0, "ab": 0,
        "singles": 0, "doubles": 0, "triples": 0, "hr": 0,
        "h": 0, "bb": 0, "hbp": 0, "so": 0, "sac": 0,
        "r": 0, "rbi": 0, "sb": 0,
    }
    for raw in at_bats:
        result = classify(raw)
        if result is None:
            continue
        key, counts_as_ab = result
        stats["pa"] += 1
        if counts_as_ab:
            stats["ab"] += 1
        if key in ("singles", "doubles", "triples", "hr"):
            stats[key] += 1
            stats["h"] += 1
        elif key in ("bb", "hbp", "sac"):
            stats[key] += 1
        elif key == "so":
            stats["so"] += 1
        # "out" contributes to ab only (already counted above)
    # Derived
    stats["avg"] = round(stats["h"] / stats["ab"], 3) if stats["ab"] else None
    stats["obp"] = round(
        (stats["h"] + stats["bb"] + stats["hbp"]) / stats["pa"], 3
    ) if stats["pa"] else None
    tb = stats["singles"] + 2 * stats["doubles"] + 3 * stats["triples"] + 4 * stats["hr"]
    stats["slg"] = round(tb / stats["ab"], 3) if stats["ab"] else None
    if stats["obp"] is not None and stats["slg"] is not None:
        stats["ops"] = round(stats["obp"] + stats["slg"], 3)
    else:
        stats["ops"] = None
    return stats


# ---- PDF table parsing ----

def _parse_players_from_page(page) -> list[dict]:
    """Extract player rows from a scorebook page table."""
    tables = page.extract_tables()
    if not tables:
        return []
    table = tables[0]

    players = []
    seen_numbers = set()
    for row in table:
        if not row:
            continue
        num_str = str(row[0] or "").strip()
        name_str = str(row[1] or "").strip()
        # Valid player row: numeric jersey number, non-empty name, not header
        if not re.match(r"^\d+$", num_str):
            continue
        if not name_str or name_str in ("Name", "#"):
            continue
        if num_str in seen_numbers:
            continue
        seen_numbers.add(num_str)

        pos = str(row[2] or "").strip()
        # Collect at-bat result cells from col 5 onwards
        raw_abs = []
        for cell in row[5:]:
            if cell is None:
                continue
            v = str(cell).strip()
            if not v or re.match(r"^#\d+$", v) or v.isdigit():
                continue
            raw_abs.append(v)

        players.append({
            "number": num_str,
            "name": name_str,
            "pos": pos,
            "at_bats_raw": raw_abs,
            "batting": stats_from_at_bats(raw_abs),
        })
    return players


def _page_team_and_side(page) -> tuple[str, str]:
    """Return (team_name, 'home'|'away') from the page header text."""
    text = page.extract_text() or ""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    team_name = lines[0] if lines else "Unknown"
    side_line = lines[1] if len(lines) > 1 else ""
    side = "away" if "Away" in side_line else "home"
    # Extract date if present (format: YYYY/MM/DD)
    date_match = re.search(r"(\d{4})/(\d{2})/(\d{2})", side_line)
    date_str = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}" if date_match else None
    return team_name, side, date_str


# ---- PDF filename metadata ----

def _slug_from_name(name: str) -> str:
    name = re.sub(r"[^a-z0-9]+", "_", name.lower().strip())
    return name.strip("_")[:30]


def _metadata_from_filename(pdf_path: Path) -> dict:
    """Best-effort parse of date, opponent, home/away from filename."""
    stem = pdf_path.stem
    # Try to find a date pattern: Feb_19_2026, Mar_3_2026, Mar_7_2026
    date_match = re.search(
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[_\s](\d{1,2})[_\s](\d{4})",
        stem, re.IGNORECASE
    )
    iso_date = None
    if date_match:
        month_map = {m: f"{i:02d}" for i, m in enumerate(
            ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], 1)}
        m = month_map.get(date_match.group(1).capitalize(), "01")
        d = date_match.group(2).zfill(2)
        y = date_match.group(3)
        iso_date = f"{y}-{m}-{d}"

    # Try ISO date in filename: 021926 → Feb 19 2026
    if not iso_date:
        iso_match = re.search(r"(\d{2})(\d{2})(\d{2})", stem)
        if iso_match:
            mo, dy, yr = iso_match.groups()
            iso_date = f"20{yr}-{mo}-{dy}"

    return {"date": iso_date}


# ---- Main parse function ----

def parse_pdf(pdf_path: Path) -> dict | None:
    """Parse a single scorebook PDF and return game data dict."""
    meta = _metadata_from_filename(pdf_path)
    game_date = meta["date"]

    sharks_page = None
    opponent_page = None
    sharks_side = None
    opponent_name = None
    game_date_from_pdf = None

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            team_name, side, pdf_date = _page_team_and_side(page)
            if game_date_from_pdf is None and pdf_date:
                game_date_from_pdf = pdf_date
            if team_name.lower() in SHARKS_NAMES or "sharks" in team_name.lower():
                sharks_page = page
                sharks_side = side
            else:
                opponent_page = page
                opponent_name = team_name

    if game_date_from_pdf and not game_date:
        game_date = game_date_from_pdf

    if sharks_page is None:
        print(f"[PDF] ⚠ Could not find Sharks page in {pdf_path.name}")
        return None

    sharks_players = _parse_players_from_page(sharks_page)
    opponent_players = _parse_players_from_page(opponent_page) if opponent_page else []

    # Opponent slug for filename
    opp_slug = _slug_from_name(opponent_name or "unknown")
    game_id = f"{game_date}_{opp_slug}" if game_date else f"unknown_{opp_slug}"

    game = {
        "game_id": game_id,
        "date": game_date,
        "opponent": opponent_name or "Unknown",
        "sharks_side": sharks_side or "unknown",
        "source": "scorebook_pdf",
        "pdf_file": pdf_path.name,
        "sharks_batting": sharks_players,
        "opponent_batting": opponent_players,
    }
    return game


def compute_team_totals(players: list[dict]) -> dict:
    """Sum batting stats across all players."""
    totals = {
        "pa": 0, "ab": 0, "h": 0, "singles": 0, "doubles": 0,
        "triples": 0, "hr": 0, "bb": 0, "hbp": 0, "so": 0, "sac": 0,
    }
    for p in players:
        bat = p.get("batting", {})
        for k in totals:
            totals[k] += bat.get(k, 0)
    totals["avg"] = round(totals["h"] / totals["ab"], 3) if totals["ab"] else None
    return totals


def run(scorebooks_dir: Path = SCOREBOOKS_DIR, games_dir: Path = GAMES_DIR):
    pdfs = list(scorebooks_dir.glob("*.pdf"))
    if not pdfs:
        print(f"[PDF] No PDFs found in {scorebooks_dir}")
        return []

    games_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for pdf_path in sorted(pdfs):
        print(f"[PDF] Parsing {pdf_path.name}...")
        game = parse_pdf(pdf_path)
        if not game:
            continue

        # Add team batting totals
        game["sharks_totals"] = compute_team_totals(game["sharks_batting"])

        out_path = games_dir / f"{game['game_id']}.json"
        with open(out_path, "w") as f:
            json.dump(game, f, indent=2)
        print(f"[PDF] Saved {out_path.name} "
              f"({len(game['sharks_batting'])} Sharks players, "
              f"{game['sharks_totals']['h']}H/{game['sharks_totals']['ab']}AB)")
        results.append(game)

    # Write combined index for the API
    index_path = games_dir / "index.json"
    index = [
        {
            "game_id": g["game_id"],
            "date": g["date"],
            "opponent": g["opponent"],
            "sharks_side": g["sharks_side"],
            "sharks_totals": g["sharks_totals"],
        }
        for g in sorted(results, key=lambda x: x.get("date") or "")
    ]
    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)
    print(f"[PDF] Wrote index with {len(index)} games to {index_path}")
    return results


if __name__ == "__main__":
    run()
