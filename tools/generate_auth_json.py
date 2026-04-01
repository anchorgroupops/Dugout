"""Generate a Playwright auth.json from environment variables.

Required env vars:
  GC_EDEN_AUTH_TOKENS   – eden-auth-tokens localStorage value
  GC_PERSIST_ROOT       – persist:root localStorage value

Optional env vars:
  GC_AUTH_OUTPUT        – output path (default: data/auth.json)
"""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

EDEN_AUTH_TOKENS = os.getenv("GC_EDEN_AUTH_TOKENS", "").strip()
PERSIST_ROOT = os.getenv("GC_PERSIST_ROOT", "").strip()

if not EDEN_AUTH_TOKENS or not PERSIST_ROOT:
    print("ERROR: Set GC_EDEN_AUTH_TOKENS and GC_PERSIST_ROOT in .env")
    print("  Extract these from browser DevTools → Application → Local Storage → https://web.gc.com")
    sys.exit(1)

COOKIES = [
    {"domain": "gc.com", "expires": 1807359794, "name": "afUserId", "path": "/", "sameSite": "Lax", "secure": False, "value": os.getenv("GC_AF_USER_ID", "")},
    {"domain": "gc.com", "expires": 1775388038, "name": "gc_logged_in", "path": "/", "sameSite": "Lax", "secure": False, "value": "1"},
]

storage_state = {
    "cookies": COOKIES,
    "origins": [
        {
            "origin": "https://web.gc.com",
            "localStorage": [
                {"name": "eden-auth-tokens", "value": EDEN_AUTH_TOKENS},
                {"name": "persist:root", "value": PERSIST_ROOT},
            ],
        }
    ],
}

output_path = Path(os.getenv("GC_AUTH_OUTPUT", Path(__file__).parent.parent / "data" / "auth.json"))
output_path.parent.mkdir(parents=True, exist_ok=True)

with open(output_path, "w") as f:
    json.dump(storage_state, f, indent=2)

print(f"Successfully created {output_path}")
