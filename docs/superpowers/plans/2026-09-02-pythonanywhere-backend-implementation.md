# ALBAZ Asteroid Archive PythonAnywhere Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the abandoned Render deployment path with a free PythonAnywhere WSGI backend while preserving GitHub Pages, local Windows mode, SQLite, NASA/JPL/Horizons behavior, and the frozen scientific engine version `0.7.2`.

**Architecture:** Extract browser-facing API behavior from `server.py` into a transport-neutral `api_core.py`. Keep `server.py` as the local `ThreadingHTTPServer` adapter and add `pythonanywhere_wsgi.py` as an API-only WSGI adapter; both adapters call the same core so cloud and desktop scientific behavior cannot drift.

**Tech Stack:** Python 3.11+ standard library, WSGI, `http.server`, SQLite, vanilla JavaScript/HTML, GitHub Pages, PythonAnywhere free Web App.

**Spec:** `docs/superpowers/specs/2026-09-02-pythonanywhere-backend-design.md`

## Global Constraints

- Scientific engine version remains exactly `0.7.2`.
- No astronomical formula, Horizons vector interpretation, API-version policy, Sentry interpretation, database schema semantics, missing-data policy, or NASA/JPL payload transformation changes.
- Existing `jpl_client.py` serialized NASA/JPL access and signature validation remain authoritative.
- GitHub Pages remains the public frontend.
- Local Windows mode remains available on `127.0.0.1:8872` with the existing fallback-port behavior.
- Production CORS origin is exactly `https://mralehsas.github.io`; wildcard CORS is forbidden.
- PythonAnywhere is API-only and must never serve or duplicate the GitHub Pages frontend.
- Cloud `/api/update/start` must return structured `503 Service Unavailable`; full archive refresh is console-administered on the free plan.
- `ALBAZ_DATA_DIR` controls mutable SQLite/cache state. PythonAnywhere production value is `$HOME/.albaz-asteroid-data`.
- `data/bootstrap.json` and `data/earth_history.json` remain immutable repository seed inputs and never move with `ALBAZ_DATA_DIR`.
- No third-party Python package is introduced.
- Network failures remain visibly different from valid scientific results.

---

## File Map Locked for This Migration

- Create `api_core.py` — normalized API response type, CORS policy, shared GET route behavior, cloud update-status semantics, and short-lived upstream response cache.
- Modify `server.py` — retain local HTTP/static/browser/update-thread behavior but delegate API GET behavior and CORS policy to `api_core.py`.
- Create `pythonanywhere_wsgi.py` — WSGI adapter, PythonAnywhere runtime-data bootstrap, CORS/preflight, cloud POST policy.
- Create `cache_maintenance.py` — safe generated-cache pruning CLI/function; never touches SQLite archival rows or bundled seed files.
- Modify `deployment_test.py` — replace Render-specific assertions with shared-core, local-adapter, WSGI, cache, and PythonAnywhere documentation contracts.
- Keep `runtime_paths.py` as the existing path authority; change it only if a test proves an additional helper is necessary.
- Keep `database.py`, `horizons_engine.py`, `update_engine.py`, `update_data.py`, and `jpl_client.py` scientifically unchanged unless a failing migration test identifies an adapter-only defect.
- Create `PYTHONANYWHERE_DEPLOYMENT.md` — exact free-account setup, WSGI config, database initialization, console refresh, cache maintenance, and final frontend binding.
- Delete `render.yaml`.
- Delete `RENDER_DEPLOYMENT.md`.
- Modify `web-config.js` only after the real PythonAnywhere HTTPS origin exists.

---

### Task 1: Create the Transport-Neutral API Foundation

**Files:**
- Create: `api_core.py`
- Modify: `deployment_test.py`

**Interfaces:**
- Produces `ApiResponse(status: int, body: bytes, content_type: str, headers: tuple[tuple[str, str], ...])`.
- Produces `json_response(payload, status=200, headers=()) -> ApiResponse`.
- Produces `error_response(status, message, detail) -> ApiResponse`.
- Produces `allowed_cors_origin(origin: str | None) -> str | None`.
- Produces `cors_headers(origin: str | None) -> tuple[tuple[str, str], ...]`.
- Produces `cloud_update_snapshot() -> dict[str, Any]`.
- Later tasks consume these exact names.

- [ ] **Step 1: Add failing API-foundation tests**

Append to `deployment_test.py`:

