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
