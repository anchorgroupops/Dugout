import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from mitmproxy import http
from mitmproxy import ctx

DATA_DIR = Path(r"h:\Repos\Personal\Softball\data\sharks")
DATA_DIR.mkdir(parents=True, exist_ok=True)

EVENTS_PATH = DATA_DIR / "app_plays_api.json"
SCOREBOOK_LATEST = DATA_DIR / "scorebook_latest.pdf"
CAPTURE_INDEX = DATA_DIR / "app_captures_index.json"

EXIT_ON_CAPTURE = os.getenv("GC_CAPTURE_EXIT", "0") == "1"

ET = ZoneInfo("America/New_York")

def _now_tag():
    return datetime.now(ET).strftime("%Y%m%d_%H%M%S")

def _is_json(content_type: str) -> bool:
    return "json" in content_type or "text" in content_type

def _is_pdf(content_type: str, url: str) -> bool:
    return "pdf" in content_type or url.lower().endswith(".pdf")

def _is_events_url(url: str) -> bool:
    return "api.team-manager.gc.com/game-streams" in url and "/events" in url

def _is_scorebook_url(url: str) -> bool:
    url_l = url.lower()
    return "scorebook" in url_l or "scorecard" in url_l or url_l.endswith(".pdf")

def _load_index():
    if CAPTURE_INDEX.exists():
        try:
            with open(CAPTURE_INDEX, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def _save_index(entries: list[dict]):
    with open(CAPTURE_INDEX, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)

class GCCaptureAddon:
    def response(self, flow: http.HTTPFlow):
        url = flow.request.pretty_url
        content_type = flow.response.headers.get("content-type", "")

        captured_any = False
        entries = _load_index()

        # Capture Events JSON (play-by-play)
        if _is_events_url(url):
            ctx.log.info(f"[GC Capture] Found events API: {url}")
            try:
                body = flow.response.get_text()
                EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
                with open(EVENTS_PATH, "w", encoding="utf-8") as f:
                    f.write(body)
                entries.append({
                    "type": "events",
                    "url": url,
                    "status": flow.response.status_code,
                    "content_type": content_type,
                    "size": len(body),
                    "saved_to": str(EVENTS_PATH),
                    "captured_at": datetime.now(ET).isoformat()
                })
                ctx.log.info(f"[GC Capture] Saved events JSON -> {EVENTS_PATH}")
                captured_any = True
            except Exception as e:
                ctx.log.error(f"[GC Capture] Error saving events: {e}")

        # Capture scorebook/scorecard
        if _is_scorebook_url(url) or _is_pdf(content_type, url):
            ctx.log.info(f"[GC Capture] Found scorebook candidate: {url}")
            try:
                pdf_bytes = flow.response.content
                tag = _now_tag()
                scorebook_file = DATA_DIR / f"scorebook_{tag}.pdf"
                with open(scorebook_file, "wb") as f:
                    f.write(pdf_bytes)
                with open(SCOREBOOK_LATEST, "wb") as f:
                    f.write(pdf_bytes)
                entries.append({
                    "type": "scorebook",
                    "url": url,
                    "status": flow.response.status_code,
                    "content_type": content_type,
                    "size": len(pdf_bytes),
                    "saved_to": str(scorebook_file),
                    "saved_latest_to": str(SCOREBOOK_LATEST),
                    "captured_at": datetime.now().isoformat()
                })
                ctx.log.info(f"[GC Capture] Saved scorebook -> {scorebook_file}")
                captured_any = True
            except Exception as e:
                ctx.log.error(f"[GC Capture] Error saving scorebook: {e}")

        if captured_any:
            _save_index(entries)
            if EXIT_ON_CAPTURE:
                ctx.master.shutdown()

addons = [GCCaptureAddon()]
