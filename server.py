#!/usr/bin/env python3
"""Local desktop server for Asteroid Archive v0.7 — Final Audited Edition.

Usage:
    python server.py
    python server.py --port 8872 --no-open
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Final

from api_core import ApiResponse, cors_headers, handle_get
from database import DB_PATH, initialize, seed_if_empty
from update_engine import run_update

ROOT: Final[Path] = Path(__file__).resolve().parent
VERSION: Final[str] = "0.7.2"


def environment_default_host() -> str:
    return str(os.environ.get("HOST") or "127.0.0.1").strip() or "127.0.0.1"


def environment_default_port() -> int:
    raw = str(os.environ.get("PORT") or "8872").strip()
    try:
        port = int(raw)
    except ValueError:
        return 8872
    return port if 1 <= port <= 65535 else 8872
UPDATE_LOCK = threading.RLock()
UPDATE_CANCEL = threading.Event()
UPDATE_STATE: dict[str, Any] = {
    "running": False,
    "status": "idle",
    "percent": 0,
    "stage": "idle",
    "message": "محرك التحديث جاهز",
    "started_at": None,
    "finished_at": None,
    "logs": [],
    "result": None,
    "error": None,
}


def utc_stamp() -> str:
    import datetime as dt

    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def update_snapshot() -> dict[str, Any]:
    with UPDATE_LOCK:
        return json.loads(json.dumps(UPDATE_STATE, ensure_ascii=False, default=str))


def update_progress(item: dict[str, Any]) -> None:
    with UPDATE_LOCK:
        UPDATE_STATE["percent"] = int(item.get("percent", UPDATE_STATE.get("percent", 0)))
        UPDATE_STATE["stage"] = item.get("stage", UPDATE_STATE.get("stage"))
        UPDATE_STATE["message"] = item.get("message", UPDATE_STATE.get("message"))
        UPDATE_STATE["logs"].append(item)
        UPDATE_STATE["logs"] = UPDATE_STATE["logs"][-300:]


def update_worker(config: dict[str, Any]) -> None:
    try:
        result = run_update(config, progress=update_progress, cancel_event=UPDATE_CANCEL, trigger="ui")
        with UPDATE_LOCK:
            UPDATE_STATE["result"] = result
            UPDATE_STATE["status"] = result.get("status", "success")
            UPDATE_STATE["error"] = result.get("error")
    except Exception as exc:  # External network boundary; preserve last good database.
        with UPDATE_LOCK:
            UPDATE_STATE["status"] = "failed"
            UPDATE_STATE["error"] = str(exc)
            UPDATE_STATE["message"] = f"فشل التحديث: {exc}"
            UPDATE_STATE["percent"] = 100
    finally:
        with UPDATE_LOCK:
            UPDATE_STATE["running"] = False
            UPDATE_STATE["finished_at"] = utc_stamp()


class ArchiveHandler(SimpleHTTPRequestHandler):
    server_version = f"AsteroidArchive/{VERSION}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data: blob:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; font-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
        # Prevent a previously opened localhost application from being reused from cache.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("X-Asteroid-Archive-Version", VERSION)
        for name, value in cors_headers(self.headers.get("Origin")):
            self.send_header(name, value)
        super().end_headers()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path.startswith("/api/"):
            runtime = {
                "deployment": "local",
                "host_default": environment_default_host(),
                "port_default": environment_default_port(),
                "data_dir": str(DB_PATH.parent),
                "external_data_dir": bool(str(os.environ.get("ALBAZ_DATA_DIR") or "").strip()),
            }
            response = handle_get(parsed.path, parsed.query, update_state=update_snapshot(), runtime=runtime)
            self._write_api_response(response)
            return
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/api/update/start":
            self._start_update()
            return
        if parsed.path == "/api/update/cancel":
            self._cancel_update()
            return
        self._send_error_json(HTTPStatus.NOT_FOUND, "Unknown API route", parsed.path)

    def _read_json_body(self, max_bytes: int = 65536) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length < 0 or length > max_bytes:
            raise ValueError("Request body is too large")
        if not length:
            return {}
        raw = self.rfile.read(length)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _start_update(self) -> None:
        global UPDATE_CANCEL
        try:
            config = self._read_json_body()
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "Invalid update configuration", str(exc))
            return
        with UPDATE_LOCK:
            if UPDATE_STATE["running"]:
                self._send_json({"accepted": False, "reason": "update_already_running", "state": update_snapshot()}, HTTPStatus.CONFLICT)
                return
            UPDATE_CANCEL = threading.Event()
            UPDATE_STATE.update(
                {
                    "running": True,
                    "status": "running",
                    "percent": 0,
                    "stage": "queued",
                    "message": "تمت جدولة تحديث NASA/JPL",
                    "started_at": utc_stamp(),
                    "finished_at": None,
                    "logs": [],
                    "result": None,
                    "error": None,
                    "config": config,
                }
            )
        thread = threading.Thread(target=update_worker, args=(config,), name="NASADataEngine", daemon=True)
        thread.start()
        self._send_json({"accepted": True, "state": update_snapshot()}, HTTPStatus.ACCEPTED)

    def _cancel_update(self) -> None:
        snapshot = update_snapshot()
        if not snapshot.get("running"):
            self._send_json({"accepted": False, "reason": "no_running_update", "state": snapshot}, HTTPStatus.CONFLICT)
            return
        UPDATE_CANCEL.set()
        self._send_json({"accepted": True, "message": "cancel_requested", "state": update_snapshot()}, HTTPStatus.ACCEPTED)

    def _write_api_response(self, response: ApiResponse) -> None:
        self.send_response(int(response.status))
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        for name, value in response.headers:
            self.send_header(name, value)
        self.end_headers()
        if response.body:
            self.wfile.write(response.body)

    def _send_json(self, payload: object, status: int | HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_error_json(self, status: int | HTTPStatus, message: str, detail: str) -> None:
        self._send_json({"error": message, "detail": detail}, status)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Asteroid Archive v0.7 Final Audited Edition with SQLite, serialized NASA/JPL access, Horizons and comparison.")
    parser.add_argument("--host", default=environment_default_host(), help="Bind host")
    parser.add_argument("--port", type=int, default=environment_default_port(), help="Bind port")
    parser.add_argument("--no-open", action="store_true", help="Do not open the browser automatically")
    args = parser.parse_args()

    initialize()
    seed_if_empty()
    mimetypes.add_type("image/svg+xml", ".svg")
    requested_port = int(args.port)
    server = None
    last_error = None
    environment_managed_port = bool(str(os.environ.get("PORT") or "").strip())
    port_candidates = [requested_port] if environment_managed_port else range(requested_port, requested_port + 21)
    for candidate_port in port_candidates:
        try:
            server = ThreadingHTTPServer((args.host, candidate_port), ArchiveHandler)
            args.port = candidate_port
            break
        except OSError as exc:
            last_error = exc
    if server is None:
        raise RuntimeError(f"Unable to bind a local port starting at {requested_port}: {last_error}")
    if args.port != requested_port:
        print(f"Port {requested_port} was busy; using {args.port} instead.")
    base_url = f"http://{args.host}:{args.port}/"
    launch_url = f"{base_url}?app=asteroid-archive-v072-r1&ts={int(time.time())}"
    print(f"Asteroid Archive v{VERSION} — Final Audited Command Center")
    print(f"Database: {DB_PATH}")
    print(f"Dedicated local port: {args.port}")
    print(f"Open: {launch_url}")
    print("Press Ctrl+C to stop.")

    # Start serving first, verify that this exact application answers, then open the browser.
    worker = threading.Thread(target=server.serve_forever, name="AsteroidArchiveHTTP", daemon=True)
    worker.start()
    health_url = f"{base_url}api/health"
    ready = False
    for _ in range(40):
        try:
            with urllib.request.urlopen(health_url, timeout=0.5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("application") == "Asteroid Archive" and payload.get("version") == VERSION:
                ready = True
                break
        except Exception:
            time.sleep(0.1)
    if not ready:
        server.shutdown()
        server.server_close()
        raise RuntimeError("The dedicated Asteroid Archive server did not pass its identity check.")
    if not args.no_open:
        webbrowser.open_new_tab(launch_url)
    try:
        while worker.is_alive():
            worker.join(timeout=0.5)
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        UPDATE_CANCEL.set()
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
