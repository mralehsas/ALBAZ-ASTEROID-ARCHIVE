#!/usr/bin/env python3
from __future__ import annotations

import multiprocessing as mp
import os
import sqlite3
import tempfile
import time
from pathlib import Path

from cloud_sqlite import archive_update_lock, cloud_connect


def _hold_lock(lock_path: str, ready) -> None:
    with archive_update_lock(timeout=1.0, lock_path=Path(lock_path)):
        ready.set()
        time.sleep(0.8)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        db_path = root / "archive.db"
        with cloud_connect(db_path) as db:
            db.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT)")
            db.execute("INSERT INTO sample(value) VALUES('ok')")
            journal = str(db.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            integrity = str(db.execute("PRAGMA integrity_check").fetchone()[0]).lower()
        assert journal == "delete", journal
        assert integrity == "ok", integrity
        assert db_path.read_bytes()[:16] == b"SQLite format 3\x00"
        with sqlite3.connect(db_path) as db:
            assert db.execute("SELECT value FROM sample").fetchone()[0] == "ok"

        if os.name == "posix":
            lock_path = root / "archive.update.lock"
            ready = mp.Event()
            proc = mp.Process(target=_hold_lock, args=(str(lock_path), ready))
            proc.start()
            assert ready.wait(3), "child never acquired update lock"
            blocked = False
            try:
                with archive_update_lock(timeout=0.15, lock_path=lock_path):
                    pass
            except RuntimeError:
                blocked = True
            proc.join(3)
            assert blocked, "second process acquired an update lock concurrently"
            assert proc.exitcode == 0, proc.exitcode

    print("PythonAnywhere SQLite safety: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
