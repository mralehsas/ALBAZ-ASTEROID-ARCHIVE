#!/usr/bin/env python3
"""Offline deterministic verification for Asteroid Archive v0.7.

No internet connection is required. The Horizons request path is exercised with
controlled official-format JSON and vector tables, including object resolution,
CSV parsing, epoch alignment, distance calculation and cache writing.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import database
import horizons_engine
from jpl_client import COMPATIBLE_API_VERSIONS, EXPECTED_API_VERSIONS, ensure_signature, signature_info

ROOT = Path(__file__).resolve().parent


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def vector_payload(rows: list[tuple[float, str, float, float, float]]) -> dict:
    lines = ["JDTDB, Calendar Date, X, Y, Z, VX, VY, VZ,"]
    for jd, date, x, y, z in rows:
        lines.append(f"{jd:.9f}, {date}, {x:.12f}, {y:.12f}, {z:.12f}, 0.0, 0.0, 0.0,")
    return {
        "signature": {"source": "NASA/JPL Horizons API", "version": "1.2"},
        "result": "API VERSION: 1.2\n$$SOE\n" + "\n".join(lines) + "\n$$EOE\n",
    }


def test_vector_parser() -> None:
    payload = vector_payload([
        (2461000.5, "A.D. 2025-Nov-21 00:00:00.0000", 1.0, 2.0, 3.0),
        (2461001.5, "A.D. 2025-Nov-22 00:00:00.0000", 1.1, 2.1, 3.1),
    ])
    rows = horizons_engine.parse_horizons_vectors(payload["result"])
    assert_true(len(rows) == 2, "Horizons CSV parser did not return two rows")
    assert_true(rows[0]["x"] == 1.0 and rows[1]["z"] == 3.1, "Horizons vector values were parsed incorrectly")


def test_horizons_pipeline() -> None:
    original_request = horizons_engine.request_json
    original_cache = horizons_engine.CACHE_DIR
    with tempfile.TemporaryDirectory() as tmp:
        horizons_engine.CACHE_DIR = Path(tmp)

        target_rows = [
            (2461000.5, "A.D. 2025-Nov-21 00:00:00.0000", 1.05, 0.0, 0.0),
            (2461001.5, "A.D. 2025-Nov-22 00:00:00.0000", 1.01, 0.0, 0.0),
            (2461002.5, "A.D. 2025-Nov-23 00:00:00.0000", 1.08, 0.0, 0.0),
        ]
        earth_rows = [
            (2461000.5, "A.D. 2025-Nov-21 00:00:00.0000", 1.00, 0.0, 0.0),
            (2461001.5, "A.D. 2025-Nov-22 00:00:00.0000", 1.00, 0.0, 0.0),
            (2461002.5, "A.D. 2025-Nov-23 00:00:00.0000", 1.00, 0.0, 0.0),
        ]

        def fake_request(url, params=None, **kwargs):
            if "horizons_lookup" in url:
                return {
                    "signature": {"source": "NASA/JPL Horizons Lookup API", "version": "1.1"},
                    "result": [
                        {
                            "name": "99942 Apophis",
                            "pdes": "2004 MN4",
                            "spkid": "2099942",
                            "type": "asteroid (integrated barycenter)",
                            "alias": ["3264226", "K04M04N"],
                        },
                        {
                            "name": "199942 Audit Decoy",
                            "pdes": "2009 ZZ",
                            "spkid": "2199942",
                            "type": "asteroid (integrated barycenter)",
                            "alias": [],
                        },
                    ],
                }
            command = str((params or {}).get("COMMAND", ""))
            return vector_payload(earth_rows if "399" in command else target_rows)

        horizons_engine.request_json = fake_request
        try:
            result = horizons_engine.get_orbit_track("99942", "2025-11-21", days=2, step_days=1, refresh=True)
            assert_true(result["status"] == "success", "Horizons pipeline did not complete")
            assert_true(result["target_command"] == "DES=2004 MN4;", "Resolved Horizons command is incorrect")
            assert_true(len(result["target_points"]) == len(result["earth_points"]) == 3, "Epoch alignment failed")
            assert_true(result["nearest"]["index"] == 1, "Sampled nearest epoch is incorrect")
            assert_true(abs(result["nearest"]["distance_au"] - 0.01) < 1e-12, "Earth distance calculation is incorrect")
            assert_true(Path(tmp, result["cache"]["path"]).exists(), "Horizons cache was not written atomically")
            def offline_request(*args, **kwargs):
                raise RuntimeError("network deliberately disabled")
            horizons_engine.request_json = offline_request
            cached = horizons_engine.get_orbit_track("99942", "2025-11-21", days=2, step_days=1, refresh=False)
            assert_true(cached.get("cache", {}).get("hit") is True, "Valid Horizons cache was not reused offline")
        finally:
            horizons_engine.request_json = original_request
            horizons_engine.CACHE_DIR = original_cache


def test_lookup_ambiguity() -> None:
    original_request = horizons_engine.request_json

    def fake_request(url, params=None, **kwargs):
        return {
            "signature": {"source": "NASA/JPL Horizons Lookup API", "version": "1.1"},
            "result": [
                {"name": "Alpha", "pdes": "100", "spkid": "2000100", "alias": []},
                {"name": "Alpha II", "pdes": "101", "spkid": "2000101", "alias": []},
            ],
        }

    horizons_engine.request_json = fake_request
    try:
        try:
            horizons_engine.resolve_horizons_target("Al")
        except ValueError as exc:
            assert_true("Ambiguous" in str(exc), "Ambiguous lookup did not return a clear error")
        else:
            raise AssertionError("Ambiguous Horizons lookup was accepted")
    finally:
        horizons_engine.request_json = original_request


def test_database_backup_restore() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "audit.db"
        database.initialize(db_path)
        with sqlite3.connect(db_path) as con:
            con.execute("CREATE TABLE IF NOT EXISTS audit_probe(value TEXT)")
            con.execute("INSERT INTO audit_probe(value) VALUES ('before')")
            con.commit()
        backup = database.backup_database(path=db_path)
        with sqlite3.connect(db_path) as con:
            con.execute("DELETE FROM audit_probe")
            con.execute("INSERT INTO audit_probe(value) VALUES ('after')")
            con.commit()
        database.restore_database(backup, path=db_path)
        with sqlite3.connect(db_path) as con:
            value = con.execute("SELECT value FROM audit_probe").fetchone()[0]
            integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
            version = con.execute("PRAGMA user_version").fetchone()[0]
        database.remove_database_backup(backup)
        assert_true(value == "before", "SQLite rollback did not restore the last valid database")
        assert_true(integrity == "ok", "SQLite integrity_check failed")
        assert_true(version == 7, "SQLite schema version is not 7")


def test_versions_and_assets() -> None:
    expected = {
        "cad": "1.5", "fireball": "1.2", "sbdb": "1.3",
        "sentry": "2.0", "horizons": "1.3", "horizons_lookup": "1.1",
    }
    assert_true(EXPECTED_API_VERSIONS == expected, "Expected NASA/JPL API versions are not synchronized")
    assert_true(COMPATIBLE_API_VERSIONS["horizons"] == frozenset({"1.2", "1.3"}), "Horizons compatible versions are incorrect")
    for service, version in expected.items():
        info = signature_info({"signature": {"version": version, "source": "test"}}, service)
        assert_true(info["version_match"] is True, f"Version verifier failed for {service}")
        assert_true(info["version_compatible"] is True, f"Compatibility verifier failed for {service}")
    live_horizons = ensure_signature({"signature": {"version": "1.2", "source": "NASA/JPL Horizons API"}}, "horizons")
    assert_true(live_horizons["version_match"] is False and live_horizons["version_compatible"] is True, "Horizons 1.2 live response was not accepted")

    index = (ROOT / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "js" / "app.js").read_text(encoding="utf-8")
    for element_id in (
        "nasaUpdateForm", "testNasaConnectionButton", "orbitForm", "orbitCanvas",
        "orbitForceRefresh", "orbitMetricNearest", "compareCards", "compareContent", "approachTableBody", "fireballTableBody",
        "smartMapStage", "smart2DMarkerLayer", "smartGlobeCanvas", "smartGlobeMarkerLayer", "smartMapResetButton",
    ):
        assert_true(f'id="{element_id}"' in index, f"Required interface element is missing: {element_id}")
    assert_true("data-service=\"horizons_lookup\"" in index, "Horizons Lookup diagnostic card is missing")
    assert_true("results.push(await loadCloseApproaches())" in app, "Official API datasets are not loaded sequentially")
    assert_true("timeout: 90" in app, "Horizons timeout parameter is not exposed to the local bridge")
    assert_true("function renderSmartMap(" in app and "function initSmartGlobe(" in app, "Smart 2D/3D map engine is missing")
    assert_true("assets/blue_marble_1280.png" in index, "Smart map does not reuse the local NASA Blue Marble asset")


def main() -> int:
    tests = [
        test_vector_parser,
        test_horizons_pipeline,
        test_lookup_ambiguity,
        test_database_backup_restore,
        test_versions_and_assets,
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
