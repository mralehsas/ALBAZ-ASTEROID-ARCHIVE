#!/usr/bin/env python3
"""PythonAnywhere-safe launcher for the full Asteroid Archive refresh."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("ALBAZ_DATA_DIR", str(Path.home() / ".albaz-asteroid-data"))

from cloud_sqlite import activate_cloud_sqlite, install_update_lock

activate_cloud_sqlite()
install_update_lock()

from update_data import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
