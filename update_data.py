#!/usr/bin/env python3
"""Command-line launcher for Asteroid Archive v0.7 Final Audited NASA Data Engine."""
from __future__ import annotations

import argparse
import json
from typing import Any

from update_engine import run_update


def print_progress(item: dict[str, Any]) -> None:
    print(f"[{int(item.get('percent', 0)):3d}%] {item.get('message', '')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Update Asteroid Archive SQLite/cache from official NASA/JPL APIs.")
    parser.add_argument("--days", type=int, default=365, help="Close-approach future window in days")
    parser.add_argument("--distance-ld", type=float, default=10, help="Maximum close-approach distance in lunar distances")
    parser.add_argument("--limit", type=int, default=2000, help="Maximum close-approach records")
    parser.add_argument("--fireball-limit", type=int, default=2000, help="Maximum fireball records")
    parser.add_argument("--profiles", type=int, default=30, help="Number of priority SBDB object profiles to cache")
    parser.add_argument("--no-profiles", action="store_true", help="Skip SBDB profile enrichment")
    args = parser.parse_args()

    config = {
        "days": args.days,
        "distance_ld": args.distance_ld,
        "approach_limit": args.limit,
        "fireball_limit": args.fireball_limit,
        "profile_limit": args.profiles,
        "include_profiles": not args.no_profiles,
    }
    try:
        result = run_update(config, progress=print_progress, trigger="cli")
    except Exception as exc:
        print(f"\nفشل التحديث مع الإبقاء على آخر قاعدة سليمة: {exc}")
        return 1
    print("\nنتيجة التحديث:")
    print(json.dumps({k: v for k, v in result.items() if k != "logs"}, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
