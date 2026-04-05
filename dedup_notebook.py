"""
dedup_notebook.py — Find and remove duplicate sources from NotebookLM notebooks.

Fetches the source list from each notebook, identifies duplicates by URL,
and deletes the extras (keeping the first occurrence).

Usage:
    python dedup_notebook.py                  # check all notebooks
    python dedup_notebook.py --notebook jack  # check specific notebook
    python dedup_notebook.py --dry-run        # show what would be deleted
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
NOTEBOOKS_JSON = ROOT / "notebooks.json"
DELAY = 1.0  # seconds between API calls

DRY_RUN = "--dry-run" in sys.argv
NOTEBOOK_FILTER = None
for i, arg in enumerate(sys.argv[1:], 1):
    if arg == "--notebook" and i < len(sys.argv) - 1:
        NOTEBOOK_FILTER = sys.argv[i + 1].lower()


def load_env():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.split("#")[0].strip()
                if k and k not in os.environ:
                    os.environ[k] = v

load_env()

sys.path.insert(0, str(ROOT))
from tools.mcp_client import MCPClient


# ── Source parser ─────────────────────────────────────────────────────────────

def parse_sources(result: dict) -> list[tuple[str, str, str]]:
    """
    Parse notebook_get response into list of (source_id, title, url) tuples.

    The notebooklm-mcp returns a nested list structure:
      result["notebook"][0][1] = sources list
      Each source: [[source_uuid], title, [null, n, ts, meta, n, [url, video_id, channel], n], ...]
    """
    parsed = []
    try:
        nb = result.get("notebook", [])
        if isinstance(nb, list) and nb:
            sources_list = nb[0][1] if len(nb[0]) > 1 else []
        else:
            sources_list = []

        for s in sources_list:
            id_part = s[0] if s else None
            source_id = id_part[0] if isinstance(id_part, list) and id_part else str(id_part)

            title = s[1] if len(s) > 1 else ""

            url = None
            meta = s[2] if len(s) > 2 else None
            if isinstance(meta, list) and len(meta) > 5:
                url_info = meta[5]
                if isinstance(url_info, list) and url_info:
                    url = url_info[0] if isinstance(url_info[0], str) else None

            if source_id and url:
                parsed.append((source_id, title or "", url))

    except (IndexError, TypeError, KeyError) as e:
        print(f"  [WARNING] Source parse error: {e}")

    return parsed


# ── Dedup logic ───────────────────────────────────────────────────────────────

def dedup_notebook(notebook_id: str, title: str, mcp: MCPClient) -> dict:
    """Get sources, find duplicates, delete extras."""
    print(f"\n{'='*60}")
    print(f"Notebook: {title}  ({notebook_id[:8]}...)")

    print("  Fetching sources from NotebookLM...")
    try:
        result = mcp.get_notebook(notebook_id)
    except Exception as e:
        print(f"  ERROR fetching notebook: {e}")
        return {"checked": 0, "duplicates": 0, "deleted": 0}

    sources = parse_sources(result)
    print(f"  Found {len(sources)} sources in NotebookLM")

    if not sources:
        print("  No sources found.")
        return {"checked": 0, "duplicates": 0, "deleted": 0}

    url_to_sources: dict[str, list] = {}
    no_url_count = 0

    for source_id, src_title, url in sources:
        if not url:
            no_url_count += 1
            continue
        url_to_sources.setdefault(url, []).append((source_id, src_title, url))

    duplicated_urls = {url: srcs for url, srcs in url_to_sources.items() if len(srcs) > 1}
    total_extra = sum(len(srcs) - 1 for srcs in duplicated_urls.values())

    print(f"  Unique URLs: {len(url_to_sources)}")
    print(f"  Duplicate URLs: {len(duplicated_urls)}  ({total_extra} extra sources to delete)")
    if no_url_count:
        print(f"  Sources with no URL (skipped): {no_url_count}")

    if not duplicated_urls:
        print("  No duplicates found.")
        return {"checked": len(sources), "duplicates": 0, "deleted": 0}

    deleted = 0
    failed = 0

    for url, srcs in duplicated_urls.items():
        keep_id, keep_title, _ = srcs[0]
        to_delete = srcs[1:]
        safe_url = url[:80].encode("ascii", errors="replace").decode("ascii")
        safe_title = keep_title[:50].encode("ascii", errors="replace").decode("ascii")
        print(f"\n  Dup ({len(srcs)}x): {safe_url}")
        print(f"    Keep: {keep_id}  ({safe_title})")

        for (s_id, s_title, s_url) in to_delete:
            if DRY_RUN:
                print(f"    [DRY RUN] Would delete: {s_id}")
                deleted += 1
                continue

            time.sleep(DELAY)
            try:
                mcp.delete_source(s_id)
                print(f"    Deleted: {s_id}")
                deleted += 1
            except Exception as e:
                print(f"    FAIL: {s_id} -> {e}")
                failed += 1

    return {"checked": len(sources), "duplicates": total_extra, "deleted": deleted, "failed": failed}


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    with open(NOTEBOOKS_JSON, encoding="utf-8") as f:
        data = json.load(f)

    targets = [
        nb for nb in data["notebooks"]
        if nb.get("status") == "active"
        and nb.get("id")
        and (not NOTEBOOK_FILTER or NOTEBOOK_FILTER in nb["title"].lower())
    ]

    if not targets:
        print("No matching notebooks.")
        return

    print(f"[INFO] Deduplicating {len(targets)} notebook(s)  DRY_RUN={DRY_RUN}")

    with MCPClient() as mcp:
        total_deleted = 0
        for nb in targets:
            result = dedup_notebook(nb["id"], nb["title"], mcp)
            total_deleted += result.get("deleted", 0)

    print(f"\n{'='*60}")
    print(f"DEDUP COMPLETE -- {total_deleted} duplicate sources {'would be ' if DRY_RUN else ''}deleted")


if __name__ == "__main__":
    main()