```python
def test_api_core_response_contract() -> None:
    import api_core

    response = api_core.json_response({"ok": True}, status=201, headers=(("X-Test", "yes"),))
    assert_true(response.status == 201, "ApiResponse status changed")
    assert_true(response.content_type == "application/json; charset=utf-8", "JSON content type changed")
    assert_true(json.loads(response.body.decode("utf-8")) == {"ok": True}, "JSON payload encoding changed")
    assert_true(("X-Test", "yes") in response.headers, "ApiResponse custom header missing")


def test_api_core_cors_policy() -> None:
    import api_core

    assert_true(api_core.allowed_cors_origin("https://mralehsas.github.io") == "https://mralehsas.github.io", "Pages origin rejected")
    assert_true(api_core.allowed_cors_origin("http://127.0.0.1:8872") == "http://127.0.0.1:8872", "Local 127.0.0.1 rejected")
    assert_true(api_core.allowed_cors_origin("http://localhost:8872") == "http://localhost:8872", "Localhost rejected")
    assert_true(api_core.allowed_cors_origin("https://evil.example") is None, "Unknown origin allowed")
    headers = dict(api_core.cors_headers("https://mralehsas.github.io"))
    assert_true(headers.get("Access-Control-Allow-Origin") == "https://mralehsas.github.io", "CORS allow-origin missing")
    assert_true("GET" in headers.get("Access-Control-Allow-Methods", ""), "CORS GET method missing")
    assert_true("POST" in headers.get("Access-Control-Allow-Methods", ""), "CORS POST method missing")


def test_cloud_update_snapshot_contract() -> None:
    import api_core

    payload = api_core.cloud_update_snapshot()
    assert_true(payload["running"] is False, "Cloud update must never claim a background worker is running")
    assert_true(payload["status"] == "console_only", "Cloud update status must be console_only")
    assert_true(payload["stage"] == "console", "Cloud update stage must be console")
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
python -c "import deployment_test as t; t.test_api_core_response_contract(); t.test_api_core_cors_policy(); t.test_cloud_update_snapshot_contract()"
```

Expected: fail with `ModuleNotFoundError: No module named 'api_core'`.

- [ ] **Step 3: Create `api_core.py` with the minimal foundation**

Create:

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass
from typing import Any, Final, Iterable

VERSION: Final[str] = "0.7.2"
PAGES_ORIGIN: Final[str] = "https://mralehsas.github.io"


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
```

- [ ] **Step 4: Run foundation tests**

```bash
python -c "import deployment_test as t; t.test_api_core_response_contract(); t.test_api_core_cors_policy(); t.test_cloud_update_snapshot_contract(); print('PASS api foundation')"
```

Expected: `PASS api foundation`.

- [ ] **Step 5: Commit**

```bash
git add api_core.py deployment_test.py
git commit -m "feat: add transport neutral API foundation"
```

---

### Task 2: Move Shared Read-Only API Behavior Into `api_core.py`

**Files:**
- Modify: `api_core.py`
- Modify: `deployment_test.py`
- Read-only reference: `server.py`

**Interfaces:**
- Produces `handle_get(path: str, query: str, *, update_state: dict[str, Any] | None = None, runtime: dict[str, Any] | None = None) -> ApiResponse`.
- Produces `handle_cloud_post(path: str, body: bytes = b"") -> ApiResponse`.
- Consumes existing database functions, `fetch_json`, `get_orbit_track`, `test_nasa_services`, and `ensure_signature` without changing them.

- [ ] **Step 1: Add failing route-contract tests**

Append:

```python
def test_api_core_health_and_unknown_routes() -> None:
    import api_core

    update = api_core.cloud_update_snapshot()
    runtime = {"deployment": "test", "data_dir": "/tmp/albaz", "external_data_dir": True}
    response = api_core.handle_get("/api/health", "", update_state=update, runtime=runtime)
    payload = json.loads(response.body.decode("utf-8"))
    assert_true(response.status == 200, "Health route failed")
    assert_true(payload["status"] == "ok", "Health status changed")
    assert_true(payload["application"] == "Asteroid Archive", "Health application changed")
    assert_true(payload["version"] == "0.7.2", "Scientific version changed")
    assert_true(payload["runtime"] == runtime, "Runtime metadata not preserved")

    missing = api_core.handle_get("/api/does-not-exist", "")
    missing_payload = json.loads(missing.body.decode("utf-8"))
    assert_true(missing.status == 404, "Unknown API route must be 404")
    assert_true(missing_payload["error"] == "Unknown API route", "Unknown-route payload changed")


def test_api_core_proxy_and_horizons_are_transport_neutral() -> None:
    import api_core

    original_fetch = api_core.fetch_json
    original_track = api_core.get_orbit_track
    try:
        api_core.fetch_json = lambda url, params, timeout=45: {
            "signature": {"source": "NASA/JPL", "version": "1.5"},
            "count": 0,
            "fields": [],
            "data": [],
        }
        cad = api_core.handle_get("/api/cad", "date-min=2026-09-02&date-max=2026-09-03")
        assert_true(cad.status == 200, "CAD proxy did not return 200")
        assert_true(dict(cad.headers).get("X-Archive-Cache") == "MISS", "First CAD response must be cache MISS")

        api_core.get_orbit_track = lambda target, start, **kwargs: {
            "target": target,
            "start": start,
            "points": [],
            "source": "NASA/JPL Horizons",
        }
        track = api_core.handle_get("/api/horizons/track", "target=99942&start=2026-09-02&days=10&step=2&timeout=10")
        track_payload = json.loads(track.body.decode("utf-8"))
        assert_true(track.status == 200, "Horizons route failed")
        assert_true(track_payload["target"] == "99942", "Horizons target changed")
    finally:
        api_core.fetch_json = original_fetch
        api_core.get_orbit_track = original_track


def test_cloud_update_post_policy() -> None:
    import api_core

    start = api_core.handle_cloud_post("/api/update/start", b"{}")
    start_payload = json.loads(start.body.decode("utf-8"))
    assert_true(start.status == 503, "Cloud update start must return 503")
    assert_true(start_payload["reason"] == "console_administered", "Cloud update start reason changed")

    cancel = api_core.handle_cloud_post("/api/update/cancel", b"{}")
    cancel_payload = json.loads(cancel.body.decode("utf-8"))
    assert_true(cancel.status == 409, "Cloud update cancel must return 409")
    assert_true(cancel_payload["reason"] == "no_cloud_background_worker", "Cloud cancel reason changed")
