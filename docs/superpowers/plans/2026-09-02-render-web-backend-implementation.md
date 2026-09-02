# ALBAZ Asteroid Archive Render Web Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing GitHub Pages application use a Render-hosted Python backend for NASA/JPL, Horizons, Sentry, SBDB, SQLite, cache, and update operations while preserving local Windows behavior and the frozen v0.7.2 scientific core.

**Architecture:** Keep GitHub Pages as the public front end and introduce one configurable HTTPS API origin for the deployed Render service. Keep the existing Python server and SQLite data model, but make filesystem paths, bind host/port, CORS, and browser endpoint resolution deployment-aware without changing scientific calculations.

**Tech Stack:** Python 3.11+, standard-library `http.server`, SQLite, vanilla JavaScript/HTML, GitHub Pages, Render Web Service, Render Blueprint YAML.

**Spec:** `docs/superpowers/specs/2026-09-02-render-web-backend-design.md`

## Global Constraints

- Scientific core version remains `0.7.2`; no astronomical formula or interpretation changes.
- Public application URL remains `https://mralehsas.github.io/ALBAZ-ASTEROID-ARCHIVE/`.
- Production CORS origin is exactly `https://mralehsas.github.io`; do not use wildcard CORS.
- Local Windows operation must continue to work on `127.0.0.1:8872` or the existing fallback-port behavior.
- `ALBAZ_DATA_DIR` controls runtime-writable SQLite/cache storage when set; otherwise the existing repository-local `data/` path remains the default.
- Missing data must remain unavailable; network/deployment failures must not be represented as scientific success.
- No new third-party Python package is required unless a test proves the standard library is insufficient.
- A free Render Web Service is acceptable for initial functional deployment, but its filesystem is ephemeral and cannot provide persistent SQLite updates; persistence requires a paid service with a persistent disk.

---

## File Structure Locked for This Change

- Create `runtime_paths.py` — one source of truth for `ALBAZ_DATA_DIR`, SQLite path, live-cache path, and Horizons-cache directory.
- Modify `database.py` — consume `runtime_paths.DB_PATH`; schema and queries remain unchanged.
- Modify `horizons_engine.py` — consume `runtime_paths.HORIZONS_CACHE_DIR`; vector calculations remain unchanged.
- Modify `update_engine.py` — consume `runtime_paths.LIVE_CACHE_PATH`; update semantics remain unchanged.
- Modify `server.py` — add deployment-aware defaults, CORS/preflight handling, and explicit runtime metadata in health output.
- Create `web-config.js` — one replaceable production API-origin setting.
- Modify `index.html` — load `web-config.js`, route API requests through one resolver, enable remote health checks, and display backend/local/offline state.
- Create `render.yaml` — Render Web Service blueprint.
- Create `deployment_test.py` — deterministic deployment/integration tests using only the Python standard library.
- Modify `self_test.py` — keep existing scientific checks working with the current single-file Pages build where JavaScript is embedded in `index.html`.
- Create `RENDER_DEPLOYMENT.md` — exact Render setup, free-plan limitations, paid-disk upgrade, and final URL handoff steps.

---

### Task 1: Restore the Test Baseline for the Current Standalone Pages Build

**Files:**
- Modify: `self_test.py` in `test_versions_and_assets()`
- Test: `self_test.py`

**Interfaces:**
- Consumes: existing `ROOT`, existing scientific tests, current standalone `index.html`.
- Produces: a baseline `self_test.py` that validates either modular `js/app.js` when present or the embedded JavaScript in `index.html` when the repository is in standalone Pages form.

- [ ] **Step 1: Run the current baseline test and record the failure**

Run:

```bash
python self_test.py
```

Expected before the fix: the scientific tests run until `test_versions_and_assets()`, then fail when `ROOT / "js" / "app.js"` is absent in the current standalone repository layout.

- [ ] **Step 2: Change only the application-source lookup in `test_versions_and_assets()`**

Replace:

