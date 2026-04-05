# SOP-05: URL Deduplication
**Layer:** 1 — Architecture
**Enforced by:** `tools/deduplicator.py`
**Called by:** All fetcher tools before queuing additions
**Last Updated:** 2026-03-19

---

## Purpose
Ensure no duplicate source URLs are added to a notebook. Deduplication must happen before any MCP write call.

## Normalization Pipeline

Every URL is run through this pipeline before comparison:

```python
# Step 1: Parse URL
parsed = urlparse(url.strip().lower())

# Step 2: Strip tracking params
STRIP_PARAMS = ["utm_source","utm_medium","utm_campaign","utm_content",
                "utm_term","ref","si","t","list","feature","pp","index",
                "start_radio","ab_channel"]
query = {k:v for k,v in parse_qs(parsed.query).items() if k not in STRIP_PARAMS}

# Step 3: YouTube canonical form
if "youtube.com" in parsed.netloc or "youtu.be" in parsed.netloc:
    video_id = extract_youtube_id(url)  # handles youtu.be and ?v= forms
    return f"https://www.youtube.com/watch?v={video_id}"

# Step 4: Remove trailing slash, lowercase, sort query params
normalized = parsed._replace(query=urlencode(sorted(query.items())), fragment="")
return normalized.geturl().rstrip("/")
```

## Duplicate Detection Logic

1. **Within-notebook dedupe:** Normalize all existing registry URLs for a notebook → store in a set → check each candidate against set.
2. **Cross-notebook dedupe:** NOT enforced (a URL can exist in multiple notebooks intentionally).
3. **Text source dedupe:** Hash the text content → compare hashes (no URL to normalize).

## YouTube ID Extraction

Handles all YouTube URL forms:
- `https://www.youtube.com/watch?v=VIDEO_ID`
- `https://youtu.be/VIDEO_ID`
- `https://www.youtube.com/shorts/VIDEO_ID`
- `https://m.youtube.com/watch?v=VIDEO_ID`

## Dedup Report Output

```json
{
  "candidates_in": 10,
  "duplicates_found": 3,
  "duplicates": ["https://youtube.com/watch?v=abc123", "..."],
  "clean_queue": [{"url": "...", "title": "..."}, ...]
}
```

## Learning Log
- `?si=` is YouTube's share-link tracking param — commonly causes false "new source" detection if not stripped
- `youtu.be` short URLs must be resolved to full `watch?v=` form for consistent dedup
