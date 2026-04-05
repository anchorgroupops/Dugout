# SOP 08: n8n Integration Guide

Layer 3 — Connectivity | The Librarian

## 📐 Overview

The Librarian is designed to be triggered by n8n for fully automated library maintenance.

## 🔌 Connection Setup

### 1. Credential Configuration

In n8n, create a **Header Auth** credential:

- **Name:** Authorization
- **Value:** `Bearer <LIBRARIAN_API_KEY>`

### 2. Trigger Workflow (The "Nightly Sync")

Create a scheduled n8n workflow:

- **Schedule Trigger:** Daily at 3:00 AM.
- **HTTP Request Node:**
  - **Method:** POST
  - **URL:** `http://librarian.joelycannoli.com/run`
  - **Body Format:** JSON
  - **Body Parameters:** `{"dry_run": false}`
  - **Authentication:** Header Auth (from step 1)

### 3. Status Reporting

To send a summary to Slack or Telegram after the sync completes:

- **HTTP Request Node:**
  - **Method:** GET
  - **URL:** `http://librarian.joelycannoli.com/status`
  - **Logic:** Filter `status.added > 0` and format a notification.

## 🛠️ Troubleshooting

- **Timeout:** If the JSON-RPC session in NotebookLM expires, `mcp_client.py` will attempt a reconnect. However, the Pi must remain logged in via `notebooklm-mcp-auth`.
- **CORS:** The dashboard (running on the Pi or your PC) can reach the API. If blocked, check the `CORS_ALLOW_ORIGIN` settings in `api.py`.