```python
index = (ROOT / "index.html").read_text(encoding="utf-8")
app = (ROOT / "js" / "app.js").read_text(encoding="utf-8")
```

with:

```python
index = (ROOT / "index.html").read_text(encoding="utf-8")
app_path = ROOT / "js" / "app.js"
app = app_path.read_text(encoding="utf-8") if app_path.exists() else index
```

Do not change the assertions that validate Horizons versions, DOM IDs, sequential loading, timeout policy, or smart-map functions.

- [ ] **Step 3: Re-run the baseline**

Run:

```bash
python self_test.py
```

Expected: all existing scientific tests report `PASS`, including vector parsing, Horizons pipeline, lookup ambiguity, SQLite backup/restore, and versions/assets.

- [ ] **Step 4: Commit**

```bash
git add self_test.py
git commit -m "test: support standalone Pages build"
```

---

### Task 2: Centralize Runtime-Writable Paths Without Changing Scientific Data Semantics

**Files:**
- Create: `runtime_paths.py`
- Modify: `database.py` at the `ROOT` / `DB_PATH` definitions
- Modify: `horizons_engine.py` at the `ROOT` / `CACHE_DIR` definitions
- Modify: `update_engine.py` at the `ROOT` / `CACHE_PATH` definitions
- Create/extend: `deployment_test.py`

**Interfaces:**
- Produces: `ROOT: Path`, `DATA_DIR: Path`, `DB_PATH: Path`, `LIVE_CACHE_PATH: Path`, `HORIZONS_CACHE_DIR: Path` from `runtime_paths.py`.
- Consumed by: `database.py`, `horizons_engine.py`, `update_engine.py`, later health reporting.

- [ ] **Step 1: Write the failing path-resolution tests in `deployment_test.py`**

