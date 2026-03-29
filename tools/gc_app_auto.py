"""
GameChanger App Auto-Scraper
Connects to BlueStacks emulator via uiautomator2, extracts stats and schedule,
writes structured JSON to data/<team_slug>/.

Usage:
  python gc_app_auto.py             # full scrape (stats + schedule)
  python gc_app_auto.py --schedule  # schedule only
  python gc_app_auto.py --stats     # stats only
"""
import sys
import json
import time
import re
import xml.etree.ElementTree as ET
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

ET_TZ = ZoneInfo("America/New_York")

# BlueStacks ADB serial — HD-Adb.exe assigns 'emulator-5554'
ADB_SERIAL = "emulator-5554"

ROOT_DIR = Path(__file__).parent.parent
DATA_DIR = ROOT_DIR / "data" / "sharks"

BATTING_STD_COLS  = ["gp", "pa", "ab", "avg", "obp", "ops", "slg", "h", "1b", "2b", "3b", "hr", "rbi", "bb", "hbp", "so", "sb", "cs"]
BATTING_ADV_COLS  = ["gp", "pa", "ab", "qab", "qab_pct", "pa_per_bb", "bb_per_k", "c_pct", "hhb", "ld_pct", "fb_pct", "gb_pct"]
PITCHING_STD_COLS = ["ip", "gp", "gs", "bf", "pitches", "w", "l", "sv", "svo", "bs", "era", "whip", "k", "bb", "h", "r", "er", "hr"]
FIELDING_STD_COLS = ["tc", "a", "po", "fpct", "e", "dp", "tp"]

OPPONENTS_DIR = ROOT_DIR / "data" / "opponents"

# Known opponents: display name fragment (lowercase) -> slug
OPPONENT_SLUGS = {
    "ravens":     "ravens",
    "peppers":    "peppers",
    "riptide":    "riptide_rebels",
    "nwvll":      "nwvll",
    "stihler":    "nwvll",
    "wildcat":    "wildcats",
}


def connect():
    import uiautomator2 as u2
    print(f"[GC App] Connecting to {ADB_SERIAL}...")
    d = u2.connect(ADB_SERIAL)
    print(f"[GC App] Connected: {d.info.get('productName', 'unknown')}")
    return d


def gc_texts(d):
    """Return list of visible text strings from the GC app package."""
    xml = d.dump_hierarchy()
    root = ET.fromstring(xml)
    return [n.get("text", "") for n in root.iter("node")
            if n.get("package", "").startswith("com.gc") and n.get("text", "").strip()]

def _click_first_visible_text(d, labels: list[str], timeout_sec: float = 5.0) -> bool:
    """
    Try clicking one of the requested labels using exact and fuzzy visible-text matching.
    Returns True when a click is performed.
    """
    deadline = time.time() + timeout_sec
    labels_l = [x.lower() for x in labels]

    while time.time() < deadline:
        for label in labels:
            if d(text=label).exists(timeout=0.3):
                d(text=label).click()
                time.sleep(1.0)
                return True

        texts = gc_texts(d)
        for t in texts:
            tl = t.strip().lower()
            if any(lbl in tl for lbl in labels_l):
                if d(text=t).exists(timeout=0.3):
                    d(text=t).click()
                    time.sleep(1.0)
                    return True
        time.sleep(0.4)

    return False


def scroll_down(d, n=1):
    for _ in range(n):
        d.swipe(540, 750, 540, 250, duration=0.4)
        time.sleep(0.8)


def scroll_up(d, n=1):
    for _ in range(n):
        d.swipe(540, 250, 540, 750, duration=0.4)
        time.sleep(0.8)


def scroll_right(d):
    d.swipe(900, 500, 300, 500, duration=0.4)
    time.sleep(0.8)


# ---------------------------------------------------------------------------
# SCHEDULE SCRAPING
# ---------------------------------------------------------------------------
MONTH_NAMES = {"january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
               "july":7,"august":8,"september":9,"october":10,"november":11,"december":12}
DAYS_OF_WEEK = {"sun","mon","tue","wed","thu","fri","sat"}
TIME_RE = re.compile(r'^\d{1,2}:\d{2}\s*(AM|PM)$', re.I)
RESULT_RE = re.compile(r'^[WLT]\s+\d+[-–]\d+$', re.I)
SCORE_ONLY_RE = re.compile(r'^\d+[-–]\d+$')

