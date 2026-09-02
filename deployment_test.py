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


def test_server_bind_environment_defaults() -> None:
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
        response = conn.getresponse(); response.read()
        assert_true(response.status == 204, "Approved preflight did not return 204")
        assert_true(response.getheader("Access-Control-Allow-Origin") == "https://mralehsas.github.io", "Approved preflight missing allow-origin")
        assert_true("POST" in str(response.getheader("Access-Control-Allow-Methods") or ""), "Approved preflight missing POST")
        conn.close()

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("OPTIONS", "/api/update/start", headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        })
        response = conn.getresponse(); response.read()
        assert_true(response.status == 204, "Rejected-origin preflight should still complete")
        assert_true(response.getheader("Access-Control-Allow-Origin") is None, "Rejected origin received allow-origin")
        conn.close()
    finally:
        httpd.shutdown(); httpd.server_close(); thread.join(timeout=5)


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


def test_api_core_response_contract() -> None:
    import api_core

    response = api_core.json_response({"ok": True}, status=201, headers=(("X-Test", "yes"),))
    assert_true(response.status == 201, "ApiResponse status changed")
    assert_true(response.content_type == "application/json; charset=utf-8", "JSON content type changed")
    assert_true(json.loads(response.body.decode("utf-8")) == {"ok": True}, "JSON payload encoding changed")
    assert_true(("X-Test", "yes") in response.headers, "ApiResponse custom header missing")


def test_api_core_cors_policy() -> None:
    import api_core

    assert_true(api_core.allowed_cors_origin("https://mralehsas.github.io") == "https://mralehsas.github.io", "Pages origin rejected")
    assert_true(api_core.allowed_cors_origin("http://127.0.0.1:8872") == "http://127.0.0.1:8872", "Local 127.0.0.1 rejected")
    assert_true(api_core.allowed_cors_origin("http://localhost:8872") == "http://localhost:8872", "Localhost rejected")
    assert_true(api_core.allowed_cors_origin("https://evil.example") is None, "Unknown origin allowed")
    headers = dict(api_core.cors_headers("https://mralehsas.github.io"))
    assert_true(headers.get("Access-Control-Allow-Origin") == "https://mralehsas.github.io", "CORS allow-origin missing")
    assert_true("GET" in headers.get("Access-Control-Allow-Methods", ""), "CORS GET method missing")
    assert_true("POST" in headers.get("Access-Control-Allow-Methods", ""), "CORS POST method missing")


def test_cloud_update_snapshot_contract() -> None:
    import api_core

    payload = api_core.cloud_update_snapshot()
    assert_true(payload["running"] is False, "Cloud update must never claim a background worker is running")
    assert_true(payload["status"] == "console_only", "Cloud update status must be console_only")
    assert_true(payload["stage"] == "console", "Cloud update stage must be console")


def test_api_core_health_and_unknown_routes() -> None:
    import api_core

    update = api_core.cloud_update_snapshot()
    runtime = {"deployment": "test", "data_dir": "/tmp/albaz", "external_data_dir": True}
    response = api_core.handle_get("/api/health", "", update_state=update, runtime=runtime)
    payload = json.loads(response.body.decode("utf-8"))
    assert_true(response.status == 200, "Health route failed")
    assert_true(payload["status"] == "ok", "Health status changed")
    assert_true(payload["application"] == "Asteroid Archive", "Health application changed")
    assert_true(payload["version"] == "0.7.2", "Scientific version changed")
    assert_true(payload["runtime"] == runtime, "Runtime metadata not preserved")

    missing = api_core.handle_get("/api/does-not-exist", "")
    missing_payload = json.loads(missing.body.decode("utf-8"))
    assert_true(missing.status == 404, "Unknown API route must be 404")
    assert_true(missing_payload["error"] == "Unknown API route", "Unknown-route payload changed")


