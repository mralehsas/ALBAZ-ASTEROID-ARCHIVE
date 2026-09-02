# ALBAZ Asteroid Archive — Render Deployment

## Initial deployment

1. Open Render Dashboard -> **New** -> **Blueprint**.
2. Connect the repository `mralehsas/ALBAZ-ASTEROID-ARCHIVE`.
3. Apply `render.yaml` from the repository root.
4. Wait for the service health check at `/api/health` to pass.
5. Copy the HTTPS `onrender.com` origin shown by Render.
6. Edit `web-config.js` and set `apiBaseUrl` to exactly that copied origin, without a trailing slash.
7. Commit `web-config.js` and wait for GitHub Pages to deploy.
8. Open `https://mralehsas.github.io/ALBAZ-ASTEROID-ARCHIVE/` and verify **Backend Online**.

## Free-plan storage

A free Render Web Service has an ephemeral filesystem. SQLite changes and generated caches can be lost on restart, redeploy, or idle spin-down. Free mode is therefore a functional web deployment, not durable archival storage.

The initial free deployment deliberately does **not** set `ALBAZ_DATA_DIR`. The application uses its repository-local `data/` path for runtime state, and that state is treated as ephemeral.

## Durable SQLite upgrade

Upgrade the Render Web Service to a paid compute plan, attach a persistent disk mounted at `/var/data`, and set:

```text
ALBAZ_DATA_DIR=/var/data
```

Only writable runtime state moves to `/var/data`:

- `asteroid_archive.db`
- generated `live-cache.js`
- generated Horizons cache files

Bundled `data/bootstrap.json` and `data/earth_history.json` remain in the repository and seed an empty persistent disk automatically.

## Operational verification

After deployment, verify these URLs/actions in order:

1. `https://<service>.onrender.com/api/health` returns JSON with `status: ok` and `version: 0.7.2`.
2. The GitHub Pages header shows **Backend Online**.
3. CAD, Fireball, Sentry, and SBDB data load through the backend.
4. **NASA/JPL connectivity test** returns service diagnostics.
5. **Horizons** track loading succeeds for a known target such as `99942`.
6. If the backend is intentionally unavailable, the Pages UI shows **Backend Offline** and falls back without claiming cached/sample values are live.

## Service architecture

```text
GitHub Pages
  -> HTTPS
Render: albaz-asteroid-api
  -> NASA/JPL CAD / Fireball / SBDB / Sentry / Horizons
  -> SQLite + cache
```

The public application URL remains the GitHub Pages URL. Render is the backend API only.
