import json
import re
from pathlib import Path
from datetime import datetime, date
from zoneinfo import ZoneInfo
from gc_scraper import GameChangerScraper

ET = ZoneInfo("America/New_York")

DATA_DIR = Path(__file__).parent.parent / "data"
SHARKS_DIR = DATA_DIR / "sharks"
TMP_DIR = Path(__file__).parent.parent / ".tmp"

# ── Schedule text parser (mirrors gc_app_auto._parse_schedule) ────────────────
_MONTH_NAMES = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
}
_DAYS_OF_WEEK = {"sun","mon","tue","wed","thu","fri","sat"}
_TIME_RE = re.compile(r'^\d{1,2}:\d{2}\s*(AM|PM)$', re.I)
_RESULT_RE = re.compile(r'^[WLT]\s+\d+[-–]\d+$', re.I)


def _parse_schedule_text(text: str) -> dict:
    """Parse raw GameChanger schedule inner_text into {upcoming, past}."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    today = date.today()
    today_str = today.isoformat()
    current_year = today.year
    current_month = today.month
    games = []
    i = 0
    n = len(lines)

    while i < n:
        t = lines[i]
        tl = t.lower()

        # Month-year header: "April 2026"
        matched_month = False
        for mn, mv in _MONTH_NAMES.items():
            if mn in tl and any(str(y) in tl for y in range(2025, 2030)):
                yr_match = re.search(r'(\d{4})', t)
                if yr_match:
                    current_year = int(yr_match.group(1))
                    current_month = mv
                matched_month = True
                i += 1
                break
        if matched_month:
            continue

        # Day-of-week token: "Fri"
        if tl[:3] in _DAYS_OF_WEEK:
            dow = t
            i += 1
            if i >= n:
                break
            # Next token: day number
            day_str = lines[i].strip()
            if not day_str.isdigit():
                continue
            day_num = int(day_str)
            i += 1

            # Optional "Next" label
            if i < n and lines[i].strip().lower() == "next":
                i += 1

            if i >= n:
                break

            opponent_raw = lines[i].strip()
            i += 1

            is_game = opponent_raw.lower().startswith(("vs.", "vs ", "@", "at "))
            try:
                game_date = date(current_year, current_month, day_num)
            except ValueError:
                continue

            entry = {
                "date": game_date.isoformat(),
                "dow": dow,
                "opponent": opponent_raw,
                "is_game": is_game,
                "home_away": "away" if opponent_raw.startswith("@") else "home",
                "league": "",
                "time": "",
                "result": "",
                "score": "",
            }

            # Collect fields until the next day-of-week or month header
            while i < n:
                nxt = lines[i].strip()
                nxtl = nxt.lower()
                if nxtl[:3] in _DAYS_OF_WEEK:
                    break
                if any(mn in nxtl for mn in _MONTH_NAMES) and any(str(y) in nxt for y in range(2025, 2030)):
                    break
                if _TIME_RE.match(nxt):
                    entry["time"] = nxt
                elif _RESULT_RE.match(nxt):
                    entry["result"] = nxt[0].upper()
                    entry["score"] = nxt[2:].strip()
                elif nxt.lower().startswith("pcll") or "softball" in nxt.lower():
                    entry["league"] = nxt
                i += 1

            games.append(entry)
        else:
            i += 1

    def dedup(lst):
        seen = set()
        out = []
        for g in lst:
            k = (g["date"], g["opponent"].lower()[:20])
            if k not in seen:
                seen.add(k)
                out.append(g)
        return sorted(out, key=lambda x: x["date"])

    upcoming = [g for g in games if g["is_game"] and g["date"] >= today_str and not g["result"]]
    past = [g for g in games if g["is_game"] and (g["result"] or g["date"] < today_str)]
    return {"upcoming": dedup(upcoming), "past": dedup(past)}


def _merge_schedule(existing: dict, scraped: dict) -> dict:
    """Merge scraped games into existing schedule, preserving manually-set fields."""
    def index_by_date(games):
        return {g["date"]: g for g in games}

    def merge_list(existing_list, scraped_list):
        ex_map = index_by_date(existing_list)
        for g in scraped_list:
            if g["date"] in ex_map:
                ex = ex_map[g["date"]]
                # Keep manually-set result/score; fill from scraped if blank
                if not ex.get("result") and g.get("result"):
                    ex["result"] = g["result"]
                if not ex.get("score") and g.get("score"):
                    ex["score"] = g["score"]
                if not ex.get("time") and g.get("time"):
                    ex["time"] = g["time"]
                ex.setdefault("opponent", g["opponent"])
                ex.setdefault("home_away", g["home_away"])
            else:
                ex_map[g["date"]] = g
        return sorted(ex_map.values(), key=lambda x: x["date"])

    return {
        "upcoming": merge_list(existing.get("upcoming", []), scraped.get("upcoming", [])),
        "past": merge_list(existing.get("past", []), scraped.get("past", [])),
    }


class ScheduleScraper(GameChangerScraper):
    def scrape_schedule(self):
        """Scrapes past games, scrimmages, and future schedule from the DOM."""
        schedule_data = {
            "last_updated": datetime.now(ET).isoformat(),
            "games": []
        }

        from playwright.sync_api import (
            sync_playwright,
            TimeoutError as PlaywrightTimeoutError,
        )

        text_content = ""
        page = None
        with sync_playwright() as pw:
            try:
                page = self.login(pw)

                print("[GC_SCHEDULE] Navigating to The Sharks team page...")
                team_link = page.locator(f'text="{self.team_name}"').first
                if team_link:
                    team_link.click()
                    page.wait_for_timeout(3000)
                else:
                    print(f"[ERROR] Could not find team link for {self.team_name}. Check session or team name.")
                    return schedule_data

                print("[GC_SCHEDULE] Opening Schedule tab...")
                schedule_tab = page.locator('text="Schedule"').first
                if schedule_tab:
                    schedule_tab.click()
                    page.wait_for_timeout(5000)
                else:
                    print("[ERROR] Could not find Schedule tab.")
                    return schedule_data

                print("[GC_SCHEDULE] Extracting games...")
                schedule_container = page.locator('main').first
                text_content = schedule_container.inner_text() if schedule_container else ""

                schedule_data["raw_content"] = text_content
                print(f"[GC_SCHEDULE] Captured {len(text_content)} chars of schedule text")

            except PlaywrightTimeoutError as e:
                print(f"[ERROR] Timeout during schedule scrape: {e}")
                if page:
                    self._take_error_snapshot(page, "schedule_timeout")
            except Exception as e:
                print(f"[ERROR] Unexpected error during schedule scrape: {e}")
                if page:
                    self._take_error_snapshot(page, "schedule_error")
            finally:
                if self.browser:
                    self.browser.close()

        # Parse captured text into structured games
        if text_content:
            parsed = _parse_schedule_text(text_content)
            schedule_data["games"] = parsed.get("upcoming", []) + parsed.get("past", [])
            total = len(schedule_data["games"])
            print(f"[GC_SCHEDULE] Parsed {total} games ({len(parsed['upcoming'])} upcoming, {len(parsed['past'])} past)")

            # Merge into schedule_manual.json so the API picks it up
            manual_file = SHARKS_DIR / "schedule_manual.json"
            existing = {}
            if manual_file.exists():
                try:
                    with open(manual_file) as f:
                        existing = json.load(f)
                except Exception:
                    existing = {}
            merged = _merge_schedule(existing, parsed)
            merged["last_updated"] = datetime.now(ET).isoformat()
            SHARKS_DIR.mkdir(parents=True, exist_ok=True)
            with open(manual_file, "w") as f:
                json.dump(merged, f, indent=2)
            print(f"[GC_SCHEDULE] Wrote {manual_file}")
        else:
            print("[GC_SCHEDULE] No text content captured — schedule_manual.json not updated")

        # Also write the raw schedule.json for debugging
        SHARKS_DIR.mkdir(parents=True, exist_ok=True)
        with open(SHARKS_DIR / "schedule.json", "w") as f:
            json.dump(schedule_data, f, indent=2)

        return schedule_data

    def _take_error_snapshot(self, page, name_prefix):
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(ET).strftime("%Y%m%d_%H%M%S")
        try:
            filename = TMP_DIR / f"{name_prefix}_{timestamp}.png"
            page.screenshot(path=str(filename))
            print(f"[DEBUG] Saved error screenshot to {filename}")
        except Exception as snap_err:
            print(f"[DEBUG] Failed to take screenshot: {snap_err}")


if __name__ == "__main__":
    scraper = ScheduleScraper()
    scraper.scrape_schedule()
