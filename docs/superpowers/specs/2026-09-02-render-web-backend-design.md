# ALBAZ Asteroid Archive — Render Web Backend Design

Date: 2026-09-02
Status: Approved architecture / pre-implementation specification
Repository: mralehsas/ALBAZ-ASTEROID-ARCHIVE

## 1. Objective

Publish ALBAZ Asteroid Archive as a real web application while preserving the existing GitHub Pages front end and the frozen scientific core. GitHub Pages remains the public presentation layer; a Render Python Web Service becomes the online API/backend for NASA/JPL, Horizons, Sentry, SBDB, SQLite, cache, and update operations.

The implementation must not alter astronomical formulas, Horizons calculations, scientific interpretation, database schema semantics, or the frozen v0.7.2 scientific-core behavior.

## 2. Target Architecture

```text
Browser
  |
  v
GitHub Pages
https://mralehsas.github.io/ALBAZ-ASTEROID-ARCHIVE/
  |
  | HTTPS API requests
  v
Render Web Service
https://<render-service>.onrender.com
  |
  +--> NASA/JPL CAD
  +--> NASA/JPL Fireball
  +--> NASA/JPL SBDB
  +--> NASA/JPL Sentry
  +--> JPL Horizons Lookup
  +--> JPL Horizons Vectors
  |
  +--> SQLite persistent data/cache when a persistent disk is configured
```

The Windows desktop/local mode remains supported and continues to use the same local Python server workflow.

## 3. Deployment Model

### 3.1 Front end

GitHub Pages continues to host the public interface. The current Pages URL remains the primary user-facing URL.

The front end must determine an API base URL through one small configuration layer rather than hard-coded `/api` assumptions.

Expected modes:

- Local desktop mode: API base resolves to the current origin, preserving `http://127.0.0.1:<port>/api/...` behavior.
- GitHub Pages mode: API base resolves to the configured Render HTTPS origin.
- Unconfigured/failed backend: interface stays usable for static presentation and explicitly reports backend offline.

### 3.2 Backend

Render runs the existing Python server as a Web Service. The service binds to `0.0.0.0` and reads its port from Render's `PORT` environment variable. A local command-line port override remains available for Windows usage.

The Render start command will be equivalent to:

```text
python server.py --host 0.0.0.0 --port <PORT> --no-open
```

A `render.yaml` blueprint will define the service and `/api/health` health check.

## 4. API Compatibility

Existing API route semantics are preserved, including:

- `/api/health`
- `/api/cad`
- `/api/fireball`
- `/api/sbdb`
- `/api/sentry`
- `/api/sbdb-query`
- `/api/horizons-lookup`
- `/api/horizons/track`
- `/api/local/approaches`
- `/api/local/fireballs`
- `/api/local/sentry`
- `/api/local/objects`
- `/api/local/meteorites`
- `/api/local/impact-structures`
- `/api/object`
- `/api/connectivity/test`
- `/api/update/status`
- `/api/update/history`
- `/api/update/start`
- `/api/update/cancel`

The front end must not need route-specific knowledge of Render; it only prepends the configured backend origin.

## 5. CORS and Browser Security

The backend will implement explicit CORS behavior for the production Pages origin:

```text
https://mralehsas.github.io
```

The implementation will also permit the local development origins needed by the desktop workflow. Production CORS must not default to `*`.

The server must:

- return `Access-Control-Allow-Origin` only for approved origins;
- support preflight `OPTIONS` requests where needed;
- permit the methods used by the existing API (`GET`, required `POST`, and `OPTIONS`);
- return appropriate allowed headers;
- avoid credentials unless a future authenticated feature explicitly requires them;
- keep upstream NASA/JPL communication server-to-server.

No secret keys or private credentials are embedded in GitHub Pages.

## 6. Content Security Policy

The local-only `connect-src 'self'` policy cannot block the Pages-to-Render architecture. The web deployment must allow the configured Render HTTPS API origin while preserving restrictive defaults for all other resource classes.

Local mode must remain compatible with the existing security headers.

## 7. SQLite and Persistent Storage

Database path selection becomes environment-aware without changing the database schema or scientific data model.

Priority:

1. If `ALBAZ_DATA_DIR` is set, database/cache state uses that directory.
2. Otherwise, retain the current repository-local `data/` behavior.

Recommended Render persistent path:

```text
ALBAZ_DATA_DIR=/var/data
```

A Render Persistent Disk should be mounted at `/var/data` for production persistence. Without a persistent disk, the service may still start, but state written to the instance filesystem is considered ephemeral and must be reported as such in deployment documentation.

The implementation must create the data directory if absent and retain existing initialization/seeding behavior.

## 8. Scientific-Core Preservation

The following policy is mandatory:

- no new astronomical formulas;
- no changes to JPL/Horizons physical interpretation;
- no changes to Sentry probability semantics;
- no replacement of missing scientific values;
- no change to database schema semantics unless independently approved as a scientific-core version change;
- network/deployment changes remain infrastructure changes only.

