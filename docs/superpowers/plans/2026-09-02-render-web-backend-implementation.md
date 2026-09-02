# ALBAZ Asteroid Archive Render Web Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing GitHub Pages application use a Render-hosted Python backend for NASA/JPL, Horizons, Sentry, SBDB, SQLite, cache, and update operations while preserving local Windows behavior and the frozen v0.7.2 scientific core.

**Architecture:** GitHub Pages remains the public front end. A Render Web Service runs the existing Python API and acts as the only browser-facing gateway to NASA/JPL services and SQLite-backed data. Runtime-writable storage is separated from bundled reference data so a paid persistent disk can be enabled later without changing scientific logic.

**Tech Stack:** Python 3.11+, Python standard library `http.server`, SQLite, vanilla HTML/JavaScript, GitHub Pages, Render Web Service, Render Blueprint YAML.

**Spec:** `docs/superpowers/specs/2026-09-02-render-web-backend-design.md`

## Global Constraints

- Scientific core version remains exactly `0.7.2`.
- No astronomical formula, Horizons interpretation, Sentry semantics, database schema semantics, or missing-data policy changes.
- Public application URL remains `https://mralehsas.github.io/ALBAZ-ASTEROID-ARCHIVE/`.
- Production CORS origin is exactly `https://mralehsas.github.io`; wildcard CORS is forbidden.
- Local Windows mode remains supported on `127.0.0.1:8872` with the existing local fallback-port behavior.
- `ALBAZ_DATA_DIR` controls writable SQLite/cache state when set; otherwise writable state remains under repository-local `data/`.
- Bundled reference inputs `data/bootstrap.json` and `data/earth_history.json` always remain read from the repository bundle, even when writable state is redirected to another directory.
- A free Render Web Service is valid for functional deployment but its filesystem is ephemeral. Durable SQLite updates require a paid service with a persistent disk.
- No third-party Python package is introduced unless standard-library tests prove it necessary.

---

## File Map

- Create `runtime_paths.py` — central bundle/writable path definitions.
- Modify `database.py` — use the runtime database path while preserving bundled seed-source paths.
- Modify `horizons_engine.py` — move generated Horizons cache to the runtime data directory.
- Modify `update_engine.py` — move generated `live-cache.js` to the runtime data directory.
- Modify `server.py` — Render host/port defaults, restricted CORS, preflight, runtime health metadata.
- Create `web-config.js` — one replaceable API-origin setting for GitHub Pages.
- Modify `index.html` — one backend resolver, Render health check, backend/local/offline status.
- Modify `self_test.py` — support the current standalone Pages layout where application JavaScript is embedded in `index.html`.
- Create `deployment_test.py` — deterministic infrastructure tests.
- Create `render.yaml` — free-first Render Blueprint.
- Create `RENDER_DEPLOYMENT.md` — exact operational deployment and persistence instructions.

---

### Task 1: Restore the Existing Test Baseline for the Standalone Pages Layout

**Files:**
- Modify: `self_test.py` inside `test_versions_and_assets()`
- Test: `self_test.py`

**Interfaces:**
- Consumes: current standalone `index.html` and optional historical `js/app.js`.
- Produces: unchanged scientific assertions that work in either repository layout.

- [ ] **Step 1: Run the current test before editing**

```bash
python self_test.py
```

Expected in the current repository: failure when `test_versions_and_assets()` attempts to read the absent `js/app.js`.

- [ ] **Step 2: Change only the JavaScript source lookup**

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

Do not alter any scientific or UI-integrity assertion below those lines.

- [ ] **Step 3: Re-run the baseline**

```bash
python self_test.py
```

Expected: all existing vector parser, Horizons pipeline, ambiguity, SQLite rollback, API-version, and interface checks pass.

- [ ] **Step 4: Commit**

```bash
git add self_test.py
git commit -m "test: support standalone Pages build"
```

---

### Task 2: Separate Bundled Reference Data from Runtime-Writable State

**Files:**
- Create: `runtime_paths.py`
- Modify: `database.py` at the top-level path definitions and inside `seed_if_empty()`
- Modify: `horizons_engine.py` at `CACHE_DIR`
- Modify: `update_engine.py` at `CACHE_PATH`
- Create: `deployment_test.py`

**Interfaces:**
- Produces from `runtime_paths.py`: `ROOT`, `BUNDLE_DATA_DIR`, `DATA_DIR`, `DB_PATH`, `LIVE_CACHE_PATH`, `HORIZONS_CACHE_DIR`.
- Consumed by database, update, Horizons, and health reporting.

