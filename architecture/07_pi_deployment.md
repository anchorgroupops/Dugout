# SOP 07: Raspberry Pi 5 Deployment

Layer 3 — Infrastructure | The Librarian

## 📐 Overview

This SOP defines the process for deploying The Librarian to the Raspberry Pi 5 (`192.168.7.222`).

## 🛠️ Prerequisites

- Raspberry Pi 5 (ARM64)
- Python 3.12+
- `pip install notebooklm-mcp` (logged in with Google cookies)
- Syncthing (paired with development workstation)

## 📦 Deployment Steps

### 1. Sync Files

Ensure the `h:/Repos/NotebookLM Librarian` directory is synced to the Pi via Syncthing.
Destination path on Pi: `~/librarian`

### 2. Environment Configuration

Create/Update `~/librarian/.env` on the Pi:

```bash
LIBRARIAN_API_KEY=your_secure_key
LIBRARIAN_MCP_EXE=notebooklm-mcp  # Use the PATH version on Linux
YOUTUBE_API_KEY=your_google_key
MAX_SOURCES_PER_RUN=200
```

### 3. Install Dependencies

```bash
cd ~/librarian
pip install -r requirements.txt
playwright install chromium
```

### 4. Systemd Service (Process Management)

Create `/etc/systemd/system/librarian.service`:

```ini
[Unit]
Description=The Librarian API Gateway
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/librarian
ExecStart=/usr/bin/python3 api.py
Restart=always
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

### 5. Start and Enable

```bash
sudo systemctl daemon-reload
sudo systemctl enable librarian
sudo systemctl start librarian
```

## 🔍 Verification

1. Access the API health check: `http://librarian.joelycannoli.com/health`
2. Trigger a dry-run sync:

   ```bash
   curl -X POST http://librarian.joelycannoli.com/run -H "Authorization: Bearer key" -d '{"dry_run": true}'
   ```