Create the file with these helpers and tests:

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def python_probe(code: str, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return proc.stdout.strip()


def test_runtime_paths_default() -> None:
    env = os.environ.copy()
    env.pop("ALBAZ_DATA_DIR", None)
    output = python_probe(
        "import json, runtime_paths as r; print(json.dumps({'data':str(r.DATA_DIR),'db':str(r.DB_PATH)}))",
        env,
    )
    payload = json.loads(output)
    assert_true(Path(payload["data"]) == ROOT / "data", "Default data directory changed")
    assert_true(Path(payload["db"]) == ROOT / "data" / "asteroid_archive.db", "Default DB path changed")


def test_runtime_paths_environment_override() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        env = os.environ.copy()
        env["ALBAZ_DATA_DIR"] = tmp
        output = python_probe(
            "import json, runtime_paths as r; print(json.dumps({'data':str(r.DATA_DIR),'db':str(r.DB_PATH),'live':str(r.LIVE_CACHE_PATH),'h':str(r.HORIZONS_CACHE_DIR)}))",
            env,
        )
        payload = json.loads(output)
        base = Path(tmp).resolve()
        assert_true(Path(payload["data"]) == base, "ALBAZ_DATA_DIR was not honored")
        assert_true(Path(payload["db"]) == base / "asteroid_archive.db", "DB did not move with runtime data directory")
        assert_true(Path(payload["live"]) == base / "live-cache.js", "Live cache did not move with runtime data directory")
        assert_true(Path(payload["h"]) == base / "horizons_cache", "Horizons cache did not move with runtime data directory")
```

- [ ] **Step 2: Run the new tests and verify they fail because `runtime_paths` does not exist**

Run:

```bash
python -c "import deployment_test as t; t.test_runtime_paths_default(); t.test_runtime_paths_environment_override()"
```

Expected: failure with `ModuleNotFoundError: No module named 'runtime_paths'`.

- [ ] **Step 3: Create `runtime_paths.py`**

```python
#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_raw_data_dir = str(os.environ.get("ALBAZ_DATA_DIR") or "").strip()
DATA_DIR = Path(_raw_data_dir).expanduser().resolve() if _raw_data_dir else ROOT / "data"
DB_PATH = DATA_DIR / "asteroid_archive.db"
LIVE_CACHE_PATH = DATA_DIR / "live-cache.js"
HORIZONS_CACHE_DIR = DATA_DIR / "horizons_cache"
```

- [ ] **Step 4: Point the three existing modules at the centralized paths**

In `database.py` replace the local `ROOT`/`DB_PATH` assignment with:

```python
from runtime_paths import DB_PATH
```

Keep all existing functions and default `path: Path = DB_PATH` parameters unchanged.

In `horizons_engine.py` replace the local `CACHE_DIR` assignment with:

```python
from runtime_paths import HORIZONS_CACHE_DIR
CACHE_DIR: Final[Path] = HORIZONS_CACHE_DIR
```

In `update_engine.py` replace the local `CACHE_PATH` assignment with:

```python
from runtime_paths import LIVE_CACHE_PATH
CACHE_PATH: Final[Path] = LIVE_CACHE_PATH
```

Do not change `VERSION`, JPL URLs, cache TTL, vector calculations, database schema, update order, or rollback behavior.

- [ ] **Step 5: Run path tests and the complete scientific baseline**

Run:

```bash
python -c "import deployment_test as t; t.test_runtime_paths_default(); t.test_runtime_paths_environment_override(); print('PASS paths')"
python self_test.py
```

Expected: both commands pass.

- [ ] **Step 6: Commit**

```bash
git add runtime_paths.py database.py horizons_engine.py update_engine.py deployment_test.py
git commit -m "feat: make runtime data paths deployment aware"
```

---

### Task 3: Make `server.py` Render-Compatible and Add Restricted CORS

**Files:**
- Modify: `server.py` in imports, CORS helpers, `ArchiveHandler.end_headers()`, new `ArchiveHandler.do_OPTIONS()`, `_serve_health()`, and `main()` argument defaults
- Extend: `deployment_test.py`

**Interfaces:**
- Produces: `allowed_cors_origin(origin: str | None) -> str | None`, `environment_default_host() -> str`, `environment_default_port() -> int`.
- HTTP contract: approved Pages origin receives CORS headers; arbitrary origins do not; `OPTIONS` returns `204`; `/api/health` remains JSON `200` and reports runtime storage mode/path.

- [ ] **Step 1: Add failing pure-function tests**

Append to `deployment_test.py`:

```python
def test_cors_origin_policy() -> None:
    import server
    assert_true(server.allowed_cors_origin("https://mralehsas.github.io") == "https://mralehsas.github.io", "Pages origin was rejected")
    assert_true(server.allowed_cors_origin("http://127.0.0.1:8872") == "http://127.0.0.1:8872", "Localhost development origin was rejected")
    assert_true(server.allowed_cors_origin("http://localhost:8872") == "http://localhost:8872", "localhost development origin was rejected")
    assert_true(server.allowed_cors_origin("https://evil.example") is None, "Unapproved origin received CORS access")
    assert_true(server.allowed_cors_origin(None) is None, "Missing Origin must not emit allow-origin")


def test_render_bind_defaults() -> None:
    env = os.environ.copy()
    env["HOST"] = "0.0.0.0"
    env["PORT"] = "12345"
    output = python_probe(
        "import json, server; print(json.dumps({'host':server.environment_default_host(),'port':server.environment_default_port()}))",
        env,
    )
    payload = json.loads(output)
    assert_true(payload == {"host": "0.0.0.0", "port": 12345}, "Render HOST/PORT defaults were not honored")
```

- [ ] **Step 2: Run and verify failure**

```bash
python -c "import deployment_test as t; t.test_cors_origin_policy(); t.test_render_bind_defaults()"
```

Expected: failure because the new helper functions do not exist.

- [ ] **Step 3: Implement environment defaults and CORS helpers in `server.py`**

Add `import os` and define near the constants:

```python
PAGES_ORIGIN: Final[str] = "https://mralehsas.github.io"


def environment_default_host() -> str:
    return str(os.environ.get("HOST") or "127.0.0.1").strip() or "127.0.0.1"


def environment_default_port() -> int:
    raw = str(os.environ.get("PORT") or "8872").strip()
    try:
        port = int(raw)
    except ValueError:
        return 8872
    return port if 1 <= port <= 65535 else 8872


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
```

- [ ] **Step 4: Add restricted response headers and preflight handling**

In `ArchiveHandler.end_headers()` add before `super().end_headers()`:

```python
origin = allowed_cors_origin(self.headers.get("Origin"))
if origin:
    self.send_header("Access-Control-Allow-Origin", origin)
    self.send_header("Vary", "Origin")
    self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    self.send_header("Access-Control-Allow-Headers", "Content-Type")
```

Add:

```python
def do_OPTIONS(self) -> None:  # noqa: N802
    origin = allowed_cors_origin(self.headers.get("Origin"))
    if not origin:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()
        return
    self.send_response(HTTPStatus.NO_CONTENT)
    self.end_headers()
```

Do not add `Access-Control-Allow-Credentials` and do not use `*`.

- [ ] **Step 5: Make `main()` defaults environment-aware while preserving CLI overrides**

Use:

```python
parser.add_argument("--host", default=environment_default_host(), help="Bind host")
parser.add_argument("--port", type=int, default=environment_default_port(), help="Bind port")
```

Retain the existing 21-port fallback loop for local desktop use. When Render supplies an explicit `$PORT`, the blueprint start command also passes that exact port; if binding fails, deployment must fail visibly rather than silently selecting an externally unrouted port. Implement this by disabling fallback when `PORT` is present in the environment:

```python
render_managed_port = bool(str(os.environ.get("PORT") or "").strip())
port_candidates = [requested_port] if render_managed_port else range(requested_port, requested_port + 21)
```

- [ ] **Step 6: Extend `/api/health` with deployment metadata only**

Add fields without removing existing fields:

```python
"runtime": {
    "host_default": environment_default_host(),
    "port_default": environment_default_port(),
    "data_dir": str(DB_PATH.parent),
    "storage": "configured" if os.environ.get("ALBAZ_DATA_DIR") else "repository-local",
},
```

This is infrastructure metadata only; do not alter counts, metadata, update state, or scientific payloads.

- [ ] **Step 7: Add a real HTTP CORS integration test**

Append to `deployment_test.py`:

```python
def test_cors_preflight_http() -> None:
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
        conn.request("OPTIONS", "/api/update/start", headers={
            "Origin": "https://mralehsas.github.io",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        })
        response = conn.getresponse()
        response.read()
        assert_true(response.status == 204, "CORS preflight did not return 204")
        assert_true(response.getheader("Access-Control-Allow-Origin") == "https://mralehsas.github.io", "Approved origin missing")
        conn.close()

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("OPTIONS", "/api/update/start", headers={"Origin": "https://evil.example"})
        response = conn.getresponse()
        response.read()
        assert_true(response.getheader("Access-Control-Allow-Origin") is None, "Unapproved origin was allowed")
        conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
```

- [ ] **Step 8: Run deployment and scientific tests**

```bash
python -c "import deployment_test as t; t.test_cors_origin_policy(); t.test_render_bind_defaults(); t.test_cors_preflight_http(); print('PASS server deployment')"
python self_test.py
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add server.py deployment_test.py
git commit -m "feat: add Render binding and restricted CORS"
```

---

### Task 4: Add One Front-End API-Origin Configuration Layer

**Files:**
- Create: `web-config.js`
- Modify: `index.html` around the script loading boundary, `isLocalServer()`, `endpoint()`, `checkHealth()`, and `updateConnectionUi()`
- Extend: `deployment_test.py`

**Interfaces:**
- Consumes: `window.ALBAZ_WEB_CONFIG.apiBaseUrl`.
- Produces: `apiBaseUrl() -> string`, `endpoint(kind, params) -> string`, and browser status modes `backend`, `local`, `offline`.
- All API route names continue to map to the existing `/api/...` server contract.

- [ ] **Step 1: Add failing static contract tests for the browser integration**

Append:

```python
def test_frontend_backend_contract() -> None:
    index = (ROOT / "index.html").read_text(encoding="utf-8")
    config = (ROOT / "web-config.js").read_text(encoding="utf-8")
    assert_true('src="web-config.js"' in index or "src='./web-config.js'" in index or 'src="./web-config.js"' in index, "web-config.js is not loaded")
    assert_true("ALBAZ_WEB_CONFIG" in config, "Web config object missing")
    assert_true("function apiBaseUrl(" in index, "API base resolver missing")
    assert_true("apiBaseUrl()" in index, "Endpoint resolver does not consume API base")
    assert_true("if (!isLocalServer()) return false;" not in index, "Remote health check is still disabled")
    assert_true("Backend Online" in index and "Backend Offline" in index and "Local Desktop Mode" in index, "Backend mode labels missing")
```

- [ ] **Step 2: Run and verify failure**

```bash
python -c "import deployment_test as t; t.test_frontend_backend_contract()"
```

Expected: failure because `web-config.js` and the resolver do not exist.

- [ ] **Step 3: Create `web-config.js` with one intentionally empty deployment value**

```javascript
window.ALBAZ_WEB_CONFIG = Object.freeze({
  apiBaseUrl: ''
});
```

An empty value is the defined pre-deployment state, not a hidden fallback URL.

- [ ] **Step 4: Load `web-config.js` before the embedded application script**

In `index.html`, insert this before the embedded application JavaScript executes:

```html
<script src="./web-config.js"></script>
```

Keep the current embedded CSS, embedded application JavaScript, embedded icon, and embedded map asset intact.

- [ ] **Step 5: Replace the current mixed direct-NASA/relative endpoint selection with one API route table**

Use this structure in the embedded JavaScript:

```javascript
function isLocalServer() {
  return ['127.0.0.1', 'localhost'].includes(location.hostname) && ['http:', 'https:'].includes(location.protocol);
}

function apiBaseUrl() {
  if (isLocalServer()) return location.origin;
  const raw = String(window.ALBAZ_WEB_CONFIG?.apiBaseUrl || '').trim();
  return raw.replace(/\/+$/, '');
}

function endpoint(kind, params = {}) {
  const routes = {
    cad: '/api/cad',
    fireball: '/api/fireball',
    sbdb: '/api/sbdb',
    sentry: '/api/sentry',
    health: '/api/health',
    localApproaches: '/api/local/approaches',
    localFireballs: '/api/local/fireballs',
    localSentry: '/api/local/sentry',
    localMeteorites: '/api/local/meteorites',
    localImpacts: '/api/local/impact-structures',
    object: '/api/object',
    updateStatus: '/api/update/status',
    updateHistory: '/api/update/history',
    updateStart: '/api/update/start',
    updateCancel: '/api/update/cancel',
    connectivity: '/api/connectivity/test',
    horizonsTrack: '/api/horizons/track'
  };
  const route = routes[kind];
  if (!route) throw new Error(`Unknown API endpoint: ${kind}`);
  const apiBase = apiBaseUrl();
  const base = apiBase ? `${apiBase}${route}` : route;
  const url = new URL(base, location.href);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value));
  });
  return url.toString();
}
```

This intentionally routes CAD, Fireball, SBDB, and Sentry through the Python backend in both local and deployed modes.

- [ ] **Step 6: Allow `checkHealth()` to test Render as well as localhost**

Remove the current early return:

```javascript
if (!isLocalServer()) return false;
```

At the start of `checkHealth()`, use:

```javascript
const base = apiBaseUrl();
if (!isLocalServer() && !base) {
  state.backendReachable = false;
  state.databaseReady = false;
  updateConnectionUi();
  return false;
}
```

On successful health fetch set:

```javascript
state.backendReachable = true;
```

In the catch branch set:

```javascript
state.backendReachable = false;
state.databaseReady = false;
```

Add `backendReachable: false` to the initial `state` object.

- [ ] **Step 7: Make the top connection pill distinguish the three deployment states**

In `updateConnectionUi()` derive:

```javascript
const backendMode = isLocalServer()
  ? 'local'
  : state.backendReachable
    ? 'backend'
    : 'offline';