```

- [ ] **Step 2: Run and verify RED**

```bash
python -c "import deployment_test as t; t.test_api_core_health_and_unknown_routes(); t.test_api_core_proxy_and_horizons_are_transport_neutral(); t.test_cloud_update_post_policy()"
```

Expected: fail because `handle_get` and `handle_cloud_post` do not exist.

- [ ] **Step 3: Add existing scientific/storage dependencies and route constants to `api_core.py`**

Add imports exactly:

```python
import time
import urllib.error
from http import HTTPStatus

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
```

Add the current route maps from `server.py` unchanged:

```python
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
```

- [ ] **Step 4: Implement the shared GET dispatcher**

Add:

```python
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
```

- [ ] **Step 5: Move each current `server.py` read-only handler into response-returning helpers**

Use the current method bodies as the authority and make only the transport substitutions below:

```text
server._proxy_api             -> api_core._proxy_api
server._serve_local_dataset   -> api_core._local_dataset
server._serve_object_list     -> api_core._object_list
server._serve_object          -> api_core._object
server._serve_connectivity_test -> api_core._connectivity
server._serve_horizons_track  -> api_core._horizons_track
server._serve_update_history  -> api_core._update_history
server._serve_health          -> api_core._health
```

For every moved helper:

```text
self._send_json(payload, status)          becomes return json_response(payload, int(status))
self._send_error_json(status,msg,detail)  becomes return error_response(int(status), msg, detail)
self._send_json_bytes(raw,type,cached=...) becomes return ApiResponse(200, raw, f"{type}; charset=utf-8", (("X-Archive-Cache", "HIT" or "MISS"),))
```

Keep all current query defaults, bounds, upstream URLs, timeout values, signature checks, stale-SQLite fallback rules, and error status codes unchanged.

The health helper is exactly:

```python
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
```

- [ ] **Step 6: Implement cloud POST policy**

Add:

```python
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
```

The `body` parameter is intentionally accepted for a stable adapter interface; cloud update operations do not execute request-body configuration.

- [ ] **Step 7: Run core route tests and scientific regression**

```bash
python -c "import deployment_test as t; t.test_api_core_health_and_unknown_routes(); t.test_api_core_proxy_and_horizons_are_transport_neutral(); t.test_cloud_update_post_policy(); print('PASS core routes')"
python self_test.py
```

Expected: both commands pass.

- [ ] **Step 8: Commit**

```bash
git add api_core.py deployment_test.py
git commit -m "feat: centralize shared API behavior"
```

---

### Task 3: Refactor the Local HTTP Server Into an Adapter Without Changing Desktop Behavior

**Files:**
- Modify: `server.py`
- Modify: `deployment_test.py`

**Interfaces:**
- Consumes `api_core.handle_get`, `api_core.cors_headers`, and `ApiResponse`.
- Preserves local threaded `/api/update/start` and `/api/update/cancel` behavior in `server.py`.
- Produces `ArchiveHandler._write_api_response(response: ApiResponse) -> None`.

- [ ] **Step 1: Add a failing local-adapter health test**

Append:

```python
def test_local_http_adapter_uses_shared_core() -> None:
    import http.client
    import threading
    from http.server import ThreadingHTTPServer
    import server

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.ArchiveHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        port = httpd.server_address[1]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/api/health", headers={"Origin": "https://mralehsas.github.io"})
        response = conn.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        assert_true(response.status == 200, "Local shared-core health failed")
        assert_true(payload["version"] == "0.7.2", "Local scientific version changed")
        assert_true(response.getheader("Access-Control-Allow-Origin") == "https://mralehsas.github.io", "Local shared CORS failed")
        conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
```

Before production changes, strengthen the static contract:

```python
def test_server_delegation_contract() -> None:
    text = (ROOT / "server.py").read_text(encoding="utf-8")
    assert_true("from api_core import" in text, "server.py does not import shared API core")
    assert_true("handle_get(" in text, "server.py does not delegate API GET routes")
    assert_true("def _proxy_api(" not in text, "Duplicate proxy implementation remains in server.py")
    assert_true("def _serve_horizons_track(" not in text, "Duplicate Horizons implementation remains in server.py")
```

- [ ] **Step 2: Verify the delegation contract is RED**

```bash
python -c "import deployment_test as t; t.test_server_delegation_contract()"
```

Expected: fail because `server.py` still contains the old duplicated handlers.

- [ ] **Step 3: Replace shared imports/constants in `server.py`**

Import:

```python
from api_core import ApiResponse, cors_headers, handle_get
```

Remove from `server.py` only the symbols that moved into `api_core.py`:

```text
REMOTE_ENDPOINTS
REMOTE_SERVICE_KEYS
LOCAL_DATASETS
CACHE_TTL_SECONDS
CACHE
PAGES_ORIGIN
allowed_cors_origin
_proxy_api
_serve_local_dataset
_serve_object_list
_serve_object
_serve_connectivity_test
_serve_horizons_track
_serve_update_history
_serve_health
```

Keep `environment_default_host`, `environment_default_port`, local update state/worker code, static serving, browser launch, and local database initialization.

- [ ] **Step 4: Use the shared CORS policy in `end_headers()`**

Replace the local origin calculation with:

```python
for name, value in cors_headers(self.headers.get("Origin")):
    self.send_header(name, value)