def _slug_for_opponent(name: str) -> str:
    """Map a schedule opponent name to a filesystem slug."""
    nl = name.lower()
    for fragment, slug in OPPONENT_SLUGS.items():
        if fragment in nl:
            return slug
    # Fallback: lowercase, no spaces
    return re.sub(r'[^a-z0-9]+', '_', nl).strip('_')[:30]


def _navigate_to_sharks_team(d):
    """From anywhere in the app, navigate to the configured team page."""
    # If we're already on the team page Schedule/Stats tabs are visible
    if _click_first_visible_text(d, ["Schedule", "Events"], timeout_sec=1.0):
        return
    # Restart app to get to home feed
    d.app_stop("com.gc.teammanager")
    time.sleep(2)
    d.app_start("com.gc.teammanager")
    time.sleep(7)
    # Tap the team entry
    if d(text="Sharks", packageName="com.gc.teammanager").exists(timeout=5):
        d(text="Sharks", packageName="com.gc.teammanager").click()
        time.sleep(4)
    else:
        # Fallback: tap first visible team name anywhere
        if not _click_first_visible_text(d, ["Sharks"], timeout_sec=5.0):
            raise RuntimeError("Could not open Sharks team page in GC app.")
        time.sleep(4)


def _stream_scroll(d, scrolls=20):
    """Scroll through a page and return a de-overlapped sequential text stream."""
    scroll_up(d, 8)
    time.sleep(1)

    NAV_JUNK = {"lexi mckinney", "message team", "team", "video", "stats",
                "leagues", "schedule", "home", "events", "messages",
                "announcements", "account", "jm", "lm", "get team pass",
                "sharks", "staff", "spring 2026", ".", "opponents",
                "batting", "pitching", "fielding", "filter stats", "standard", "advanced"}

    def clean(texts):
        return [t for t in texts if t.strip() and t.strip().lower() not in NAV_JUNK]

    stream = []
    prev = []
    prev_win = None

    for _ in range(scrolls):
        raw = gc_texts(d)
        win = tuple(raw)
        if win == prev_win:
            break
        prev_win = win
        cur = clean(raw)

        if not prev:
            stream.extend(cur)
        else:
            # Find longest suffix of prev that matches a prefix of cur
            overlap = 0
            for k in range(min(len(prev), len(cur)), 0, -1):
                if prev[-k:] == cur[:k]:
                    overlap = k
                    break
            new_items = cur[overlap:]
            stream.extend(new_items)
        prev = cur
        scroll_down(d)

    return stream


def scrape_schedule(d):
    print("[GC App] Navigating to Schedule...")
    _navigate_to_sharks_team(d)
    if not _click_first_visible_text(d, ["Schedule", "Events"], timeout_sec=6.0):
        visible = gc_texts(d)[:30]
        raise RuntimeError(f"Schedule/Events tab not found. Visible texts: {visible}")
    time.sleep(3)
    stream = _stream_scroll(d, scrolls=20)
    return _parse_schedule(stream)


