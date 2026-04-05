# SOP-02: YouTube Channel Sync
**Layer:** 1 — Architecture
**Enforced by:** `tools/fetch_youtube_channel.py`
**Applies to notebook types:** `youtube_channel`
**Last Updated:** 2026-03-19

---

## Purpose
Automatically discover new videos from configured YouTube channels and queue them for addition to the corresponding notebook.

## Data Flow

```
Input:  notebook.config.youtube_channel_ids[]
        notebook.config.refresh_interval_days
        notebook.config.max_sources

Step 1: Fetch RSS feed per channel_id
        URL: https://www.youtube.com/feeds/videos.xml?channel_id={id}
        Returns: Last 15 videos (Google limit — no API key needed)

Step 2: Filter by age
        Only videos published within last (refresh_interval_days * 4) days
        Rationale: weekly refresh × 4 = monthly horizon

Step 3: Normalize URLs
        Canonical form: https://www.youtube.com/watch?v={VIDEO_ID}
        Strip: ?si=, &t=, &list=, UTM params

Step 4: Deduplicate
        Pass to deduplicator.py with existing registry source URLs
        Discard any URL already in registry

Step 5: Enforce max_sources
        If (current_count + new_count) > max_sources:
          Generate removal suggestion (oldest videos first)
          Add only up to max_sources - current_count new videos
        
Step 6: Return queue
        Output: [{url, title, published_at, channel_id}]
```

## Error Handling

| Error | Action |
|---|---|
| RSS feed HTTP error / timeout | Log warning, skip channel, continue |
| Feed returns 0 items | Log info "channel has no new videos", skip |
| Malformed XML | Log error + raw response snippet, skip |

## Learning Log
- `?si=` param is YouTube's share tracking parameter — must be stripped before dedup
- RSS feeds are rate-limit-free but return only 15 videos; run at least weekly
- Channel IDs start with `UC`; handle `@handle` resolution separately if needed
