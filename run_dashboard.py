"""
run_dashboard.py — Launch the Librarian Dashboard.
Serves the project directory via a local HTTP server to bypass CORS issues.
"""
import http.server
import socketserver
import webbrowser
import os
import sys
from pathlib import Path

# Project root is the current directory of this script or its parent
ROOT = Path(__file__).parent.parent if "tools" in str(Path(__file__)) else Path(__file__).parent
PORT = 8000

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

def launch():
    print(f"\n{'='*60}")
    print(f"📚 The Librarian Dashboard Launcher")
    print(f"{'='*60}\n")
    
    os.chdir(ROOT)
    
    # Try to find an open port starting at 8000
    port = PORT
    while port < 8100:
        try:
            with socketserver.TCPServer(("", port), Handler) as httpd:
                url = f"http://localhost:{port}/dashboard/index.html"
                print(f"🚀 Dashboard serving at: {url}")
                print(f"👉 Opening your browser now...")
                print(f"ℹ️  Press Ctrl+C to stop the server.")
                
                webbrowser.open(url)
                httpd.serve_forever()
                break
        except OSError:
            port += 1

if __name__ == "__main__":
    try:
        launch()
    except KeyboardInterrupt:
        print("\n👋 Dashboard server stopped.")
        sys.exit(0)
