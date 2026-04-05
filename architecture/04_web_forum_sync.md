# SOP-04: Web & Forum Source Sync
**Layer:** 1 — Architecture
**Enforced by:** `tools/fetch_web_sources.py`
**Applies to notebook types:** `forum`, `documentation`, `mixed`
**Last Updated:** 2026-03-19

---

## Purpose
Discover updated or new content from configured web URLs (forum threads, documentation pages, changelogs) using Firecrawl.

## Data Flow

```
Input:  notebook.config.forum_urls[]
        notebook.config.web_urls[]
        notebook.config.refresh_interval_days

Step 1: For each URL, call Firecrawl MCP
        Mode: scrape (single page) or crawl (follow links within domain)
        
        a) Forum index pages → crawl mode
           Extract all child thread/post URLs within domain
           Depth: 1 (do not go deep — just top-level posts)
        
        b) Documentation pages → scrape mode
           Extract last-modified header or on-page date
           If newer than registry last_checked → mark as updated
        
        c) Changelog URLs → scrape mode
           Look for date patterns in content
           Compare to last known modification date

Step 2: Filter new/updated content
        - For forum: URLs not in registry = candidates
        - For docs/changelogs: page content changed since last_checked

Step 3: Normalize URLs
        Strip tracking params: ?utm_*, ?ref=, #anchors (unless anchor is the content)
        
Step 4: Deduplicate → queue additions

Step 5: Return queue
        Output: [{url, title, last_modified, source_type}]
```

## Firecrawl Specifics

- Use `firecrawl_scrape` for single pages; `firecrawl_crawl` for index/forum pages
- Always cache the raw response to `.tmp/firecrawl_{hash}.json`
- Add 2-second delay between Firecrawl calls to be respectful of rate limits
- Max 20 URLs per run across all notebooks

## Staleness Detection for Existing Sources

When checking existing sources (from registry):
1. Re-fetch the URL via Firecrawl
2. Compare page hash to cached hash in `.tmp/`  
3. If unchanged AND older than `staleness_threshold_days` without activity → mark stale
4. Generate removal suggestion (user-approved)

## Error Handling

| Error | Action |
|---|---|
| HTTP 404 | Mark source as `"status": "dead"` — generate removal suggestion |
| HTTP 403/429 | Log, skip, cache failure in registry |
| Firecrawl timeout | Retry once with 5s delay; then skip |
| Blocked by robots.txt | Log and skip — never bypass robots.txt |

## Learning Log
- Reddit URLs: use `old.reddit.com` variants for better scrapeability
- Forum pages with JS rendering: Firecrawl handles JS by default
