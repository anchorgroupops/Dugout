# 📚 The Librarian: Handoff to Claude Code

## Project Context
"The Librarian" is a premium automation layer for NotebookLM. It manages notebook synchronization, deep YouTube scraping (bypassing RSS limits), and automated workspace cleanup. It is branded with a **Google Color Scheme**.

## Current State
- **Branding:** Renamed from "NotebookLM Librarian" to "The Librarian". Dashboard is fully reskinned with Google colors and logo.
- **Sync Engine:** `orchestrator.py` is configured for **Deep Sync** (last 200 videos) for Jack Roberts, Jon Cheplak, and Nate Herk.
- **Cleanup:** `nb_cleaner.py` (Playwright) is integrated to delete empty notebooks older than 7 days.
- **n8n Ready:** `api.py` (Flask) is functional and ready for deployment to the Raspberry Pi (`192.168.7.222`).

## Live Sync Result (2026-03-19)
- **Jon Cheplak:** Successfully scraped ~148 recent videos.
- **Jack Roberts:** Scraped recent content.
- **Status:** All sources are queued in `notebooks.json`.

## Phase 8: Your Mission (Production Ready)
1. **Pi Deployment:** Migrate the codebase to the Raspberry Pi 5 (`192.168.7.222`).
2. **n8n Integration:** Setup a webhook in your n8n instance to trigger `python api.py`. Ensure it can reach the Pi on port 5000.
3. **Write to NotebookLM:** The orchestrator identifies additions but the `nb_writer.py` needs to be actively called to push URLs to NotebookLM via the MCP. Ensure the Pi has the correct cookies/auth for `notebooklm-mcp`.
4. **Final Polish:** Ensure `the-librarian.com` placeholder or subpath is reachable if requested by the user.

## Instructions for Continuation
Run `python tools/orchestrator.py` to see the current queued additions. Use the `notebooklm` MCP tools to execute those additions into the notebooks identified in `notebooks.json`.
