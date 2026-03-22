"""
GameChanger App Auto-Scraper
Connects to BlueStacks emulator via uiautomator2, extracts stats and schedule,
writes structured JSON to data/sharks/.

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
BATTING_ADV_COLS  = ["gp", "pa", "ab", "qab", "qab_pct", "pa_per_bb", "bb_per_k", "c_pct", "hhb", "ld_pct"]
PITCHING_STD_COLS = ["ip", "gp", "gs", "bf", "pitches", "w", "l", "sv", "svo", "bs", "era", "whip", "k", "bb", "h", "r", "er", "hr"]
FIELDING_STD_COLS = ["tc", "a", "po", "fpct", "e", "dp", "tp"]


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

def _navigate_to_sharks_team(d):
    """From anywhere in the app, navigate to the Sharks team page."""
    # If we're already on the team page Schedule/Stats tabs are visible
    if d(text="Schedule").exists(timeout=2):
        return
    # Restart app to get to home feed
    d.app_stop("com.gc.teammanager")
    time.sleep(2)
    d.app_start("com.gc.teammanager")
    time.sleep(7)
    # Tap the Sharks team entry
    if d(text="Sharks", packageName="com.gc.teammanager").exists(timeout=5):
        d(text="Sharks", packageName="com.gc.teammanager").click()
        time.sleep(4)
    else:
        # Fallback: tap first visible "Sharks" anywhere
        d(text="Sharks").click()
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
    d(text="Schedule").click()
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
    d(text="Stats").click()
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
    do_schedule = "--stats" not in args
    do_stats = "--schedule" not in args

    d = connect()

    if do_schedule:
        schedule = scrape_schedule(d)
        save_schedule(schedule)

    if do_stats:
        stats = scrape_stats(d)
        save_stats(stats)

    print("[GC App] Done.")


if __name__ == "__main__":
    main()