```

Set the visible label to exactly one of:

```javascript
const backendLabel = backendMode === 'local'
  ? 'Local Desktop Mode'
  : backendMode === 'backend'
    ? 'Backend Online'
    : 'Backend Offline';
```

Use online styling for `local` and `backend`, offline styling only for `offline`. Keep the existing source-mode and database-state displays below it; this new label represents backend connectivity, not scientific data provenance.

- [ ] **Step 8: Run static front-end test and full baseline**

```bash
python -c "import deployment_test as t; t.test_frontend_backend_contract(); print('PASS frontend contract')"
python self_test.py
```

If Node.js is available, also extract/check the embedded application script using the repository's existing validation workflow or run the equivalent `node --check` on the extracted script. Expected: JavaScript syntax passes.

- [ ] **Step 9: Commit**

```bash
git add web-config.js index.html deployment_test.py
git commit -m "feat: route Pages through configurable backend"
```

---

### Task 5: Add the Render Blueprint and Deployment Documentation

**Files:**
- Create: `render.yaml`
- Create: `RENDER_DEPLOYMENT.md`
- Extend: `deployment_test.py`

**Interfaces:**
- Produces: Render service definition `albaz-asteroid-api`, health check `/api/health`, Python start command using Render's assigned `$PORT`.
- Does not require a persistent disk for the initial free deployment; documentation defines the paid-disk upgrade path.

- [ ] **Step 1: Add a failing blueprint contract test**

Append:

```python
def test_render_blueprint_contract() -> None:
    text = (ROOT / "render.yaml").read_text(encoding="utf-8")
    required = [
        "type: web",
        "name: albaz-asteroid-api",
        "runtime: python",
        "healthCheckPath: /api/health",
        "python server.py --host 0.0.0.0 --port $PORT --no-open",
    ]
    for token in required:
        assert_true(token in text, f"Render blueprint missing: {token}")
    assert_true("disk:" not in text, "Free-first blueprint must not require a paid persistent disk")
