"""
api.py - Flask REST API for The Librarian.

Production hardening included:
- dotenv-based secret loading
- constant-time API key auth decorator
- security headers (CSP, X-Content-Type-Options, HSTS)
- structured JSON logging with correlation IDs and rotation
- operational health checks (disk, YouTube API, last batch sync state)
"""

from __future__ import annotations

import functools
import hmac
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import requests
import structlog
from dotenv import load_dotenv
from flask import Flask, Response, g, jsonify, request, send_from_directory


ROOT = Path(__file__).parent
LOGS_DIR = ROOT / "logs"
REGISTRY_PATH = ROOT / "notebooks.json"
SUGGESTIONS_PATH = ROOT / "suggestions.json"
PID_FILE = ROOT / ".sync_pid"
BATCH_SYNC_STATE_PATH = LOGS_DIR / "batch_sync_state.json"


def _to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


load_dotenv(ROOT / ".env", override=False)


def _configure_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    max_bytes = int(os.environ.get("LOG_MAX_BYTES", "5242880"))
    backup_count = int(os.environ.get("LOG_BACKUP_COUNT", "5"))

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()

    formatter = logging.Formatter("%(message)s")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        LOGS_DIR / "api.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root_logger.addHandler(stream_handler)
    root_logger.addHandler(file_handler)

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


_configure_logging()

app = Flask(__name__, static_folder=None)

app.config["LIBRARIAN_API_KEY"] = os.environ.get("LIBRARIAN_API_KEY", "").strip()
app.config["ALLOWED_ORIGIN"] = os.environ.get("LIBRARIAN_ALLOWED_ORIGIN", "").strip()
app.config["ARCHIVE_PATH"] = Path(os.environ.get("LIBRARIAN_ARCHIVE_PATH", str(ROOT))).expanduser()
app.config["ARCHIVE_MIN_FREE_GB"] = float(os.environ.get("LIBRARIAN_MIN_FREE_GB", "5"))
app.config["HEALTH_TIMEOUT_SECS"] = float(os.environ.get("HEALTH_TIMEOUT_SECS", "5"))
app.config["ENABLE_HSTS"] = _to_bool(os.environ.get("LIBRARIAN_ENABLE_HSTS"), default=True)
app.config["HSTS_VALUE"] = os.environ.get(
    "LIBRARIAN_HSTS_VALUE", "max-age=63072000; includeSubDomains"
)
app.config["CSP"] = os.environ.get(
    "LIBRARIAN_CSP",
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'",
)


def _logger() -> structlog.stdlib.BoundLogger:
    correlation_id = getattr(g, "correlation_id", "n/a")
    return structlog.get_logger("api").bind(module="api", correlation_id=correlation_id)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            json.dump(payload, tmp_file, indent=2, ensure_ascii=False)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_name, path)
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            # Directory fsync may not be supported on all filesystems.
            pass
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


def _read_json(path: Path, fallback: dict[str, Any] | list[Any] | None = None) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return fallback
    except json.JSONDecodeError as exc:
        _logger().error("json_decode_failed", path=str(path), error=str(exc))
        return fallback


@app.before_request
def _attach_request_context() -> None:
    incoming = request.headers.get("X-Correlation-ID", "").strip()
    g.correlation_id = incoming or str(uuid.uuid4())
    g.request_started = time.monotonic()


@app.after_request
def _apply_response_hardening(response: Response) -> Response:
    response.headers["X-Correlation-ID"] = getattr(g, "correlation_id", "")
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = app.config["CSP"]

    if app.config["ENABLE_HSTS"]:
        response.headers["Strict-Transport-Security"] = app.config["HSTS_VALUE"]

    allowed_origin = app.config["ALLOWED_ORIGIN"]
    if allowed_origin:
        response.headers["Access-Control-Allow-Origin"] = allowed_origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Headers"] = (
            "Content-Type, Authorization, X-API-Key, X-Correlation-ID"
        )
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"

    duration_ms = int((time.monotonic() - getattr(g, "request_started", time.monotonic())) * 1000)
    _logger().info(
        "request_complete",
        method=request.method,
        path=request.path,
        status_code=response.status_code,
        duration_ms=duration_ms,
    )
    return response