def _parse_schedule(texts):
    """Parse flat text list into structured game/event list."""
    today = date.today()
    current_year = today.year
    current_month = today.month

    games = []
    i = 0
    n = len(texts)

    # texts are already cleaned/streamed — no further dedup needed
    i = 0
    n = len(texts)
    while i < n:
        t = texts[i]
        tl = t.strip().lower()

        # Month-year header
        for mn, mv in MONTH_NAMES.items():
            if mn in tl and any(str(y) in tl for y in range(2025, 2028)):
                yr_match = re.search(r'(\d{4})', t)
                if yr_match:
                    current_year = int(yr_match.group(1))
                    current_month = mv
                i += 1
                break
        else:
            # Day-of-week entry
            if tl in DAYS_OF_WEEK:
                dow = t.strip()
                i += 1
                if i >= n:
                    break
                # Next should be day number
                day_num_str = texts[i].strip()
                if not day_num_str.isdigit():
                    continue
                day_num = int(day_num_str)
                i += 1

                # Optional "Next" tag
                if i < n and texts[i].strip().lower() == "next":
                    i += 1

                if i >= n:
                    break

                opponent_or_event = texts[i].strip()
                i += 1

                # Check if it's a practice/event (no vs./@ prefix) or a game
                is_game = opponent_or_event.lower().startswith(("vs.", "vs ", "@", "at "))

                # Build game date
                try:
                    game_date = date(current_year, current_month, day_num)
                except ValueError:
                    continue

                entry = {
                    "date": game_date.isoformat(),
                    "dow": dow,
                    "opponent": opponent_or_event,
                    "is_game": is_game,
                    "home_away": "away" if opponent_or_event.startswith("@") else "home",
                    "league": "",
                    "time": "",
                    "result": "",
                    "score": ""
                }

                # Collect additional fields until next day-of-week or month header
                while i < n:
                    nxt = texts[i].strip()
                    nxtl = nxt.lower()
                    if nxtl in DAYS_OF_WEEK:
                        break
                    if any(mn in nxtl for mn in MONTH_NAMES) and any(str(y) in nxt for y in range(2025, 2028)):
                        break
                    if TIME_RE.match(nxt):
                        entry["time"] = nxt
                    elif RESULT_RE.match(nxt):
                        entry["result"] = nxt[0].upper()  # W/L/T
                        entry["score"] = nxt[2:].strip()
                    elif nxt.lower().startswith("pcll") or "softball" in nxt.lower() or "baseball" in nxt.lower():
                        entry["league"] = nxt
                    elif nxt.isdigit() or len(nxt) <= 2:
                        pass  # skip nav/junk
                    i += 1

                games.append(entry)
            else:
                i += 1

    # Split into upcoming / past
    today_str = today.isoformat()
    upcoming = [g for g in games if g["is_game"] and g["date"] >= today_str and not g["result"]]
    past = [g for g in games if g["is_game"] and (g["result"] or g["date"] < today_str)]

    # Deduplicate by date+opponent
    def dedup(lst):
        seen = set()
        out = []
        for g in lst:
            k = (g["date"], g["opponent"].lower()[:20])
            if k not in seen:
                seen.add(k)
                out.append(g)
        return sorted(out, key=lambda x: x["date"])

    return {"upcoming": dedup(upcoming), "past": dedup(past)}


# ---------------------------------------------------------------------------
# STATS SCRAPING
# ---------------------------------------------------------------------------
def _scroll_and_collect_table(d, expected_cols):
    """Scroll through a stats table, returning parsed player rows."""
    stream = _stream_scroll(d, scrolls=15)
    # Strip everything up to and including the PLAYER column header
    try:
        idx = stream.index("PLAYER")
        stream = stream[idx + 1:]
    except ValueError:
        pass
    # Truncate at glossary/footer markers
    for marker in ("Export Stats", "PLAYER\nGP"):
        if marker in stream:
            stream = stream[:stream.index(marker)]
    for i, t in enumerate(stream):
        if t.strip().lower().startswith("gp - games played") or t.strip().lower() == "export stats":
            stream = stream[:i]
            break

    # Also skip the column header names that follow PLAYER in the stream
    col_upper = {c.upper() for c in expected_cols}
    DISPLAY_HEADERS = {"GP","PA","AB","AVG","OBP","OPS","SLG","H","1B","2B","3B","HR",
                       "RBI","BB","HBP","SO","SB","CS","QAB","QAB%","PA/BB","BB/K",
                       "C%","HHB","LD%","IP","GS","BF","#P","W","L","SV","SVO","BS",
                       "ERA","WHIP","K","R","ER","TC","A","PO","FPCT","E","DP","TP",
                       "PLAYER"} | col_upper
    while stream and stream[0].strip().upper() in DISPLAY_HEADERS:
        stream = stream[1:]
    return _parse_table_rows(stream, expected_cols)


