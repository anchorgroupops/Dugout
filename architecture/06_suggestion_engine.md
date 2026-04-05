# SOP-06: Suggestion Engine
**Layer:** 1 — Architecture
**Enforced by:** `tools/suggestion_engine.py`
**Last Updated:** 2026-03-19

---

## Purpose
Generate an actionable, prioritized suggestion list for user review. The Suggestion Engine is the Librarian's "intelligence" layer — it identifies opportunities beyond routine source additions.

## When Suggestions Are Generated

The engine runs after every Orchestrator cycle and evaluates:

| Trigger Condition | Suggestion Type | Priority |
|---|---|---|
| Notebook source count > max_sources | `remove_source` (oldest LRU) | HIGH |
| Source URL returns HTTP 404 | `remove_source` (dead link) | HIGH |
| Notebook has 0 sources and >30 days old | `delete_notebook` or `configure_notebook` | MEDIUM |
| 3+ notebooks share the same YouTube channel | `merge_notebooks` | MEDIUM |
| Notebook is `unclassified` | `classify_notebook` | MEDIUM |
| Known topic gap detected (e.g., new tech mentioned in queries) | `create_notebook` | LOW |
| Source URL unchanged for > staleness_threshold_days | `remove_source` (stale) | LOW |

## Reasoning Quality Rules

Every suggestion MUST include a `reasoning` string that is:
- Written in plain English, one to two sentences
- Specific: names the notebook and the source/action
- Non-alarming: constructive, not critical

**Bad:** "Source is stale."
**Good:** "The source 'Reddit: r/n8n Weekly discussion' has not changed in 94 days. A fresher thread from the same subreddit is available as a candidate replacement."

## Approval Gate Protocol

```
1. Write suggestions.json
2. Display to user via dashboard or CLI summary
3. User marks each suggestion: approved | rejected
4. Orchestrator reads approved list → executes via nb_writer.py
5. Update suggestions.json status field
6. Log all executions to logger.py
```

## Proactive New Notebook Suggestions

The engine scans the user's query history (from `notebook_query` MCP usage) and existing source topics to identify:
- Clusters of sources in one notebook that could form a standalone notebook
- Topic areas with no existing notebook coverage
- Channels/topics mentioned in approved sources that aren't yet tracked

These are always LOW priority and require explicit user approval.

## Output Format

```json
{
  "generated_at": "2026-03-19T08:00:00Z",
  "suggestions": [
    {
      "id": "uuid",
      "type": "remove_source",
      "priority": "high",
      "target_notebook_id": "9a93f238-...",
      "reasoning": "Source 'docs.n8n.io/v0.195' returns 404. The page was removed when n8n restructured their docs in Jan 2026.",
      "payload": {
        "source_ids_to_remove": ["source-uuid-here"],
        "url": "https://docs.n8n.io/old-path"
      },
      "status": "pending"
    }
  ]
}
```