```

Keep the existing local security/cache headers unchanged.

- [ ] **Step 5: Add the API response writer**

Inside `ArchiveHandler` add:

```python
def _write_api_response(self, response: ApiResponse) -> None:
    self.send_response(int(response.status))
    self.send_header("Content-Type", response.content_type)
    self.send_header("Content-Length", str(len(response.body)))
    for name, value in response.headers:
        self.send_header(name, value)
    self.end_headers()
    if response.body:
        self.wfile.write(response.body)
```

- [ ] **Step 6: Delegate all API GET requests to the shared core**

Replace the API branch chain at the start of `do_GET()` with:

```python
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
```

Do not route local POST update-start/cancel through the cloud policy. Keep the existing local `do_POST`, `_start_update`, and `_cancel_update` implementations.

- [ ] **Step 7: Remove obsolete local JSON-response helpers only after all local callers are gone**

Delete `_send_json_bytes` and `_send_error_json` when `grep` confirms no caller remains. Keep `_send_json` if local update POST methods still use it.

Rename the internal variable:

```python
render_managed_port
```

to:

```python
environment_managed_port
```

without changing the current behavior that an explicitly supplied `PORT` disables fallback-port selection.

- [ ] **Step 8: Rename the Render-era bind test without changing its behavior**

Rename `test_render_bind_defaults` in `deployment_test.py` to:

```python
def test_server_bind_environment_defaults() -> None:
```

Keep its `HOST=0.0.0.0` and `PORT=12345` assertions unchanged.

- [ ] **Step 9: Run local adapter, CORS, and scientific tests**

```bash
python -c "import deployment_test as t; t.test_server_delegation_contract(); t.test_local_http_adapter_uses_shared_core(); t.test_cors_preflight_http(); t.test_server_bind_environment_defaults(); print('PASS local adapter')"
python self_test.py
```

Expected: pass.

- [ ] **Step 10: Commit**

```bash
git add server.py deployment_test.py
git commit -m "refactor: make local server an API core adapter"
```

---

### Task 4: Add the PythonAnywhere WSGI Adapter

**Files:**
- Create: `pythonanywhere_wsgi.py`
- Modify: `deployment_test.py`

**Interfaces:**
- Produces standard WSGI callable `application(environ, start_response)`.
- Uses `$HOME/.albaz-asteroid-data` as the default PythonAnywhere runtime-data directory before importing database/core modules.
- Consumes `api_core.handle_get`, `api_core.handle_cloud_post`, `api_core.cors_headers`, `api_core.cloud_update_snapshot`.

- [ ] **Step 1: Add WSGI test helper and failing tests**

Append:

```python
def call_wsgi(
    method: str,
    path: str,
    *,
    query: str = "",
    origin: str | None = None,
    body: bytes = b"",
) -> tuple[str, dict[str, str], bytes]:
    import io
    import pythonanywhere_wsgi

    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]], exc_info=None):
        captured["status"] = status
        captured["headers"] = headers

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": "application/json",
        "wsgi.input": io.BytesIO(body),
    }
    if origin is not None:
        environ["HTTP_ORIGIN"] = origin
    chunks = pythonanywhere_wsgi.application(environ, start_response)
    payload = b"".join(chunks)
    return str(captured["status"]), dict(captured["headers"]), payload


def test_pythonanywhere_wsgi_health_and_cors() -> None:
    status, headers, body = call_wsgi("GET", "/api/health", origin="https://mralehsas.github.io")
    payload = json.loads(body.decode("utf-8"))
    assert_true(status.startswith("200 "), "WSGI health did not return 200")
    assert_true(payload["application"] == "Asteroid Archive", "WSGI health application changed")
    assert_true(payload["version"] == "0.7.2", "WSGI scientific version changed")
    assert_true(payload["runtime"]["deployment"] == "pythonanywhere", "WSGI deployment metadata missing")
    assert_true(headers.get("Access-Control-Allow-Origin") == "https://mralehsas.github.io", "WSGI Pages CORS missing")


def test_pythonanywhere_wsgi_preflight_and_rejected_origin() -> None:
    status, headers, body = call_wsgi("OPTIONS", "/api/update/start", origin="https://mralehsas.github.io")
    assert_true(status.startswith("204 "), "WSGI preflight did not return 204")
    assert_true(body == b"", "WSGI preflight must have an empty body")
    assert_true(headers.get("Access-Control-Allow-Origin") == "https://mralehsas.github.io", "WSGI preflight allow-origin missing")

    status, headers, _ = call_wsgi("OPTIONS", "/api/update/start", origin="https://evil.example")
    assert_true(status.startswith("204 "), "Unknown-origin preflight should still complete")
    assert_true("Access-Control-Allow-Origin" not in headers, "Unknown origin received CORS")


def test_pythonanywhere_wsgi_cloud_update_policy() -> None:
    status, _, body = call_wsgi("POST", "/api/update/start", origin="https://mralehsas.github.io", body=b"{}")
    payload = json.loads(body.decode("utf-8"))
    assert_true(status.startswith("503 "), "PythonAnywhere update start must return 503")
    assert_true(payload["reason"] == "console_administered", "PythonAnywhere update policy changed")
