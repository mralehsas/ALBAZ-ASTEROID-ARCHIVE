#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
index = (ROOT / "index.html").read_text(encoding="utf-8")


def require(fragment: str, message: str) -> None:
    if fragment not in index:
        raise AssertionError(message)


require("engineConsoleOnly:", "Console-only translation key is missing")
require("console_only:'إدارة عبر Console'", "Arabic console_only status label is missing")
require("console_only:'Console administered'", "English console_only status label is missing")
require("const consoleOnly = status === 'console_only';", "Engine renderer does not recognize console_only")
require("consoleOnly ? t('engineConsoleOnly')", "Engine renderer does not display the console-only message")
require("running || consoleOnly || !isLocalServer()", "Remote update button policy is not explicit")
require("backendApiAvailable() ? t('engineConsoleOnly') : t('engineLocalOnly')", "Initial remote engine message still points users to server.py")

print("frontend console-only UI: PASS")
