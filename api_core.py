#!/usr/bin/env python3
"""Transport-neutral API behavior shared by local HTTP and WSGI adapters."""
from __future__ import annotations

import datetime as dt
import json
import time
import urllib.error
import urllib.parse
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Final, Iterable

from database import (
    DB_PATH,
    counts,
    get_object_profile,
    list_object_profiles,
    metadata,
    read_dataset,
    recent_update_runs,
    upsert_object_profile,
)
from horizons_engine import get_orbit_track, test_nasa_services
from jpl_client import ensure_signature
from update_engine import fetch_json

VERSION: Final[str] = "0.7.2"
PAGES_ORIGIN: Final[str] = "https://mralehsas.github.io"
REMOTE_ENDPOINTS: Final[dict[str, str]] = {
    "/api/cad": "https://ssd-api.jpl.nasa.gov/cad.api",
    "/api/fireball": "https://ssd-api.jpl.nasa.gov/fireball.api",
    "/api/sbdb": "https://ssd-api.jpl.nasa.gov/sbdb.api",
    "/api/sentry": "https://ssd-api.jpl.nasa.gov/sentry.api",
    "/api/sbdb-query": "https://ssd-api.jpl.nasa.gov/sbdb_query.api",
    "/api/horizons-lookup": "https://ssd.jpl.nasa.gov/api/horizons_lookup.api",
}
REMOTE_SERVICE_KEYS: Final[dict[str, str]] = {
    "/api/cad": "cad",
    "/api/fireball": "fireball",
    "/api/sbdb": "sbdb",
    "/api/sentry": "sentry",
    "/api/horizons-lookup": "horizons_lookup",
}
LOCAL_DATASETS: Final[dict[str, str]] = {
    "/api/local/approaches": "approaches",
    "/api/local/fireballs": "fireballs",
    "/api/local/sentry": "sentry",
    "/api/local/objects": "objects",
    "/api/local/meteorites": "meteorites",
    "/api/local/impact-structures": "impact_structures",
}
CACHE_TTL_SECONDS: Final[int] = 300
CACHE: dict[str, tuple[float, bytes, str]] = {}


@dataclass(frozen=True)
class ApiResponse:
    status: int
    body: bytes
    content_type: str = "application/json; charset=utf-8"
    headers: tuple[tuple[str, str], ...] = ()


def json_response(
    payload: object,
    status: int = 200,
    headers: Iterable[tuple[str, str]] = (),
) -> ApiResponse:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    return ApiResponse(int(status), raw, "application/json; charset=utf-8", tuple(headers))


def error_response(status: int, message: str, detail: str) -> ApiResponse:
    return json_response({"error": message, "detail": detail}, status=int(status))


def allowed_cors_origin(origin: str | None) -> str | None:
    value = str(origin or "").strip()
    if value == PAGES_ORIGIN:
        return value
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost"}:
        return value
    return None


def cors_headers(origin: str | None) -> tuple[tuple[str, str], ...]:
    approved = allowed_cors_origin(origin)
    if not approved:
        return ()
    return (
        ("Access-Control-Allow-Origin", approved),
        ("Vary", "Origin"),
        ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
        ("Access-Control-Allow-Headers", "Content-Type"),
    )


def cloud_update_snapshot() -> dict[str, Any]:
    return {
        "running": False,
        "status": "console_only",
        "percent": 0,
        "stage": "console",
        "message": "Full archive refresh is administered from the PythonAnywhere Bash console.",
        "started_at": None,
        "finished_at": None,
        "logs": [],
        "result": None,
        "error": None,
    }


def utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _proxy_api(route: str, query: str) -> ApiResponse:
    """Proxy official JSON APIs through the existing serialized JPL client."""
    base_url = REMOTE_ENDPOINTS[route]
    pairs = urllib.parse.parse_qsl(query, keep_blank_values=False)
    params: dict[str, Any] = {}
    for key, value in pairs:
        if key in params:
            current = params[key]
            params[key] = [*current, value] if isinstance(current, list) else [current, value]
        else:
            params[key] = value
    cache_key = base_url + "?" + urllib.parse.urlencode(sorted(pairs)) if pairs else base_url
    cached = CACHE.get(cache_key)
    if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
        return ApiResponse(
            HTTPStatus.OK,
            cached[1],
            f"{cached[2]}; charset=utf-8",
            (("X-Archive-Cache", "HIT"),),
        )
    try:
        payload = fetch_json(base_url, params, timeout=45)
        service_key = REMOTE_SERVICE_KEYS.get(route)
        if service_key:
            ensure_signature(payload, service_key)
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
        content_type = "application/json"
        CACHE[cache_key] = (time.time(), raw, content_type)
        return ApiResponse(
            HTTPStatus.OK,
            raw,
            f"{content_type}; charset=utf-8",
            (("X-Archive-Cache", "MISS"),),
        )
    except Exception as exc:
        return error_response(HTTPStatus.BAD_GATEWAY, "Unable to reach NASA/JPL", str(exc))


def _local_dataset(dataset: str, query: str) -> ApiResponse:
    params = urllib.parse.parse_qs(query)
    try:
        limit = int(params.get("limit", ["5000"])[0])
    except (TypeError, ValueError):
        limit = 5000
    rows = read_dataset(dataset, limit=limit)
    return json_response({"dataset": dataset, "count": len(rows), "records": rows})


def _object_list(query: str) -> ApiResponse:
    params = urllib.parse.parse_qs(query)
    q = params.get("q", [""])[0]
    try:
        limit = int(params.get("limit", ["100"])[0])
    except (TypeError, ValueError):
        limit = 100
    rows = list_object_profiles(q, limit=limit)
    return json_response({"dataset": "objects", "count": len(rows), "records": rows})


