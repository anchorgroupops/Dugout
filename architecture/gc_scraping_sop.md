# GameChanger Scraping SOP

## Access Rules

> **🚨 CRITICAL: All GC access is STRICTLY READ-ONLY.**
> NEVER modify, delete, or write any data on gc.com.
> Any write action requires EXPLICIT Q&A approval from the user.

## Authentication

1. Credentials stored in `.env` (GC_EMAIL, GC_PASSWORD)
2. Login via Playwright at `https://web.gc.com/login`
3. Fill email → fill password → click submit → wait for dashboard

## Scraping Flow

1. **Login** → Navigate to team → Navigate to Stats tab
2. **Primary Method**: Intercept internal API responses (XHR) for structured JSON
3. **Fallback**: Use GC's built-in CSV export (Staff → Stats → Export)
4. **Last Resort**: Parse HTML tables from the stats page

## Rate Limiting

- Wait 2-3 seconds between page navigations
- No more than 1 scrape per 15 minutes
- Never run concurrent scraper instances

## Error Handling

| Error | Action |
|:---|:---|
| Login failed | Check credentials in .env, retry once |
| Session expired | Re-login, retry from dashboard |
| Stats not loading | Wait 10s, reload page, retry |
| Export button missing | Fall back to API interception |
| Captcha/block | STOP. Notify user. Do not retry. |

## Output

- Team data → `data/sharks/team.json`
- Opponent data → `data/opponents/<name>/team.json`
- Raw captures → `.tmp/gc_api_capture.json`
