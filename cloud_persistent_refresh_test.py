#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import api_core


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def decode(response):
    return json.loads(response.body.decode("utf-8"))


def test_cloud_live_refresh_is_persisted_and_bounded() -> None:
    calls: list[tuple[dict, str]] = []
    original_run_update = getattr(api_core, "run_update", None)
    original_recent = api_core.recent_update_runs

    def fake_run_update(config, trigger="manual", **_kwargs):
        calls.append((dict(config), str(trigger)))
        return {
            "status": "success",
            "run_id": 42,
            "generated_at": "2026-09-03T00:00:00+00:00",
            "config": dict(config),
            "counts": {"approaches": 321, "fireballs": 123, "sentry": 77},
            "logs": [],
        }

    try:
        if original_run_update is not None:
            api_core.run_update = fake_run_update
        api_core.recent_update_runs = lambda limit=20: []
        response = api_core.handle_cloud_post(
            "/api/update/live",
            json.dumps({
                "days": 9999,
                "distance_ld": 999,
                "approach_limit": 99999,
                "fireball_limit": 99999,
                "profile_limit": 250,
                "include_profiles": True,
            }).encode("utf-8"),
        )
        payload = decode(response)
        assert_true(response.status == 200, f"Cloud live refresh route missing or failed: {response.status} {payload}")
        assert_true(payload.get("persisted") is True, "Cloud live refresh must explicitly report persisted=true")
        assert_true(payload.get("accepted") is True, "Fresh cloud live refresh must be accepted")
        assert_true(bool(calls), "Cloud live refresh did not invoke the persistent update engine")
        config, trigger = calls[0]
        assert_true(trigger == "web-live", f"Unexpected persistent refresh trigger: {trigger}")
        assert_true(config["days"] <= 365, "Cloud live refresh days are not server-bounded")
        assert_true(config["distance_ld"] <= 10, "Cloud live refresh distance is not server-bounded")
        assert_true(config["approach_limit"] <= 2000, "Cloud live refresh approach limit is not server-bounded")
        assert_true(config["fireball_limit"] <= 2000, "Cloud live refresh fireball limit is not server-bounded")
        assert_true(config["profile_limit"] == 0, "Cloud live refresh must not batch-refresh SBDB profiles")
        assert_true(config["include_profiles"] is False, "Cloud live refresh must force include_profiles=false")
    finally:
        api_core.recent_update_runs = original_recent
        if original_run_update is not None:
            api_core.run_update = original_run_update


def test_cloud_refresh_implementation_is_unique() -> None:
    text = Path("api_core.py").read_text(encoding="utf-8")
    assert_true(text.count("def _bounded_live_refresh_config(") == 1, "Cloud refresh config helper is duplicated")
    assert_true(text.count("def _web_live_cooldown_remaining(") == 1, "Cloud refresh cooldown helper is duplicated")
    assert_true(text.count("def _cloud_live_refresh(") == 1, "Cloud refresh endpoint implementation is duplicated")
    assert_true(text.count("LIVE_REFRESH_COOLDOWN_SECONDS: Final[int] = 300") == 1, "Cloud refresh cooldown constant is duplicated")
    assert_true("run_update, run_update" not in text, "run_update import is duplicated")


def test_heavy_cloud_update_remains_console_only() -> None:
    response = api_core.handle_cloud_post("/api/update/start", b"{}")
    payload = decode(response)
    assert_true(response.status == 503, "Heavy cloud update unexpectedly became web-accessible")
    assert_true(payload.get("reason") == "console_administered", "Heavy update policy changed")


def test_frontend_uses_persisted_cloud_refresh_route() -> None:
    text = Path("index.html").read_text(encoding="utf-8")
    assert_true("updateLive: '/api/update/live'" in text, "Frontend endpoint map lacks /api/update/live")
    assert_true("postJson(endpoint('updateLive')" in text, "Cloud refresh button does not POST the persisted refresh endpoint")


def main() -> int:
    tests = [
        test_cloud_live_refresh_is_persisted_and_bounded,
        test_cloud_refresh_implementation_is_unique,
        test_heavy_cloud_update_remains_console_only,
        test_frontend_uses_persisted_cloud_refresh_route,
    ]
    for test in tests:
        test()
        print(f"[PASS] {test.__name__}")
    print(f"[PASS] {len(tests)}/{len(tests)} persistent cloud refresh tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