def _parse_table_rows(flat, col_names):
    """Parse flat list of [player_name, val1, val2, ...] into list of dicts."""
    players = []
    i = 0
    n = len(flat)
    # Player names match pattern: "First Last, #NN" or just "First"
    PLAYER_RE = re.compile(r'^[A-Za-z]')

    while i < n:
        t = flat[i].strip()
        # Detect player name: starts with letter, not a number, not a stat value
        if PLAYER_RE.match(t) and not re.match(r'^[\d.]+$', t):
            name = t
            number = ""
            nm = re.search(r'#(\w+)', name)
            if nm:
                number = nm.group(1)
                name = name[:name.rfind(",")].strip() if "," in name else name

            i += 1
            vals = []
            while i < n and len(vals) < len(col_names):
                v = flat[i].strip()
                if PLAYER_RE.match(v) and not re.match(r'^[\d.]+$', v) and len(v) > 2:
                    break
                vals.append(v)
                i += 1

            row = {"name": name, "number": number}
            for j, col in enumerate(col_names):
                row[col] = vals[j] if j < len(vals) else ""
            players.append(row)
        else:
            i += 1

    # Merge duplicates (same player from multiple scroll positions)
    merged = {}
    for p in players:
        key = p["number"] or p["name"]
        if key not in merged:
            merged[key] = p
    return list(merged.values())


def scrape_stats(d):
    print("[GC App] Navigating to Stats...")
    _navigate_to_sharks_team(d)
    if not _click_first_visible_text(d, ["Stats"], timeout_sec=6.0):
        visible = gc_texts(d)[:30]
        raise RuntimeError(f"Stats tab not found. Visible texts: {visible}")
    time.sleep(2)

    # --- Batting Standard ---
    print("[GC App] Scraping batting (standard)...")
    d(text="Batting").click()
    time.sleep(1.5)
    # Ensure Standard is selected
    if d(text="Advanced").exists:
        pass  # already on standard or need to switch
    batting_std = _scroll_and_collect_table(d, BATTING_STD_COLS)
    print(f"  -> {len(batting_std)} batters")

    # --- Batting Advanced ---
    print("[GC App] Scraping batting (advanced)...")
    if d(text="Standard").exists:
        d(text="Standard").click()
        time.sleep(1)
        if d(text="Advanced").exists:
            d(text="Advanced").click()
            time.sleep(1.5)
    batting_adv = _scroll_and_collect_table(d, BATTING_ADV_COLS)
    print(f"  -> {len(batting_adv)} batters (advanced)")

    # Merge advanced into standard rows
    adv_by_num = {p["number"]: p for p in batting_adv if p["number"]}
    adv_by_name = {p["name"]: p for p in batting_adv}
    for p in batting_std:
        adv = adv_by_num.get(p["number"]) or adv_by_name.get(p["name"])
        if adv:
            p.update({k: v for k, v in adv.items() if k not in ("name", "number", "gp", "pa", "ab")})

    # --- Pitching ---
    print("[GC App] Scraping pitching...")
    if d(text="Advanced").exists:
        d(text="Advanced").click()
        time.sleep(0.5)
        d(text="Standard").click()
        time.sleep(1)
    d(text="Pitching").click()
    time.sleep(1.5)
    pitching = _scroll_and_collect_table(d, PITCHING_STD_COLS)
    print(f"  -> {len(pitching)} pitchers")

    # --- Fielding ---
    print("[GC App] Scraping fielding...")
    d(text="Fielding").click()
    time.sleep(1.5)
    fielding = _scroll_and_collect_table(d, FIELDING_STD_COLS)
    print(f"  -> {len(fielding)} fielders")

    return {
        "batting": batting_std,
        "pitching": pitching,
        "fielding": fielding
    }