def _object(query: str) -> ApiResponse:
    params = urllib.parse.parse_qs(query)
    sstr = str(params.get("sstr", [""])[0]).strip()
    refresh = str(params.get("refresh", ["0"])[0]).lower() in {"1", "true", "yes"}
    if not sstr:
        return error_response(HTTPStatus.BAD_REQUEST, "Missing object identifier", "Parameter sstr is required")
    cached = None if refresh else get_object_profile(sstr)
    if cached:
        cached.setdefault("archive_cache", {}).update({"hit": True, "source": "SQLite"})
        return json_response(cached)
    try:
        payload = fetch_json(
            "https://ssd-api.jpl.nasa.gov/sbdb.api",
            {"sstr": sstr, "phys-par": "true", "full-prec": "true"},
            timeout=35,
        )
        ensure_signature(payload, "sbdb")
        upsert_object_profile(payload)
        payload["archive_cache"] = {"hit": False, "stored_locally": True, "source": "NASA/JPL SBDB"}
        return json_response(payload)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else str(exc)
        return error_response(exc.code, "SBDB request failed", detail)
    except Exception as exc:
        fallback = get_object_profile(sstr)
        if fallback:
            fallback.setdefault("archive_cache", {}).update({"hit": True, "stale": True, "error": str(exc)})
            return json_response(fallback)
        return error_response(HTTPStatus.BAD_GATEWAY, "Unable to load object profile", str(exc))


def _connectivity(query: str) -> ApiResponse:
    params = urllib.parse.parse_qs(query)
    try:
        timeout = int(params.get("timeout", ["10"])[0])
    except (TypeError, ValueError):
        timeout = 10
    try:
        return json_response(test_nasa_services(timeout=timeout))
    except Exception as exc:
        return error_response(HTTPStatus.INTERNAL_SERVER_ERROR, "Connectivity test failed", str(exc))


def _horizons_track(query: str) -> ApiResponse:
    params = urllib.parse.parse_qs(query)
    target = str(params.get("target", ["99942"])[0]).strip()
    start = str(params.get("start", [utc_stamp()[:10]])[0]).strip()
    try:
        days = int(params.get("days", ["730"])[0])
        step_days = int(params.get("step", ["5"])[0])
        timeout = int(params.get("timeout", ["55"])[0])
    except (TypeError, ValueError):
        return error_response(
            HTTPStatus.BAD_REQUEST,
            "Invalid Horizons parameters",
            "days, step and timeout must be integers",
        )
    refresh = str(params.get("refresh", ["0"])[0]).lower() in {"1", "true", "yes"}
    try:
        payload = get_orbit_track(target, start, days=days, step_days=step_days, timeout=timeout, refresh=refresh)
        return json_response(payload)
    except ValueError as exc:
        return error_response(HTTPStatus.BAD_REQUEST, "Horizons request is invalid", str(exc))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else str(exc)
        return error_response(exc.code, "Horizons request failed", detail)
    except Exception as exc:
        return error_response(HTTPStatus.BAD_GATEWAY, "Unable to load Horizons trajectory", str(exc))


def _update_history(query: str) -> ApiResponse:
    params = urllib.parse.parse_qs(query)
    try:
        limit = int(params.get("limit", ["10"])[0])
    except (TypeError, ValueError):
        limit = 10
    return json_response({"records": recent_update_runs(limit=limit)})


def _health(update_state: dict[str, Any], runtime: dict[str, Any]) -> ApiResponse:
    return json_response({
        "status": "ok",
        "application": "Asteroid Archive",
        "package": "v0.7.2 Horizons Fixed — Port Isolation R1",
        "version": VERSION,
        "database_ready": DB_PATH.exists(),
        "database_path": str(DB_PATH.name),
        "counts": counts(),
        "metadata": metadata(),
        "cache_entries": len(CACHE),
        "update": update_state,
        "recent_updates": recent_update_runs(limit=3),
        "runtime": runtime,
    })


def handle_get(
    path: str,
    query: str,
    *,
    update_state: dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
) -> ApiResponse:
    if path in REMOTE_ENDPOINTS:
        return _proxy_api(path, query)
    if path in LOCAL_DATASETS:
        dataset = LOCAL_DATASETS[path]
        return _object_list(query) if dataset == "objects" else _local_dataset(dataset, query)
    if path == "/api/object":
        return _object(query)
    if path == "/api/connectivity/test":
        return _connectivity(query)
    if path == "/api/horizons/track":
        return _horizons_track(query)
    if path == "/api/update/status":
        return json_response(update_state or cloud_update_snapshot())
    if path == "/api/update/history":
        return _update_history(query)
    if path == "/api/health":
        return _health(update_state or cloud_update_snapshot(), runtime or {})
    return error_response(HTTPStatus.NOT_FOUND, "Unknown API route", path)


def handle_cloud_post(path: str, body: bytes = b"") -> ApiResponse:
    if path == "/api/update/start":
        return json_response({
            "accepted": False,
            "reason": "console_administered",
            "message": "Full archive refresh must be run from the PythonAnywhere Bash console on the free deployment.",
            "state": cloud_update_snapshot(),
        }, status=HTTPStatus.SERVICE_UNAVAILABLE)
    if path == "/api/update/cancel":
        return json_response({
            "accepted": False,
            "reason": "no_cloud_background_worker",
            "message": "No web-request background update worker exists on this deployment.",
            "state": cloud_update_snapshot(),
        }, status=HTTPStatus.CONFLICT)
    return error_response(HTTPStatus.NOT_FOUND, "Unknown API route", path)
