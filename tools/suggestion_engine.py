"""
suggestion_engine.py — Generate a prioritized suggestion list for user review.
Layer 3 Tool | NotebookLM Librarian
SOP Reference: architecture/06_suggestion_engine.md
"""
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SUGGESTIONS_PATH = Path(__file__).parent.parent / "suggestions.json"

# Max sources per notebook before triggering overflow removal suggestions
DEFAULT_MAX_SOURCES = 50


def _make_suggestion(
    s_type: str,
    priority: str,
    reasoning: str,
    target_notebook_id: str = None,
    payload: dict = None,
) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "type": s_type,
        "priority": priority,
        "target_notebook_id": target_notebook_id,
        "reasoning": reasoning,
        "payload": payload or {},
        "status": "pending",
    }


def generate_suggestions(registry: dict, analysis_results: dict) -> list[dict]:
    """
    Evaluate the registry and analysis results to produce actionable suggestions.

    Args:
        registry: Full notebooks.json registry dict
        analysis_results: {
            "dead_sources": [{notebook_id, url, source_id}],
            "stale_sources": [{notebook_id, url, source_id, age_days}],
            "overflow_notebooks": [{notebook_id, current_count, max_sources}],
        }

    Returns:
        List of suggestion dicts
    """
    suggestions = []
    titles = {nb["id"]: nb["title"] for nb in registry["notebooks"]}

    # --- Dead source removal (HIGH priority) ---
    for dead in analysis_results.get("dead_sources", []):
        nb_title = titles.get(dead["notebook_id"], dead["notebook_id"])
        suggestions.append(_make_suggestion(
            s_type="remove_source",
            priority="high",
            target_notebook_id=dead["notebook_id"],
            reasoning=f"The source '{dead['url']}' in notebook '{nb_title}' returns a 404 error — the page no longer exists. Removing it will keep the notebook clean.",
            payload={"url": dead["url"], "source_ids_to_remove": [dead.get("source_id", "")]},
        ))

    # --- Overflow removal (HIGH priority) ---
    for overflow in analysis_results.get("overflow_notebooks", []):
        nb_title = titles.get(overflow["notebook_id"], overflow["notebook_id"])
        suggestions.append(_make_suggestion(
            s_type="remove_source",
            priority="high",
            target_notebook_id=overflow["notebook_id"],
            reasoning=f"Notebook '{nb_title}' has {overflow['current_count']} sources, exceeding the {overflow['max_sources']} source limit. Suggest removing the oldest {overflow['current_count'] - overflow['max_sources']} sources to make room for new content.",
            payload={"notebook_id": overflow["notebook_id"], "remove_count": overflow["current_count"] - overflow["max_sources"]},
        ))

    # --- Empty/stale notebooks (MEDIUM priority) ---
    for nb in registry["notebooks"]:
        if nb["ownership"] != "owned":
            continue
        if nb.get("status") == "empty_stale":
            suggestions.append(_make_suggestion(
                s_type="delete_notebook",
                priority="medium",
                target_notebook_id=nb["id"],
                reasoning=f"Notebook '{nb['title'] or '(Untitled)'}' has been empty since {nb.get('created_at', 'unknown date')}. It appears to be unused. Consider deleting it to keep your collection tidy.",
                payload={"notebook_id": nb["id"], "title": nb.get("title", "(Untitled)")},
            ))

    # --- Unclassified notebooks (MEDIUM priority) ---
    for nb in registry["notebooks"]:
        if nb["ownership"] != "owned":
            continue
        if nb.get("type") == "unclassified" and nb.get("status") != "empty_stale":
            suggestions.append(_make_suggestion(
                s_type="classify_notebook",
                priority="medium",
                target_notebook_id=nb["id"],
                reasoning=f"Notebook '{nb['title']}' is unclassified. Run the inspector to analyze its sources and set a type (youtube_channel, forum, documentation, etc.) so the Librarian can auto-manage it.",
                payload={"notebook_id": nb["id"]},
            ))

    # --- Stale sources (LOW priority) ---
    for stale in analysis_results.get("stale_sources", []):
        nb_title = titles.get(stale["notebook_id"], stale["notebook_id"])
        suggestions.append(_make_suggestion(
            s_type="remove_source",
            priority="low",
            target_notebook_id=stale["notebook_id"],
            reasoning=f"The source '{stale['url']}' in notebook '{nb_title}' has shown no updates in {stale['age_days']} days. It may be outdated. Review and remove if no longer relevant.",
            payload={"url": stale["url"], "source_ids_to_remove": [stale.get("source_id", "")]},
        ))

    # --- Proactive new notebook suggestions (LOW priority) ---
    # Suggest creating topic notebooks based on current inventory gaps
    owned_types = {nb.get("type") for nb in registry["notebooks"] if nb["ownership"] == "owned"}
    if "youtube_topic" not in owned_types:
        suggestions.append(_make_suggestion(
            s_type="create_notebook",
            priority="low",
            reasoning="You don't have any owned YouTube topic notebooks. Based on your existing sources (n8n, MCP, AI agents, real estate tech), you could benefit from topic-based notebooks that auto-discover new videos. Suggestions: 'AI Agents & MCP', 'Real Estate Tech', 'Homelab & Pi'.",
            payload={"suggested_notebooks": ["AI Agents & MCP", "Real Estate Tech", "Homelab & Pi"]},
        ))

    return suggestions


def save_suggestions(suggestions: list[dict]) -> Path:
    """Save suggestions to suggestions.json and return the path."""
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(suggestions),
        "pending": sum(1 for s in suggestions if s["status"] == "pending"),
        "suggestions": suggestions,
    }
    tmp = SUGGESTIONS_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp.replace(SUGGESTIONS_PATH)
    return SUGGESTIONS_PATH


def load_approved(suggestions: list[dict]) -> list[dict]:
    """Return only approved suggestions ready for execution."""
    return [s for s in suggestions if s["status"] == "approved"]


def print_summary(suggestions: list[dict]):
    by_priority = {"high": [], "medium": [], "low": []}
    for s in suggestions:
        by_priority[s["priority"]].append(s)

    print(f"\n💡 Suggestion Summary ({len(suggestions)} total):")
    for priority, items in by_priority.items():
        if items:
            emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}[priority]
            print(f"  {emoji} {priority.upper()} ({len(items)}):")
            for s in items:
                print(f"     [{s['type']}] {s['reasoning'][:80]}...")
    print(f"\n  📄 Suggestions written to: {SUGGESTIONS_PATH}")
