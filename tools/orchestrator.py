"""
orchestrator.py — Main run loop. Wires all Librarian tools together.
Layer 2 — Navigation | NotebookLM Librarian

State Machine:
  Load → Sync → Fetch → Deduplicate → Analyze → Suggest → (Gate) → Execute → Log → Save

Usage:
  python tools/orchestrator.py              # Normal run
  python tools/orchestrator.py --dry-run    # Simulate without writes
  python tools/orchestrator.py --inspect <notebook_id>  # Describe a notebook's sources
"""
import io
import os
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 stdout so emoji don't crash on Windows cp1252 terminals
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Add project root to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from tools.logger import RunLogger
from tools.registry_manager import (
    load, save, get_all_owned, find_notebook,
    get_source_urls, add_source_to_registry,
)
from tools.deduplicator import deduplicate
from tools.fetch_youtube_channel import fetch_channels
from tools.fetch_youtube_topic import search_topic
from tools.suggestion_engine import generate_suggestions, save_suggestions, print_summary as print_suggestions


# ── Env setup ────────────────────────────────────────────────────────────────

def load_env():
    env_path = ROOT / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


DRY_RUN = "--dry-run" in sys.argv or os.environ.get("DRY_RUN", "false").lower() == "true"


# ── Inspect Mode ─────────────────────────────────────────────────────────────

def inspect_notebook(notebook_id: str, registry: dict):
    """Print a detailed view of a notebook's sources and config."""
    nb = find_notebook(registry, notebook_id)
    if not nb:
        print(f"❌ Notebook {notebook_id} not found in registry.")
        return

    print(f"\n📖 Notebook: {nb['title']}")
    print(f"   ID: {nb['id']}")
    print(f"   Type: {nb.get('type', '?')} | Status: {nb.get('status', '?')}")
    print(f"   Ownership: {nb['ownership']}")
    print(f"   Sources in registry: {len(nb.get('sources', []))}")
    print(f"   Auto-add: {nb.get('config', {}).get('auto_add', False)}")
    print(f"   Config: {nb.get('config', {})}")
    if nb.get("sources"):
        print(f"\n   Source URLs:")
        for s in nb["sources"][:10]:
            flag = "🔴 STALE" if s.get("is_stale") else ("⚠️  EXT" if s.get("added_externally") else "")
            print(f"   [{s.get('type','?')}] {s.get('url','?')} {flag}")
        if len(nb["sources"]) > 10:
            print(f"   ... and {len(nb['sources']) - 10} more")


# ── Main Orchestrator ─────────────────────────────────────────────────────────

