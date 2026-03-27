import hashlib
import json
import os
import re
from typing import Any, Dict, Iterable, List

import google.generativeai as genai
from pinecone import Pinecone

DEFAULT_INDEX = "softball-sharks"
DEFAULT_NAMESPACE = "softball"
DEFAULT_EMBED_MODEL = "models/text-embedding-004"
MAX_TEXT_CHARS = 12000
MAX_METADATA_PREVIEW_CHARS = 500


def _safe_id(raw: str) -> str:
    val = re.sub(r"[^a-zA-Z0-9:_\-./]", "_", str(raw or "").strip())
    return val[:256] or "unknown"


def _canonical_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _content_hash(data: Any) -> str:
    return hashlib.sha1(_canonical_json(data).encode("utf-8")).hexdigest()


def _flatten_metadata(metadata: Dict[str, Any] | None) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        k = str(key)[:64]
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[k] = value
        else:
            out[k] = json.dumps(value, ensure_ascii=False)[:1000]
    return out


class MemoryEngine:
    """
    RAG memory engine backed by Gemini embeddings + Pinecone.
    """

    def __init__(
        self,
        index_name: str = DEFAULT_INDEX,
        namespace: str = DEFAULT_NAMESPACE,
        embed_model: str = DEFAULT_EMBED_MODEL,
    ):
        pinecone_key = os.getenv("PINECONE_API_KEY", "").strip()
        if not pinecone_key:
            raise ValueError("Missing PINECONE_API_KEY for MemoryEngine.")

        gemini_key = os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip()
        if not gemini_key:
            raise ValueError("Missing GEMINI_API_KEY (or GOOGLE_API_KEY) for MemoryEngine.")

        genai.configure(api_key=gemini_key)
        self.embed_model = embed_model
        self.namespace = namespace
        self.pc = Pinecone(api_key=pinecone_key)
        self.index = self.pc.Index(index_name)

    def _embed(self, text: str, task_type: str) -> List[float]:
        payload = (text or "").strip()[:MAX_TEXT_CHARS] or "empty"
        response = genai.embed_content(
            model=self.embed_model,
            content=payload,
            task_type=task_type,
        )
        if not isinstance(response, dict) or "embedding" not in response:
            raise RuntimeError("Gemini embedding response missing 'embedding'.")
        return response["embedding"]

    def _doc_text(self, data: Dict[str, Any]) -> str:
        return _canonical_json(data)

    def upsert_game_data(self, game_id: str, data: Dict[str, Any]):
        """Index one game document."""
        doc_id = f"game::{_safe_id(game_id)}"
        text = self._doc_text(data)
        vector = self._embed(text, task_type="retrieval_document")
        metadata = {
            "entity_type": "game",
            "game_id": str(game_id),
            "doc_hash": _content_hash(data),
            "preview": text[:MAX_METADATA_PREVIEW_CHARS],
        }
        self.index.upsert(
            vectors=[{"id": doc_id, "values": vector, "metadata": metadata}],
            namespace=self.namespace,
        )
        return doc_id

    def upsert_document(self, doc_id: str, data: Dict[str, Any], metadata: Dict[str, Any] | None = None) -> str:
        """Index an arbitrary JSON document."""
        safe_doc_id = _safe_id(doc_id)
        text = self._doc_text(data)
        vector = self._embed(text, task_type="retrieval_document")
        final_metadata = {
            "entity_type": "document",
            "doc_hash": _content_hash(data),
            "preview": text[:MAX_METADATA_PREVIEW_CHARS],
            **_flatten_metadata(metadata),
        }
        self.index.upsert(
            vectors=[{"id": safe_doc_id, "values": vector, "metadata": final_metadata}],
            namespace=self.namespace,
        )
        return safe_doc_id

    def batch_upsert_documents(self, docs: Iterable[Dict[str, Any]], batch_size: int = 32) -> int:
        """
        Batch upsert docs where each item has:
          {"id": str, "data": dict, "metadata": dict(optional)}
        """
        vectors = []
        total = 0
        for item in docs:
            if not isinstance(item, dict):
                continue
            raw_id = item.get("id")
            data = item.get("data")
            if not raw_id or not isinstance(data, dict):
                continue
            safe_doc_id = _safe_id(str(raw_id))
            text = self._doc_text(data)
            vector = self._embed(text, task_type="retrieval_document")
            metadata = {
                "entity_type": "document",
                "doc_hash": _content_hash(data),
                "preview": text[:MAX_METADATA_PREVIEW_CHARS],
                **_flatten_metadata(item.get("metadata")),
            }
            vectors.append({"id": safe_doc_id, "values": vector, "metadata": metadata})
            if len(vectors) >= batch_size:
                self.index.upsert(vectors=vectors, namespace=self.namespace)
                total += len(vectors)
                vectors = []

        if vectors:
            self.index.upsert(vectors=vectors, namespace=self.namespace)
            total += len(vectors)

        return total

    def search_history(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Search memory for nearest historical documents."""
        vector = self._embed(query, task_type="retrieval_query")
        res = self.index.query(
            vector=vector,
            top_k=top_k,
            include_metadata=True,
            include_values=False,
            namespace=self.namespace,
        )
        matches = []
        for m in getattr(res, "matches", []) or []:
            matches.append(
                {
                    "id": getattr(m, "id", ""),
                    "score": float(getattr(m, "score", 0.0)),
                    "metadata": dict(getattr(m, "metadata", {}) or {}),
                }
            )
        return matches

    def sync_local_files(self, data_dir: str) -> int:
        """
        Index critical team files for RAG.
        Excludes large logs or raw HTML/XML dumps.
        """
        critical_files = [
            "swot_analysis.json",
            "lineups.json",
            "team.json",
            "opponent_discovery.json",
            "schedule_manual.json",
            "next_practice.txt",
            "stats_anomalies.json",
            "api_captures.json",
        ]

        docs_to_upsert = []
        for filename in critical_files:
            path = os.path.join(data_dir, filename)
            if not os.path.exists(path):
                continue

            try:
                if filename.endswith(".json"):
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    docs_to_upsert.append({
                        "id": f"file::{filename}",
                        "data": data,
                        "metadata": {"filename": filename, "source": "local_filesystem"}
                    })
                elif filename.endswith(".txt"):
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                    docs_to_upsert.append({
                        "id": f"file::{filename}",
                        "data": {"content": content},
                        "metadata": {"filename": filename, "source": "local_filesystem"}
                    })
            except Exception as e:
                print(f"Error reading {filename}: {e}")

        if docs_to_upsert:
            return self.batch_upsert_documents(docs_to_upsert)
        return 0


if __name__ == "__main__":
    import sys
    engine = MemoryEngine()
    
    # Simple CLI: if "sync" is passed, run full directory sync
    if len(sys.argv) > 1 and sys.argv[1] == "sync":
        data_path = sys.argv[2] if len(sys.argv) > 2 else "data/sharks"
        print(f"Syncing all critical files from {data_path}...")
        count = engine.sync_local_files(data_path)
        print(f"Successfully indexed {count} documents.")
    else:
        print(f"Memory Engine initialized for namespace '{engine.namespace}'.")
        print("Usage: python memory_engine.py sync [data_dir]")
