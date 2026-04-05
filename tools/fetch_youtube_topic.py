"""
fetch_youtube_topic.py — Search YouTube by keyword/topic using Data API v3.
Layer 3 Tool | NotebookLM Librarian
SOP Reference: architecture/03_youtube_topic_search.md

Requires: YOUTUBE_API_KEY in .env
Quota: 100 units/search call. Free tier = 100 units/day = 1 search/day.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

CACHE_DIR = Path(__file__).parent.parent / ".tmp" / "yt_cache"
SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"


def _get_api_key() -> str | None:
    """Load API key from environment."""
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    return key if key else None


def _cache_key(query: str, published_after: str) -> str:
    import hashlib
    return hashlib.md5(f"{query}|{published_after}".encode()).hexdigest()


def search_topic(
    keywords: list[str],
    published_after_days: int = 7,
    max_results: int = 25,
    min_duration_seconds: int = 180,
    use_cache: bool = True,
) -> list[dict]:
    """
    Search YouTube for videos matching keywords.

    Args:
        keywords: list of search keywords (joined with OR)
        published_after_days: only return videos from last N days
        max_results: max results (YouTube cap: 50 per call)
        min_duration_seconds: filter out shorts < this duration (rough filter)
        use_cache: cache results to .tmp/ to save quota

    Returns:
        List of {url, title, published_at, channel_title, type} dicts
    """
    api_key = _get_api_key()
    if not api_key:
        print("[WARNING] YOUTUBE_API_KEY not set. Skipping topic search.")
        return []

    query = " OR ".join(f'"{k}"' if " " in k else k for k in keywords)
    published_after = (
        datetime.now(timezone.utc) - timedelta(days=published_after_days)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Check cache
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{_cache_key(query, published_after)}.json"
    if use_cache and cache_file.exists():
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_hours < 20:  # Cache valid for 20 hours
            print(f"[INFO] Using cached results for query: {query}")
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)

    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "order": "date",
        "publishedAfter": published_after,
        "maxResults": min(max_results, 50),
        "relevanceLanguage": "en",
        "key": api_key,
    }
    url = f"{SEARCH_URL}?{urlencode(params)}"

    try:
        req = Request(url, headers={"User-Agent": "NotebookLM-Librarian/1.0"})
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        if e.code == 403:
            print("[ERROR] YouTube API quota exceeded (403). Will retry tomorrow.")
        else:
            print(f"[ERROR] YouTube API HTTP error {e.code}: {e.reason}")
        return []
    except URLError as e:
        print(f"[ERROR] YouTube API network error: {e}")
        return []

    results = []
    for item in data.get("items", []):
        video_id = item.get("id", {}).get("videoId")
        snippet = item.get("snippet", {})
        if not video_id:
            continue
        results.append({
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": snippet.get("title", ""),
            "published_at": snippet.get("publishedAt", ""),
            "channel_title": snippet.get("channelTitle", ""),
            "type": "youtube",
            "query": query,
        })

    # Cache results
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(results, f)

    print(f"[INFO] Topic search '{query}': {len(results)} results found")
    return results


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
    keywords = sys.argv[1:] if len(sys.argv) > 1 else ["n8n automation", "MCP protocol AI"]
    vids = search_topic(keywords, published_after_days=14)
    for v in vids[:5]:
        print(f"  [{v['published_at'][:10]}] {v['title']}\n  → {v['url']}")
    print(f"\n✅ Total returned: {len(vids)}")