def run():
    load_env()
    log = RunLogger()

    mode = "DRY RUN" if DRY_RUN else "LIVE"
    print(f"\n{'='*60}")
    print(f"📚 The Librarian: Initialization started ({mode})")
    print(f"   {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}\n")

    # ── STEP 1: Load Registry ─────────────────────────────────────────────
    print("📂 Loading registry...")
    try:
        registry = load()
    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)

    owned_nbs = get_all_owned(registry)
    managed_nbs = [nb for nb in owned_nbs if nb.get("config", {}).get("auto_add", False)]
    print(f"   Owned notebooks: {len(owned_nbs)} | Auto-managed: {len(managed_nbs)}\n")

    if not managed_nbs:
        print("ℹ️  No notebooks have auto_add=true yet.")
        print("   Edit notebooks.json to set auto_add=true and configure sources for any notebook.")
        print("   Running suggestion/analysis pass on full inventory instead...\n")

    # ── STEP 1.5: Auto-Cleanup (Delete empty notebooks > 1 week) ──────
    print("🧹 Checking for stale empty notebooks...")
    to_delete = []
    now = datetime.now(timezone.utc)
    for nb in owned_nbs:
        created_at = datetime.fromisoformat(nb['created_at'].replace('Z', '+00:00'))
        if len(nb.get('sources', [])) == 0 and (now - created_at).days >= 7:
            to_delete.append(nb['id'])
    
    if to_delete:
        print(f"🗑️ Found {len(to_delete)} notebooks for auto-deletion.")
        if not DRY_RUN:
            subprocess.run([sys.executable, str(ROOT / "tools" / "nb_cleaner.py")] + to_delete)
            # Filter registry locally
            registry['notebooks'] = [nb for nb in registry['notebooks'] if nb['id'] not in to_delete]
            owned_nbs = get_all_owned(registry)
        else:
            print(f"   [DRY RUN] Would delete: {', '.join(to_delete)}")

    # ── STEP 2: Fetch new sources for managed notebooks ────────────────────
    additions_queue = {}  # notebook_id → [clean source dicts]

    for nb in managed_nbs:
        nb_id = nb["id"]
        nb_title = nb["title"]
        config = nb.get("config", {})
        nb_type = nb.get("type", "unclassified")
        existing_urls = get_source_urls(nb)

        print(f"🔄 Processing: '{nb_title}' [{nb_type}]")
        candidates = []

        # YouTube channel fetch
        channel_ids = config.get("youtube_channel_ids", [])
        if channel_ids and nb_type in ("youtube_channel", "mixed"):
            deep_sync = config.get("deep_sync", False)
            api_key = os.environ.get("YOUTUBE_API_KEY", "").strip() or None
            max_videos = config.get("max_sources", 50)
            raw = fetch_channels(
                channel_ids,
                max_age_days=config.get("refresh_interval_days", 7) * 4,
                deep_sync=deep_sync,
                max_videos=max_videos,
                api_key=api_key,
            )
            candidates.extend(raw)

        # YouTube topic search
        keywords = config.get("youtube_topic_keywords", [])
        if keywords and nb_type in ("youtube_topic", "mixed"):
            raw = search_topic(keywords, published_after_days=config.get("refresh_interval_days", 7))
            candidates.extend(raw)

        # Web/forum sources (needs Firecrawl MCP — placeholder for now)
        forum_urls = config.get("forum_urls", []) + config.get("web_urls", [])
        if forum_urls:
            print(f"   ℹ️  Web sources configured ({len(forum_urls)} URLs) — call via Firecrawl MCP in agent context")

        # Deduplicate
        if candidates:
            result = deduplicate(candidates, existing_urls)
            clean = result["clean_queue"]
            print(f"   Found {len(candidates)} candidates → {result['duplicates_found']} dupes removed → {len(clean)} to add")

            # Enforce max_sources
            max_sources = config.get("max_sources", 50)
            current_count = len(existing_urls)
            slots_available = max(0, max_sources - current_count)
            if len(clean) > slots_available:
                print(f"   ⚠️  Only {slots_available} slots available (max={max_sources}). Trimming queue.")
                clean = clean[:slots_available]

            additions_queue[nb_id] = clean
        else:
            print(f"   No new candidates found.")

    # ── STEP 3: Analysis Pass (suggestions) ───────────────────────────────
    print("\n🧠 Running analysis for suggestions...")
    analysis = {
        "dead_sources": [],
        "stale_sources": [],
        "overflow_notebooks": [],
    }

    for nb in owned_nbs:
        config = nb.get("config", {})
        max_sources = config.get("max_sources", 50)
        sources = nb.get("sources", [])

        # Check for overflow
        if len(sources) > max_sources:
            analysis["overflow_notebooks"].append({
                "notebook_id": nb["id"],
                "current_count": len(sources),
                "max_sources": max_sources,
            })

        # Check for stale/dead (from registry flags)
        for s in sources:
            if s.get("is_stale"):
                analysis["stale_sources"].append({
                    "notebook_id": nb["id"],
                    "url": s["url"],
                    "source_id": s.get("source_id"),
                    "age_days": 99,  # Will be calculated properly by staleness_checker
                })

    suggestions = generate_suggestions(registry, analysis)
    suggestions_path = save_suggestions(suggestions)
    log.data["summary"]["suggestions_generated"] = len(suggestions)
    print_suggestions(suggestions)

    # ── STEP 4: Execute additions ──────────────────────────────────────────
    if not DRY_RUN and additions_queue:
        print("\n[INFO] Writing sources to NotebookLM...")
        from tools.mcp_client import MCPClient, MCP_EXE
        from tools.nb_writer import add_sources
        from tools.notify import notify_sync_complete, notify_error
        from tools.db_sync import log_sync_run, ensure_tables

        ensure_tables()
        total_added = 0
        total_failed = 0

        if not Path(MCP_EXE).exists():
            print(f"[ERROR] MCP executable not found: {MCP_EXE}")
            notify_error("orchestrator write step", f"MCP exe missing: {MCP_EXE}")
        else:
            with MCPClient(MCP_EXE, client_name="librarian-orchestrator") as mcp:
                import time as _time
                for nb_id, sources in additions_queue.items():
                    nb = find_notebook(registry, nb_id)
                    nb_title = nb["title"] if nb else nb_id
                    print(f"[INFO] Writing {len(sources)} sources to '{nb_title}'...")
                    t0 = _time.monotonic()
                    result = add_sources(nb_id, sources, mcp, log)
                    duration_ms = int((_time.monotonic() - t0) * 1000)
                    log_sync_run(nb_id, nb_title, result["added"], result["failed"], duration_ms)
                    total_added += result["added"]
                    total_failed += result["failed"]
                    # Persist added sources to registry
                    if nb:
                        for res in result.get("results", []):
                            if res["status"] in ("success", "dry_run"):
                                add_source_to_registry(
                                    nb,
                                    url=res["url"],
                                    title=res.get("title", ""),
                                    source_type="youtube",
                                    source_id=res.get("source_id"),
                                )
                    print(f"[INFO] '{nb_title}': {result['added']} added, {result['failed']} failed")

            notify_sync_complete(total_added, total_failed, len(additions_queue), 0)

    elif DRY_RUN and additions_queue:
        print("\n[DRY RUN] Would add sources to:")
        for nb_id, sources in additions_queue.items():
            nb = find_notebook(registry, nb_id)
            nb_title = nb["title"] if nb else nb_id
            print(f"   → '{nb_title}': {len(sources)} new sources")
            for s in sources[:3]:
                print(f"     • {s.get('title', s['url'])[:60]}")

    # ── STEP 5: Save registry and log ─────────────────────────────────────
    registry.setdefault("_meta", {})["last_full_sync"] = datetime.now(timezone.utc).isoformat()
    save(registry)
    log.print_summary()

    print(f"\n✅ Run complete. Registry saved. Suggestions: {suggestions_path.name}")


# ── Entry Points ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--inspect" in sys.argv:
        idx = sys.argv.index("--inspect")
        nb_id = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        if not nb_id:
            print("Usage: python tools/orchestrator.py --inspect <notebook_id>")
            sys.exit(1)
        load_env()
        registry = load()
        inspect_notebook(nb_id, registry)
    else:
        run()
