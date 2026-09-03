#!/usr/bin/env python3
"""Regression for PythonAnywhere SQLite connections under a live peer connection.

A cloud connection must never attempt to change journal_mode on every connect,
because that requires an exclusive lock and fails while a web worker already has
the database open. The shared update lock remains responsible for serializing
archive-changing update jobs across processes.
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from cloud_sqlite import cloud_connect


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "archive.db"
        with sqlite3.connect(path) as seed:
            seed.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT)")
            seed.execute("INSERT INTO sample(value) VALUES('ok')")

        # Keep a normal peer connection alive to model the already-running web worker.
        peer = sqlite3.connect(path, timeout=5)
        try:
            with cloud_connect(path) as db:
                assert db.execute("SELECT value FROM sample").fetchone()[0] == "ok"
                assert str(db.execute("PRAGMA integrity_check").fetchone()[0]).lower() == "ok"
        finally:
            peer.close()

    print("PythonAnywhere live-peer SQLite connect: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