```

- [ ] **Step 2: Run and verify RED**

```bash
python -c "import deployment_test as t; t.test_pythonanywhere_wsgi_health_and_cors()"
```

Expected: `ModuleNotFoundError: No module named 'pythonanywhere_wsgi'`.

- [ ] **Step 3: Create `pythonanywhere_wsgi.py` with environment bootstrap before project imports**

Create:

```python
#!/usr/bin/env python3
from __future__ import annotations

import os
from http import HTTPStatus
from pathlib import Path
from typing import Iterable

os.environ.setdefault("ALBAZ_DATA_DIR", str(Path.home() / ".albaz-asteroid-data"))

from api_core import (
    ApiResponse,
    cloud_update_snapshot,
    cors_headers,
    error_response,
    handle_cloud_post,
    handle_get,
)
from database import DB_PATH, initialize, seed_if_empty

MAX_BODY_BYTES = 65536

initialize()
seed_if_empty()


def _runtime_info() -> dict[str, object]:
    return {
        "deployment": "pythonanywhere",
        "data_dir": str(DB_PATH.parent),
        "external_data_dir": True,
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
```

- [ ] **Step 4: Add a WSGI unknown-method test**

Append:

```python
def test_pythonanywhere_wsgi_method_and_unknown_route_errors() -> None:
    status, _, body = call_wsgi("DELETE", "/api/health")
    payload = json.loads(body.decode("utf-8"))
    assert_true(status.startswith("405 "), "Unsupported WSGI method must return 405")
    assert_true(payload["error"] == "Method not allowed", "WSGI method error changed")

    status, _, body = call_wsgi("GET", "/api/not-real")
    payload = json.loads(body.decode("utf-8"))
    assert_true(status.startswith("404 "), "Unknown WSGI API route must return 404")
    assert_true(payload["error"] == "Unknown API route", "WSGI unknown-route payload changed")
```

- [ ] **Step 5: Run all WSGI tests and scientific regression**

```bash
python -c "import deployment_test as t; t.test_pythonanywhere_wsgi_health_and_cors(); t.test_pythonanywhere_wsgi_preflight_and_rejected_origin(); t.test_pythonanywhere_wsgi_cloud_update_policy(); t.test_pythonanywhere_wsgi_method_and_unknown_route_errors(); print('PASS WSGI')"
python self_test.py
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add pythonanywhere_wsgi.py deployment_test.py
git commit -m "feat: add PythonAnywhere WSGI adapter"
```

---

### Task 5: Add Safe Generated-Cache Maintenance

**Files:**
- Create: `cache_maintenance.py`
- Modify: `deployment_test.py`

**Interfaces:**
- Produces `prune_generated_caches(*, horizons_dir: Path = HORIZONS_CACHE_DIR, live_cache: Path = LIVE_CACHE_PATH, max_age_days: int = 30, now: float | None = None) -> dict[str, int]`.
- Deletes only generated files under Horizons cache and an old generated `live-cache.js`; never opens or deletes `DB_PATH`, `BUNDLE_DATA_DIR/bootstrap.json`, or `BUNDLE_DATA_DIR/earth_history.json`.

- [ ] **Step 1: Add a failing cache-safety test**

Append:

```python
def test_cache_maintenance_deletes_only_stale_generated_files() -> None:
    import time
    from pathlib import Path
    import cache_maintenance

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        horizons = root / "horizons_cache"
        horizons.mkdir()
        old_file = horizons / "old.json"
        new_file = horizons / "new.json"
        live = root / "live-cache.js"
        db = root / "asteroid_archive.db"
        old_file.write_text("old", encoding="utf-8")
        new_file.write_text("new", encoding="utf-8")
        live.write_text("cache", encoding="utf-8")
        db.write_text("must-survive", encoding="utf-8")

        now = time.time()
        old_time = now - 40 * 86400
        os.utime(old_file, (old_time, old_time))
        os.utime(live, (old_time, old_time))

        report = cache_maintenance.prune_generated_caches(
            horizons_dir=horizons,
            live_cache=live,
            max_age_days=30,
            now=now,
        )
        assert_true(not old_file.exists(), "Old Horizons cache survived")
        assert_true(not live.exists(), "Old live-cache survived")
        assert_true(new_file.exists(), "Fresh Horizons cache was deleted")
        assert_true(db.exists(), "SQLite file was deleted by cache maintenance")
        assert_true(report["files_deleted"] == 2, "Cache maintenance deleted unexpected file count")
```

- [ ] **Step 2: Run and verify RED**

```bash
python -c "import deployment_test as t; t.test_cache_maintenance_deletes_only_stale_generated_files()"
```

Expected: fail because `cache_maintenance.py` does not exist.

- [ ] **Step 3: Create `cache_maintenance.py`**

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from runtime_paths import HORIZONS_CACHE_DIR, LIVE_CACHE_PATH


def prune_generated_caches(
    *,
    horizons_dir: Path = HORIZONS_CACHE_DIR,
    live_cache: Path = LIVE_CACHE_PATH,
    max_age_days: int = 30,
    now: float | None = None,
) -> dict[str, int]:
    days = max(1, int(max_age_days))
    current = time.time() if now is None else float(now)
    cutoff = current - days * 86400
    deleted = 0
    reclaimed = 0

    candidates: list[Path] = []
    if horizons_dir.exists():
        candidates.extend(path for path in horizons_dir.rglob("*") if path.is_file())
    if live_cache.exists() and live_cache.is_file():
        candidates.append(live_cache)

    for path in candidates:
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_mtime >= cutoff:
            continue
        try:
            path.unlink()
        except OSError:
            continue
        deleted += 1
        reclaimed += int(stat.st_size)

    remaining = 0
    if horizons_dir.exists():
        for path in horizons_dir.rglob("*"):
            if path.is_file():
                try:
                    remaining += int(path.stat().st_size)
                except OSError:
                    pass
    if live_cache.exists():
        try:
            remaining += int(live_cache.stat().st_size)
        except OSError:
            pass

    return {
        "files_deleted": deleted,
        "bytes_reclaimed": reclaimed,
        "remaining_cache_bytes": remaining,
        "max_age_days": days,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prune stale generated Asteroid Archive caches without touching SQLite archival data.")
    parser.add_argument("--max-age-days", type=int, default=30)
    args = parser.parse_args()
    print(json.dumps(prune_generated_caches(max_age_days=args.max_age_days), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the cache test and scientific regression**

```bash
python -c "import deployment_test as t; t.test_cache_maintenance_deletes_only_stale_generated_files(); print('PASS cache maintenance')"
python self_test.py
```

- [ ] **Step 5: Commit**

```bash
git add cache_maintenance.py deployment_test.py
git commit -m "feat: add safe cache maintenance"
```

---

### Task 6: Remove Render Artifacts and Add Exact PythonAnywhere Deployment Operations

**Files:**
- Delete: `render.yaml`
- Delete: `RENDER_DEPLOYMENT.md`
- Create: `PYTHONANYWHERE_DEPLOYMENT.md`
- Modify: `deployment_test.py`

**Interfaces:**
- Produces one operational deployment guide with exact repository clone, WSGI config, runtime storage, health test, console refresh, cache maintenance, and frontend-binding commands.

- [ ] **Step 1: Replace the Render blueprint test with a failing PythonAnywhere documentation contract**

Delete `test_render_blueprint_contract()` and add:

```python
def test_pythonanywhere_deployment_contract() -> None:
    guide = (ROOT / "PYTHONANYWHERE_DEPLOYMENT.md").read_text(encoding="utf-8")
    assert_true(not (ROOT / "render.yaml").exists(), "Render blueprint still exists")
    assert_true(not (ROOT / "RENDER_DEPLOYMENT.md").exists(), "Render deployment guide still exists")
    required = (
        "pythonanywhere_wsgi.application",
        "$HOME/.albaz-asteroid-data",
        "https://mralehsas.github.io",
        "python update_data.py",
        "python cache_maintenance.py --max-age-days 30",
        "/api/health",
        "web-config.js",
    )
    for token in required:
        assert_true(token in guide, f"PythonAnywhere guide missing: {token}")
```

- [ ] **Step 2: Run and verify RED**

```bash
python -c "import deployment_test as t; t.test_pythonanywhere_deployment_contract()"
```

Expected: fail because Render artifacts still exist and the PythonAnywhere guide does not.

- [ ] **Step 3: Delete Render-specific deployment artifacts**

```bash
git rm render.yaml RENDER_DEPLOYMENT.md
```

Do not delete the historical Render design/plan files under `docs/superpowers/`; those are project history, not active deployment configuration.

- [ ] **Step 4: Create `PYTHONANYWHERE_DEPLOYMENT.md` with these exact operational sections**

The guide must include the following commands and WSGI configuration verbatim.

Repository setup in a PythonAnywhere Bash console:

```bash
cd ~
git clone https://github.com/mralehsas/ALBAZ-ASTEROID-ARCHIVE.git
cd ~/ALBAZ-ASTEROID-ARCHIVE
export ALBAZ_DATA_DIR="$HOME/.albaz-asteroid-data"
python -c "from database import initialize,seed_if_empty; initialize(); print('seeded=', seed_if_empty())"
python -c "from database import DB_PATH,counts; print(DB_PATH); print(counts())"
```

PythonAnywhere Web App WSGI configuration:

```python
import os
import sys
from pathlib import Path

repo = Path.home() / "ALBAZ-ASTEROID-ARCHIVE"
if str(repo) not in sys.path:
    sys.path.insert(0, str(repo))

os.environ["ALBAZ_DATA_DIR"] = str(Path.home() / ".albaz-asteroid-data")

from pythonanywhere_wsgi import application
```

Health verification after pressing **Reload** on the PythonAnywhere Web tab:

```text
https://<pythonanywhere-username>.pythonanywhere.com/api/health
```

Required health fields:

```json
{
  "status": "ok",
  "application": "Asteroid Archive",
  "version": "0.7.2",
  "database_ready": true
}
```

Manual full archive refresh from Bash console:

```bash
cd ~/ALBAZ-ASTEROID-ARCHIVE
export ALBAZ_DATA_DIR="$HOME/.albaz-asteroid-data"
python update_data.py --days 365 --distance-ld 10 --limit 2000 --fireball-limit 2000 --profiles 30
```

Generated-cache maintenance:

```bash
cd ~/ALBAZ-ASTEROID-ARCHIVE
export ALBAZ_DATA_DIR="$HOME/.albaz-asteroid-data"
python cache_maintenance.py --max-age-days 30
```

Code update procedure:

```bash
cd ~/ALBAZ-ASTEROID-ARCHIVE
git pull --ff-only origin main
```

Then press **Reload** in the PythonAnywhere Web tab. The data directory remains outside the repository checkout and is not touched by `git pull`.

Frontend binding after the real hostname is known:

```javascript
window.ALBAZ_WEB_CONFIG = Object.freeze({
  apiBaseUrl: 'https://<pythonanywhere-username>.pythonanywhere.com'
});
```

State explicitly that the exact real hostname replaces the example and that there is no trailing slash.

- [ ] **Step 5: Update the deployment test runner**

The final `main()` test list in `deployment_test.py` must be exactly:

```python
tests = [
    test_runtime_paths_default,
    test_runtime_paths_environment_override,
    test_api_core_response_contract,
    test_api_core_cors_policy,
    test_cloud_update_snapshot_contract,
    test_api_core_health_and_unknown_routes,
    test_api_core_proxy_and_horizons_are_transport_neutral,
    test_cloud_update_post_policy,
    test_server_bind_environment_defaults,
    test_cors_preflight_http,
    test_server_delegation_contract,
    test_local_http_adapter_uses_shared_core,
    test_frontend_backend_contract,
    test_pythonanywhere_wsgi_health_and_cors,
    test_pythonanywhere_wsgi_preflight_and_rejected_origin,
    test_pythonanywhere_wsgi_cloud_update_policy,
    test_pythonanywhere_wsgi_method_and_unknown_route_errors,
    test_cache_maintenance_deletes_only_stale_generated_files,
    test_pythonanywhere_deployment_contract,
]
```

- [ ] **Step 6: Run documentation/platform tests and scientific regression**

```bash
python -c "import deployment_test as t; t.test_pythonanywhere_deployment_contract(); print('PASS PythonAnywhere docs')"
python deployment_test.py
python self_test.py
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add PYTHONANYWHERE_DEPLOYMENT.md deployment_test.py
git add -u render.yaml RENDER_DEPLOYMENT.md
git commit -m "docs: replace Render with PythonAnywhere deployment"
```

---

### Task 7: Run the Complete Pre-Deployment Verification Gate

**Files:**
- Modify implementation files only if a verification failure identifies a real migration defect.

**Interfaces:**
- Produces a verified commit that is safe to deploy on PythonAnywhere and still safe for local Windows use.

- [ ] **Step 1: Compile every touched/runtime module**

```bash
python -m compileall -q api_core.py pythonanywhere_wsgi.py cache_maintenance.py runtime_paths.py database.py horizons_engine.py update_engine.py update_data.py jpl_client.py server.py self_test.py deployment_test.py
```

Expected: exit code `0`.

- [ ] **Step 2: Run deterministic scientific regression**

```bash
python self_test.py
```

Expected: all existing scientific/vector/Horizons/database assertions pass.

- [ ] **Step 3: Run deterministic migration regression**

```bash
python deployment_test.py
```

Expected: all 19 tests pass.

- [ ] **Step 4: Run an isolated PythonAnywhere-style storage smoke test**

Linux/macOS:

```bash
TMP_DATA="$(mktemp -d)"
ALBAZ_DATA_DIR="$TMP_DATA" python -c "import json; from database import initialize,seed_if_empty,DB_PATH,counts; initialize(); seed_if_empty(); print(json.dumps({'db':str(DB_PATH),'exists':DB_PATH.exists(),'counts':counts()}))"
```

Expected: `exists` is `true`, the database path is under the temporary directory, and bundled seed counts are nonzero where bundled data exists.

- [ ] **Step 5: Run local desktop HTTP smoke test**

Start:

```bash
python server.py --port 8872 --no-open
```

From a second terminal:

```bash
python -c "import json,urllib.request; p=json.load(urllib.request.urlopen('http://127.0.0.1:8872/api/health',timeout=5)); assert p['status']=='ok'; assert p['version']=='0.7.2'; assert p['runtime']['deployment']=='local'; print('PASS local 8872')"
```

Expected: `PASS local 8872`.

- [ ] **Step 6: Confirm no active Render deployment artifacts remain**

```bash
test ! -e render.yaml
test ! -e RENDER_DEPLOYMENT.md
```

Expected: both commands exit `0`.

- [ ] **Step 7: Record the verification commit**

If no implementation change was required, do not create an empty commit. If a verified defect was fixed through TDD, commit only that fix with its covering test.

---

### Task 8: Deploy on PythonAnywhere and Bind the Real HTTPS Origin to GitHub Pages

**Files:**
- Modify: `web-config.js` only after the real PythonAnywhere hostname is live and verified.
- No scientific Python file changes are allowed in this task unless the live deployment exposes a reproducible adapter defect that first receives a failing test.

**Interfaces:**
- Consumes the exact public origin `https://<actual-username>.pythonanywhere.com`.
- Produces live `GitHub Pages -> PythonAnywhere WSGI API -> NASA/JPL + SQLite` operation.

- [ ] **Step 1: Create the free PythonAnywhere account and clone the repository**

Follow `PYTHONANYWHERE_DEPLOYMENT.md` exactly. Select a Python version offered by PythonAnywhere that is `3.11` or newer.

- [ ] **Step 2: Initialize the persistent runtime database outside the repository checkout**

In Bash:

```bash
cd ~/ALBAZ-ASTEROID-ARCHIVE
export ALBAZ_DATA_DIR="$HOME/.albaz-asteroid-data"
python -c "from database import initialize,seed_if_empty,DB_PATH,counts; initialize(); seed_if_empty(); print(DB_PATH); print(counts())"
```

Required: printed `DB_PATH` is under `~/.albaz-asteroid-data/`.

- [ ] **Step 3: Configure the Web App WSGI file and reload**

Use exactly:

```python
import os
import sys
from pathlib import Path

repo = Path.home() / "ALBAZ-ASTEROID-ARCHIVE"
if str(repo) not in sys.path:
    sys.path.insert(0, str(repo))

os.environ["ALBAZ_DATA_DIR"] = str(Path.home() / ".albaz-asteroid-data")

from pythonanywhere_wsgi import application
```

Press **Reload** in the PythonAnywhere Web tab.

- [ ] **Step 4: Verify public health before changing GitHub Pages**

Open:

```text
https://<actual-username>.pythonanywhere.com/api/health
```

Required values:

```json
{
  "status": "ok",
  "application": "Asteroid Archive",
  "version": "0.7.2",
  "database_ready": true
}
```

Also require:

```text
runtime.deployment = pythonanywhere
runtime.external_data_dir = true
```

Do not modify `web-config.js` until this health check is correct.

- [ ] **Step 5: Verify restricted CORS on the public backend**

Approved-origin request:

```bash
curl -i -H 'Origin: https://mralehsas.github.io' 'https://<actual-username>.pythonanywhere.com/api/health'
```

Required header:

```text
Access-Control-Allow-Origin: https://mralehsas.github.io
```

Rejected-origin request:

```bash
curl -i -H 'Origin: https://evil.example' 'https://<actual-username>.pythonanywhere.com/api/health'
```

Required: no `Access-Control-Allow-Origin` header.

- [ ] **Step 6: Write the exact live origin into `web-config.js`**

Replace the current empty value with the exact verified origin, without a trailing slash:

```javascript
window.ALBAZ_WEB_CONFIG = Object.freeze({
  apiBaseUrl: 'https://<actual-username>.pythonanywhere.com'
});
```

Only the hostname token is substituted with the actual account hostname; change no other line.

- [ ] **Step 7: Commit the production origin**

```bash
git add web-config.js
git commit -m "config: connect Pages to PythonAnywhere backend"
```

- [ ] **Step 8: Verify GitHub Pages transport state**

Open:

```text
https://mralehsas.github.io/ALBAZ-ASTEROID-ARCHIVE/?backend=pythonanywhere
```

Required: status pill reads `Backend Online`, database state is ready, and no local `server.py` process is needed.

- [ ] **Step 9: Verify the complete public service matrix**

Verify each independently through the deployed backend/frontend:

```text
/api/cad
/api/fireball
/api/sentry
/api/sbdb
/api/sbdb-query
/api/horizons-lookup
/api/horizons/track
/api/local/approaches
/api/local/fireballs
/api/local/sentry
/api/local/objects
/api/local/meteorites
/api/local/impact-structures
/api/object
/api/connectivity/test
/api/update/status
/api/update/history
```

Required behavior: valid scientific responses remain distinct from `4xx/5xx` network/request failures.

- [ ] **Step 10: Verify cloud update policy and console update path**

Browser/API call to:

```text
POST /api/update/start
```

must return `503` with `reason=console_administered`.

Then run one console refresh:

```bash
cd ~/ALBAZ-ASTEROID-ARCHIVE
export ALBAZ_DATA_DIR="$HOME/.albaz-asteroid-data"
python update_data.py --days 365 --distance-ld 10 --limit 2000 --fireball-limit 2000 --profiles 30
```

Required: the command terminates with success and `/api/update/history` shows the completed CLI-triggered run.

- [ ] **Step 11: Run final regressions after the production-origin commit**

```bash
python self_test.py
python deployment_test.py
```

Expected: both remain green.

---

## Final Acceptance Gate

```text
[PASS] scientific engine remains v0.7.2
[PASS] self_test.py scientific regression
[PASS] deployment_test.py migration regression (19 tests)
[PASS] local Windows server still serves 127.0.0.1:8872
[PASS] shared api_core.py owns read-only API behavior
[PASS] PythonAnywhere WSGI /api/health is public and healthy
[PASS] production CORS allows https://mralehsas.github.io only (plus localhost development origins)
[PASS] PythonAnywhere runtime SQLite lives under $HOME/.albaz-asteroid-data
[PASS] bundled bootstrap.json and earth_history.json still seed a fresh external database
[PASS] cloud POST /api/update/start returns structured 503 console_administered
[PASS] console update_data.py refresh succeeds and appears in update history
[PASS] cache_maintenance.py deletes only stale generated cache files
[PASS] render.yaml and RENDER_DEPLOYMENT.md are absent
[PASS] real PythonAnywhere HTTPS origin is stored in web-config.js
[PASS] GitHub Pages displays Backend Online without local server.py
[PASS] CAD / Fireball / Sentry / SBDB / Horizons work through PythonAnywhere
[PASS] SQLite datasets / meteorites / impact structures work through PythonAnywhere
[PASS] no scientific formula, schema semantics, missing-data rule, or API interpretation changed
```