```

- [ ] **Step 2: Run and verify failure**

```bash
python -c "import deployment_test as t; t.test_render_blueprint_contract()"
```

Expected: failure because `render.yaml` does not exist.

- [ ] **Step 3: Create `render.yaml`**

```yaml
services:
  - type: web
    name: albaz-asteroid-api
    runtime: python
    plan: free
    buildCommand: pip install -r requirements.txt
    startCommand: python server.py --host 0.0.0.0 --port $PORT --no-open
    healthCheckPath: /api/health
    autoDeployTrigger: commit
```

Do not set `ALBAZ_DATA_DIR` in the free-first blueprint. The default repository-local runtime data directory is intentionally ephemeral on the free service.

- [ ] **Step 4: Create `RENDER_DEPLOYMENT.md` with exact operational steps**

Document these facts and actions:

```text
1. Open Render Dashboard and choose New -> Blueprint.
2. Connect mralehsas/ALBAZ-ASTEROID-ARCHIVE.
3. Use render.yaml from the repository root.
4. Confirm the service name albaz-asteroid-api and Free plan for initial validation.
5. Wait until /api/health passes and copy the exact https://...onrender.com service URL.
6. Update web-config.js so apiBaseUrl contains that exact HTTPS origin, with no trailing slash.
7. Commit the config change and wait for GitHub Pages deployment.
8. Open the GitHub Pages URL with a cache-busting query and verify Backend Online.
```

Also state explicitly:

```text
Free Render web services use an ephemeral filesystem. SQLite changes and generated caches can disappear on restart, redeploy, or idle spin-down. This mode is suitable for functional validation but not durable archival updates.

