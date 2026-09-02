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
require("start.disabled = running || !backendApiAvailable();", "Live refresh must stay enabled when the cloud backend is available")
require("consoleOnly ? t('refreshLiveNasa') : t('startNasaUpdate')", "Cloud button must be labelled as a live refresh, not a full archive update")
require("if (consoleOnly && !isLocalServer()) {", "Cloud live-refresh branch is missing")
require("backendApiAvailable() ? t('engineConsoleOnly') : t('engineLocalOnly')", "Initial remote engine message still points users to server.py")
require("التحديث الشامل يُدار من وحدة Bash في PythonAnywhere", "Arabic UI no longer states that full archive refresh remains console-administered")
require("Full archive refresh is administered from the PythonAnywhere Bash console", "English UI no longer states that full archive refresh remains console-administered")

print("frontend console-only UI: PASS")