@app.errorhandler(Exception)
def _handle_unexpected_error(exc: Exception):
    from werkzeug.exceptions import HTTPException

    if isinstance(exc, HTTPException):
        return jsonify({"error": exc.description}), exc.code
    _logger().exception("unhandled_exception", error=str(exc))
    return jsonify({"error": "Internal server error"}), 500


@app.route("/favicon.ico", methods=["GET"])
def favicon():
    return "", 204


@app.route("/<path:_path>", methods=["OPTIONS"])
@app.route("/", methods=["OPTIONS"])
def options_handler(_path: str = ""):
    return "", 204


def _extract_api_token() -> str:
    auth = request.headers.get("Authorization", "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("X-API-Key", "").strip()


def require_api_key(handler):
    @functools.wraps(handler)
    def wrapper(*args, **kwargs):
        if request.method == "OPTIONS":
            return "", 204

        expected = app.config["LIBRARIAN_API_KEY"]
        if not expected:
            _logger().error("api_key_not_configured")
            return jsonify({"error": "Server authentication is not configured"}), 503

        provided = _extract_api_token()
        if not provided:
            _logger().warning("auth_missing")
            return jsonify({"error": "Unauthorized"}), 401

        is_valid = hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))
        if not is_valid:
            _logger().warning("auth_invalid")
            return jsonify({"error": "Unauthorized"}), 401

        return handler(*args, **kwargs)

    return wrapper


def _is_sync_running() -> tuple[bool, int | None]:
    if not PID_FILE.exists():
        return False, None
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        os.kill(pid, 0)
        return True, pid
    except (OSError, ValueError):
        PID_FILE.unlink(missing_ok=True)
        return False, None


def _start_sync(args: list[str]) -> subprocess.Popen | None:
    running, _ = _is_sync_running()
    if running:
        return None

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(args, cwd=str(ROOT), env=env)
    PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    _logger().info("sync_started", pid=proc.pid, cmd=args)
    return proc


def _disk_health() -> dict[str, Any]:
    archive_path = Path(app.config["ARCHIVE_PATH"])
    if not archive_path.exists():
        return {
            "status": "error",
            "path": str(archive_path),
            "error": "Archive path does not exist",
        }

    usage = shutil.disk_usage(archive_path)
    free_gb = round(usage.free / (1024**3), 2)
    total_gb = round(usage.total / (1024**3), 2)
    min_free = app.config["ARCHIVE_MIN_FREE_GB"]
    is_ok = free_gb >= min_free
    return {
        "status": "ok" if is_ok else "low_space",
        "path": str(archive_path),
        "free_gb": free_gb,
        "total_gb": total_gb,
        "min_required_free_gb": min_free,
    }


def _youtube_connectivity() -> dict[str, Any]:
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        return {"status": "degraded", "detail": "YOUTUBE_API_KEY is not configured"}

    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {
        "part": "id",
        "id": "dQw4w9WgXcQ",
        "maxResults": 1,
        "key": api_key,
    }

    try:
        response = requests.get(url, params=params, timeout=app.config["HEALTH_TIMEOUT_SECS"])
        if response.status_code == 200:
            return {"status": "ok", "http_status": 200}
        if response.status_code in (403, 429):
            return {
                "status": "rate_limited",
                "http_status": response.status_code,
                "detail": "YouTube API quota/rate limit reached",
            }
        return {
            "status": "error",
            "http_status": response.status_code,
            "detail": "YouTube API returned non-success status",
        }
    except requests.RequestException as exc:
        return {"status": "error", "detail": str(exc)}