def test_api_core_proxy_and_horizons_are_transport_neutral() -> None:
    import api_core

    original_fetch = api_core.fetch_json
    original_track = api_core.get_orbit_track
    api_core.CACHE.clear()
    try:
        api_core.fetch_json = lambda url, params, timeout=45: {
            "signature": {"source": "NASA/JPL", "version": "1.5"},
            "count": 0,
            "fields": [],
            "data": [],
        }
        cad = api_core.handle_get("/api/cad", "date-min=2026-09-02&date-max=2026-09-03")
        assert_true(cad.status == 200, "CAD proxy did not return 200")
        assert_true(dict(cad.headers).get("X-Archive-Cache") == "MISS", "First CAD response must be cache MISS")

        api_core.get_orbit_track = lambda target, start, **kwargs: {
            "target": target,
            "start": start,
            "points": [],
            "source": "NASA/JPL Horizons",
        }
        track = api_core.handle_get("/api/horizons/track", "target=99942&start=2026-09-02&days=10&step=2&timeout=10")
        track_payload = json.loads(track.body.decode("utf-8"))
        assert_true(track.status == 200, "Horizons route failed")
        assert_true(track_payload["target"] == "99942", "Horizons target changed")
    finally:
        api_core.fetch_json = original_fetch
        api_core.get_orbit_track = original_track
        api_core.CACHE.clear()


def test_cloud_update_post_policy() -> None:
    import api_core

    start = api_core.handle_cloud_post("/api/update/start", b"{}")
    start_payload = json.loads(start.body.decode("utf-8"))
    assert_true(start.status == 503, "Cloud update start must return 503")
    assert_true(start_payload["reason"] == "console_administered", "Cloud update start reason changed")

    cancel = api_core.handle_cloud_post("/api/update/cancel", b"{}")
    cancel_payload = json.loads(cancel.body.decode("utf-8"))
    assert_true(cancel.status == 409, "Cloud update cancel must return 409")
    assert_true(cancel_payload["reason"] == "no_cloud_background_worker", "Cloud cancel reason changed")


def test_local_http_adapter_uses_shared_core() -> None:
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
        conn.request("GET", "/api/health", headers={"Origin": "https://mralehsas.github.io"})
        response = conn.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        assert_true(response.status == 200, "Local shared-core health failed")
        assert_true(payload["version"] == "0.7.2", "Local scientific version changed")
        assert_true(response.getheader("Access-Control-Allow-Origin") == "https://mralehsas.github.io", "Local shared CORS failed")
        conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_server_delegation_contract() -> None:
    text = (ROOT / "server.py").read_text(encoding="utf-8")
    assert_true("from api_core import" in text, "server.py does not import shared API core")
    assert_true("handle_get(" in text, "server.py does not delegate API GET routes")
    assert_true("def _proxy_api(" not in text, "Duplicate proxy implementation remains in server.py")
    assert_true("def _serve_horizons_track(" not in text, "Duplicate Horizons implementation remains in server.py")


def call_wsgi(
    method: str,
    path: str,
    *,
    query: str = "",
    origin: str | None = None,
    body: bytes = b"",
) -> tuple[str, dict[str, str], bytes]:
    import io
    import pythonanywhere_wsgi

    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]], exc_info=None):
        captured["status"] = status
        captured["headers"] = headers

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": "application/json",
        "wsgi.input": io.BytesIO(body),
    }
    if origin is not None:
        environ["HTTP_ORIGIN"] = origin
    chunks = pythonanywhere_wsgi.application(environ, start_response)
    payload = b"".join(chunks)
    return str(captured["status"]), dict(captured["headers"]), payload


def test_pythonanywhere_wsgi_health_and_cors() -> None:
    status, headers, body = call_wsgi("GET", "/api/health", origin="https://mralehsas.github.io")
    payload = json.loads(body.decode("utf-8"))
    assert_true(status.startswith("200 "), "WSGI health did not return 200")
    assert_true(payload["application"] == "Asteroid Archive", "WSGI health application changed")
    assert_true(payload["version"] == "0.7.2", "WSGI scientific version changed")
    assert_true(payload["runtime"]["deployment"] == "pythonanywhere", "WSGI deployment metadata missing")
    assert_true(headers.get("Access-Control-Allow-Origin") == "https://mralehsas.github.io", "WSGI Pages CORS missing")


def test_pythonanywhere_wsgi_preflight_and_rejected_origin() -> None:
    status, headers, body = call_wsgi("OPTIONS", "/api/update/start", origin="https://mralehsas.github.io")
    assert_true(status.startswith("204 "), "WSGI preflight did not return 204")
    assert_true(body == b"", "WSGI preflight must have an empty body")
    assert_true(headers.get("Access-Control-Allow-Origin") == "https://mralehsas.github.io", "WSGI preflight allow-origin missing")

    status, headers, _ = call_wsgi("OPTIONS", "/api/update/start", origin="https://evil.example")
    assert_true(status.startswith("204 "), "Unknown-origin preflight should still complete")
    assert_true("Access-Control-Allow-Origin" not in headers, "Unknown origin received CORS")


