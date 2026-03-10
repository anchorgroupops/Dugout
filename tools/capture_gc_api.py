import sys
from mitmproxy import http
from mitmproxy import ctx
from pathlib import Path

SAVE_PATH = Path(r"h:\Repos\Personal\Softball\data\sharks\app_plays_api.json")

class GCCaptureAddon:
    def response(self, flow: http.HTTPFlow):
        # GameChanger events API
        if "api.team-manager.gc.com/game-streams" in flow.request.pretty_url and "/events" in flow.request.pretty_url:
            ctx.log.info(f"[GC Capture] Found target API request: {flow.request.pretty_url}")
            
            # Save the JSON body
            try:
                body = flow.response.get_text()
                SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
                with open(SAVE_PATH, "w", encoding="utf-8") as f:
                    f.write(body)
                ctx.log.info(f"[GC Capture] SUCCESSFULLY SAVED API JSON to {SAVE_PATH}!")
                
                # Shutdown mitmproxy safely since we got what we came for
                ctx.master.shutdown()
            except Exception as e:
                ctx.log.error(f"[GC Capture] Error saving response: {e}")

addons = [
    GCCaptureAddon()
]