- [ ] **Step 1: Create failing path tests in `deployment_test.py`**

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
        "import json,runtime_paths as r; print(json.dumps({'bundle':str(r.BUNDLE_DATA_DIR),'data':str(r.DATA_DIR),'db':str(r.DB_PATH)}))",
        env,
    )
    payload = json.loads(output)
    assert_true(Path(payload["bundle"]) == ROOT / "data", "Bundled data directory changed")
    assert_true(Path(payload["data"]) == ROOT / "data", "Default writable data directory changed")
    assert_true(Path(payload["db"]) == ROOT / "data" / "asteroid_archive.db", "Default database path changed")


def test_runtime_paths_environment_override() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        env = os.environ.copy()
        env["ALBAZ_DATA_DIR"] = tmp
        output = python_probe(
            "import json,runtime_paths as r; print(json.dumps({'bundle':str(r.BUNDLE_DATA_DIR),'data':str(r.DATA_DIR),'db':str(r.DB_PATH),'live':str(r.LIVE_CACHE_PATH),'h':str(r.HORIZONS_CACHE_DIR)}))",
            env,
        )
        payload = json.loads(output)
        runtime = Path(tmp).resolve()
        assert_true(Path(payload["bundle"]) == ROOT / "data", "Bundled source data moved with writable state")
        assert_true(Path(payload["data"]) == runtime, "ALBAZ_DATA_DIR was not honored")
        assert_true(Path(payload["db"]) == runtime / "asteroid_archive.db", "Database path did not move")
        assert_true(Path(payload["live"]) == runtime / "live-cache.js", "Live cache path did not move")
        assert_true(Path(payload["h"]) == runtime / "horizons_cache", "Horizons cache path did not move")
```

- [ ] **Step 2: Run the tests and verify failure**

```bash
python -c "import deployment_test as t; t.test_runtime_paths_default(); t.test_runtime_paths_environment_override()"
```

Expected: `ModuleNotFoundError` for `runtime_paths`.

- [ ] **Step 3: Create `runtime_paths.py`**

```python
#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUNDLE_DATA_DIR = ROOT / "data"
_raw_data_dir = str(os.environ.get("ALBAZ_DATA_DIR") or "").strip()
DATA_DIR = Path(_raw_data_dir).expanduser().resolve() if _raw_data_dir else BUNDLE_DATA_DIR
DB_PATH = DATA_DIR / "asteroid_archive.db"
LIVE_CACHE_PATH = DATA_DIR / "live-cache.js"
HORIZONS_CACHE_DIR = DATA_DIR / "horizons_cache"
```

- [ ] **Step 4: Modify `database.py` without touching schema/query logic**

At imports add:

```python
from runtime_paths import BUNDLE_DATA_DIR, DB_PATH
```

Remove the local `ROOT = ...` and `DB_PATH = ROOT / "data" / ...` definitions.

Inside `seed_if_empty()` replace:

```python
bootstrap = ROOT / "data" / "bootstrap.json"
earth_history = ROOT / "data" / "earth_history.json"
```

with:

```python
bootstrap = BUNDLE_DATA_DIR / "bootstrap.json"
earth_history = BUNDLE_DATA_DIR / "earth_history.json"
```

This ensures an empty persistent disk is seeded from immutable repository reference files.

- [ ] **Step 5: Redirect only generated cache paths**

In `horizons_engine.py` import and use:

```python
from runtime_paths import HORIZONS_CACHE_DIR
CACHE_DIR: Final[Path] = HORIZONS_CACHE_DIR
```

In `update_engine.py` import and use:

```python
from runtime_paths import LIVE_CACHE_PATH
CACHE_PATH: Final[Path] = LIVE_CACHE_PATH
```

Do not edit version constants, upstream URLs, calculations, retries, rollback sequence, or data transforms.

- [ ] **Step 6: Run path tests and scientific regression**

```bash
python -c "import deployment_test as t; t.test_runtime_paths_default(); t.test_runtime_paths_environment_override(); print('PASS paths')"
python self_test.py
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add runtime_paths.py database.py horizons_engine.py update_engine.py deployment_test.py
git commit -m "feat: separate runtime and bundled data paths"
```

---

### Task 3: Make the Python Server Render-Aware and Add Restricted CORS

**Files:**
- Modify: `server.py` imports, constants/helpers, `ArchiveHandler.end_headers()`, new `do_OPTIONS()`, `_serve_health()`, `main()`
- Extend: `deployment_test.py`

**Interfaces:**
- Produces: `environment_default_host()`, `environment_default_port()`, `allowed_cors_origin()`.
- HTTP: approved Pages/local origins receive CORS headers; other origins receive none; preflight returns `204`.

- [ ] **Step 1: Add failing server-policy tests**

```python
def test_cors_origin_policy() -> None:
    import server
    assert_true(server.allowed_cors_origin("https://mralehsas.github.io") == "https://mralehsas.github.io", "Pages origin rejected")
    assert_true(server.allowed_cors_origin("http://127.0.0.1:8872") == "http://127.0.0.1:8872", "127.0.0.1 origin rejected")
    assert_true(server.allowed_cors_origin("http://localhost:8872") == "http://localhost:8872", "localhost origin rejected")
    assert_true(server.allowed_cors_origin("https://evil.example") is None, "Unapproved origin allowed")
    assert_true(server.allowed_cors_origin(None) is None, "Missing Origin emitted CORS")


