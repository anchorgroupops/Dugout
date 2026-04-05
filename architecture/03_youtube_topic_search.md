# SOP-03: YouTube Topic / Keyword Search
**Layer:** 1 — Architecture
**Enforced by:** `tools/fetch_youtube_topic.py`
**Applies to notebook types:** `youtube_topic`
**Last Updated:** 2026-03-19

---

## Purpose
Discover new YouTube videos by keyword/topic for notebooks that track a subject area rather than a specific channel.

## Data Flow

```
Input:  notebook.config.youtube_topic_keywords[]
        notebook.config.refresh_interval_days
        YOUTUBE_API_KEY (from .env)

Step 1: Build search query
        Join keywords with " OR " for broad match
        OR use multiple queries (one per keyword) and merge

Step 2: Call YouTube Data API v3 — Search endpoint
        GET https://www.googleapis.com/youtube/v3/search
        params:
          q: {joined keywords}
          type: video
          order: date
          publishedAfter: {now - refresh_interval_days}ISO8601
          maxResults: 25
          relevanceLanguage: en
          videoDuration: any
          key: YOUTUBE_API_KEY

Step 3: Filter results
        Min video duration: > 3 minutes (exclude shorts by default)
        Min view count: configurable (default 0, skip if not fetching stats)
        
Step 4: Normalize URLs (same as SOP-02)
        Canonical: https://www.youtube.com/watch?v={VIDEO_ID}

Step 5: Deduplicate → queue additions (same as SOP-02 steps 4-6)

Output: [{url, title, published_at, channel_title, query}]
```

## Quota Management

YouTube Data API v3 has **100 units/day** free quota. Search costs **100 units** per call.
- **Hard limit:** 1 automated search per day (1 topic notebook per daily run).
- **Strategy:** Stagger topic notebooks — run each on a different day of the week.
- **Fallback:** If quota exceeded, fall back to RSS search via channel IDs if known.

## Graceful Degradation (No API Key)
If `YOUTUBE_API_KEY` is not set:
- Log warning: "YouTube topic search skipped — no API key configured"
- Skip all `youtube_topic` notebooks for this run
- Generate suggestion to add a key

## Error Handling

| Error | Action |
|---|---|
| 403 quotaExceeded | Log, skip, schedule retry next day |
| 400 invalid key | Log error clearly, disable topic notebooks until fixed |
| Network timeout | Log, skip, continue |
