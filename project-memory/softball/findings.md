# Findings: Softball

## Research & Discoveries

### GameChanger (gc.com) Data Access

- **No public API.** GC explicitly does not share their API.
- **CSV Export** is available for staff accounts at `web.gc.com` (Season Totals). Stat filters can be applied before export.
- **Box Score PDFs** can be generated per-game for staff members.
- **XML Export** is available only for college-level teams.
- **Browser Scraping** is the primary workaround. Users report success with:
  - Inspecting `web.gc.com` via browser DevTools to find internal JSON endpoints.
  - Playwright/Puppeteer browser automation to log in and scrape stats.
  - Chrome extensions that export game stats as CSV.
- **Team Pages** are publicly shareable with season records and game info.
- **Career Stats** require a Premium Subscription.

### Palm Coast Little League (PCLL)

- **Divisions for Spring 2026**: Machine Pitch, Minors, Majors, Seniors Softball.
- **Key Rules (2025-2026 LL Softball)**:
  - Pitching: No restrictions on number of pitchers per game (Majors+). Pitcher removed from circle can return once in same inning.
  - Batting: BPF 1.20 required for non-wood bats.
  - Mandatory Play: 1 at-bat and 6 defensive outs minimum per player.
  - Courtesy Runners: 2 allowed with continuous batting order (last out / second-to-last out).
  - One-way communication devices allowed (dugout to catcher for pitch calling).
- **Local rules** — specific PCLL supplements not found online. User should provide or we scrape from PCLL site when published.

### SWOT Analysis Framework for Softball

- **Strengths** (Internal): High OBP, speed, defensive range, power hitting.
- **Weaknesses** (Internal): Low BA, frequent strikeouts, inconsistent fielding, slow baserunning.
- **Opportunities** (External): Weak opponent pitching, favorable matchups, positional flexibility.
- **Threats** (External): Strong opponent bats, weather, injuries, umpire tendencies.

### Key Statistics to Track

| Category | Stats |
| :--- | :--- |
| **Hitting** | BA, OBP, SLG, OPS, RBI, H, AB, K, BB, HBP, 2B, 3B, HR |
| **Pitching** | ERA, WHIP, K, BB, W/L, IP |
| **Fielding** | Fielding %, PO, A, E |
| **Baserunning** | SB, CS, Runs |

### Lineup Optimization Strategy

- **1st (Leadoff)**: High OBP, speed, discipline.
- **2nd**: Good contact, advances runners.
- **3rd**: Best all-around hitter (average + power).
- **4th (Cleanup)**: Power hitter, RBI producer.
- **5th**: Secondary power or speed threat.
- **6-9**: Contact hitters, development spots, or a second leadoff type at 9th.

### User's Practice Plans (Google Doc)

- **3 practice sessions documented**: 2/4/2026, 2/14/2026, + Home Steal Drill.
- **Themes**: Arm strength, throwing mechanics, baserunning, outfield positioning, fielding strategy, force outs, live situations, cutoffs, pickle drills.
- **Format**: Numbered drills with objectives, key coaching points, and competitive games.

## Constraints & Limitations

- **GC Access**: Requires user's staff login credentials for scraping/export. No API keys needed — browser auth only.
- **Audio Mixing**: N/A (wrong project — this is strategy).
- **Data Refresh**: Must handle GC session/cookie management for repeated scraping.
- **NotebookLM Integration**: Need to determine API/MCP access for uploading categorized stats.
- **Google Docs Integration**: Practice plans need to be appended to the existing Google Doc.
