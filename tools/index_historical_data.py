"""
Index all team + opponent JSON artifacts into Pinecone via MemoryEngine.

Usage:
  python tools/index_historical_data.py
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
TEAM_DIR = DATA_DIR / os.getenv("TEAM_SLUG", "sharks")
OPPONENTS_DIR = DATA_DIR / "opponents"


def _iter_json_files() -> Iterable[Path]:
    for base in (TEAM_DIR, OPPONENTS_DIR):
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.json")):
            if path.is_file():
                yield path


def _load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        parsed = json.load(f)
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list):
        return {"items": parsed}
    return {"value": parsed}


def _doc_metadata(path: Path) -> Dict[str, Any]:
    rel = path.relative_to(DATA_DIR).as_posix()
    parts = rel.split("/")
    scope = parts[0] if parts else "unknown"
    meta: Dict[str, Any] = {
        "source_path": rel,
        "scope": scope,
        "filename": path.name,
    }
    if scope == "opponents" and len(parts) > 1:
        meta["opponent_slug"] = parts[1]
    return meta


def run(index_name: str, namespace: str, batch_size: int, dry_run: bool = False) -> int:
    docs = []
    for path in _iter_json_files():
        rel = path.relative_to(DATA_DIR).as_posix()
        doc_id = f"json::{rel.replace('/', '::')}"
        try:
            payload = _load_json(path)
            docs.append({"id": doc_id, "data": payload, "metadata": _doc_metadata(path)})
        except Exception as e:
            print(f"[INDEX] Skipping {rel}: {e}")

    if dry_run:
        print(f"[INDEX] Dry run: {len(docs)} documents discovered.")
        return len(docs)

    from memory_engine import MemoryEngine

    engine = MemoryEngine(index_name=index_name, namespace=namespace)
    total = engine.batch_upsert_documents(docs, batch_size=batch_size)
    print(f"[INDEX] Upserted {total} documents to index='{index_name}' namespace='{namespace}'.")
    return total


def main():
    parser = argparse.ArgumentParser(description="Index historical Sharks/opponent JSON data into Pinecone.")
    parser.add_argument("--index", default="dugout", help="Pinecone index name.")
    parser.add_argument("--namespace", default="softball", help="Pinecone namespace.")
    parser.add_argument("--batch-size", type=int, default=16, help="Upsert batch size.")
    parser.add_argument("--dry-run", action="store_true", help="Discover docs without writing to Pinecone.")
    args = parser.parse_args()

    run(index_name=args.index, namespace=args.namespace, batch_size=args.batch_size, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
