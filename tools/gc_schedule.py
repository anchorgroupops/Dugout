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


def _alert_empty_scrape(text_chars: int = 0) -> None:
    """Record that the schedule scraper returned 0 parsed games.

    Updates `data/sharks/pipeline_health.json` (creating it if needed) with
    a `schedule_empty_streak` counter and a `last_empty_scrape_at` timestamp.
    Triggers a stderr WARN line on every empty run AND a louder alert when
    the streak hits 3+ — at that point the GameChanger UI/parser has almost
    certainly drifted and a human needs to look at it.
    """
    import sys
    SHARKS_DIR.mkdir(parents=True, exist_ok=True)
    health_file = SHARKS_DIR / "pipeline_health.json"
    health = {}
    if health_file.exists():
        try:
            with open(health_file) as f:
                health = json.load(f) or {}
        except Exception:
            health = {}
    streak = int(health.get("schedule_empty_streak") or 0) + 1
    now_iso = datetime.now(ET).isoformat()
    health["schedule_empty_streak"] = streak
    health["last_empty_scrape_at"] = now_iso
    health["last_empty_scrape_chars"] = int(text_chars)
    with open(health_file, "w") as f:
        json.dump(health, f, indent=2)
    msg = (f"[GC_SCHEDULE][ALERT] Empty schedule scrape "
           f"(streak={streak}, captured {text_chars} chars).")
    print(msg, file=sys.stderr)
    if streak >= 3:
        print(
            "[GC_SCHEDULE][ALERT] 3+ consecutive empty scrapes — likely "
            "GameChanger parser drift. Inspect data/sharks/pipeline_health.json "
            "and recent .tmp/schedule_*.png snapshots.",
            file=sys.stderr,
        )


def _clear_empty_scrape_alert() -> None:
    """Reset the empty-scrape streak after a successful parse."""
    health_file = SHARKS_DIR / "pipeline_health.json"
    if not health_file.exists():
        return
    try:
        with open(health_file) as f:
            health = json.load(f) or {}
        if int(health.get("schedule_empty_streak") or 0) > 0:
            health["schedule_empty_streak"] = 0
            health["last_successful_scrape_at"] = datetime.now(ET).isoformat()
            with open(health_file, "w") as f:
                json.dump(health, f, indent=2)
    except Exception:
        pass


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
        parsed = {"upcoming": [], "past": []}
        if text_content:
            parsed = _parse_schedule_text(text_content)
            schedule_data["games"] = parsed.get("upcoming", []) + parsed.get("past", [])
            total = len(schedule_data["games"])
            up_n = len(parsed.get("upcoming", []))
            past_n = len(parsed.get("past", []))
            print(f"[GC_SCHEDULE] Parsed {total} games ({up_n} upcoming, {past_n} past)")
            # Verbose preview to help diagnose schema/parser drift on empty results
            if total == 0:
                preview = text_content[:1000].replace("\n", " | ")
                print(f"[GC_SCHEDULE] Parser returned 0 games. Raw preview: {preview!r}")
                # Persist a sticky alert flag so monitoring can pick it up.
                # _alert_empty_scrape() bumps a counter on consecutive empty
                # runs and writes to data/sharks/pipeline_health.json.
                try:
                    _alert_empty_scrape(text_chars=len(text_content))
                except Exception as _ae:
                    print(f"[GC_SCHEDULE] Could not record empty-scrape alert: {_ae}")
            else:
                # Reset the empty-scrape streak on any parsed result.
                try:
                    _clear_empty_scrape_alert()
                except Exception:
                    pass

            # Merge into schedule_manual.json so the API picks it up.
            # GUARD: if the scrape returned 0 games, don't overwrite a
            # known-good file — only refresh `last_updated` so we know the
            # scraper ran. The PWA continues serving last-known schedule
            # while the parser/schema mismatch is fixed.
            manual_file = SHARKS_DIR / "schedule_manual.json"
            existing = {}
            if manual_file.exists():
                try:
                    with open(manual_file) as f:
                        existing = json.load(f)
                except Exception:
                    existing = {}
            scraped_total = len(parsed.get("upcoming", []) or []) + len(parsed.get("past", []) or [])
            existing_total = len(existing.get("upcoming", []) or []) + len(existing.get("past", []) or [])
            SHARKS_DIR.mkdir(parents=True, exist_ok=True)
            if scraped_total == 0 and existing_total > 0:
                print(
                    f"[GC_SCHEDULE] Scrape returned 0 parsed games but existing schedule_manual.json "
                    f"has {existing_total}. Preserving last-known-good content; only refreshing last_updated."
                )
                existing["last_updated"] = datetime.now(ET).isoformat()
                existing["last_empty_scrape_at"] = existing["last_updated"]
                with open(manual_file, "w") as f:
                    json.dump(existing, f, indent=2)
                print(f"[GC_SCHEDULE] Wrote {manual_file} (preserved {existing_total} existing games)")
            else:
                merged = _merge_schedule(existing, parsed)
                merged["last_updated"] = datetime.now(ET).isoformat()
                with open(manual_file, "w") as f:
                    json.dump(merged, f, indent=2)
                print(f"[GC_SCHEDULE] Wrote {manual_file}")
        else:
            print("[GC_SCHEDULE] No text content captured — schedule_manual.json not updated")

        # Write the raw schedule.json for debugging — but DO NOT clobber a
        # known-good file with an empty result. If we have zero games AND the
        # existing file has games, only refresh `last_updated` and bail.
        SHARKS_DIR.mkdir(parents=True, exist_ok=True)
        schedule_path = SHARKS_DIR / "schedule.json"
        new_count = len(schedule_data.get("games") or [])
        if new_count == 0 and schedule_path.exists():
            try:
                with open(schedule_path) as f:
                    prev = json.load(f) or {}
                prev_count = len(prev.get("games") or [])
                if prev_count > 0:
                    print(
                        f"[GC_SCHEDULE] Scrape returned 0 games but existing schedule.json "
                        f"has {prev_count}. Preserving last-known-good content; only refreshing last_updated."
                    )
                    prev["last_updated"] = schedule_data["last_updated"]
                    if "raw_content" in schedule_data:
                        prev["raw_content"] = schedule_data["raw_content"]
                    prev["last_empty_scrape_at"] = schedule_data["last_updated"]
                    with open(schedule_path, "w") as f:
                        json.dump(prev, f, indent=2)
                    return prev
            except Exception as e:
                print(f"[GC_SCHEDULE] Could not read existing schedule.json: {e}")

        with open(schedule_path, "w") as f:
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
