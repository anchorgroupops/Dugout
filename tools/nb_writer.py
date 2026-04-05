"""
nb_writer.py — Execute approved source additions via NotebookLM MCP.
Layer 3 Tool | NotebookLM Librarian

This tool is the ONLY component that writes to NotebookLM.
It operates under the strict approval gate defined in gemini.md.
"""
import os
import time
from pathlib import Path
from typing import Any

# Max sources that can be added in a single automated run (safety guard)
MAX_SOURCES_PER_RUN = int(os.environ.get("MAX_SOURCES_PER_RUN", "200"))
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"


def add_sources(
    notebook_id: str,
    sources: list[dict],
    mcp_client: Any,
    logger: Any,
    delay_secs: float = 1.5,
) -> dict:
    """
    Add a list of sources to a NotebookLM notebook via MCP.

    Args:
        notebook_id: NotebookLM notebook UUID
        sources: List of {url, title, type} dicts
        mcp_client: NotebookLM MCP client (injected by orchestrator)
        logger: RunLogger instance
        delay_secs: Polite delay between API calls

    Returns:
        {added: int, failed: int, skipped: int, results: list}
    """
    added, failed, skipped = 0, 0, 0
    results = []

    if len(sources) > MAX_SOURCES_PER_RUN:
        print(f"[WARNING] {len(sources)} sources requested but MAX_SOURCES_PER_RUN={MAX_SOURCES_PER_RUN}. Truncating.")
        sources = sources[:MAX_SOURCES_PER_RUN]

    for i, source in enumerate(sources):
        url = source.get("url", "")
        title = source.get("title", "")
        if not url:
            skipped += 1
            continue

        if DRY_RUN:
            print(f"[DRY RUN] Would add: {url} → notebook {notebook_id}")
            results.append({"url": url, "status": "dry_run"})
            added += 1
            continue

        if i > 0:
            time.sleep(delay_secs)

        try:
            result = mcp_client.notebook_add_url(notebook_id=notebook_id, url=url)
            if result and result.get("status") == "success":
                logger.log("add_source", notebook_id=notebook_id, source_url=url, status="success")
                results.append({"url": url, "status": "success", "source_id": result.get("source_id")})
                added += 1
            else:
                raise ValueError(f"MCP returned non-success: {result}")

        except Exception as e:
            error_msg = str(e)
            logger.log("add_source", notebook_id=notebook_id, source_url=url, status="failed", error=error_msg)
            results.append({"url": url, "status": "failed", "error": error_msg})
            failed += 1

    return {"added": added, "failed": failed, "skipped": skipped, "results": results}


def add_text_source(
    notebook_id: str,
    text: str,
    title: str,
    mcp_client: Any,
    logger: Any,
) -> dict:
    """Add a text/paste source to a notebook."""
    if DRY_RUN:
        print(f"[DRY RUN] Would add text source '{title}' → notebook {notebook_id}")
        return {"status": "dry_run"}
    try:
        result = mcp_client.notebook_add_text(notebook_id=notebook_id, text=text, title=title)
        if result and result.get("status") == "success":
            logger.log("add_text_source", notebook_id=notebook_id, status="success")
            return {"status": "success", "source_id": result.get("source_id")}
        raise ValueError(f"MCP returned: {result}")
    except Exception as e:
        logger.log("add_text_source", notebook_id=notebook_id, status="failed", error=str(e))
        return {"status": "failed", "error": str(e)}
