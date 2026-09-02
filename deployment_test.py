#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def python_probe(code: str, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return proc.stdout.strip()


def test_runtime_paths_default() -> None:
    env = os.environ.copy()
    env.pop("ALBAZ_DATA_DIR", None)
    output = python_probe(
        "import json,runtime_paths as r; print(json.dumps({'bundle':str(r.BUNDLE_DATA_DIR),'data':str(r.DATA_DIR),'db':str(r.DB_PATH)}))",
        env,
    )
    payload = json.loads(output)
    assert_true(Path(payload["bundle"]) == ROOT / "data", "Bundled data directory changed")
    assert_true(Path(payload["data"]) == ROOT / "data", "Default writable data directory changed")
    assert_true(Path(payload["db"]) == ROOT / "data" / "asteroid_archive.db", "Default database path changed")


def test_runtime_paths_environment_override() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        env = os.environ.copy()
        env["ALBAZ_DATA_DIR"] = tmp
        output = python_probe(
            "import json,runtime_paths as r; print(json.dumps({'bundle':str(r.BUNDLE_DATA_DIR),'data':str(r.DATA_DIR),'db':str(r.DB_PATH),'live':str(r.LIVE_CACHE_PATH),'h':str(r.HORIZONS_CACHE_DIR)}))",
            env,
        )
        payload = json.loads(output)
        runtime = Path(tmp).resolve()
        assert_true(Path(payload["bundle"]) == ROOT / "data", "Bundled source data moved with writable state")
        assert_true(Path(payload["data"]) == runtime, "ALBAZ_DATA_DIR was not honored")
        assert_true(Path(payload["db"]) == runtime / "asteroid_archive.db", "Database path did not move")
        assert_true(Path(payload["live"]) == runtime / "live-cache.js", "Live cache path did not move")
        assert_true(Path(payload["h"]) == runtime / "horizons_cache", "Horizons cache path did not move")


def test_cors_origin_policy() -> None:
    import server
    assert_true(server.allowed_cors_origin("https://mralehsas.github.io") == "https://mralehsas.github.io", "Pages origin rejected")
    assert_true(server.allowed_cors_origin("http://127.0.0.1:8872") == "http://127.0.0.1:8872", "127.0.0.1 origin rejected")
    assert_true(server.allowed_cors_origin("http://localhost:8872") == "http://localhost:8872", "localhost origin rejected")
    assert_true(server.allowed_cors_origin("https://evil.example") is None, "Unapproved origin allowed")
    assert_true(server.allowed_cors_origin(None) is None, "Missing Origin emitted CORS")


def test_render_bind_defaults() -> None:
    env = os.environ.copy()
    env["HOST"] = "0.0.0.0"
    env["PORT"] = "12345"
    output = python_probe(
        "import json,server; print(json.dumps({'host':server.environment_default_host(),'port':server.environment_default_port()}))",
        env,
    )
    assert_true(json.loads(output) == {"host": "0.0.0.0", "port": 12345}, "HOST/PORT environment defaults failed")


def test_cors_preflight_http() -> None:
    import http.client
    import threading
    from http.server import ThreadingHTTPServer
    import server

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.ArchiveHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        port = httpd.server_address[1]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("OPTIONS", "/api/update/start", headers={
            "Origin": "https://mralehsas.github.io",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        })
        response = conn.getresponse()
        response.read()
        assert_true(response.status == 204, "Approved preflight did not return 204")
        assert_true(response.getheader("Access-Control-Allow-Origin") == "https://mralehsas.github.io", "Approved preflight missing allow-origin")
        assert_true("POST" in str(response.getheader("Access-Control-Allow-Methods") or ""), "Approved preflight missing POST")
        conn.close()

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("OPTIONS", "/api/update/start", headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        })
        response = conn.getresponse()
        response.read()
        assert_true(response.status == 204, "Rejected-origin preflight should still complete")
        assert_true(response.getheader("Access-Control-Allow-Origin") is None, "Rejected origin received allow-origin")
        conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_frontend_backend_contract() -> None:
    index = (ROOT / "index.html").read_text(encoding="utf-8")
    config = (ROOT / "web-config.js").read_text(encoding="utf-8")
    assert_true('src="./web-config.js"' in index, "web-config.js not loaded")
    assert_true("ALBAZ_WEB_CONFIG" in config, "Web config object missing")
    assert_true("function apiBaseUrl(" in index, "API base resolver missing")
    assert_true("backendReachable" in index, "Backend state missing")
    assert_true("if (!isLocalServer()) return false;" not in index, "Remote health check still disabled")
    for label in ("Backend Online", "Backend Offline", "Local Desktop Mode"):
        assert_true(label in index, f"Connection label missing: {label}")
    for route in ("/api/cad", "/api/fireball", "/api/sbdb", "/api/sentry", "/api/health", "/api/horizons/track"):
        assert_true(route in index, f"Backend route missing: {route}")
    assert_true("https://ssd-api.jpl.nasa.gov/cad.api" not in index, "Browser still bypasses backend for CAD")


def test_render_blueprint_contract() -> None:
    text = (ROOT / "render.yaml").read_text(encoding="utf-8")
    required = (
        "type: web",
        "name: albaz-asteroid-api",
        "runtime: python",
        "plan: free",
        "healthCheckPath: /api/health",
        "python server.py --host 0.0.0.0 --port $PORT --no-open",
        "autoDeployTrigger: commit",
    )
    for token in required:
        assert_true(token in text, f"Render blueprint missing: {token}")
    assert_true("disk:" not in text, "Free blueprint must not require a paid persistent disk")


def main() -> int:
    tests = [
        test_runtime_paths_default,
        test_runtime_paths_environment_override,
        test_cors_origin_policy,
        test_render_bind_defaults,
        test_cors_preflight_http,
        test_frontend_backend_contract,
        test_render_blueprint_contract,
    ]
    report = []
    for test in tests:
        test()
        report.append({"test": test.__name__, "status": "PASS"})
        print(f"PASS  {test.__name__}")
    print(json.dumps({"status": "PASS", "count": len(report), "tests": report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