For durable SQLite storage, upgrade the Web Service to a paid compute plan, attach a persistent disk mounted at /var/data, and set ALBAZ_DATA_DIR=/var/data. Only files under /var/data are then persistent.
```

- [ ] **Step 5: Run blueprint and baseline tests**

```bash
python -c "import deployment_test as t; t.test_render_blueprint_contract(); print('PASS render blueprint')"
python self_test.py
```

Expected: both pass.

- [ ] **Step 6: Commit**

```bash
git add render.yaml RENDER_DEPLOYMENT.md deployment_test.py
git commit -m "docs: add Render deployment blueprint"
```

---

### Task 6: Run the Complete Offline/Local Verification Gate Before Creating the Render Service

**Files:**
- Modify only if a test exposes a deployment defect: files from Tasks 1-5
- Test: `self_test.py`, `deployment_test.py`

**Interfaces:**
- Produces: a repository state that is safe to deploy to Render without requiring live NASA/JPL success for deterministic tests.

- [ ] **Step 1: Add `main()` to `deployment_test.py`**

```python
def main() -> int:
    tests = [
        test_runtime_paths_default,
        test_runtime_paths_environment_override,
        test_cors_origin_policy,
        test_render_bind_defaults,
        test_cors_preflight_http,
        test_frontend_backend_contract,
        test_render_blueprint_contract,
    ]
    report = []
    for test in tests:
        test()
        report.append({"test": test.__name__, "status": "PASS"})
        print(f"PASS  {test.__name__}")
    print(json.dumps({"status": "PASS", "count": len(report), "tests": report}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run Python compilation**

```bash
python -m compileall -q server.py database.py runtime_paths.py horizons_engine.py update_engine.py update_data.py jpl_client.py self_test.py deployment_test.py
```

Expected: exit code `0`.

- [ ] **Step 3: Run deterministic scientific regression**

```bash
python self_test.py
```

Expected: all scientific tests `PASS`.

- [ ] **Step 4: Run deterministic deployment regression**

```bash
python deployment_test.py
```

Expected: all deployment tests `PASS`.

- [ ] **Step 5: Run a Render-like local smoke test with isolated storage**

Linux/macOS shell:

```bash
TMP_DATA="$(mktemp -d)"
HOST=0.0.0.0 PORT=8899 ALBAZ_DATA_DIR="$TMP_DATA" python server.py --no-open &
SERVER_PID=$!
sleep 2
python -c "import json,urllib.request; p=json.load(urllib.request.urlopen('http://127.0.0.1:8899/api/health',timeout=5)); assert p['status']=='ok'; assert p['database_ready'] is True; print('PASS health', p['runtime'])"
kill "$SERVER_PID"
```

Windows PowerShell equivalent:

```powershell
$env:HOST='0.0.0.0'
$env:PORT='8899'
$env:ALBAZ_DATA_DIR=Join-Path $env:TEMP 'albaz-render-smoke'
$job = Start-Job { python server.py --no-open }
Start-Sleep -Seconds 2
$r = Invoke-RestMethod http://127.0.0.1:8899/api/health
if ($r.status -ne 'ok' -or -not $r.database_ready) { throw 'Health check failed' }
Stop-Job $job
Remove-Job $job
```

Expected: health reports `ok`, `database_ready=true`, and the configured data directory.

- [ ] **Step 6: Re-run local desktop mode without Render variables**

```bash
python server.py --port 8872 --no-open
```

From another terminal:

```bash
python -c "import json,urllib.request; p=json.load(urllib.request.urlopen('http://127.0.0.1:8872/api/health',timeout=5)); assert p['status']=='ok'; print('PASS local')"
```

Expected: local mode still works on `127.0.0.1:8872`.

- [ ] **Step 7: Commit the verification harness**

```bash
git add deployment_test.py
git commit -m "test: add web deployment verification gate"
```

---

### Task 7: Create the Render Service and Bind the Final URL to GitHub Pages

**Files:**
- Modify: `web-config.js` after Render supplies the production URL
- No scientific Python code changes in this task

**Interfaces:**
- Consumes: the actual Render service origin created from `render.yaml`.
- Produces: live Pages-to-Render HTTPS connection.

- [ ] **Step 1: Create the Render Blueprint service**

In Render Dashboard choose **New -> Blueprint**, connect `mralehsas/ALBAZ-ASTEROID-ARCHIVE`, and apply the repository-root `render.yaml`.

Expected: service `albaz-asteroid-api` reaches deployed/healthy state. A free service can take roughly a minute to wake after idle; this is a platform behavior, not a scientific failure.

- [ ] **Step 2: Verify Render health before changing Pages**

Open the service's exact HTTPS origin plus `/api/health`.

Expected JSON fields include:

```json
{
  "status": "ok",
  "application": "Asteroid Archive",
  "version": "0.7.2",
  "database_ready": true
}
```

Do not continue if the Render health endpoint is not healthy.

- [ ] **Step 3: Put the exact Render origin into `web-config.js`**

Change only the value:

```javascript
window.ALBAZ_WEB_CONFIG = Object.freeze({
  apiBaseUrl: 'THE_EXACT_HTTPS_ORIGIN_COPIED_FROM_RENDER'
});
```

At execution time, replace the quoted value with the exact Render-provided origin. Keep no trailing slash.

- [ ] **Step 4: Commit the production API origin**

```bash
git add web-config.js
git commit -m "config: connect Pages to Render backend"
```

- [ ] **Step 5: Wait for GitHub Pages deployment and verify the public application**

Open:

```text
https://mralehsas.github.io/ALBAZ-ASTEROID-ARCHIVE/?backend=render
```

Expected: top status displays `Backend Online`, database state is ready, and the page is no longer dependent on a desktop `server.py` process.

- [ ] **Step 6: Verify backend CORS from the browser path**

Use the browser application to load data. If DevTools is used, a request to the Render `/api/health` response must include:

```text
Access-Control-Allow-Origin: https://mralehsas.github.io
```

An arbitrary unrelated origin must not receive this header.

- [ ] **Step 7: Verify the functional service matrix through Pages**

From the public Pages UI verify, one at a time:

```text
CAD close approaches
Fireball data
Sentry data
SBDB object lookup
Horizons Lookup
Horizons track/vectors
Local SQLite-backed approaches/fireballs/sentry/object records
Meteorite register
Impact structures
Connectivity diagnostics
```

For each function, a network error must remain visibly distinct from a valid scientific result.

- [ ] **Step 8: Verify update behavior and document free-storage status**

On a free Render service, run an update only as a functional test and confirm `/api/update/status` completes. Record that database/cache writes are ephemeral and can disappear on spin-down/restart/redeploy.

For durable production updates, perform the paid-storage upgrade exactly as documented in `RENDER_DEPLOYMENT.md`: attach a persistent disk at `/var/data` and set `ALBAZ_DATA_DIR=/var/data`.

- [ ] **Step 9: Final regression**

After the Pages config commit:

```bash
python self_test.py
python deployment_test.py
```

Expected: both remain fully green.

---

## Final Acceptance Gate

The implementation is complete only when all of the following are true:

```text
[PASS] self_test.py scientific regression
[PASS] deployment_test.py infrastructure regression
[PASS] local Windows server mode
[PASS] Render /api/health
[PASS] restricted CORS from GitHub Pages
[PASS] Pages Backend Online state
[PASS] CAD / Fireball / Sentry / SBDB through Render
[PASS] Horizons Lookup and track through Render
[PASS] SQLite-backed datasets through Render
[PASS] free filesystem explicitly marked ephemeral OR paid persistent disk configured
[PASS] no scientific formula, interpretation, schema semantics, or v0.7.2 outputs changed
```