def test_render_bind_defaults() -> None:
    env = os.environ.copy()
    env["HOST"] = "0.0.0.0"
    env["PORT"] = "12345"
    output = python_probe(
        "import json,server; print(json.dumps({'host':server.environment_default_host(),'port':server.environment_default_port()}))",
        env,
    )
    assert_true(json.loads(output) == {"host": "0.0.0.0", "port": 12345}, "HOST/PORT environment defaults failed")
```

- [ ] **Step 2: Verify they fail**

```bash
python -c "import deployment_test as t; t.test_cors_origin_policy(); t.test_render_bind_defaults()"
```

- [ ] **Step 3: Add environment and CORS helpers to `server.py`**

Add `import os`, then:

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

- [ ] **Step 4: Add CORS headers and preflight**

Before `super().end_headers()` in `ArchiveHandler.end_headers()`:

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
    self.send_response(HTTPStatus.NO_CONTENT)
    self.end_headers()
```

`end_headers()` will add the allow-origin header only when the request Origin is approved. Do not add credentials and do not use `*`.

- [ ] **Step 5: Make bind defaults environment-aware**

Use:

```python
parser.add_argument("--host", default=environment_default_host(), help="Bind host")
parser.add_argument("--port", type=int, default=environment_default_port(), help="Bind port")
```

Preserve local port fallback, but do not select another port when Render has assigned `PORT`:

```python
requested_port = int(args.port)
render_managed_port = bool(str(os.environ.get("PORT") or "").strip())
port_candidates = [requested_port] if render_managed_port else range(requested_port, requested_port + 21)
```

Iterate `port_candidates` in the existing bind loop.

- [ ] **Step 6: Add runtime metadata to `/api/health`**

Add without removing existing fields:

```python
"runtime": {
    "host_default": environment_default_host(),
    "port_default": environment_default_port(),
    "data_dir": str(DB_PATH.parent),
    "external_data_dir": bool(str(os.environ.get("ALBAZ_DATA_DIR") or "").strip()),
},
```

- [ ] **Step 7: Add HTTP preflight integration test**

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
        assert_true(response.status == 204, "Preflight status is not 204")
        assert_true(response.getheader("Access-Control-Allow-Origin") == "https://mralehsas.github.io", "Approved CORS header missing")
        conn.close()

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("OPTIONS", "/api/update/start", headers={"Origin": "https://evil.example"})
        response = conn.getresponse()
        response.read()
        assert_true(response.getheader("Access-Control-Allow-Origin") is None, "Unapproved CORS header emitted")
        conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
