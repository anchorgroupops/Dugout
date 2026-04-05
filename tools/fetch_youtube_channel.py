"""
fetch_youtube_channel.py — Fetch new videos from YouTube channels via RSS or Data API.
Layer 3 Tool | NotebookLM Librarian
SOP Reference: architecture/02_youtube_channel_sync.md

Supports:
  - Channel IDs (UC...) and @handles
  - RSS mode: last ~15 videos, no API key required
  - Deep sync mode: up to 200 videos via YouTube Data API (requires YOUTUBE_API_KEY)
"""
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}
YT_API_BASE = "https://www.googleapis.com/youtube/v3"


# ── Handle Resolution ─────────────────────────────────────────────────────────

def resolve_handle(handle: str, api_key: str) -> str | None:
    """
    Resolve a YouTube @handle to a UC... channel ID via the Data API.
    Returns None if resolution fails.
    """
    clean = handle.lstrip("@")
    url = f"{YT_API_BASE}/channels?part=id&forHandle=%40{clean}&key={api_key}"
    try:
        req = Request(url, headers={"User-Agent": "NotebookLM-Librarian/1.0"})
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        items = data.get("items", [])
        if items:
            channel_id = items[0]["id"]
            print(f"[INFO] Resolved {handle} -> {channel_id}")
            return channel_id
        print(f"[WARNING] Could not resolve handle: {handle}")
        return None
    except HTTPError as e:
        print(f"[ERROR] Handle resolution failed for {handle}: HTTP {e.code}")
        return None
    except Exception as e:
        print(f"[ERROR] Handle resolution failed for {handle}: {e}")
        return None


# ── RSS Mode (no API key) ─────────────────────────────────────────────────────

def _parse_rss(xml_bytes: bytes) -> list[dict]:
    """Parse YouTube RSS XML into a list of video dicts."""
    root = ET.fromstring(xml_bytes)
    videos = []
    for entry in root.findall("atom:entry", NS):
        video_id_el = entry.find("yt:videoId", NS)
        title_el = entry.find("atom:title", NS)
        published_el = entry.find("atom:published", NS)
        if video_id_el is None:
            continue
        video_id = video_id_el.text
        videos.append({
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": title_el.text if title_el is not None else "",
            "published_at": published_el.text if published_el is not None else "",
            "type": "youtube",
        })
    return videos


