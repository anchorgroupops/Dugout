#!/bin/bash
sudo python3 -c '
content = r"""[Unit]
Description=The Librarian Flask API
After=network.target

[Service]
User=joelycannoli
WorkingDirectory="/home/joelycannoli/repos/antigravity-repos/NotebookLM Librarian"
Environment=PYTHONPATH="/home/joelycannoli/repos/antigravity-repos/NotebookLM Librarian"
Environment=PYTHONUNBUFFERED=1
ExecStart="/home/joelycannoli/repos/antigravity-repos/NotebookLM Librarian/venv/bin/python3" api.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
with open("/etc/systemd/system/librarian.service", "w") as f:
    f.write(content)
'
sudo systemctl daemon-reload
sudo systemctl enable librarian.service
sudo systemctl restart librarian.service
