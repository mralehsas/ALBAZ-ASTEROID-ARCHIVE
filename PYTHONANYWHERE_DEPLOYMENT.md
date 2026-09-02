# ALBAZ Asteroid Archive — PythonAnywhere Deployment

This is the active deployment guide for the free PythonAnywhere backend. GitHub Pages remains the public frontend at `https://mralehsas.github.io/ALBAZ-ASTEROID-ARCHIVE/`; PythonAnywhere hosts the API only. The WSGI callable is `pythonanywhere_wsgi.application`.

## 1. Clone and initialize persistent runtime data

Open a PythonAnywhere **Bash** console and run:

```bash
cd ~
git clone https://github.com/mralehsas/ALBAZ-ASTEROID-ARCHIVE.git
cd ~/ALBAZ-ASTEROID-ARCHIVE
export ALBAZ_DATA_DIR="$HOME/.albaz-asteroid-data"
python -c "from database import initialize,seed_if_empty; initialize(); print('seeded=', seed_if_empty())"
python -c "from database import DB_PATH,counts; print(DB_PATH); print(counts())"
```

The printed database path must be under `$HOME/.albaz-asteroid-data`. Mutable SQLite and generated caches live outside the Git checkout. Repository files `data/bootstrap.json` and `data/earth_history.json` remain immutable seed inputs.

## 2. Create the Web App and configure WSGI

Create one PythonAnywhere Web App using a Python version 3.11 or newer. Edit its WSGI configuration to contain:

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

## 3. Verify health before connecting GitHub Pages

Open:

```text
https://<pythonanywhere-username>.pythonanywhere.com/api/health
```

The response must contain at least:

```json
{
  "status": "ok",
  "application": "Asteroid Archive",
  "version": "0.7.2",
  "database_ready": true
}
```

Also verify `runtime.deployment` is `pythonanywhere` and `runtime.external_data_dir` is `true`.

Do not modify `web-config.js` until this health check is correct.

## 4. Verify production CORS

The approved browser origin is exactly `https://mralehsas.github.io`.

```bash
curl -i -H 'Origin: https://mralehsas.github.io' 'https://<pythonanywhere-username>.pythonanywhere.com/api/health'
```

The response must include:

```text
Access-Control-Allow-Origin: https://mralehsas.github.io
```

An unapproved origin such as `https://evil.example` must receive no `Access-Control-Allow-Origin` header.

## 5. Full archive refresh from Bash console

The free deployment does not run the long archive refresh as a web-request background job. Run it administratively:

```bash
cd ~/ALBAZ-ASTEROID-ARCHIVE
export ALBAZ_DATA_DIR="$HOME/.albaz-asteroid-data"
python update_data.py --days 365 --distance-ld 10 --limit 2000 --fireball-limit 2000 --profiles 30
```

`POST /api/update/start` intentionally returns HTTP 503 with `reason=console_administered`. `/api/update/status` and `/api/update/history` remain readable.

## 6. Generated-cache maintenance

Remove only stale generated cache files with:

```bash
cd ~/ALBAZ-ASTEROID-ARCHIVE
export ALBAZ_DATA_DIR="$HOME/.albaz-asteroid-data"
python cache_maintenance.py --max-age-days 30
```

This command does not delete SQLite archival records or bundled seed data.

## 7. Update application code

```bash
cd ~/ALBAZ-ASTEROID-ARCHIVE
git pull --ff-only origin main
```

Then press **Reload** in the PythonAnywhere Web tab. `$HOME/.albaz-asteroid-data` remains outside the repository and is not touched by `git pull`.

## 8. Bind the verified PythonAnywhere origin to GitHub Pages

After the real hostname has passed `/api/health` and CORS checks, change only `web-config.js`:

```javascript
window.ALBAZ_WEB_CONFIG = Object.freeze({
  apiBaseUrl: 'https://<pythonanywhere-username>.pythonanywhere.com'
});
```

Replace the example hostname with the exact real PythonAnywhere HTTPS hostname. Do not include a trailing slash.

Then verify the public frontend:

```text
https://mralehsas.github.io/ALBAZ-ASTEROID-ARCHIVE/?backend=pythonanywhere
```

The connection state must read **Backend Online** without any local `server.py` process.

## 9. Public service matrix

Verify these routes independently through PythonAnywhere: `/api/cad`, `/api/fireball`, `/api/sentry`, `/api/sbdb`, `/api/sbdb-query`, `/api/horizons-lookup`, `/api/horizons/track`, `/api/local/approaches`, `/api/local/fireballs`, `/api/local/sentry`, `/api/local/objects`, `/api/local/meteorites`, `/api/local/impact-structures`, `/api/object`, `/api/connectivity/test`, `/api/update/status`, and `/api/update/history`.

Scientific results must remain distinguishable from explicit `4xx/5xx` request or upstream-network failures.