def _last_batch_sync_status() -> dict[str, Any]:
    state = _read_json(BATCH_SYNC_STATE_PATH, fallback={})
    if state:
        return {
            "status": state.get("status", "unknown"),
            "stage": state.get("stage", "unknown"),
            "updated_at": state.get("updated_at"),
            "correlation_id": state.get("correlation_id"),
            "summary": state.get("summary", {}),
            "last_error": state.get("last_error"),
        }

    if not LOGS_DIR.exists():
        return {"status": "unknown", "detail": "No batch sync state available"}

    logs = sorted(LOGS_DIR.glob("run_*.json"), reverse=True)
    if not logs:
        return {"status": "unknown", "detail": "No run logs available"}

    last_log = _read_json(logs[0], fallback={})
    return {
        "status": "unknown",
        "detail": "Derived from run log",
        "updated_at": last_log.get("run_at"),
        "summary": {
            "added": last_log.get("added", 0),
            "failed": last_log.get("failed", 0),
        },
    }


@app.route("/", methods=["GET", "POST"])
def index():
    return send_from_directory(ROOT / "dashboard", "index.html")


@app.route("/health", methods=["GET"])
def health():
    payload = {
        "status": "ok",
        "ts": datetime.now(timezone.utc).isoformat(),
        "disk": _disk_health(),
        "youtube_api": _youtube_connectivity(),
        "last_batch_sync": _last_batch_sync_status(),
    }
    return jsonify(payload)


@app.route("/notebooks", methods=["GET"])
@require_api_key
def notebooks():
    data = _read_json(REGISTRY_PATH)
    if data is None:
        return jsonify({"error": "Registry not found"}), 404
    return jsonify(data)


@app.route("/notebooks/discover", methods=["GET"])
@require_api_key
def discover_notebooks():
    """List all notebooks from NotebookLM via MCP, marking which are registered."""
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        from mcp_client import MCPClient

        client = MCPClient()
        result = client.list_notebooks()
        client.close()

        all_nbs = result.get("notebooks", [])

        registry = _read_json(REGISTRY_PATH, fallback={"notebooks": []})
        registered_ids = {nb["id"] for nb in registry.get("notebooks", [])}

        notebooks = []
        for nb in all_nbs:
            nb_id = nb.get("id", "")
            notebooks.append({
                "id": nb_id,
                "title": nb.get("title", "(Untitled)"),
                "source_count": nb.get("source_count", 0),
                "ownership": nb.get("ownership", "unknown"),
                "registered": nb_id in registered_ids,
                "url": nb.get("url", ""),
            })

        return jsonify({"notebooks": notebooks, "total": len(notebooks)})
    except Exception as exc:
        _logger().exception("discover_failed", error=str(exc))
        return jsonify({"error": str(exc), "notebooks": []}), 500


@app.route("/status", methods=["GET"])
@require_api_key
def get_status():
    if not LOGS_DIR.exists():
        return jsonify({"status": "no_logs"})

    logs = sorted(LOGS_DIR.glob("run_*.json"), reverse=True)
    if not logs:
        return jsonify({"status": "no_logs"})

    data = _read_json(logs[0], fallback={})
    return jsonify(data)


@app.route("/run/status", methods=["GET"])
@require_api_key
def run_status():
    running, pid = _is_sync_running()
    return jsonify({"running": running, "pid": pid})


@app.route("/run", methods=["POST"])
@require_api_key
def trigger_run():
    running, pid = _is_sync_running()
    if running:
        return jsonify({"status": "already_running", "pid": pid})

    data = request.get_json(silent=True) or {}
    args = [sys.executable, str(ROOT / "batch_sync.py")]
    if data.get("dry_run"):
        args.append("--dry-run")
    if data.get("notebook"):
        args += ["--notebook", str(data["notebook"])]
    if data.get("limit") is not None:
        args += ["--limit", str(data["limit"])]

    proc = _start_sync(args)
    if proc is None:
        return jsonify({"status": "already_running"})
    return jsonify({"status": "triggered", "pid": proc.pid})