```

- [ ] **Step 8: Run tests**

```bash
python -c "import deployment_test as t; t.test_cors_origin_policy(); t.test_render_bind_defaults(); t.test_cors_preflight_http(); print('PASS server')"
python self_test.py
```

- [ ] **Step 9: Commit**

```bash
git add server.py deployment_test.py
git commit -m "feat: add Render server compatibility"
```

---

### Task 4: Add a Single Browser API Resolver and Backend Status

**Files:**
- Create: `web-config.js`
- Modify: `index.html` around the application script loading boundary, state object, `isLocalServer()`, `endpoint()`, `checkHealth()`, `updateConnectionUi()`
- Extend: `deployment_test.py`

**Interfaces:**
- Consumes: `window.ALBAZ_WEB_CONFIG.apiBaseUrl`.
- Produces: `apiBaseUrl()`, backend-routed `endpoint()`, `state.backendReachable`, and three connection states.

- [ ] **Step 1: Add a failing static contract test**

```python
def test_frontend_backend_contract() -> None:
    index = (ROOT / "index.html").read_text(encoding="utf-8")
    config = (ROOT / "web-config.js").read_text(encoding="utf-8")
    assert_true('src="./web-config.js"' in index, "web-config.js not loaded")
    assert_true("ALBAZ_WEB_CONFIG" in config, "Web config object missing")
    assert_true("function apiBaseUrl(" in index, "API base resolver missing")
    assert_true("backendReachable" in index, "Backend state missing")
    assert_true("if (!isLocalServer()) return false;" not in index, "Remote health check still disabled")
    for label in ("Backend Online", "Backend Offline", "Local Desktop Mode"):
        assert_true(label in index, f"Connection label missing: {label}")
    for route in ("/api/cad", "/api/fireball", "/api/sbdb", "/api/sentry", "/api/health", "/api/horizons/track"):
        assert_true(route in index, f"Backend route missing: {route}")
```

- [ ] **Step 2: Verify failure**

```bash
python -c "import deployment_test as t; t.test_frontend_backend_contract()"
```

- [ ] **Step 3: Create the pre-deployment config file**

`web-config.js`:

```javascript
window.ALBAZ_WEB_CONFIG = Object.freeze({
  apiBaseUrl: ''
});
```

The empty string is the defined pre-deployment state. The exact Render HTTPS origin is inserted only after Render creates the service.

- [ ] **Step 4: Load `web-config.js` before the embedded application JavaScript**

Insert:

```html
<script src="./web-config.js"></script>
```

before the final application `<script>` block. Do not remove embedded CSS, embedded icon, embedded map image, sample data, or application JavaScript.

- [ ] **Step 5: Replace the current mixed direct-NASA/relative endpoint map**

Use:

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
  const origin = apiBaseUrl();
  const base = origin ? `${origin}${route}` : route;
  const url = new URL(base, location.href);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value));
  });
  return url.toString();
}
```

All browser NASA/JPL operations now go through `/api/...` and therefore through the local Python server or Render backend.

- [ ] **Step 6: Enable health checks for Render**

Add to the initial state:

```javascript
backendReachable: false,
```

At the beginning of `checkHealth()` use:

```javascript
const base = apiBaseUrl();
if (!isLocalServer() && !base) {
  state.backendReachable = false;
  state.databaseReady = false;
  updateConnectionUi();
  return false;
}
```

On successful `/api/health` fetch set:

```javascript
state.backendReachable = true;
```

In the catch branch set:

```javascript
state.backendReachable = false;
state.databaseReady = false;
```

Remove the old unconditional non-local early return.

- [ ] **Step 7: Display connection mode independently of data provenance**

Inside `updateConnectionUi()` derive:

```javascript
const backendMode = isLocalServer() ? 'local' : state.backendReachable ? 'backend' : 'offline';
const backendLabel = backendMode === 'local'
  ? 'Local Desktop Mode'
  : backendMode === 'backend'
    ? 'Backend Online'
    : 'Backend Offline';
```

Set `#connectionText` to `backendLabel`. Use online pill styling for `local` and `backend`, offline styling only for `offline`. Keep `sourceModeValue` and `databaseStateValue` as separate scientific/data-source indicators.

- [ ] **Step 8: Run front-end contract and baseline tests**

```bash
python -c "import deployment_test as t; t.test_frontend_backend_contract(); print('PASS frontend')"
python self_test.py
```

If Node.js is available, extract the embedded application script and run `node --check` on it. Syntax must pass.

- [ ] **Step 9: Commit**

```bash
git add web-config.js index.html deployment_test.py
git commit -m "feat: route Pages through web backend"
```

---

### Task 5: Add the Free-First Render Blueprint and Deployment Documentation

**Files:**
- Create: `render.yaml`
- Create: `RENDER_DEPLOYMENT.md`
- Extend: `deployment_test.py`

**Interfaces:**
- Produces service `albaz-asteroid-api`, Python runtime, free plan, `/api/health` health check, start command using Render `$PORT`.
- Paid persistent disk is deliberately an upgrade step because Render free web services cannot attach persistent disks.

- [ ] **Step 1: Add a failing blueprint test**

