import json
import os
from pathlib import Path

# Essential Auth Data extracted from browser — populate from your GC session
EDEN_AUTH_TOKENS = os.getenv("GC_EDEN_AUTH_TOKENS", "")
PERSIST_ROOT = os.getenv("GC_PERSIST_ROOT", "")

if not EDEN_AUTH_TOKENS or not PERSIST_ROOT:
    raise SystemExit("ERROR: GC_EDEN_AUTH_TOKENS and GC_PERSIST_ROOT env vars are required")

COOKIES = [
    {"domain": "gc.com", "expires": 0, "name": "afUserId", "path": "/", "sameSite": "Lax", "secure": False, "value": os.getenv("GC_AF_USER_ID", "")},
    {"domain": "gc.com", "expires": 0, "name": "gc_logged_in", "path": "/", "sameSite": "Lax", "secure": False, "value": "1"},
]

# Construct Playwright storage state
storage_state = {
    "cookies": COOKIES,
    "origins": [
      {
        "origin": "https://web.gc.com",
        "localStorage": [
          { "name": "eden-auth-tokens", "value": EDEN_AUTH_TOKENS },
          { "name": "persist:root", "value": PERSIST_ROOT }
        ]
      }
    ]
}

# Ensure directory exists
output_path = Path(os.getenv("GC_AUTH_OUTPUT", str(Path(__file__).parent.parent / "data" / "auth.json")))
output_path.parent.mkdir(parents=True, exist_ok=True)

with open(output_path, "w") as f:
    json.dump(storage_state, f, indent=2)

print(f"Successfully created {output_path}")
