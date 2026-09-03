#!/usr/bin/env python3
from pathlib import Path

path = Path("api_core.py")
text = path.read_text(encoding="utf-8")

text = text.replace(
    "from update_engine import fetch_json, run_update, run_update",
    "from update_engine import fetch_json, run_update",
)
text = text.replace(
    "LIVE_REFRESH_COOLDOWN_SECONDS: Final[int] = 300\nLIVE_REFRESH_LOCK = threading.Lock()\nLIVE_REFRESH_COOLDOWN_SECONDS: Final[int] = 300\nLIVE_REFRESH_LOCK = threading.Lock()",
    "LIVE_REFRESH_COOLDOWN_SECONDS: Final[int] = 300\nLIVE_REFRESH_LOCK = threading.Lock()",
)

marker = "\ndef _bounded_live_refresh_config("
positions = []
start = 0
while True:
    pos = text.find(marker, start)
    if pos < 0:
        break
    positions.append(pos)
    start = pos + len(marker)

if len(positions) == 2:
    second = positions[1]
    handler = text.find("\ndef handle_cloud_post(", second)
    if handler < 0:
        raise SystemExit("Could not locate handle_cloud_post after duplicate helper block")
    text = text[:second] + text[handler:]
elif len(positions) != 1:
    raise SystemExit(f"Expected one or two cloud helper blocks, found {len(positions)}")

checks = {
    "config helper": text.count("def _bounded_live_refresh_config("),
    "cooldown helper": text.count("def _web_live_cooldown_remaining("),
    "refresh helper": text.count("def _cloud_live_refresh("),
    "cooldown constant": text.count("LIVE_REFRESH_COOLDOWN_SECONDS: Final[int] = 300"),
}
for name, count in checks.items():
    if count != 1:
        raise SystemExit(f"{name} count after cleanup is {count}, expected 1")
if "run_update, run_update" in text:
    raise SystemExit("Duplicate run_update import remains")

path.write_text(text, encoding="utf-8")
print("persistent refresh duplicate cleanup complete")