```python
def test_render_blueprint_contract() -> None:
    text = (ROOT / "render.yaml").read_text(encoding="utf-8")
    required = (
        "type: web",
        "name: albaz-asteroid-api",
        "runtime: python",
        "plan: free",
        "healthCheckPath: /api/health",
        "python server.py --host 0.0.0.0 --port $PORT --no-open",
        "autoDeployTrigger: commit",
    )
    for token in required:
        assert_true(token in text, f"Render blueprint missing: {token}")
    assert_true("disk:" not in text, "Free blueprint must not require a paid persistent disk")
```

- [ ] **Step 2: Verify failure**

```bash
python -c "import deployment_test as t; t.test_render_blueprint_contract()"
```

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

- [ ] **Step 4: Create `RENDER_DEPLOYMENT.md` with exact operational instructions**

The document must state:

```text
Initial deployment
1. Render Dashboard -> New -> Blueprint.
2. Connect mralehsas/ALBAZ-ASTEROID-ARCHIVE.
3. Apply render.yaml from the repository root.
4. Wait for the service health check to pass.
5. Copy the HTTPS onrender.com origin shown by Render.
6. Edit web-config.js and set apiBaseUrl to exactly that copied origin, without a trailing slash.
7. Commit web-config.js and wait for GitHub Pages to deploy.
8. Open the GitHub Pages application and verify Backend Online.

Free-plan storage
A free Render Web Service has an ephemeral filesystem. SQLite changes and generated caches can be lost on restart, redeploy, or idle spin-down. Free mode is therefore a functional web deployment, not durable archival storage.

Durable SQLite upgrade
Upgrade the Render Web Service to a paid compute plan, attach a persistent disk mounted at /var/data, and set ALBAZ_DATA_DIR=/var/data. The bundled bootstrap and Earth-history JSON remain in the repository and seed an empty disk automatically.
```

- [ ] **Step 5: Run blueprint and scientific tests**

```bash
python -c "import deployment_test as t; t.test_render_blueprint_contract(); print('PASS blueprint')"
python self_test.py
```

- [ ] **Step 6: Commit**

```bash
git add render.yaml RENDER_DEPLOYMENT.md deployment_test.py
git commit -m "docs: add Render deployment blueprint"
```

---

### Task 6: Build the Complete Deterministic Verification Gate

**Files:**
- Extend: `deployment_test.py`
- Modify implementation files only when a failing test identifies a deployment defect.

**Interfaces:**
- Produces one command for scientific regression and one for deployment regression.

