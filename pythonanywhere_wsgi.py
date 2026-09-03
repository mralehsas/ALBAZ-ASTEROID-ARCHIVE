#!/usr/bin/env python3
"""WSGI adapter for the PythonAnywhere deployment of Asteroid Archive."""
from __future__ import annotations

import os
from http import HTTPStatus
from pathlib import Path
from typing import Iterable

# Must be set before importing modules that bind runtime paths at import time.
os.environ.setdefault("ALBAZ_DATA_DIR", str(Path.home() / ".albaz-asteroid-data"))

# PythonAnywhere can keep multiple processes connected to the same SQLite file.
# Preserve the database's established journal mode on ordinary connections and
# serialize archive-changing full/web refreshes across independent processes.
from cloud_sqlite import activate_cloud_sqlite, install_update_lock  # noqa: E402

activate_cloud_sqlite()
install_update_lock()

from api_core import (  # noqa: E402
    ApiResponse,
    cloud_update_snapshot,
    cors_headers,
    error_response,
    handle_cloud_post,
    handle_get,
)
from database import DB_PATH, initialize, seed_if_empty  # noqa: E402

MAX_BODY_BYTES = 65536

initialize()
seed_if_empty()


def _runtime_info() -> dict[str, object]:
    return {
        "deployment": "pythonanywhere",
        "data_dir": str(DB_PATH.parent),
        "external_data_dir": True,
        "sqlite_journal_policy": "preserve-existing",
        "shared_update_lock": True,
    }


def _read_body(environ: dict[str, object]) -> bytes:
    raw_length = str(environ.get("CONTENT_LENGTH") or "0").strip()
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise ValueError("Invalid Content-Length") from exc
    if length < 0 or length > MAX_BODY_BYTES:
        raise ValueError("Request body is too large")
    stream = environ.get("wsgi.input")
    if not length:
        return b""
    if stream is None or not hasattr(stream, "read"):
        raise ValueError("Missing WSGI request body stream")
    return stream.read(length)


def _status_line(status: int) -> str:
    try:
        phrase = HTTPStatus(int(status)).phrase
    except ValueError:
        phrase = "Unknown"
    return f"{int(status)} {phrase}"


def application(environ, start_response) -> Iterable[bytes]:
    method = str(environ.get("REQUEST_METHOD") or "GET").upper()
    path = str(environ.get("PATH_INFO") or "/")
    query = str(environ.get("QUERY_STRING") or "")
    origin = environ.get("HTTP_ORIGIN")

    if method == "OPTIONS":
        response = ApiResponse(HTTPStatus.NO_CONTENT, b"", "application/json; charset=utf-8")
    elif method == "GET":
        response = handle_get(
            path,
            query,
            update_state=cloud_update_snapshot(),
            runtime=_runtime_info(),
        )
    elif method == "POST":
        try:
            body = _read_body(environ)
        except ValueError as exc:
            response = error_response(HTTPStatus.BAD_REQUEST, "Invalid request body", str(exc))
        else:
            response = handle_cloud_post(path, body)
    else:
        response = error_response(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed", method)

    headers = [
        ("Content-Type", response.content_type),
        ("Content-Length", str(len(response.body))),
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "no-referrer"),
        ("X-Asteroid-Archive-Version", "0.7.2"),
        *response.headers,
        *cors_headers(str(origin) if origin is not None else None),
    ]
    start_response(_status_line(int(response.status)), headers)
    return [response.body]