# ---------------------------------------------------------------------------
# OPPONENT SCRAPING
# ---------------------------------------------------------------------------
def _navigate_to_opponent_from_schedule(d, opponent_keyword: str) -> bool:
    """
    From the team Schedule tab, find the first upcoming game vs opponent_keyword,
    tap it to open the game detail, then tap the opponent team name to open their page.
    Returns True if successfully landed on the opponent team page (Stats tab visible).
    """
    _navigate_to_sharks_team(d)
    if not _click_first_visible_text(d, ["Schedule", "Events"], timeout_sec=6.0):
        print("  [Opponent] Could not open Schedule/Events tab")
        return False
    time.sleep(2)

    # Scroll down looking for the opponent entry
    found = False
    for _ in range(15):
        texts = gc_texts(d)
        for t in texts:
            if opponent_keyword.lower() in t.lower():
                print(f"  [Opponent] Found '{t}' — tapping...")
                d(text=t, packageName="com.gc.teammanager").click()
                time.sleep(3)
                found = True
                break
        if found:
            break
        scroll_down(d)

    if not found:
        print(f"  [Opponent] Could not find '{opponent_keyword}' in schedule")
        return False

    # Now on game detail page — look for the opponent team name as a short, tappable link.
    # Avoid re-tapping the full schedule entry (which contains "Team @" or "vs.").
    # GC shows each team as a separate tappable row on the game detail page.
    time.sleep(2)
    texts_after = gc_texts(d)
    print(f"  [Opponent] Game detail texts: {texts_after[:20]}")

    tapped = False
    # First pass: prefer a short string that has the keyword but NOT our team name or "@ " or "vs."
    for t in texts_after:
        tl = t.lower()
        if (opponent_keyword.lower() in tl
                and "sharks" not in tl
                and not tl.startswith("@ ")
                and not tl.startswith("vs.")):
            print(f"  [Opponent] Tapping short team link: '{t}'")
            d(text=t, packageName="com.gc.teammanager").click()
            time.sleep(4)
            tapped = True
            break

    # Second pass: any text with keyword (fallback)
    if not tapped:
        for t in texts_after:
            if opponent_keyword.lower() in t.lower() and t.strip() != "":
                print(f"  [Opponent] Tapping fallback link: '{t}'")
                d(text=t, packageName="com.gc.teammanager").click()
                time.sleep(4)
                break

    # Confirm we're on the opponent's team page
    if d(text="Stats").exists(timeout=5):
        print(f"  [Opponent] Landed on team page with Stats tab.")
        return True
    # Dump visible texts for debugging
    debug_texts = gc_texts(d)
    print(f"  [Opponent] Stats tab not found. Visible: {debug_texts[:15]}")
    return False


def scrape_opponent_stats(d, opponent_name: str) -> dict | None:
    """Navigate to an opponent's team page and scrape their batting + pitching stats."""
    slug = _slug_for_opponent(opponent_name)
    print(f"[GC App] Scraping opponent '{opponent_name}' (slug={slug})...")

    # Try to navigate via schedule game link
    keyword = opponent_name.split()[0] if " " in opponent_name else opponent_name
    ok = _navigate_to_opponent_from_schedule(d, keyword)
    if not ok:
        return None

    # Scrape batting
    d(text="Stats").click()
    time.sleep(2)
    if d(text="Batting").exists(timeout=3):
        d(text="Batting").click()
        time.sleep(1.5)
    batting = _scroll_and_collect_table(d, BATTING_STD_COLS)
    print(f"  -> {len(batting)} batters")

    # Scrape pitching
    if d(text="Pitching").exists(timeout=3):
        d(text="Pitching").click()
        time.sleep(1.5)
        pitching = _scroll_and_collect_table(d, PITCHING_STD_COLS)
        print(f"  -> {len(pitching)} pitchers")
    else:
        pitching = []

    # Scrape fielding
    if d(text="Fielding").exists(timeout=3):
        d(text="Fielding").click()
        time.sleep(1.5)
        fielding = _scroll_and_collect_table(d, FIELDING_STD_COLS)
        print(f"  -> {len(fielding)} fielders")
    else:
        fielding = []

    return {
        "slug": slug,
        "team_name": opponent_name,
        "batting": batting,
        "pitching": pitching,
        "fielding": fielding,
    }


def scrape_all_opponents(d) -> dict:
    """Scrape stats for all known opponents from the schedule."""
    schedule_file = DATA_DIR / "schedule_manual.json"
    if not schedule_file.exists():
        print("[GC App] No schedule_manual.json found — run --schedule first.")
        return {}

    with open(schedule_file) as f:
        sched = json.load(f)

    # Collect unique opponent names from upcoming + past
    seen_slugs = set()
    opponents_to_scrape = []
    for game in sched.get("upcoming", []) + sched.get("past", []):
        opp = game.get("opponent", "").replace("@ ", "").replace("vs. ", "").strip()
        if not opp or opp.startswith("TBD"):
            continue
        slug = _slug_for_opponent(opp)
        if slug not in seen_slugs:
            seen_slugs.add(slug)
            opponents_to_scrape.append(opp)

    results = {}
    for opp_name in opponents_to_scrape:
        try:
            data = scrape_opponent_stats(d, opp_name)
            if data:
                results[data["slug"]] = data
                save_opponent_stats(data)
        except Exception as e:
            print(f"  [Opponent] Error scraping '{opp_name}': {e}")
        # Always return to team page before next opponent
        _navigate_to_sharks_team(d)
        time.sleep(2)

    return results


