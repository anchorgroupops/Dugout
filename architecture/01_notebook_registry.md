# SOP-01: Notebook Registry Management
**Layer:** 1 — Architecture
**Enforced by:** `tools/registry_manager.py`
**Last Updated:** 2026-03-19

---

## Purpose
The `notebooks.json` file is the single source of truth for all notebooks the Librarian manages. It bridges the gap between NotebookLM's live state and our local knowledge of each notebook's purpose, configuration, and source history.

## Registry Lifecycle

```
Startup → Load notebooks.json
       → Sync with NotebookLM (list actual sources via MCP)
       → Detect drift (sources added/removed outside Librarian)
       → Save reconciled state
Shutdown → Always write updated registry before exit
```

## Rules

1. **Load before any operation.** No tool may read or write notebook data without first loading the registry via `registry_manager.load()`.
2. **Sync on every run.** On startup, compare registry source lists against live NotebookLM data. Log any drift (sources added manually, etc.).
3. **Write atomically.** Write to `notebooks.json.tmp`, then rename. Never write directly to `notebooks.json` — prevents corruption on crash.
4. **Owned-only enforcement.** Any notebook with `ownership = "shared_with_me"` must be loaded as read-only. `registry_manager` raises `PermissionError` if a write is attempted on a shared notebook.
5. **Never delete entries.** If a notebook is deleted from NotebookLM, mark it `"status": "deleted"` but keep the record.

## Notebook Type Reference

| Type | Description | Tools Used |
|---|---|---|
| `documentation` | Sources are official docs/changelogs | Firecrawl |
| `project` | Static project reference — manually managed | None (read-only) |
| `mixed` | Multiple source types | Multiple fetchers |
| `unclassified` | Not yet configured | None — suggestion generated |

## Drift Detection

On every sync, compare registry source URLs vs. live NotebookLM sources:
- **New in NotebookLM, not in registry** → Add to registry, mark `"added_externally": true`
- **In registry, not in NotebookLM** → Mark as `"status": "removed"` — do NOT re-add automatically
- **Matches** → Update `last_checked` timestamp
