"""Local-network sync endpoint for the Android companion app.

The phone only *creates* transactions, so sync is an append-only queue
instead of a reconciliation problem: every row carries a ``uuid``, a repeat
is answered with ``duplicate`` and no conflict resolution is needed. Nothing
leaves the local network and the endpoint only exists while LetoBank runs.

Endpoints (all require the shared token):

    GET  /api/ping          liveness probe
    GET  /api/meta          accounts, categories, payees, payments, tags
    POST /api/transactions  {"transactions": [...]} or a bare JSON array
"""

from __future__ import annotations

import hmac
import json
import socket
import sqlite3
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from . import __version__
from .branding import APP_NAME
from .db import DataStore

MAX_BODY_BYTES = 1_000_000


def lan_ip() -> str:
    """Best guess at this machine's LAN address, without sending a packet."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            return probe.getsockname()[0]
    except OSError:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


class SyncServer:
    """Threaded HTTP server wrapping one database file.

    Each request opens its own short-lived :class:`DataStore` connection so
    requests never share a SQLite handle across threads. ``busy_timeout`` in
    the store makes a request wait out a UI write instead of failing.
    """

    def __init__(
        self,
        db_path: str | Path,
        token: str,
        *,
        port: int = 8787,
        host: str = "0.0.0.0",
        on_ingest: Callable[[int], None] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.token = token
        self.port = int(port)
        self.host = host
        self.on_ingest = on_ingest
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port_in_use(self) -> int:
        if self._httpd is None:
            return self.port
        return int(self._httpd.server_address[1])

    @property
    def running(self) -> bool:
        return self._httpd is not None

    @property
    def url(self) -> str:
        return f"http://{lan_ip()}:{self.port_in_use}"

    def start(self) -> int | None:
        """Start serving in a background thread; ``None`` if the port is taken."""
        if self._httpd is not None:
            return self.port_in_use

        server = self

        class Handler(BaseHTTPRequestHandler):
            server_version = f"{APP_NAME}-sync"

            def log_message(self, fmt: str, *args) -> None:  # noqa: N802
                """Keep the terminal quiet; failures are answered as JSON."""

            # ------------------------------------------------------- auth
            def _authorized(self) -> bool:
                header = self.headers.get("X-Sync-Token", "")
                if not header:
                    header = self.headers.get("Authorization", "")
                    if header.lower().startswith("bearer "):
                        header = header[7:]
                return hmac.compare_digest(header.strip(), server.token)

            def _unauthorized(self) -> None:
                self._json(401, {"error": "invalid or missing sync token"})

            # ------------------------------------------------------ helpers
            def _json(self, status: int, payload: dict) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_payload(self) -> object | None:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self._json(400, {"error": "invalid Content-Length"})
                    return None
                if length <= 0:
                    self._json(400, {"error": "empty request body"})
                    return None
                if length > MAX_BODY_BYTES:
                    self._json(413, {"error": "request body too large"})
                    return None
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._json(400, {"error": "body must be valid JSON"})
                    return None
                if not isinstance(payload, (dict, list)):
                    self._json(400, {"error": "body must be a JSON object or array"})
                    return None
                return payload

            # ------------------------------------------------------- routes
            def do_GET(self) -> None:  # noqa: N802
                if not self._authorized():
                    return self._unauthorized()
                path = self.path.split("?", 1)[0].rstrip("/") or "/"
                if path == "/api/ping":
                    return self._json(
                        200,
                        {
                            "app": APP_NAME,
                            "version": __version__,
                            "time": datetime.now().isoformat(timespec="seconds"),
                        },
                    )
                if path == "/api/meta":
                    try:
                        store = DataStore(
                            server.db_path, seed=False, prepare=False
                        )
                        try:
                            return self._json(200, store.sync_meta())
                        finally:
                            store.close()
                    except sqlite3.Error as exc:
                        return self._json(503, {"error": f"database busy: {exc}"})
                return self._json(404, {"error": "not found"})

            def do_POST(self) -> None:  # noqa: N802
                if not self._authorized():
                    return self._unauthorized()
                path = self.path.split("?", 1)[0].rstrip("/") or "/"
                if path != "/api/transactions":
                    return self._json(404, {"error": "not found"})

                payload = self._read_payload()
                if payload is None:
                    return
                if isinstance(payload, list):
                    items = payload
                    apply_rules = True
                else:
                    items = payload.get("transactions", payload.get("items"))
                    if items is None:
                        return self._json(
                            400,
                            {"error": "missing 'transactions' array"},
                        )
                    apply_rules = bool(payload.get("apply_rules", True))
                if not isinstance(items, list):
                    return self._json(400, {"error": "'transactions' must be an array"})
                if len(items) > 500:
                    return self._json(400, {"error": "at most 500 transactions per request"})

                try:
                    store = DataStore(server.db_path, seed=False, prepare=False)
                    try:
                        results = store.ingest_sync_transactions(
                            items, apply_rules=apply_rules
                        )
                    finally:
                        store.close()
                except sqlite3.OperationalError as exc:
                    return self._json(503, {"error": f"database busy: {exc}"})
                except sqlite3.Error as exc:
                    return self._json(500, {"error": f"database error: {exc}"})

                inserted = sum(1 for r in results if r["status"] == "inserted")
                duplicates = sum(1 for r in results if r["status"] == "duplicate")
                errors = sum(1 for r in results if r["status"] == "error")
                if inserted and server.on_ingest is not None:
                    try:
                        server.on_ingest(inserted)
                    except Exception:  # a UI refresh must never fail the sync
                        pass
                return self._json(
                    200,
                    {
                        "inserted": inserted,
                        "duplicate": duplicates,
                        "errors": errors,
                        "results": results,
                    },
                )

        try:
            httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        except OSError:
            return None
        httpd.daemon_threads = True
        self._httpd = httpd
        self._thread = threading.Thread(
            target=httpd.serve_forever,
            name="letobank-lansync",
            daemon=True,
        )
        self._thread.start()
        return self.port_in_use

    def stop(self) -> None:
        httpd, thread = self._httpd, self._thread
        self._httpd = None
        self._thread = None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)
