# ALBAZ Asteroid Archive — PythonAnywhere Backend Design

**Date:** 2026-09-02  
**Status:** Approved architecture, pre-implementation  
**Repository:** `mralehsas/ALBAZ-ASTEROID-ARCHIVE`

## Goal

Replace the abandoned Render deployment path with a free PythonAnywhere backend while preserving the existing GitHub Pages frontend, local Windows desktop mode, SQLite data model, NASA/JPL/Horizons behavior, and the frozen scientific engine version `0.7.2`.

The public architecture becomes:

`GitHub Pages -> HTTPS -> PythonAnywhere WSGI API -> NASA/JPL services + SQLite`

The local architecture remains:

`Local browser -> server.py on 127.0.0.1:8872 -> same API core -> NASA/JPL services + SQLite`

## Binding Scientific Constraints

- The scientific engine remains version `0.7.2`.
- No astronomical formula, Horizons vector interpretation, API-version policy, Sentry interpretation, database schema semantics, missing-data policy, or NASA/JPL payload transformation is changed by this migration.
- Existing JPL client serialization/fair-use behavior remains authoritative.
- Network failure must remain visibly different from a valid scientific result.
- Bundled reference datasets remain immutable repository assets and must continue to seed an empty runtime database.

## Why PythonAnywhere

PythonAnywhere is selected because the free tier can host one WSGI web application and SQLite, and the JPL domains used by this project are available through PythonAnywhere's free-account outbound-network whitelist.

The design deliberately avoids depending on background workers or scheduled tasks because those capabilities are constrained on the free plan.

## Architecture

### 1. Shared API core

Create a transport-neutral module, `api_core.py`, that owns request-independent API behavior currently embedded in `server.py`.

The core exposes small functions that accept parsed inputs and return a normalized response object containing:

- HTTP status code
- JSON-compatible payload or encoded JSON bytes
- content type
- optional cache metadata

The core owns:

- remote NASA/JPL proxy routes
- local SQLite dataset reads
- SBDB object lookup/cache behavior
- connectivity diagnostics
- Horizons track requests
- update-history reads
- health payload generation
- shared short-lived response cache
- allowed CORS-origin policy

The core does **not** own HTTP socket handling, WSGI environment parsing, static-file serving, browser launch behavior, or PythonAnywhere configuration.

### 2. Local desktop adapter

`server.py` remains the local Windows/desktop HTTP adapter built on `ThreadingHTTPServer` and `SimpleHTTPRequestHandler`.

It continues to:

- serve the standalone `index.html` and local static assets
- bind to `127.0.0.1:8872` by default
- preserve existing local fallback-port behavior
- open the browser unless `--no-open` is used
- translate HTTP requests into calls to `api_core.py`
- translate normalized core responses back into HTTP responses

This preserves local behavior while preventing scientific/API logic from diverging between desktop and cloud deployments.

### 3. PythonAnywhere WSGI adapter

Create `pythonanywhere_wsgi.py` exposing the standard WSGI callable:

`application(environ, start_response)`

It will:

- parse method, path, query string, request body, and `Origin`
- handle `OPTIONS` preflight
- route supported API requests into `api_core.py`
- emit JSON responses with the same status and semantics as local mode
- emit restricted CORS headers only for approved origins
- never serve the GitHub Pages frontend

The PythonAnywhere app is therefore API-only.

## Public API Behavior

The following GET routes remain available through both local and WSGI adapters:

- `/api/cad`
- `/api/fireball`
- `/api/sbdb`
- `/api/sentry`
- `/api/sbdb-query`
- `/api/horizons-lookup`
- `/api/local/approaches`
- `/api/local/fireballs`
- `/api/local/sentry`
- `/api/local/objects`
- `/api/local/meteorites`
- `/api/local/impact-structures`
- `/api/object`
- `/api/connectivity/test`
- `/api/horizons/track`
- `/api/update/status`
- `/api/update/history`
- `/api/health`

## Update Operations on the Free Plan

The long-running update workflow is **not** exposed as a cloud background job on PythonAnywhere free hosting.

Cloud behavior:

- `/api/update/start` returns a structured `503 Service Unavailable` response explaining that full archive refresh is console-administered on this deployment.
- `/api/update/cancel` returns a structured non-running/unsupported response.
- `/api/update/status` and `/api/update/history` remain readable so the web UI can inspect the last completed archive refresh.

Administrative update procedure:

- run the existing update command from a PythonAnywhere Bash console
- write updates into the same SQLite database used by the WSGI app
- reload the web app after a code/config change when necessary

Local Windows mode may retain the existing threaded update start/cancel behavior because the local process controls its own lifetime.

This distinction is explicit in the API response and documentation so the browser never mistakes an unsupported cloud background job for a successful update.

## Runtime Storage

Retain `runtime_paths.py` as the single source of writable paths.

Local default:

`<repo>/data/`

PythonAnywhere production setting:

`ALBAZ_DATA_DIR=$HOME/.albaz-asteroid-data`