# ---------------------------------------------------------------------------
# WRITE OUTPUT
# ---------------------------------------------------------------------------
def save_schedule(schedule):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "last_updated": datetime.now(ET_TZ).isoformat(),
        "upcoming": schedule["upcoming"],
        "past": schedule["past"],
        "notes": "Auto-generated by gc_app_auto.py. Edit upcoming[] to add/correct games."
    }
    path = DATA_DIR / "schedule_manual.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"[GC App] Schedule saved -> {path}")
    print(f"  Upcoming: {len(schedule['upcoming'])} games, Past: {len(schedule['past'])} games")
    for g in schedule["upcoming"]:
        print(f"  {g['date']} {g['dow']} {g['opponent']} {g['time']}")


def save_opponent_stats(data: dict):
    """Save opponent stats to data/opponents/<slug>/team.json, merging with any existing PDF data."""
    slug = data["slug"]
    opp_dir = OPPONENTS_DIR / slug
    opp_dir.mkdir(parents=True, exist_ok=True)

    team_file = opp_dir / "team.json"

    # Build roster from batting rows (use existing PDF roster as base if present)
    existing = {}
    if team_file.exists():
        try:
            ex = json.load(open(team_file))
            for p in ex.get("roster", []):
                existing[p.get("number", p.get("name", ""))] = p
        except Exception:
            pass

    roster = []
    for p in data["batting"]:
        num = p.get("number", "")
        name = p.get("name", "")
        key = num or name
        base = existing.get(key, {"number": num, "name": name})
        # Build clean batting dict from app columns
        batting = {
            "gp": p.get("gp", ""), "pa": p.get("pa", ""), "ab": p.get("ab", ""),
            "avg": p.get("avg", ""), "obp": p.get("obp", ""), "ops": p.get("ops", ""),
            "slg": p.get("slg", ""), "h": p.get("h", ""), "2b": p.get("2b", ""),
            "3b": p.get("3b", ""), "hr": p.get("hr", ""), "rbi": p.get("rbi", ""),
            "bb": p.get("bb", ""), "hbp": p.get("hbp", ""), "so": p.get("so", ""),
            "sb": p.get("sb", ""),
        }
        roster.append({**base, "batting": batting})

    out = {
        "team_name": data["team_name"],
        "slug": slug,
        "last_updated": datetime.now(ET_TZ).isoformat(),
        "source": "gc_app",
        "batting_stats": data["batting"],
        "pitching_stats": data["pitching"],
        "fielding_stats": data["fielding"],
        "roster": roster,
    }

    with open(team_file, "w") as f:
        json.dump(out, f, indent=2)
    print(f"[GC App] Opponent saved -> {team_file}  ({len(roster)} players)")


def save_stats(stats):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "last_updated": datetime.now(ET_TZ).isoformat(),
        "source": "gc_app",
        "batting": stats["batting"],
        "pitching": stats["pitching"],
        "fielding": stats["fielding"]
    }
    path = DATA_DIR / "app_stats.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"[GC App] Stats saved -> {path}")
    print(f"  Batters: {len(stats['batting'])}, Pitchers: {len(stats['pitching'])}, Fielders: {len(stats['fielding'])}")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    args = set(sys.argv[1:])
    do_schedule  = "--stats" not in args and "--opponents" not in args
    do_stats     = "--schedule" not in args and "--opponents" not in args
    do_opponents = "--opponents" in args or (not {"--schedule", "--stats"} & args)

    d = connect()

    if do_schedule:
        schedule = scrape_schedule(d)
        save_schedule(schedule)

    if do_stats:
        stats = scrape_stats(d)
        save_stats(stats)

    if do_opponents:
        scrape_all_opponents(d)

    print("[GC App] Done.")


if __name__ == "__main__":
    main()
