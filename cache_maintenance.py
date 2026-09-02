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