Writable runtime files include:

- `asteroid_archive.db`
- generated live-cache data
- Horizons cache

Bundled seed sources remain under repository `data/` and are never redirected:

- `data/bootstrap.json`
- `data/earth_history.json`

This ensures that a fresh PythonAnywhere account can seed a new persistent runtime database without mixing source-controlled reference data with mutable state.

## Cache and Storage Budget

PythonAnywhere free storage is limited, so generated cache data must remain bounded.

The implementation will add an explicit cache-maintenance command or function that:

- deletes only generated stale cache files
- never deletes SQLite archival records or bundled reference data
- reports reclaimed bytes and remaining cache size

No automatic destructive cleanup runs inside a web request.

## CORS and Browser Security

Production browser origin:

`https://mralehsas.github.io`

Allowed local development origins:

- `http://127.0.0.1:<port>`
- `http://localhost:<port>`
- HTTPS localhost equivalents if used

Rules:

- no wildcard `Access-Control-Allow-Origin`
- no credentials header unless a future authenticated feature explicitly requires it
- `OPTIONS` supports the methods and headers used by the frontend
- unknown origins receive no allow-origin header
- PythonAnywhere API responses remain JSON-only

## Frontend Configuration

`web-config.js` remains the single public API-origin setting.

Before PythonAnywhere deployment it remains empty.

After deployment it is set to the exact HTTPS origin assigned by PythonAnywhere, for example:

`https://<username>.pythonanywhere.com`

The existing frontend resolver continues to:

- use `location.origin` when running locally
- use `window.ALBAZ_WEB_CONFIG.apiBaseUrl` on GitHub Pages
- route all browser NASA/JPL operations through `/api/...`

The UI connection states remain:

- `Local Desktop Mode`
- `Backend Online`
- `Backend Offline`

Data provenance remains separate from transport status.

## Repository Changes

Planned implementation changes:

- create `api_core.py`
- create `pythonanywhere_wsgi.py`
- modify `server.py` to delegate shared API behavior to `api_core.py`
- extend `runtime_paths.py` only if required for an explicit home-directory deployment helper
- modify deployment tests for WSGI behavior
- keep `self_test.py` scientific regression coverage intact
- create `PYTHONANYWHERE_DEPLOYMENT.md`
- remove `render.yaml`
- remove or replace `RENDER_DEPLOYMENT.md`
- update `web-config.js` only after the real PythonAnywhere hostname exists

No frontend redesign is part of this migration.

## PythonAnywhere Deployment Flow

1. Create a free PythonAnywhere account.
2. Open a Bash console and clone `mralehsas/ALBAZ-ASTEROID-ARCHIVE`.
3. Set up the Web App as a manual WSGI/Python application.
4. Configure the PythonAnywhere WSGI file to import the repository's `pythonanywhere_wsgi.application`.
5. Set `ALBAZ_DATA_DIR` to `$HOME/.albaz-asteroid-data` inside the WSGI startup environment.
6. Initialize/seed SQLite once from the repository's bundled reference data.
7. Reload the Web App.
8. Verify `/api/health` before modifying GitHub Pages.
9. Write the exact PythonAnywhere HTTPS origin into `web-config.js`.
10. Verify GitHub Pages displays `Backend Online` and test each API family independently.

## Error Handling

All adapters preserve normalized JSON errors.

Examples:

- upstream JPL failure -> `502` with an explicit upstream/network error
- invalid request -> `400`
- unknown route -> `404`
- unsupported cloud background update start -> `503`
- unexpected server failure -> `500` without leaking stack traces or filesystem secrets

The WSGI adapter must not convert an error into HTTP 200.

## Verification Strategy

Implementation is accepted only when all of the following pass:

- existing `self_test.py` scientific regression
- Python compile checks for all touched modules
- deterministic shared-core route tests
- local HTTP adapter tests
- WSGI `GET` tests for health, local data, proxy routing, Horizons, and errors
- WSGI `OPTIONS` CORS tests for approved and unapproved origins
- cloud update-start rejection test
- runtime-path test using a temporary external data directory
- fresh-database seed test using repository bundled JSON
- local `127.0.0.1:8872` smoke test
- final PythonAnywhere `/api/health` smoke test
- GitHub Pages -> PythonAnywhere CORS test
- frontend status reads `Backend Online`
- CAD, Fireball, Sentry, SBDB, Horizons lookup/track, SQLite datasets, meteorites, and impact structures work through the deployed backend

## Acceptance Gate

The migration is complete when:

- GitHub Pages remains the public frontend
- no Render service or card is required
- PythonAnywhere serves the API over HTTPS
- the real PythonAnywhere origin is stored in `web-config.js`
- local Windows mode still works
- SQLite survives web-app reloads because it lives outside the repository checkout
- full archive refresh is documented and executable from Bash console
- all live scientific queries work through PythonAnywhere
- all scientific regression tests remain green
- no `0.7.2` scientific behavior changed
