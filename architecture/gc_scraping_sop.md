# GameChanger Scraping SOP

## Access Rules

> **CRITICAL: All GC access is STRICTLY READ-ONLY.**
> NEVER modify, delete, or write any data on gc.com.
> Any write action requires EXPLICIT Q&A approval from the user.

## Verified Team Coordinates

| Field | Value |
|:---|:---|
| **Team Name** | The Sharks |
| **Season** | Spring 2026 |
| **GC Team ID** | `NuGgx6WvP7TO` |
| **Stats URL** | `https://web.gc.com/teams/NuGgx6WvP7TO/2026-spring-sharks/season-stats` |
| **Schedule URL** | `https://web.gc.com/teams/NuGgx6WvP7TO/2026-spring-sharks/schedule` |
| **Team URL** | `https://web.gc.com/teams/NuGgx6WvP7TO/2026-spring-sharks/team` |

> [!WARNING]
> This GC account has **multiple teams named "Sharks"** across seasons.
> Always verify the roster includes distinctive names (Leila VanDeusen, Ruby VanDeusen, Sephina Santiago) before exporting stats.

## Authentication

1. Credentials stored in `.env` (`GC_EMAIL`, `GC_PASSWORD`)
2. Login at `https://web.gc.com/login`
3. Fill email → Click Continue → Fill password → Click Sign In
4. **2FA Required**: GC sends a verification code to the email. Enter the code and click Sign In again.
5. Session persists in the browser; subsequent scrapes within the same session skip 2FA.

## Scraping Flow

1. **Navigate** directly to the Stats URL above (skip dashboard navigation)
2. **Primary Method**: Click `Export stats` button at the bottom of the stats table → CSV download
3. **Fallback**: Parse HTML tables from the stats page via DOM extraction
4. **Box Scores**: Schedule tab → Click completed game → Box Score tab (contains both teams' stats)

## Roster Policy

- **Keep ALL players** in the GC export, including supplemental/borrowed players from opponent teams
- Mark supplemental players with `"core": false` in `team.json`
- Core roster players are marked `"core": true`
- This ensures lineup planning accounts for all available personnel

## Rate Limiting

- Wait 2-3 seconds between page navigations
- No more than 1 scrape per 15 minutes
- Never run concurrent scraper instances

## Error Handling

| Error | Action |
|:---|:---|
| Login failed | Check credentials in `.env`, retry once |
| 2FA code needed | Prompt user for email code, enter manually |
| Session expired | Re-login from scratch, request new 2FA |
| Stats not loading | Wait 10s, reload page, retry |
| Export button missing | Fall back to DOM table parsing |
| Captcha/block | STOP. Notify user. Do not retry |
| Wrong team selected | Verify roster names before exporting |

## Output Files

| File | Contents |
|:---|:---|
| `data/sharks/team.json` | Structured roster + stats (all players, batting/pitching/fielding) |
| `data/sharks/season_stats.csv` | Raw CSV from GC export |
| `data/sharks/lineups.json` | Generated lineup optimizations |
| `data/sharks/swot_analysis.json` | SWOT analysis output |
| `data/sharks/next_practice.txt` | Generated practice plan |
| `data/opponents/game_[date]_[name].json` | Per-game box scores |
