"""
registry_manager.py — Load, sync, and save the notebooks.json registry.
Layer 3 Tool | NotebookLM Librarian
SOP Reference: architecture/01_notebook_registry.md
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

REGISTRY_PATH = Path(__file__).parent.parent / "notebooks.json"


def load() -> dict:
    """Load the registry from disk. Raises FileNotFoundError if missing."""
    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(f"Registry not found at {REGISTRY_PATH}. Run initial setup first.")
    with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save(registry: dict):
    """Atomically save the registry to disk."""
    tmp = REGISTRY_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)
    tmp.replace(REGISTRY_PATH)


def get_managed_notebooks(registry: dict) -> list:
    """Return only owned, non-deleted notebooks with auto_add=true or managed types."""
    return [
        nb for nb in registry["notebooks"]
        if nb["ownership"] == "owned"
        and nb.get("status") not in ("deleted",)
        and nb.get("config", {}).get("auto_add", False)
    ]


def get_all_owned(registry: dict) -> list:
    """Return all owned notebooks regardless of auto_add status."""
    return [nb for nb in registry["notebooks"] if nb["ownership"] == "owned"]


def find_notebook(registry: dict, notebook_id: str) -> Optional[dict]:
    """Find a notebook by ID."""
    for nb in registry["notebooks"]:
        if nb["id"] == notebook_id:
            return nb
    return None


def get_source_urls(notebook: dict) -> set:
    """Return normalized set of all source URLs for a notebook."""
    return {s["url"] for s in notebook.get("sources", []) if s.get("url")}


def add_source_to_registry(notebook: dict, url: str, title: str, source_type: str, source_id: str = None):
    """Add a source entry to the in-memory notebook registry (call save() after)."""
    if "sources" not in notebook:
        notebook["sources"] = []
    notebook["sources"].append({
        "source_id": source_id,
        "url": url,
        "title": title,
        "type": source_type,
        "added_at": datetime.now(timezone.utc).isoformat(),
        "last_checked": datetime.now(timezone.utc).isoformat(),
        "is_stale": False,
        "is_duplicate": False,
        "added_externally": False,
    })
    notebook["last_synced"] = datetime.now(timezone.utc).isoformat()


def mark_stale(notebook: dict, url: str):
    """Mark a source URL as stale."""
    for source in notebook.get("sources", []):
        if source.get("url") == url:
            source["is_stale"] = True
            source["last_checked"] = datetime.now(timezone.utc).isoformat()


def sync_from_live(notebook: dict, live_sources: list):
    """
    Reconcile registry sources against live NotebookLM sources.
    live_sources: list of {id, url, title} dicts from MCP notebook_get
    Returns: (added_externally: list, removed_externally: list)
    """
    registry_urls = {s["url"]: s for s in notebook.get("sources", [])}
    live_urls = {s.get("url", ""): s for s in live_sources if s.get("url")}

    added_externally = []
    removed_externally = []

    # Sources in live but not in registry
    for url, live_src in live_urls.items():
        if url and url not in registry_urls:
            add_source_to_registry(
                notebook,
                url=url,
                title=live_src.get("title", ""),
                source_type=live_src.get("type", "unknown"),
                source_id=live_src.get("id"),
            )
            notebook["sources"][-1]["added_externally"] = True
            added_externally.append(url)

    # Sources in registry but not in live (removed externally)
    for url, reg_src in registry_urls.items():
        if url and url not in live_urls:
            reg_src["status"] = "removed"
            removed_externally.append(url)

    return added_externally, removed_externally


if __name__ == "__main__":
    if "--test" in sys.argv:
        reg = load()
        owned = get_all_owned(reg)
        print(f"✅ Registry loaded. Owned notebooks: {len(owned)}")
        for nb in owned:
            print(f"  - [{nb.get('type','?')}] {nb['title']} ({nb.get('status','?')})")
