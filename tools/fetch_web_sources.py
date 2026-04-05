"""
fetch_web_sources.py — Discover updated/new content from web/forum URLs via Firecrawl MCP.
Layer 3 Tool | NotebookLM Librarian
SOP Reference: architecture/04_web_forum_sync.md

Uses the Firecrawl MCP server for web scraping and link extraction.
"""
import hashlib
import json
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

CACHE_DIR = Path(__file__).parent.parent / ".tmp" / "firecrawl_cache"


def _cache_path(url: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    h = hashlib.md5(url.encode()).hexdigest()
    return CACHE_DIR / f"{h}.json"


def _load_cache(url: str) -> dict | None:
    p = _cache_path(url)
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def _save_cache(url: str, data: dict):
    with open(_cache_path(url), "w", encoding="utf-8") as f:
        json.dump(data, f)


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def scrape_page(url: str, mcp_client: Any, use_cache: bool = True, cache_max_age_hours: int = 4) -> dict:
    """
    Scrape a single page via Firecrawl MCP.

    Args:
        url: Target URL to scrape
        mcp_client: Firecrawl MCP client (injected by orchestrator)
        use_cache: Use cached response if fresh enough
        cache_max_age_hours: Max cache age in hours

    Returns:
        {url, title, content_hash, links: [], last_modified, is_updated: bool}
    """
    cached = _load_cache(url) if use_cache else None
    if cached:
        age_hours = (time.time() - cached.get("cached_at_ts", 0)) / 3600
        if age_hours < cache_max_age_hours:
            return cached

    try:
        result = mcp_client.scrape(url=url, formats=["markdown", "links"])
        content = result.get("markdown", "")
        links = result.get("links", [])
        title = result.get("metadata", {}).get("title", "")
        new_hash = _content_hash(content)
        old_hash = cached.get("content_hash") if cached else None

        data = {
            "url": url,
            "title": title,
            "content_hash": new_hash,
            "links": links,
            "last_modified": datetime.now(timezone.utc).isoformat(),
            "is_updated": new_hash != old_hash if old_hash else True,
            "cached_at_ts": time.time(),
            "status": "ok",
        }
        _save_cache(url, data)
        return data

    except Exception as e:
        error_str = str(e)
        print(f"[WARNING] Firecrawl scrape failed for {url}: {error_str}")
        status = "dead" if "404" in error_str else "error"
        return {"url": url, "title": "", "content_hash": None, "links": [], "is_updated": False, "status": status, "error": error_str}


def crawl_forum_index(index_url: str, mcp_client: Any, max_links: int = 20, delay_secs: float = 2.0) -> list[dict]:
    """
    Crawl a forum index page and return child thread links as source candidates.

    Args:
        index_url: Forum index/listing page
        mcp_client: Firecrawl MCP client
        max_links: Max links to extract from the index
        delay_secs: Polite delay between requests

    Returns:
        List of {url, title, type} dicts
    """
    page = scrape_page(index_url, mcp_client)
    if page["status"] != "ok":
        print(f"[WARNING] Failed to crawl forum index {index_url}")
        return []

    from urllib.parse import urlparse
    base_domain = urlparse(index_url).netloc.replace("www.", "")

    candidates = []
    for link in page.get("links", [])[:max_links * 3]:
        href = link if isinstance(link, str) else link.get("url", "")
        # Only follow same-domain links
        if base_domain in href and href != index_url and not href.endswith(("#", ".pdf", ".jpg", ".png")):
            candidates.append({
                "url": href,
                "title": "",  # Will populate on scrape or from link text
                "type": "web",
            })
        if len(candidates) >= max_links:
            break

    return candidates


def check_staleness(source_url: str, last_checked: str, staleness_days: int, mcp_client: Any) -> dict:
    """
    Check if an existing source has gone stale (no update + old).

    Returns:
        {url, is_stale, is_dead, reason}
    """
    page = scrape_page(source_url, mcp_client)

    if page["status"] == "dead":
        return {"url": source_url, "is_stale": False, "is_dead": True, "reason": "404 — page no longer exists"}

    try:
        last_dt = datetime.fromisoformat(last_checked.replace("Z", "+00:00"))
        age_days = (datetime.now(timezone.utc) - last_dt).days
        is_stale = age_days > staleness_days and not page["is_updated"]
        reason = f"No update detected in {age_days} days (threshold: {staleness_days})" if is_stale else None
    except (ValueError, AttributeError):
        is_stale = False
        reason = None

    return {"url": source_url, "is_stale": is_stale, "is_dead": False, "reason": reason}