- [ ] **Step 1: Add the deployment-test runner**

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
    print(json.dumps({"status": "PASS", "count": len(report), "tests": report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Compile all affected Python code**

```bash
python -m compileall -q runtime_paths.py database.py horizons_engine.py update_engine.py update_data.py jpl_client.py server.py self_test.py deployment_test.py
```

Expected: exit code `0`.

- [ ] **Step 3: Run deterministic scientific regression**

```bash
python self_test.py
```

Expected: all tests pass.

- [ ] **Step 4: Run deterministic deployment regression**

```bash
python deployment_test.py
```

Expected: all tests pass.

- [ ] **Step 5: Run a Render-like isolated-storage smoke test**

Linux/macOS:

```bash
TMP_DATA="$(mktemp -d)"
HOST=0.0.0.0 PORT=8899 ALBAZ_DATA_DIR="$TMP_DATA" python server.py --no-open &
SERVER_PID=$!
sleep 2
python -c "import json,urllib.request; p=json.load(urllib.request.urlopen('http://127.0.0.1:8899/api/health',timeout=5)); assert p['status']=='ok'; assert p['database_ready'] is True; assert p['runtime']['external_data_dir'] is True; print('PASS render-like health')"
kill "$SERVER_PID"
```

Windows PowerShell:

```powershell
$env:HOST='0.0.0.0'
$env:PORT='8899'
$env:ALBAZ_DATA_DIR=Join-Path $env:TEMP 'albaz-render-smoke'
$p = Start-Process python -ArgumentList 'server.py','--no-open' -PassThru
Start-Sleep -Seconds 2
$r = Invoke-RestMethod http://127.0.0.1:8899/api/health
if ($r.status -ne 'ok' -or -not $r.database_ready -or -not $r.runtime.external_data_dir) { throw 'Render-like health failed' }
Stop-Process -Id $p.Id
```

Expected: database initializes under the configured runtime directory and reports healthy.

- [ ] **Step 6: Verify unchanged local desktop binding**

Clear `HOST`, `PORT`, and `ALBAZ_DATA_DIR`, then run:

```bash
python server.py --port 8872 --no-open
```

From another terminal:

```bash
python -c "import json,urllib.request; p=json.load(urllib.request.urlopen('http://127.0.0.1:8872/api/health',timeout=5)); assert p['status']=='ok'; print('PASS local')"
```

Expected: existing local server behavior remains intact.

- [ ] **Step 7: Commit verification harness**

```bash
git add deployment_test.py
git commit -m "test: add Render deployment verification gate"
```

---

### Task 7: Create the Render Service and Bind Its Real HTTPS Origin to Pages

**Files:**
- Modify: `web-config.js` only after Render creates the service.
- No scientific Python files are changed in this task.

**Interfaces:**
- Consumes: exact HTTPS origin displayed by Render after successful service creation.
- Produces: live GitHub Pages -> Render API connection.

- [ ] **Step 1: Create the Render service from the Blueprint**

In Render Dashboard choose **New -> Blueprint**, connect `mralehsas/ALBAZ-ASTEROID-ARCHIVE`, and apply `render.yaml`.

Expected: `albaz-asteroid-api` builds and reaches healthy state. On the free plan, first request after idle may take roughly a minute because the service spins down after inactivity.

- [ ] **Step 2: Verify the Render health endpoint before touching Pages**

Open the Render service origin followed by `/api/health`.

Required JSON values:

```json
{
  "status": "ok",
  "application": "Asteroid Archive",
  "version": "0.7.2",
  "database_ready": true
}
```

Do not proceed until those fields are correct.

- [ ] **Step 3: Set the actual service origin in `web-config.js`**

Copy the exact HTTPS origin shown by Render. In `web-config.js`, replace the existing empty string assigned to `apiBaseUrl` with that copied origin. Remove a trailing slash if Render displays one. Change no other line in the file.

- [ ] **Step 4: Commit the production origin**

```bash
git add web-config.js
git commit -m "config: connect Pages to Render backend"
```

- [ ] **Step 5: Verify GitHub Pages after deployment**

Open:

```text
https://mralehsas.github.io/ALBAZ-ASTEROID-ARCHIVE/?backend=render
```

Expected: the status pill reads `Backend Online`, the database state is ready, and no desktop `server.py` process is required.

- [ ] **Step 6: Verify restricted CORS through the public browser path**

A request from the Pages app to Render `/api/health` must return:

```text
Access-Control-Allow-Origin: https://mralehsas.github.io
```

A request with an unrelated Origin must not receive `Access-Control-Allow-Origin`.

- [ ] **Step 7: Verify the complete functional service matrix through Pages**

Verify each independently:

```text
CAD close approaches
Fireball data
Sentry data
SBDB object lookup
Horizons Lookup
Horizons track/vectors
SQLite-backed close approaches
SQLite-backed fireballs
SQLite-backed Sentry records
SQLite-backed object profiles
Meteorite register
Impact structures
Connectivity diagnostics
Update status/history
```

Each network failure must remain visibly different from a valid scientific result.

- [ ] **Step 8: Verify update behavior and storage classification**

On a free service, perform one update as a functional test and confirm `/api/update/status` reaches a terminal state. Keep `RENDER_DEPLOYMENT.md` explicit that those writes are ephemeral.

For durable archival use, upgrade the service, mount a persistent disk at `/var/data`, set `ALBAZ_DATA_DIR=/var/data`, redeploy, and verify `/api/health` reports `external_data_dir=true` and `data_dir=/var/data`.

- [ ] **Step 9: Final regression**

```bash
python self_test.py
python deployment_test.py
```

Expected: both remain green after the production URL commit.

---

## Final Acceptance Gate

```text
[PASS] self_test.py scientific regression
[PASS] deployment_test.py infrastructure regression
[PASS] local Windows server mode
[PASS] Render /api/health
[PASS] restricted CORS from GitHub Pages
[PASS] Pages displays Backend Online
[PASS] CAD / Fireball / Sentry / SBDB through Render
[PASS] Horizons Lookup and vector-track workflow through Render
[PASS] SQLite-backed datasets through Render
[PASS] free storage explicitly identified as ephemeral OR paid persistent disk configured
[PASS] bundled reference data still seeds a new runtime data directory
[PASS] no scientific formula, interpretation, schema semantics, or v0.7.2 output behavior changed
```
