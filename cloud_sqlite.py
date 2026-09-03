#!/usr/bin/env python3
"""PythonAnywhere-specific SQLite safety helpers.

PythonAnywhere may keep multiple processes connected to the same SQLite file. A
connection must therefore never switch journal_mode as part of ordinary request
startup, because changing journal mode requires an exclusive database lock. The
cloud adapter preserves the database's existing journal mode, applies conservative
connection pragmas, and serializes archive-changing update jobs with one advisory
lock shared by the Bash updater and web refresh path.
"""
from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from runtime_paths import DB_PATH

UPDATE_LOCK_PATH = DB_PATH.with_suffix(DB_PATH.suffix + ".update.lock")


def cloud_connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=30000")
    # Do not change journal_mode here. Switching WAL/DELETE requires an exclusive
    # lock and can fail during web-worker startup while another process still has
    # the database open. Preserve the file's established mode instead.
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def activate_cloud_sqlite() -> None:
    """Patch database.connect before API/update modules start using the database."""
    import database

    database.connect = cloud_connect


@contextmanager
def archive_update_lock(
    *,
    timeout: float = 2.0,
    lock_path: Path = UPDATE_LOCK_PATH,
) -> Iterator[None]:
    """Serialize archive updates across independent PythonAnywhere processes."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+")
    try:
        if os.name == "posix":
            import fcntl

            deadline = time.monotonic() + max(0.0, float(timeout))
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Another Asteroid Archive update is already running")
                    time.sleep(0.05)
        yield
    finally:
        if os.name == "posix":
            try:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


def install_update_lock() -> None:
    """Wrap update_engine.run_update with the shared PythonAnywhere update lock."""
    import update_engine

    current = update_engine.run_update
    if getattr(current, "_albaz_cloud_locked", False):
        return

    def locked_run_update(*args, **kwargs):
        with archive_update_lock(timeout=2.0):
            return current(*args, **kwargs)

    locked_run_update._albaz_cloud_locked = True  # type: ignore[attr-defined]
    update_engine.run_update = locked_run_update