def fetch_channel_rss(channel_id: str, max_age_days: int = 28, timeout: int = 10) -> list[dict]:
    """Fetch recent videos from a YouTube channel RSS feed (last ~15 videos)."""
    url = RSS_URL.format(channel_id=channel_id)
    try:
        req = Request(url, headers={"User-Agent": "NotebookLM-Librarian/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            xml_bytes = resp.read()
    except URLError as e:
        print(f"[WARNING] RSS fetch failed for channel {channel_id}: {e}")
        return []
    except Exception as e:
        print(f"[ERROR] Unexpected error fetching {channel_id}: {e}")
        return []

    try:
        videos = _parse_rss(xml_bytes)
    except ET.ParseError as e:
        print(f"[ERROR] XML parse failed for channel {channel_id}: {e}")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    fresh = []
    for v in videos:
        try:
            pub = datetime.fromisoformat(v["published_at"].replace("Z", "+00:00"))
            if pub >= cutoff:
                fresh.append(v)
        except (ValueError, AttributeError):
            fresh.append(v)

    print(f"[INFO] Channel {channel_id}: {len(videos)} via RSS, {len(fresh)} within {max_age_days}d window")
    return fresh


# ── Deep Sync Mode (YouTube Data API) ────────────────────────────────────────

def _uploads_playlist_id(channel_id: str) -> str:
    """Convert UC... channel ID to its uploads playlist ID (UU...)."""
    if channel_id.startswith("UC"):
        return "UU" + channel_id[2:]
    return channel_id


def fetch_channel_deep(
    channel_id: str,
    max_videos: int = 200,
    api_key: str = None,
    delay_secs: float = 0.5,
) -> list[dict]:
    """
    Fetch up to max_videos from a channel's uploads playlist via YouTube Data API.
    Paginates automatically (50 per page).
    Requires YOUTUBE_API_KEY.
    """
    if not api_key:
        print(f"[WARNING] Deep sync requires YOUTUBE_API_KEY. Falling back to RSS for {channel_id}.")
        return fetch_channel_rss(channel_id, max_age_days=365)

    playlist_id = _uploads_playlist_id(channel_id)
    videos = []
    page_token = None
    page = 0

    while len(videos) < max_videos:
        page += 1
        params = {
            "part": "snippet",
            "playlistId": playlist_id,
            "maxResults": min(50, max_videos - len(videos)),
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token

        url = f"{YT_API_BASE}/playlistItems?{urlencode(params)}"
        try:
            req = Request(url, headers={"User-Agent": "NotebookLM-Librarian/1.0"})
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            if e.code == 403:
                print(f"[ERROR] YouTube API quota exceeded. Stopping deep sync for {channel_id}.")
            else:
                print(f"[ERROR] YouTube API HTTP {e.code} for {channel_id}")
            break
        except Exception as e:
            print(f"[ERROR] Deep sync fetch failed for {channel_id}: {e}")
            break

        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            video_id = snippet.get("resourceId", {}).get("videoId")
            if not video_id:
                continue
            videos.append({
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "title": snippet.get("title", ""),
                "published_at": snippet.get("publishedAt", ""),
                "type": "youtube",
            })

        page_token = data.get("nextPageToken")
        if not page_token:
            break

        if delay_secs:
            time.sleep(delay_secs)

    print(f"[INFO] Channel {channel_id}: deep sync fetched {len(videos)} videos ({page} API pages)")
    return videos


# ── Public Interface ──────────────────────────────────────────────────────────

def fetch_channel(
    channel_id_or_handle: str,
    max_age_days: int = 28,
    timeout: int = 10,
    deep_sync: bool = False,
    max_videos: int = 200,
    api_key: str = None,
) -> list[dict]:
    """
    Fetch videos from a YouTube channel. Supports:
      - UC... channel IDs
      - @handle strings (resolved via API if api_key provided)
      - RSS mode (default) or deep sync mode (requires api_key)
    """
    channel_id = channel_id_or_handle

    # Resolve @handle to channel ID
    if channel_id_or_handle.startswith("@"):
        if api_key:
            resolved = resolve_handle(channel_id_or_handle, api_key)
            if resolved:
                channel_id = resolved
            else:
                print(f"[WARNING] Could not resolve {channel_id_or_handle}. Skipping.")
                return []
        else:
            # Try RSS directly with the handle — YouTube supports this for some handles
            rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id_or_handle}"
            print(f"[INFO] No API key — trying handle RSS directly for {channel_id_or_handle}")
            try:
                req = Request(rss_url, headers={"User-Agent": "NotebookLM-Librarian/1.0"})
                with urlopen(req, timeout=timeout) as resp:
                    xml_bytes = resp.read()
                videos = _parse_rss(xml_bytes)
                print(f"[INFO] Handle RSS for {channel_id_or_handle}: {len(videos)} videos")
                return videos
            except Exception:
                print(f"[WARNING] Handle RSS failed for {channel_id_or_handle}. Need API key to resolve handle.")
                return []

    # Fetch videos
    if deep_sync:
        return fetch_channel_deep(channel_id, max_videos=max_videos, api_key=api_key)
    else:
        return fetch_channel_rss(channel_id, max_age_days=max_age_days, timeout=timeout)


def fetch_channels(
    channel_ids: list[str],
    max_age_days: int = 28,
    delay_secs: float = 1.0,
    deep_sync: bool = False,
    max_videos: int = 200,
    api_key: str = None,
) -> list[dict]:
    """Fetch from multiple channels with a polite delay."""
    results = []
    for i, channel_id in enumerate(channel_ids):
        if i > 0:
            time.sleep(delay_secs)
        results.extend(fetch_channel(
            channel_id,
            max_age_days=max_age_days,
            deep_sync=deep_sync,
            max_videos=max_videos,
            api_key=api_key,
        ))
    return results


if __name__ == "__main__":
    # Test: python tools/fetch_youtube_channel.py @jackroberts
    # Test deep: python tools/fetch_youtube_channel.py @jackroberts --deep
    test_id = sys.argv[1] if len(sys.argv) > 1 else "@jackroberts"
    deep = "--deep" in sys.argv
    key = os.environ.get("YOUTUBE_API_KEY", "").strip() or None

    videos = fetch_channel(test_id, deep_sync=deep, max_videos=50, api_key=key)
    for v in videos[:5]:
        print(f"  [{v['published_at'][:10]}] {v['title']}\n  -> {v['url']}")
    print(f"\n✅ Total: {len(videos)} videos")