@app.route("/suggestions", methods=["GET"])
@require_api_key
def get_suggestions():
    data = _read_json(
        SUGGESTIONS_PATH,
        fallback={"generated_at": None, "total": 0, "pending": 0, "suggestions": []},
    )
    return jsonify(data)


@app.route("/suggestions/generate", methods=["POST"])
@require_api_key
def generate_suggestions():
    """Auto-generate suggestions for empty/stale notebooks."""
    registry = _read_json(REGISTRY_PATH, fallback={"notebooks": []})
    now = datetime.now(timezone.utc)
    new_suggestions = []

    for nb in registry.get("notebooks", []):
        nb_id = nb.get("id", "")
        title = nb.get("title", "(Untitled)")
        sources = nb.get("sources", [])
        config = nb.get("config", {})
        last_synced = nb.get("last_synced")
        interval = config.get("refresh_interval_days", 7)

        if not sources:
            new_suggestions.append({
                "id": f"auto-empty-{nb_id[:8]}",
                "notebook_id": nb_id,
                "notebook_title": title,
                "type": "add_source",
                "priority": "high",
                "reasoning": f'"{title}" has no sources. Add content to make this notebook useful.',
                "status": "pending",
                "generated_at": now.isoformat(),
            })
        elif last_synced:
            age_days = (now - datetime.fromisoformat(last_synced)).total_seconds() / 86400
            if age_days > interval:
                new_suggestions.append({
                    "id": f"auto-stale-{nb_id[:8]}",
                    "notebook_id": nb_id,
                    "notebook_title": title,
                    "type": "add_source",
                    "priority": "medium",
                    "reasoning": f'"{title}" was last synced {int(age_days)} days ago (interval: {interval}d). Run a sync to check for new content.',
                    "status": "pending",
                    "generated_at": now.isoformat(),
                })

    existing = _read_json(SUGGESTIONS_PATH, fallback={"suggestions": []})
    existing_ids = {s["id"] for s in existing.get("suggestions", [])}
    added = [s for s in new_suggestions if s["id"] not in existing_ids]
    all_sug = existing.get("suggestions", []) + added

    data = {
        "generated_at": now.isoformat(),
        "total": len(all_sug),
        "pending": sum(1 for s in all_sug if s.get("status") == "pending"),
        "suggestions": all_sug,
    }
    _atomic_write_json(SUGGESTIONS_PATH, data)
    return jsonify({"added": len(added), "total": len(all_sug)})


@app.route("/suggestions/<sug_id>", methods=["PATCH"])
@require_api_key
def update_suggestion(sug_id: str):
    body = request.get_json(silent=True) or {}
    new_status = body.get("status")
    if new_status not in ("approved", "dismissed", "pending"):
        return jsonify({"error": "status must be approved, dismissed, or pending"}), 400

    data = _read_json(SUGGESTIONS_PATH)
    if data is None:
        return jsonify({"error": "suggestions.json not found"}), 404

    matched = False
    for suggestion in data.get("suggestions", []):
        if suggestion.get("id") == sug_id:
            suggestion["status"] = new_status
            matched = True
            break

    if not matched:
        return jsonify({"error": f"Suggestion {sug_id} not found"}), 404

    data["pending"] = sum(1 for item in data.get("suggestions", []) if item.get("status") == "pending")
    _atomic_write_json(SUGGESTIONS_PATH, data)

    return jsonify({"status": "updated", "id": sug_id, "new_status": new_status})


if __name__ == "__main__":
    port = 5000
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        port = int(sys.argv[idx + 1])

    startup_logger = structlog.get_logger("api").bind(module="api", correlation_id="startup")
    startup_logger.info(
        "api_starting",
        port=port,
        auth_enabled=bool(app.config["LIBRARIAN_API_KEY"]),
        hsts_enabled=app.config["ENABLE_HSTS"],
    )
    app.run(host="0.0.0.0", port=port, debug=False)
