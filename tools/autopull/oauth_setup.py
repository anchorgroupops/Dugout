"""One-shot helper: run the Google OAuth consent flow for the autopull's Gmail
access and print the refresh token.

Reads GMAIL_OAUTH_CLIENT_ID / GMAIL_OAUTH_CLIENT_SECRET from .env, runs
the Installed App flow on a loopback port, and prints the refresh token.
Paste the token into .env as GMAIL_OAUTH_REFRESH_TOKEN.

Usage:
    /tmp/dugout-venv/bin/python tools/autopull/oauth_setup.py

If this host has no desktop browser, pass --no-browser; the script prints
the auth URL to open on any other device. The device must be able to
reach the Pi's loopback port (e.g. via ssh -L <port>:localhost:<port>).
"""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path


SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def _load_env():
    """Load .env from project root (no external dep)."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip("'").strip('"')
        if k and k not in os.environ:
            os.environ[k] = v


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-browser", action="store_true",
                    help="Don't try to auto-open a browser; print the URL instead.")
    ap.add_argument("--port", type=int, default=0,
                    help="Loopback port for the redirect (0 = random).")
    args = ap.parse_args()

    _load_env()
    client_id = os.environ.get("GMAIL_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GMAIL_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        print("ERROR: GMAIL_OAUTH_CLIENT_ID / GMAIL_OAUTH_CLIENT_SECRET "
              "are not set in .env", file=sys.stderr)
        return 2

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("ERROR: google-auth-oauthlib not installed. "
              "Run: /tmp/dugout-venv/bin/pip install google-auth-oauthlib",
              file=sys.stderr)
        return 3

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    # Build the auth URL ourselves so we can print it before blocking on the
    # local HTTP server. `run_local_server` eventually prints the same URL,
    # but its output is buffered which makes it invisible in piped contexts.
    import wsgiref.simple_server
    import wsgiref.util
    import socket

    # Pick a port so we can put it in the redirect URL before starting the server.
    if args.port == 0:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("localhost", 0))
        port = s.getsockname()[1]
        s.close()
    else:
        port = args.port
    redirect_uri = f"http://localhost:{port}/"
    flow.redirect_uri = redirect_uri
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )

    print("\n" + "=" * 72, flush=True)
    print("VISIT THIS URL in any browser to authorize Gmail access:", flush=True)
    print("=" * 72, flush=True)
    print(f"\n{auth_url}\n", flush=True)
    print(f"Then Google will redirect to: {redirect_uri}", flush=True)
    print(
        f"If running the browser on a different machine, open an SSH tunnel "
        f"first: ssh -L {port}:localhost:{port} <pi-host>\n",
        flush=True,
    )
    print(f"Waiting for redirect on port {port}...", flush=True)

    creds = flow.run_local_server(
        port=port,
        open_browser=not args.no_browser,
        authorization_prompt_message="",
        success_message="Authorization complete. You can close this tab.",
    )

    if not creds.refresh_token:
        print("ERROR: Google returned no refresh_token. Re-run with a fresh "
              "consent (add prompt=consent and access_type=offline).",
              file=sys.stderr)
        return 4

    print("\n" + "=" * 60)
    print("SUCCESS — refresh token generated.")
    print("=" * 60)
    print("\nAdd this to ~/dugout/.env as GMAIL_OAUTH_REFRESH_TOKEN:\n")
    print(creds.refresh_token)
    print("\nOr run this one-liner to insert it:\n")
    print(f'  sed -i "s|^GMAIL_OAUTH_REFRESH_TOKEN=.*|GMAIL_OAUTH_REFRESH_TOKEN={creds.refresh_token}|" ~/dugout/.env')
    return 0


if __name__ == "__main__":
    sys.exit(main())
