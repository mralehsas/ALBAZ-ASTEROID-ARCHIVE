#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
index = (ROOT / "index.html").read_text(encoding="utf-8")


def require(fragment: str, message: str) -> None:
    if fragment not in index:
        raise AssertionError(message)


def forbid(fragment: str, message: str) -> None:
    if fragment in index:
        raise AssertionError(message)


# Public search must use the archive-aware object endpoint so a live SBDB
# lookup also refreshes the SQLite scientific profile cache.
require(
    "endpoint('object', { sstr: value, refresh: '1' })",
    "Public SBDB search does not refresh the archive-aware object endpoint",
)
forbid(
    "isLocalServer() ? endpoint('object', { sstr: value }) : endpoint('sbdb'",
    "Public search is still display-only and bypasses SQLite profile storage",
)

# In PythonAnywhere console_only mode, the large update control must perform
# an actual live-data refresh rather than being permanently disabled.
require("refreshLiveNasa:", "Live NASA/JPL refresh translation is missing")
require(
    "if (consoleOnly && !isLocalServer()) {",
    "Cloud update handler has no console_only live-refresh branch",
)
require(
    "await loadAllData();",
    "Cloud update handler does not execute the live dataset refresh",
)
require(
    "start.disabled = running || !backendApiAvailable();",
    "Cloud live-refresh button remains disabled despite an available backend",
)

print("frontend live search/update behavior: PASS")
