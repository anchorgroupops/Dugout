"""
deduplicator.py — URL normalization and duplicate detection.
Layer 3 Tool | NotebookLM Librarian
SOP Reference: architecture/05_deduplication.md
"""
import re
import sys
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse


# Tracking params to strip from all URLs
STRIP_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "ref", "si", "t", "list", "feature", "pp", "index", "start_radio",
    "ab_channel", "fbclid", "gclid", "mc_eid", "_hsenc", "_hsmi",
}

YOUTUBE_DOMAINS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


def extract_youtube_id(url: str) -> str | None:
    """Extract YouTube video ID from any YouTube URL form."""
    parsed = urlparse(url)
    if parsed.netloc == "youtu.be":
        return parsed.path.lstrip("/").split("/")[0]
    if parsed.netloc in YOUTUBE_DOMAINS:
        qs = parse_qs(parsed.query)
        if "v" in qs:
            return qs["v"][0]
        # Handle /shorts/VIDEO_ID
        if "/shorts/" in parsed.path:
            return parsed.path.split("/shorts/")[1].split("/")[0]
        # Handle /live/VIDEO_ID
        if "/live/" in parsed.path:
            return parsed.path.split("/live/")[1].split("/")[0]
    return None


def normalize(url: str) -> str:
    """
    Normalize a URL to its canonical form.
    - Strips tracking params
    - Lowercases scheme and netloc
    - Removes trailing slashes
    - Converts all YouTube URL forms to watch?v=VIDEO_ID
    """
    url = url.strip()
    parsed = urlparse(url)

    # YouTube canonical normalization
    video_id = extract_youtube_id(url)
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"

    # General normalization
    clean_query = {
        k: v for k, v in parse_qs(parsed.query).items()
        if k.lower() not in STRIP_PARAMS
    }
    # Sort params for consistent comparison
    clean_query_str = urlencode(sorted({k: v[0] for k, v in clean_query.items()}.items()))

    normalized = urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path.rstrip("/"),
        parsed.params,
        clean_query_str,
        "",  # Strip fragment
    ))
    return normalized


def deduplicate(candidates: list[dict], existing_urls: set[str]) -> dict:
    """
    Remove duplicates from a candidate list against existing registry URLs.

    Args:
        candidates: list of {url, title, ...} dicts
        existing_urls: set of already-registered URLs (raw, will be normalized)

    Returns:
        {candidates_in, duplicates_found, duplicates, clean_queue}
    """
    normalized_existing = {normalize(u) for u in existing_urls if u}
    seen_this_run = set()

    clean_queue = []
    duplicates = []

    for item in candidates:
        url = item.get("url", "")
        if not url:
            continue
        norm = normalize(url)
        if norm in normalized_existing or norm in seen_this_run:
            duplicates.append(url)
        else:
            seen_this_run.add(norm)
            clean_queue.append({**item, "url_normalized": norm})

    return {
        "candidates_in": len(candidates),
        "duplicates_found": len(duplicates),
        "duplicates": duplicates,
        "clean_queue": clean_queue,
    }


if __name__ == "__main__":
    if "--test" in sys.argv:
        test_candidates = [
            {"url": "https://youtu.be/dQw4w9WgXcQ?si=abc123", "title": "Video A"},
            {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "title": "Video A (dupe)"},
            {"url": "https://www.youtube.com/watch?v=newvideo123", "title": "Video B"},
            {"url": "https://example.com/page?utm_source=twitter&ref=abc", "title": "Web Page"},
            {"url": "https://example.com/page", "title": "Web Page (dupe)"},
        ]
        existing = {
            "https://www.youtube.com/watch?v=alreadyhere",
        }
        result = deduplicate(test_candidates, existing)
        print(f"✅ Deduplicator test:")
        print(f"   In: {result['candidates_in']} | Dupes: {result['duplicates_found']} | Clean: {len(result['clean_queue'])}")
        for item in result["clean_queue"]:
            print(f"   → {item['url_normalized']}")
        for url in result["duplicates"]:
            print(f"   ✗ DUPE: {url}")
