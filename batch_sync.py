"""
batch_sync.py - One-shot batch sync with production hardening.

Hardening included:
- tenacity exponential backoff for external calls
- explicit VideoUnavailable / PrivateVideo / RateLimitExceeded handling
- bounded concurrency via semaphore around add/download style operations
- structured JSON logging with correlation IDs and rotation
- atomic state-file updates for run and per-notebook progress
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import structlog
from dotenv import load_dotenv
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

ROOT = Path(__file__).parent
NOTEBOOKS_JSON = ROOT / "notebooks.json"
LOGS_DIR = ROOT / "logs"
STATE_PATH = LOGS_DIR / "batch_sync_state.json"
PID_FILE = ROOT / ".sync_pid"

load_dotenv(ROOT / ".env", override=False)

sys.path.insert(0, str(ROOT))
from tools.db_sync import ensure_tables, log_source, log_sync_run
from tools.deduplicator import normalize
from tools.fetch_youtube_channel import fetch_channel
from tools.fetch_youtube_topic import search_topic
from tools.mcp_client import MCPClient, MCP_EXE
from tools.notify import notify_circuit_open, notify_error, notify_sync_complete


class SyncError(Exception):
    """Base sync exception."""


class DuplicateSource(SyncError):
    """Source already exists in NotebookLM."""


class VideoUnavailable(SyncError):
    """Video is unavailable/deleted/removed."""


class PrivateVideo(SyncError):
    """Video is private and cannot be fetched."""


class RateLimitExceeded(SyncError):
    """Upstream rate limit or quota exceeded."""


class RetryableExternalError(SyncError):
    """Transient external error eligible for retry/backoff."""


YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip() or None
DELAY_BETWEEN_ADDS = float(os.environ.get("LIBRARIAN_DELAY_BETWEEN_ADDS", "2.0"))
DELAY_BETWEEN_CHANNELS = float(os.environ.get("LIBRARIAN_DELAY_BETWEEN_CHANNELS", "1.0"))
CIRCUIT_BREAKER_THRESHOLD = int(os.environ.get("LIBRARIAN_CIRCUIT_BREAKER_THRESHOLD", "5"))
MAX_CONCURRENT_DOWNLOADS = max(1, int(os.environ.get("LIBRARIAN_MAX_CONCURRENT_DOWNLOADS", "1")))
DOWNLOAD_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_DOWNLOADS)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _configure_logging(correlation_id: str) -> structlog.stdlib.BoundLogger:
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
        LOGS_DIR / "batch_sync.log",
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

    return structlog.get_logger("batch_sync").bind(module="batch_sync", correlation_id=correlation_id)


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
            pass
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


def _load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class SyncStateStore:
    def __init__(self, state_path: Path, correlation_id: str, dry_run: bool, logger: structlog.stdlib.BoundLogger):
        self._path = state_path
        self._logger = logger
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "correlation_id": correlation_id,
            "status": "running",
            "stage": "00_initializing",
            "dry_run": dry_run,
            "started_at": _timestamp(),
            "updated_at": _timestamp(),
            "last_error": None,
            "summary": {
                "total_notebooks": 0,
                "added": 0,
                "failed": 0,
                "skipped": 0,
            },
            "notebooks": {},
        }
        self._persist_locked()

    def _persist_locked(self) -> None:
        self._state["updated_at"] = _timestamp()
        _atomic_write_json(self._path, self._state)

    def update_run(self, **fields: Any) -> None:
        with self._lock:
            self._state.update(fields)
            self._persist_locked()

    def upsert_notebook(self, notebook_id: str, **fields: Any) -> None:
        with self._lock:
            entry = self._state["notebooks"].setdefault(notebook_id, {})
            entry.update(fields)
            entry["updated_at"] = _timestamp()
            self._persist_locked()

    def set_summary(self, *, added: int, failed: int, skipped: int, total_notebooks: int) -> None:
        with self._lock:
            self._state["summary"] = {
                "total_notebooks": total_notebooks,
                "added": added,
                "failed": failed,
                "skipped": skipped,
            }
            self._persist_locked()


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run The Librarian batch sync")
    parser.add_argument("--dry-run", action="store_true", help="Simulate sync without writing")
    parser.add_argument("--notebook", type=str, default=None, help="Filter notebook title contains this value")
    parser.add_argument("--limit", type=int, default=None, help="Limit new sources per notebook")
    return parser.parse_args(argv)


def load_notebooks() -> dict[str, Any]:
    return _load_json(NOTEBOOKS_JSON)


def save_notebooks(payload: dict[str, Any]) -> None:
    _atomic_write_json(NOTEBOOKS_JSON, payload)


def get_existing_urls(notebook: dict[str, Any]) -> set[str]:
    return {normalize(src["url"]) for src in notebook.get("sources", []) if src.get("url")}


def _error_text(value: Any) -> str:
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _is_duplicate_error(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in ("already", "duplicate", "exists", "already_existed"))


def _classify_error(text: str) -> SyncError | None:
    lowered = text.lower()

    if any(token in lowered for token in ("video unavailable", "videounavailable", "not available", "removed")):
        return VideoUnavailable(text)
    if any(token in lowered for token in ("private video", "videoprivate", "privatevideo", "is private")):
        return PrivateVideo(text)
    if any(
        token in lowered
        for token in ("rate limit", "ratelimit", "quota", "quotaexceeded", "too many requests", "http 429")
    ):
        return RateLimitExceeded(text)
    if any(token in lowered for token in ("timeout", "temporarily", "connection reset", "network", "503", "502", "504")):
        return RetryableExternalError(text)
    return None


def _normalize_external_exception(exc: Exception) -> Exception:
    name = exc.__class__.__name__.lower()
    text = f"{name}: {exc}"

    if "videounavailable" in name:
        return VideoUnavailable(text)
    if "private" in name:
        return PrivateVideo(text)
    if "ratelimit" in name or "quota" in name:
        return RateLimitExceeded(text)

    classified = _classify_error(text)
    if classified:
        return classified
    return RetryableExternalError(text)


_RETRYABLE_FETCH_EXCEPTIONS = (RetryableExternalError, RateLimitExceeded, TimeoutError, OSError)
_RETRYABLE_ADD_EXCEPTIONS = (RetryableExternalError, RateLimitExceeded, TimeoutError, OSError)


@retry(
    reraise=True,
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    retry=retry_if_exception_type(_RETRYABLE_FETCH_EXCEPTIONS),
    before_sleep=before_sleep_log(logging.getLogger("batch_sync.retry"), logging.WARNING),
)
def fetch_channel_with_retry(
    channel_id_or_handle: str,
    *,
    deep_sync: bool,
    max_videos: int,
    api_key: str | None,
) -> list[dict[str, Any]]:
    try:
        return fetch_channel(
            channel_id_or_handle,
            deep_sync=deep_sync,
            max_videos=max_videos,
            api_key=api_key,
        )
    except Exception as exc:
        raise _normalize_external_exception(exc) from exc


@retry(
    reraise=True,
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    retry=retry_if_exception_type(_RETRYABLE_FETCH_EXCEPTIONS),
    before_sleep=before_sleep_log(logging.getLogger("batch_sync.retry"), logging.WARNING),
)
def search_topic_with_retry(
    keywords: list[str],
    *,
    published_after_days: int,
    max_results: int,
) -> list[dict[str, Any]]:
    try:
        return search_topic(
            keywords,
            published_after_days=published_after_days,
            max_results=max_results,
        )
    except Exception as exc:
        raise _normalize_external_exception(exc) from exc


def _is_success_result(result: dict[str, Any]) -> bool:
    status = str(result.get("status", "")).lower()
    return status in {"success", "added", "ok"} or "source_id" in result or "id" in result


@retry(
    reraise=True,
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    retry=retry_if_exception_type(_RETRYABLE_ADD_EXCEPTIONS),
    before_sleep=before_sleep_log(logging.getLogger("batch_sync.retry"), logging.WARNING),
)
def add_url_with_retry(mcp: MCPClient, notebook_id: str, url: str) -> dict[str, Any]:
    with DOWNLOAD_SEMAPHORE:
        try:
            result = mcp.add_url(notebook_id, url)
        except Exception as exc:
            raise _normalize_external_exception(exc) from exc

    if _is_success_result(result):
        return result

    text = _error_text(result)
    if _is_duplicate_error(text):
        raise DuplicateSource(text)

    classified = _classify_error(text)
    if classified:
        raise classified

    raise RetryableExternalError(text)


def _process_sources(
    *,
    notebook: dict[str, Any],
    sources: list[dict[str, Any]],
    mcp: MCPClient | None,
    dry_run: bool,
    logger: structlog.stdlib.BoundLogger,
    state: SyncStateStore,
) -> dict[str, Any]:
    nb_id = notebook["id"]
    title = notebook["title"]

    if not sources:
        logger.info("notebook_no_new_sources", notebook_id=nb_id, title=title)
        state.upsert_notebook(nb_id, stage="03_completed", status="completed", processed=0)
        return {"added": 0, "failed": 0, "skipped": 0, "added_sources": []}

    added = 0
    failed = 0
    skipped = 0
    added_sources: list[dict[str, Any]] = []
    consecutive_failures = 0

    for index, source in enumerate(sources, start=1):
        url = source["url"]
        source_title = source.get("title", "")
        source_type = source.get("type", "web")

        if index > 1 and DELAY_BETWEEN_ADDS > 0:
            time.sleep(DELAY_BETWEEN_ADDS)

        if consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
            logger.error(
                "circuit_breaker_open",
                notebook_id=nb_id,
                title=title,
                consecutive_failures=consecutive_failures,
            )
            notify_circuit_open(title, consecutive_failures)
            break

        state.upsert_notebook(
            nb_id,
            stage="02_downloading",
            status="running",
            processed=index - 1,
            queued=len(sources),
            current_url=url,
            added=added,
            failed=failed,
            skipped=skipped,
        )

        if dry_run:
            added += 1
            added_sources.append(
                {
                    "url": url,
                    "title": source_title,
                    "type": source_type,
                    "added_at": _timestamp(),
                    "note": "dry_run",
                }
            )
            logger.info(
                "dry_run_source",
                notebook_id=nb_id,
                index=index,
                total=len(sources),
                url=url,
            )
            continue

        try:
            result = add_url_with_retry(mcp, nb_id, url)
            source_id = result.get("source_id") or result.get("id")
            added += 1
            consecutive_failures = 0
            added_sources.append(
                {
                    "url": url,
                    "title": source_title,
                    "type": source_type,
                    "added_at": _timestamp(),
                    "source_id": source_id,
                }
            )
            log_source(nb_id, url, source_title, source_type, "success", source_id)
            logger.info(
                "source_added",
                notebook_id=nb_id,
                index=index,
                total=len(sources),
                url=url,
                source_id=source_id,
            )

        except DuplicateSource as exc:
            added += 1
            consecutive_failures = 0
            added_sources.append(
                {
                    "url": url,
                    "title": source_title,
                    "type": source_type,
                    "added_at": _timestamp(),
                    "note": "already_existed",
                }
            )
            log_source(nb_id, url, source_title, source_type, "success", None, error=str(exc)[:200])
            logger.info(
                "source_already_exists",
                notebook_id=nb_id,
                index=index,
                total=len(sources),
                url=url,
            )

        except VideoUnavailable as exc:
            skipped += 1
            consecutive_failures = 0
            log_source(nb_id, url, source_title, source_type, "skipped", None, error=str(exc)[:200])
            logger.warning(
                "video_unavailable",
                notebook_id=nb_id,
                index=index,
                total=len(sources),
                url=url,
            )

        except PrivateVideo as exc:
            skipped += 1
            consecutive_failures = 0
            log_source(nb_id, url, source_title, source_type, "skipped", None, error=str(exc)[:200])
            logger.warning(
                "private_video",
                notebook_id=nb_id,
                index=index,
                total=len(sources),
                url=url,
            )

        except RateLimitExceeded as exc:
            failed += 1
            consecutive_failures += 1
            log_source(nb_id, url, source_title, source_type, "failed", None, error=str(exc)[:200])
            logger.error(
                "rate_limit_exceeded",
                notebook_id=nb_id,
                index=index,
                total=len(sources),
                url=url,
            )
            state.upsert_notebook(
                nb_id,
                stage="99_failed",
                status="failed",
                last_error="RateLimitExceeded",
                processed=index,
                added=added,
                failed=failed,
                skipped=skipped,
            )
            break

        except Exception as exc:  # noqa: BLE001
            failed += 1
            consecutive_failures += 1
            err_text = str(exc)
            log_source(nb_id, url, source_title, source_type, "failed", None, error=err_text[:200])
            logger.error(
                "source_add_failed",
                notebook_id=nb_id,
                index=index,
                total=len(sources),
                url=url,
                error=err_text[:200],
            )

        state.upsert_notebook(
            nb_id,
            stage="02_downloading",
            status="running",
            processed=index,
            queued=len(sources),
            added=added,
            failed=failed,
            skipped=skipped,
        )

    return {
        "added": added,
        "failed": failed,
        "skipped": skipped,
        "added_sources": added_sources,
    }


def sync_channel_notebook(
    notebook: dict[str, Any],
    mcp: MCPClient | None,
    dry_run: bool,
    limit: int | None,
    logger: structlog.stdlib.BoundLogger,
    state: SyncStateStore,
) -> dict[str, int]:
    nb_id = notebook["id"]
    title = notebook["title"]
    notebook_start = time.monotonic()
    config = notebook.get("config", {})
    channel_ids = config.get("youtube_channel_ids", [])
    deep_sync = bool(config.get("deep_sync", False))
    max_sources = limit or config.get("max_sources", 50)

    state.upsert_notebook(
        nb_id,
        title=title,
        type="youtube_channel",
        stage="00_initializing",
        status="running",
        started_at=_timestamp(),
        channels=channel_ids,
    )

    logger.info(
        "channel_notebook_start",
        notebook_id=nb_id,
        title=title,
        channels=channel_ids,
        deep_sync=deep_sync,
        max_sources=max_sources,
    )

    all_videos: list[dict[str, Any]] = []
    for index, channel in enumerate(channel_ids):
        if index > 0 and DELAY_BETWEEN_CHANNELS > 0:
            time.sleep(DELAY_BETWEEN_CHANNELS)

        try:
            videos = fetch_channel_with_retry(
                channel,
                deep_sync=deep_sync,
                max_videos=max_sources,
                api_key=YOUTUBE_API_KEY,
            )
        except RateLimitExceeded as exc:
            logger.error("youtube_rate_limited", notebook_id=nb_id, channel=channel, error=str(exc)[:200])
            state.upsert_notebook(nb_id, stage="99_failed", status="failed", last_error="RateLimitExceeded")
            return {"added": 0, "failed": 1, "skipped": 0}
        except Exception as exc:  # noqa: BLE001
            logger.error("channel_fetch_failed", notebook_id=nb_id, channel=channel, error=str(exc)[:200])
            videos = []

        all_videos.extend(videos)
        logger.info(
            "channel_fetch_complete",
            notebook_id=nb_id,
            channel=channel,
            fetched=len(videos),
        )

    deduped_videos: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in all_videos:
        normalized = normalize(item["url"])
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped_videos.append(item)

    existing = get_existing_urls(notebook)
    new_videos = [video for video in deduped_videos if normalize(video["url"]) not in existing]

    if limit:
        new_videos = new_videos[:limit]

    state.upsert_notebook(
        nb_id,
        stage="01_metadata_fetched",
        status="running",
        fetched_count=len(deduped_videos),
        new_count=len(new_videos),
    )

    result = _process_sources(
        notebook=notebook,
        sources=new_videos,
        mcp=mcp,
        dry_run=dry_run,
        logger=logger,
        state=state,
    )

    notebook.setdefault("sources", []).extend(result["added_sources"])
    notebook["last_synced"] = _timestamp()

    duration_ms = int((time.monotonic() - notebook_start) * 1000)
    log_sync_run(nb_id, title, result["added"], result["failed"], duration_ms, dry_run)

    status = "completed" if result["failed"] == 0 else "partial"
    state.upsert_notebook(
        nb_id,
        stage="03_completed",
        status=status,
        completed_at=_timestamp(),
        added=result["added"],
        failed=result["failed"],
        skipped=result["skipped"],
    )

    logger.info(
        "channel_notebook_complete",
        notebook_id=nb_id,
        title=title,
        added=result["added"],
        failed=result["failed"],
        skipped=result["skipped"],
    )
    return {
        "added": result["added"],
        "failed": result["failed"],
        "skipped": result["skipped"],
    }


def sync_topic_notebook(
    notebook: dict[str, Any],
    mcp: MCPClient | None,
    dry_run: bool,
    limit: int | None,
    logger: structlog.stdlib.BoundLogger,
    state: SyncStateStore,
) -> dict[str, int]:
    nb_id = notebook["id"]
    title = notebook["title"]
    notebook_start = time.monotonic()
    config = notebook.get("config", {})
    keywords = config.get("youtube_topic_keywords", [])
    web_urls = config.get("web_urls", [])
    max_sources = limit or config.get("max_sources", 50)

    state.upsert_notebook(
        nb_id,
        title=title,
        type="youtube_topic",
        stage="00_initializing",
        status="running",
        started_at=_timestamp(),
    )

    logger.info(
        "topic_notebook_start",
        notebook_id=nb_id,
        title=title,
        keywords_count=len(keywords),
        web_urls_count=len(web_urls),
        max_sources=max_sources,
    )

    all_sources: list[dict[str, Any]] = []

    if keywords and YOUTUBE_API_KEY:
        try:
            videos = search_topic_with_retry(
                keywords,
                published_after_days=365,
                max_results=min(50, max_sources),
            )
        except RateLimitExceeded as exc:
            logger.error("youtube_rate_limited", notebook_id=nb_id, error=str(exc)[:200])
            state.upsert_notebook(nb_id, stage="99_failed", status="failed", last_error="RateLimitExceeded")
            return {"added": 0, "failed": 1, "skipped": 0}
        except Exception as exc:  # noqa: BLE001
            logger.error("topic_search_failed", notebook_id=nb_id, error=str(exc)[:200])
            videos = []

        deduped = []
        seen = set()
        for item in videos:
            normalized = normalize(item["url"])
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(item)
        all_sources.extend(deduped)
        logger.info("topic_search_complete", notebook_id=nb_id, fetched=len(deduped))
    elif keywords:
        logger.warning("youtube_api_key_missing_topic_notebook", notebook_id=nb_id)

    for url in web_urls:
        all_sources.append({"url": url, "title": url, "type": "web"})

    existing = get_existing_urls(notebook)
    new_sources = [src for src in all_sources if normalize(src["url"]) not in existing]

    if limit:
        new_sources = new_sources[:limit]

    state.upsert_notebook(
        nb_id,
        stage="01_metadata_fetched",
        status="running",
        fetched_count=len(all_sources),
        new_count=len(new_sources),
    )

    result = _process_sources(
        notebook=notebook,
        sources=new_sources,
        mcp=mcp,
        dry_run=dry_run,
        logger=logger,
        state=state,
    )

    notebook.setdefault("sources", []).extend(result["added_sources"])
    notebook["last_synced"] = _timestamp()

    duration_ms = int((time.monotonic() - notebook_start) * 1000)
    log_sync_run(nb_id, title, result["added"], result["failed"], duration_ms, dry_run)

    status = "completed" if result["failed"] == 0 else "partial"
    state.upsert_notebook(
        nb_id,
        stage="03_completed",
        status=status,
        completed_at=_timestamp(),
        added=result["added"],
        failed=result["failed"],
        skipped=result["skipped"],
    )

    logger.info(
        "topic_notebook_complete",
        notebook_id=nb_id,
        title=title,
        added=result["added"],
        failed=result["failed"],
        skipped=result["skipped"],
    )
    return {
        "added": result["added"],
        "failed": result["failed"],
        "skipped": result["skipped"],
    }


def _resolve_mcp_executable() -> bool:
    if Path(MCP_EXE).is_absolute():
        return Path(MCP_EXE).exists()
    return shutil.which(MCP_EXE) is not None


def _cleanup_pid(logger: structlog.stdlib.BoundLogger) -> None:
    if not PID_FILE.exists():
        return

    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        PID_FILE.unlink(missing_ok=True)
        return

    if pid == os.getpid():
        PID_FILE.unlink(missing_ok=True)
        logger.info("pid_file_removed", pid=pid)


def main() -> None:
    args = _parse_args(sys.argv[1:])
    correlation_id = str(uuid.uuid4())
    logger = _configure_logging(correlation_id)

    state = SyncStateStore(STATE_PATH, correlation_id=correlation_id, dry_run=args.dry_run, logger=logger)

    run_start = time.monotonic()
    total_added = 0
    total_failed = 0
    total_skipped = 0

    logger.info(
        "batch_sync_start",
        dry_run=args.dry_run,
        notebook_filter=args.notebook,
        limit=args.limit,
        max_concurrent_downloads=MAX_CONCURRENT_DOWNLOADS,
    )

    ensure_tables()

    data = load_notebooks()
    notebooks = data.get("notebooks", [])

    notebook_filter = args.notebook.lower() if args.notebook else None
    targets = [
        nb
        for nb in notebooks
        if nb.get("status") == "active"
        and nb.get("type") in ("youtube_channel", "youtube_topic")
        and nb.get("id")
        and (not notebook_filter or notebook_filter in nb.get("title", "").lower())
    ]

    state.set_summary(added=0, failed=0, skipped=0, total_notebooks=len(targets))

    if not targets:
        logger.warning("no_matching_notebooks")
        state.update_run(status="completed", stage="03_completed")
        _cleanup_pid(logger)
        return

    if not YOUTUBE_API_KEY:
        logger.warning("youtube_api_key_missing", detail="channel deep sync may degrade; topic search disabled")

    mcp: MCPClient | None = None
    if not args.dry_run:
        if not _resolve_mcp_executable():
            msg = f"MCP executable not found in PATH or at configured location: {MCP_EXE}"
            logger.error("mcp_executable_missing", mcp_exe=MCP_EXE)
            notify_error("batch_sync startup", msg)
            state.update_run(status="failed", stage="99_failed", last_error=msg)
            _cleanup_pid(logger)
            sys.exit(1)

        mcp = MCPClient(MCP_EXE)
        mcp.connect()

    try:
        for notebook in targets:
            nb_type = notebook.get("type")
            state.update_run(stage="01_metadata_fetched")

            if nb_type == "youtube_channel":
                result = sync_channel_notebook(
                    notebook,
                    mcp,
                    args.dry_run,
                    args.limit,
                    logger,
                    state,
                )
            elif nb_type == "youtube_topic":
                result = sync_topic_notebook(
                    notebook,
                    mcp,
                    args.dry_run,
                    args.limit,
                    logger,
                    state,
                )
            else:
                continue

            total_added += result["added"]
            total_failed += result["failed"]
            total_skipped += result.get("skipped", 0)

            state.set_summary(
                added=total_added,
                failed=total_failed,
                skipped=total_skipped,
                total_notebooks=len(targets),
            )

    except Exception as exc:  # noqa: BLE001
        err_text = str(exc)[:300]
        logger.exception("batch_sync_failed", error=err_text)
        notify_error("batch_sync run", err_text)
        state.update_run(status="failed", stage="99_failed", last_error=err_text)
        raise
    finally:
        if mcp:
            mcp.close()

    if not args.dry_run:
        save_notebooks(data)

    duration_secs = time.monotonic() - run_start

    logger.info(
        "batch_sync_complete",
        total_added=total_added,
        total_failed=total_failed,
        total_skipped=total_skipped,
        duration_secs=round(duration_secs, 2),
        dry_run=args.dry_run,
    )

    state.update_run(status="completed", stage="03_completed")
    state.set_summary(
        added=total_added,
        failed=total_failed,
        skipped=total_skipped,
        total_notebooks=len(targets),
    )

    notify_sync_complete(total_added, total_failed, len(targets), duration_secs, args.dry_run)
    _cleanup_pid(logger)


if __name__ == "__main__":
    main()