def test_pythonanywhere_wsgi_cloud_update_policy() -> None:
    status, _, body = call_wsgi("POST", "/api/update/start", origin="https://mralehsas.github.io", body=b"{}")
    payload = json.loads(body.decode("utf-8"))
    assert_true(status.startswith("503 "), "PythonAnywhere update start must return 503")
    assert_true(payload["reason"] == "console_administered", "PythonAnywhere update policy changed")


def test_pythonanywhere_wsgi_method_and_unknown_route_errors() -> None:
    status, _, body = call_wsgi("DELETE", "/api/health")
    payload = json.loads(body.decode("utf-8"))
    assert_true(status.startswith("405 "), "Unsupported WSGI method must return 405")
    assert_true(payload["error"] == "Method not allowed", "WSGI method error changed")

    status, _, body = call_wsgi("GET", "/api/not-real")
    payload = json.loads(body.decode("utf-8"))
    assert_true(status.startswith("404 "), "Unknown WSGI API route must return 404")
    assert_true(payload["error"] == "Unknown API route", "WSGI unknown-route payload changed")


def test_cache_maintenance_deletes_only_stale_generated_files() -> None:
    import time
    from pathlib import Path
    import cache_maintenance

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        horizons = root / "horizons_cache"
        horizons.mkdir()
        old_file = horizons / "old.json"
        new_file = horizons / "new.json"
        live = root / "live-cache.js"
        db = root / "asteroid_archive.db"
        old_file.write_text("old", encoding="utf-8")
        new_file.write_text("new", encoding="utf-8")
        live.write_text("cache", encoding="utf-8")
        db.write_text("must-survive", encoding="utf-8")

        now = time.time()
        old_time = now - 40 * 86400
        os.utime(old_file, (old_time, old_time))
        os.utime(live, (old_time, old_time))

        report = cache_maintenance.prune_generated_caches(
            horizons_dir=horizons,
            live_cache=live,
            max_age_days=30,
            now=now,
        )
        assert_true(not old_file.exists(), "Old Horizons cache survived")
        assert_true(not live.exists(), "Old live-cache survived")
        assert_true(new_file.exists(), "Fresh Horizons cache was deleted")
        assert_true(db.exists(), "SQLite file was deleted by cache maintenance")
        assert_true(report["files_deleted"] == 2, "Cache maintenance deleted unexpected file count")


def test_pythonanywhere_deployment_contract() -> None:
    guide = (ROOT / "PYTHONANYWHERE_DEPLOYMENT.md").read_text(encoding="utf-8")
    assert_true(not (ROOT / "render.yaml").exists(), "Render blueprint still exists")
    assert_true(not (ROOT / "RENDER_DEPLOYMENT.md").exists(), "Render deployment guide still exists")
    required = (
        "pythonanywhere_wsgi.application",
        "$HOME/.albaz-asteroid-data",
        "https://mralehsas.github.io",
        "python update_data.py",
        "python cache_maintenance.py --max-age-days 30",
        "/api/health",
        "web-config.js",
    )
    for token in required:
        assert_true(token in guide, f"PythonAnywhere guide missing: {token}")


def main() -> int:
    tests = [
        test_runtime_paths_default,
        test_runtime_paths_environment_override,
        test_api_core_response_contract,
        test_api_core_cors_policy,
        test_cloud_update_snapshot_contract,
        test_api_core_health_and_unknown_routes,
        test_api_core_proxy_and_horizons_are_transport_neutral,
        test_cloud_update_post_policy,
        test_server_bind_environment_defaults,
        test_cors_preflight_http,
        test_server_delegation_contract,
        test_local_http_adapter_uses_shared_core,
        test_frontend_backend_contract,
        test_pythonanywhere_wsgi_health_and_cors,
        test_pythonanywhere_wsgi_preflight_and_rejected_origin,
        test_pythonanywhere_wsgi_cloud_update_policy,
        test_pythonanywhere_wsgi_method_and_unknown_route_errors,
        test_cache_maintenance_deletes_only_stale_generated_files,
        test_pythonanywhere_deployment_contract,
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
