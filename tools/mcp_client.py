"""
mcp_client.py — Shared NotebookLM MCP client.
Layer 3 Tool | NotebookLM Librarian

Improvements over the original inline MCPClient:
  - Threaded stdout reader with configurable timeout (no infinite readline() blocks)
  - Automatic retry with exponential backoff on transient failures
  - Session recovery: detects dead process and reconnects transparently
  - Consistent call() interface used by all scripts
"""
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path


# Use LIBRARIAN_MCP_EXE from .env, or fall back to the Windows path, or just 'notebooklm-mcp'
MCP_EXE = os.environ.get("LIBRARIAN_MCP_EXE", "")
if not MCP_EXE:
    # Default fallback for Windows (as configured by joely)
    _win_path = (
        r"C:\Users\joely\AppData\Local\Packages"
        r"\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0"
        r"\LocalCache\local-packages\Python312\Scripts\notebooklm-mcp.exe"
    )
    if os.name == 'nt' and Path(_win_path).exists():
        MCP_EXE = _win_path
    else:
        # On Linux/Pi, we expect it to be in the PATH after 'pip install'
        MCP_EXE = "notebooklm-mcp"


class MCPTimeoutError(RuntimeError):
    pass


class MCPClient:
    """
    Synchronous MCP client over stdio with retry and session recovery.

    Usage:
        mcp = MCPClient()
        mcp.connect()
        result = mcp.add_url(notebook_id, url)
        mcp.close()

    Or as a context manager:
        with MCPClient() as mcp:
            result = mcp.add_url(notebook_id, url)
    """

    RECV_TIMEOUT = 45       # seconds to wait for any single response
    MAX_RETRIES = 3         # retry attempts on transient failure
    BACKOFF_BASE = 2.0      # delay = BACKOFF_BASE ** attempt seconds

    def __init__(self, exe_path: str = MCP_EXE, client_name: str = "librarian"):
        self.exe_path = exe_path
        self.client_name = client_name
        self._proc: subprocess.Popen | None = None
        self._req_id = 0
        self._connected = False
        self._read_queue: queue.Queue = queue.Queue()
        self._reader_thread: threading.Thread | None = None

    # ── Context manager ───────────────────────────────────────────────────────

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()

    # ── Public API ────────────────────────────────────────────────────────────

    def connect(self):
        """Start the MCP subprocess and complete the JSON-RPC initialize handshake."""
        if self._connected:
            return
        self._proc = subprocess.Popen(
            [self.exe_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._start_reader()
        self._send({
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": self.client_name, "version": "2.0"},
            },
            "id": self._next_id(),
        })
        resp = self._recv()
        if "error" in resp:
            raise RuntimeError(f"MCP initialize error: {resp['error']}")
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._connected = True
        print(f"[MCP] Connected ({Path(self.exe_path).name})")

    def call(self, tool: str, args: dict) -> dict:
        """
        Call an MCP tool with automatic retry and session recovery.

        Transient failures (timeout, process crash) trigger a reconnect + retry.
        Non-transient errors (MCP-level error responses) are raised immediately.
        """
        last_err: Exception | None = None
        for attempt in range(self.MAX_RETRIES):
            if attempt > 0:
                delay = self.BACKOFF_BASE ** attempt
                print(f"[MCP] Retry {attempt}/{self.MAX_RETRIES - 1} for {tool} (backoff {delay:.0f}s)...")
                time.sleep(delay)

            # Reconnect if process is dead
            if not self._connected or (self._proc and self._proc.poll() is not None):
                print("[MCP] Process not alive — reconnecting...")
                self._kill()
                self.connect()

            try:
                return self._call_once(tool, args)

            except MCPTimeoutError as e:
                # Timeout = session likely expired; kill and reconnect on next attempt
                print(f"[MCP] Timeout on {tool} (attempt {attempt + 1}): {e}")
                self._kill()
                last_err = e

            except RuntimeError as e:
                err_str = str(e).lower()
                if "closed" in err_str or "process" in err_str or "mcp error" in err_str:
                    # Process died or returned a transient error
                    self._kill()
                    last_err = e
                else:
                    raise  # Non-transient, propagate immediately

        raise RuntimeError(
            f"MCP call '{tool}' failed after {self.MAX_RETRIES} attempts. Last error: {last_err}"
        )

    # ── Convenience methods ───────────────────────────────────────────────────

    def add_url(self, notebook_id: str, url: str) -> dict:
        return self.call("notebook_add_url", {"notebook_id": notebook_id, "url": url})

    # Alias for nb_writer.py compatibility
    def notebook_add_url(self, notebook_id: str, url: str) -> dict:
        return self.add_url(notebook_id, url)

    def notebook_add_text(self, notebook_id: str, text: str, title: str = "") -> dict:
        return self.call("notebook_add_text", {"notebook_id": notebook_id, "text": text, "title": title})

    def get_notebook(self, notebook_id: str) -> dict:
        return self.call("notebook_get", {"notebook_id": notebook_id})

    def delete_source(self, source_id: str) -> dict:
        return self.call("source_delete", {"source_id": source_id, "confirm": True})

    def list_notebooks(self) -> dict:
        return self.call("notebook_list", {})

    def close(self):
        """Gracefully shut down the subprocess."""
        self._kill(graceful=True)

    # ── Private ───────────────────────────────────────────────────────────────

    def _call_once(self, tool: str, args: dict) -> dict:
        req_id = self._next_id()
        self._send({
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool, "arguments": args},
            "id": req_id,
        })
        # Drain responses until we find the one matching our request id
        for _ in range(30):
            resp = self._recv()
            if resp.get("id") == req_id:
                break
        if resp.get("id") != req_id:
            raise RuntimeError(f"MCP: mismatched response id for '{tool}'")
        if "error" in resp:
            raise RuntimeError(f"MCP error on '{tool}': {resp['error']}")
        return self._extract_result(resp)

    def _extract_result(self, resp: dict) -> dict:
        content = resp.get("result", {}).get("content", [])
        if content:
            try:
                return json.loads(content[0].get("text", "{}"))
            except (json.JSONDecodeError, IndexError):
                text = content[0].get("text", "")
                return {"raw": text, "status": "ok"}
        return resp.get("result", {})

    def _start_reader(self):
        """Spawn a daemon thread that continuously feeds stdout lines into a queue."""
        # Drain stale items from any previous session
        while not self._read_queue.empty():
            try:
                self._read_queue.get_nowait()
            except queue.Empty:
                break

        def _loop():
            try:
                while self._proc is not None:
                    line = self._proc.stdout.readline()
                    if not line:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        self._read_queue.put(json.loads(line))
                    except json.JSONDecodeError:
                        pass  # skip non-JSON debug output
            except Exception:
                pass

        self._reader_thread = threading.Thread(target=_loop, daemon=True, name="mcp-reader")
        self._reader_thread.start()

    def _recv(self) -> dict:
        try:
            return self._read_queue.get(timeout=self.RECV_TIMEOUT)
        except queue.Empty:
            raise MCPTimeoutError(
                f"No MCP response within {self.RECV_TIMEOUT}s — session may have expired"
            )

    def _send(self, obj: dict):
        if self._proc and self._proc.stdin:
            self._proc.stdin.write(json.dumps(obj) + "\n")
            self._proc.stdin.flush()

    def _kill(self, graceful: bool = False):
        if self._proc:
            try:
                if graceful:
                    try:
                        self._proc.stdin.close()
                    except Exception:
                        pass
                    try:
                        self._proc.wait(timeout=5)
                    except Exception:
                        self._proc.kill()
                else:
                    self._proc.kill()
                    try:
                        self._proc.wait(timeout=3)
                    except Exception:
                        pass
            except Exception:
                pass
        self._proc = None
        self._connected = False

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id