`horizons_engine.py`, `jpl_client.py`, update logic, and database queries may only receive the minimum compatibility changes needed for environment/path configuration if required. Their scientific outputs must remain unchanged.

## 9. Front-End Connection Layer

A single API resolver will be introduced. All front-end requests that currently use relative `/api/...` URLs will pass through it.

Proposed behavior:

```text
if running on mralehsas.github.io:
    API_BASE_URL = configured Render origin
else:
    API_BASE_URL = current origin / relative API mode
```

The Render URL must live in one replaceable configuration location so a future service rename does not require editing every request.

User-visible service state will distinguish:

- Backend Online
- Backend Offline
- Local Desktop Mode

The application must not label cached/static data as live when the backend is unreachable.

## 10. Error Handling

Network boundaries must fail explicitly and safely.

- Render unavailable: show Backend Offline; do not fabricate successful service state.
- NASA/JPL unavailable: preserve existing upstream error behavior and use valid local/cache fallback only where the existing scientific policy allows it.
- SQLite unavailable: `/api/health` reports database readiness accurately.
- Horizons errors: preserve current explicit invalid-target, lookup, HTTP, and gateway distinctions.
- Timeouts/retries remain bounded to prevent request storms and unnecessary Render resource use.

## 11. Render Blueprint

`render.yaml` will define a Python Web Service with:

- repository root as service root;
- Python runtime;
- no third-party dependency requirement beyond the existing `requirements.txt` unless implementation proves otherwise;
- start command using `0.0.0.0` and `$PORT`;
- health check path `/api/health`;
- environment variable support for `ALBAZ_DATA_DIR`;
- a persistent disk configuration if supported by the selected Render plan.

The Render service name target is `albaz-asteroid-api` unless unavailable at creation time.

## 12. Verification Matrix

Implementation is not complete until the following pass.

### 12.1 Static/code checks

- Python compilation passes.
- Existing project self-tests pass.
- Front-end JavaScript syntax passes.
- No broken API path references remain.
- No duplicate configuration sources for the backend URL.

### 12.2 Local regression

Run the application locally and verify:

- local server starts on `127.0.0.1:8872` or fallback port;
- `/api/health` returns success;
- local SQLite reads work;
- current desktop UI loads;
- NASA/JPL proxy endpoints retain existing behavior;
- Horizons track generation retains existing behavior.

### 12.3 Render-mode server verification

Run locally with Render-like environment:

```text
HOST=0.0.0.0
PORT=<test-port>
ALBAZ_DATA_DIR=<temporary-test-directory>
```

Verify:

- binding works;
- database initializes in configured directory;
- health endpoint reports correct path/readiness;
- no browser is automatically opened in no-open mode.

### 12.4 CORS verification

For origin `https://mralehsas.github.io`:

- GET request receives the expected allow-origin header;
- POST/update preflight succeeds where applicable.

For an unapproved arbitrary origin:

- no permissive allow-origin header is returned.

### 12.5 External scientific-service verification

Verify through the backend:

- CAD
- Fireball
- Sentry
- SBDB
- Horizons Lookup
- Horizons Vectors / track

No test may reinterpret a network failure as a scientific success.

### 12.6 GitHub Pages integration

After Render creates the production service URL:

- configure the Pages API base to the exact Render origin;
- deploy Pages;
- verify `/api/health` from the browser context;
- verify dashboard data load;
- verify connectivity diagnostic;
- verify SBDB lookup;
- verify Horizons workflow;
- verify clear offline indication when the backend is intentionally unavailable.

## 13. Rollout Sequence

1. Implement environment-aware backend binding and storage.
2. Implement CORS and preflight handling.
3. Add API base resolver to the front end.
4. Add backend/local/offline status presentation.
5. Add `render.yaml` and deployment documentation.
6. Run local and Render-mode regression tests.
7. Create the Render service from this GitHub repository.
8. Obtain the final `https://<service>.onrender.com` URL.
9. Configure that URL in the Pages front end.
10. Deploy Pages and execute the end-to-end verification matrix.

## 14. Acceptance Criteria

The design is accepted as implemented only when:

- the existing GitHub Pages URL remains the public application URL;
- the Pages UI successfully reaches the Render backend over HTTPS;
- NASA/JPL/Horizons functions operate through the backend;
- SQLite-backed local datasets operate through the backend;
- persistent storage is clearly configured or explicitly identified as ephemeral;
- CORS is restricted to approved origins;
- local Windows operation still works;
- existing scientific tests remain green;
- no scientific calculation or interpretation has changed.

## 15. Out of Scope

This architecture does not include:

- migrating SQLite to PostgreSQL;
- authentication/user accounts;
- billing;
- redesigning the scientific model;
- changing asteroid-risk algorithms;
- replacing NASA/JPL/Horizons sources;
- changing the public GitHub Pages URL.

These require separate approval if desired later.
