#!/usr/bin/env python3
"""Audited JPL Horizons bridge for Asteroid Archive v0.7.

Live tracks are resolved through the official Horizons Lookup API, requested as
Sun-centred ecliptic-J2000 Cartesian vectors, parsed from the official CSV table,
and aligned by Julian date. No trajectory values are fabricated.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import math
import re
import time
from pathlib import Path
from typing import Any, Final

from jpl_client import ensure_signature, network_error_label, request_json, signature_info

ROOT: Final[Path] = Path(__file__).resolve().parent
CACHE_DIR: Final[Path] = ROOT / "data" / "horizons_cache"
VERSION: Final[str] = "0.7.2"
HORIZONS_URL: Final[str] = "https://ssd.jpl.nasa.gov/api/horizons.api"
LOOKUP_URL: Final[str] = "https://ssd.jpl.nasa.gov/api/horizons_lookup.api"
CACHE_MAX_AGE_SECONDS: Final[int] = 7 * 24 * 3600
AU_KM: Final[float] = 149_597_870.7
LD_KM: Final[float] = 384_400.0

SERVICE_TESTS: Final[list[tuple[str, str, dict[str, Any], str]]] = [
    ("cad", "https://ssd-api.jpl.nasa.gov/cad.api", {"limit": 1, "dist-max": "0.05"}, "cad"),
    ("fireball", "https://ssd-api.jpl.nasa.gov/fireball.api", {"limit": 1}, "fireball"),
    ("sbdb", "https://ssd-api.jpl.nasa.gov/sbdb.api", {"sstr": "99942", "phys-par": "false"}, "sbdb"),
    ("sentry", "https://ssd-api.jpl.nasa.gov/sentry.api", {}, "sentry"),
    ("horizons_lookup", LOOKUP_URL, {"sstr": "99942", "group": "ast"}, "horizons_lookup"),
]


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _to_float(value: Any) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_horizons_vectors(result_text: str) -> list[dict[str, Any]]:
    """Parse a Horizons VECTORS table in CSV or labelled text format."""
    text = str(result_text or "")
    if "$$SOE" not in text or "$$EOE" not in text:
        raise ValueError("Horizons response did not contain an ephemeris table")
    body = text.split("$$SOE", 1)[1].split("$$EOE", 1)[0]
    rows: list[dict[str, Any]] = []

    # CSV_FORMAT=YES: JDTDB, calendar date, X, Y, Z, VX, VY, VZ, ...
    reader = csv.reader(io.StringIO(body), skipinitialspace=True)
    for parts in reader:
        if not parts:
            continue
        jd = _to_float(parts[0])
        if jd is None or len(parts) < 5:
            continue
        date_text = str(parts[1]).strip()
        xyz = [_to_float(token) for token in parts[2:5]]
        if any(value is None for value in xyz):
            continue
        row: dict[str, Any] = {
            "jd": jd,
            "date": date_text,
            "x": float(xyz[0]),
            "y": float(xyz[1]),
            "z": float(xyz[2]),
        }
        if len(parts) >= 8:
            velocity = [_to_float(token) for token in parts[5:8]]
            if all(value is not None for value in velocity):
                row.update({"vx": velocity[0], "vy": velocity[1], "vz": velocity[2]})
        rows.append(row)
    if rows:
        return rows

    # Defensive parser for non-CSV labelled vector layout.
    chunks = re.split(r"(?=\n?\s*\d{7}\.\d+\s*=)", body)
    for chunk in chunks:
        jd_match = re.search(r"(\d{7}\.\d+)\s*=\s*([^\n]+)", chunk)
        xyz_match = re.search(
            r"X\s*=\s*([+\-\d.Ee]+)\s+Y\s*=\s*([+\-\d.Ee]+)\s+Z\s*=\s*([+\-\d.Ee]+)",
            chunk,
        )
        if not jd_match or not xyz_match:
            continue
        values = [_to_float(value) for value in xyz_match.groups()]
        if any(value is None for value in values):
            continue
        row = {
            "jd": float(jd_match.group(1)),
            "date": jd_match.group(2).strip(),
            "x": values[0], "y": values[1], "z": values[2],
        }
        velocity_match = re.search(
            r"VX\s*=\s*([+\-\d.Ee]+)\s+VY\s*=\s*([+\-\d.Ee]+)\s+VZ\s*=\s*([+\-\d.Ee]+)",
            chunk,
        )
        if velocity_match:
            velocity = [_to_float(value) for value in velocity_match.groups()]
            if all(value is not None for value in velocity):
                row.update({"vx": velocity[0], "vy": velocity[1], "vz": velocity[2]})
        rows.append(row)
    if not rows:
        raise ValueError("Unable to parse Horizons vector table")
    return rows


def _extract_horizons_error(result_text: str) -> str | None:
    text = str(result_text or "")
    lower = text.lower()
    markers = (
        "no matches found", "cannot find", "no ephemeris for target", "no data available",
        "outside the available time span", "ambiguous target", "input error", "error:",
    )
    if any(marker in lower for marker in markers):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        relevant = [line for line in lines if any(marker in line.lower() for marker in markers)]
        return " | ".join(relevant[:4])[:800] or "Horizons rejected the request"
    return None


def resolve_horizons_target(target: str, *, timeout: int = 20) -> dict[str, Any]:
    value = str(target or "").strip().rstrip(";")
    if not value:
        raise ValueError("Target designation or name is required")
    if len(value) > 80 or any(ord(ch) < 32 for ch in value):
        raise ValueError("Invalid target identifier")

    payload = request_json(
        LOOKUP_URL,
        {"sstr": value, "group": "ast", "format": "json"},
        timeout=timeout,
        attempts=3,
        user_agent=f"AsteroidArchiveHorizons/{VERSION}",
    )
    lookup_signature = ensure_signature(payload, "horizons_lookup")
    matches = payload.get("result") if isinstance(payload.get("result"), list) else []
    matches = [item for item in matches if isinstance(item, dict)]
    if not matches:
        raise ValueError(f"No asteroid matched '{value}' in JPL Horizons")

    # Exact IAU number, name, primary designation, SPK-ID or alias wins.
    needle = value.casefold()
    exact: list[dict[str, Any]] = []
    for item in matches:
        name_token = str(item.get("name") or "").strip()
        iau_number = re.match(r"^(\d+)\b", name_token)
        bare_name = re.sub(r"^\d+\s+", "", name_token).strip() or None
        tokens = [
            item.get("name"), bare_name, item.get("pdes"), item.get("spkid"),
            iau_number.group(1) if iau_number else None,
            *(item.get("alias") or []),
        ]
        if any(str(token or "").strip().casefold() == needle for token in tokens):
            exact.append(item)
    chosen_pool = exact or matches
    if len(chosen_pool) > 1:
        labels = ", ".join(str(item.get("name") or item.get("pdes") or item.get("spkid")) for item in chosen_pool[:6])
        raise ValueError(f"Ambiguous asteroid target '{value}': {labels}")
    item = chosen_pool[0]
    pdes = str(item.get("pdes") or "").strip()
    spkid = str(item.get("spkid") or "").strip()
    name = str(item.get("name") or pdes or value).strip()

    # A DES command forces the latest numerically integrated small-body solution.
    command = f"DES={pdes};" if pdes else (spkid or f"{value};")
    return {
        "input": value,
        "name": name,
        "pdes": pdes or None,
        "spkid": spkid or None,
        "type": item.get("type"),
        "aliases": item.get("alias") or [],
        "command": command,
        "lookup_signature": lookup_signature,
    }


def _query_vectors(command: str, start: str, stop: str, step_days: int, *, timeout: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params = {
        "format": "json",
        "COMMAND": f"'{command}'",
        "OBJ_DATA": "'NO'",
        "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'VECTORS'",
        "CENTER": "'500@10'",
        "START_TIME": f"'{start}'",
        "STOP_TIME": f"'{stop}'",
        "STEP_SIZE": f"'{step_days} d'",
        "OUT_UNITS": "'AU-D'",
        "REF_PLANE": "'ECLIPTIC'",
        "REF_SYSTEM": "'ICRF'",
        "VEC_TABLE": "'2'",
        "VEC_CORR": "'NONE'",
        "CSV_FORMAT": "'YES'",
        "TIME_DIGITS": "'MINUTES'",
        "TIME_TYPE": "'TDB'",
    }
    payload = request_json(
        HORIZONS_URL,
        params,
        timeout=timeout,
        attempts=3,
        user_agent=f"AsteroidArchiveHorizons/{VERSION}",
    )
    vector_signature = ensure_signature(payload, "horizons")
    result = str(payload.get("result") or "")
    error = _extract_horizons_error(result)
    if error:
        raise ValueError(error)
    vectors = parse_horizons_vectors(result)
    return vectors, vector_signature


def _align_by_jd(target_rows: list[dict[str, Any]], earth_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    # Horizons normally returns identical epochs; rounding protects against text precision differences.
    earth_by_jd = {round(float(row["jd"]), 9): row for row in earth_rows}
    target_aligned: list[dict[str, Any]] = []
    earth_aligned: list[dict[str, Any]] = []
    for row in target_rows:
        earth = earth_by_jd.get(round(float(row["jd"]), 9))
        if earth is not None:
            target_aligned.append(row)
            earth_aligned.append(earth)
    if not target_aligned:
        raise ValueError("Horizons target and Earth epochs could not be aligned")
    return target_aligned, earth_aligned


def _cache_path(target_key: str, start: str, days: int, step_days: int) -> Path:
    key = hashlib.sha256(f"v{VERSION}|{target_key}|{start}|{days}|{step_days}".encode("utf-8")).hexdigest()[:24]
    return CACHE_DIR / f"track_{key}.json"


def _read_cache(path: Path) -> dict[str, Any] | None:
    try:
        age = time.time() - path.stat().st_mtime
        if age > CACHE_MAX_AGE_SECONDS:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("engine_version") != VERSION:
            return None
        if not payload.get("target_points") or not payload.get("earth_points"):
            return None
        payload["cache"] = {"hit": True, "path": path.name, "age_seconds": round(age)}
        return payload
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _find_cached_track(target: str, start: str, days: int, step_days: int) -> dict[str, Any] | None:
    """Find a fresh v0.7 cache by the original label or any resolved alias."""
    if not CACHE_DIR.exists():
        return None
    needle = str(target or "").strip().casefold()
    try:
        paths = sorted(CACHE_DIR.glob("track_*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    except OSError:
        return None
    for path in paths:
        payload = _read_cache(path)
        if not payload:
            continue
        if str(payload.get("start")) != start or int(payload.get("days", -1)) != days or int(payload.get("step_days", -1)) != step_days:
            continue
        resolved = payload.get("resolved_target") if isinstance(payload.get("resolved_target"), dict) else {}
        resolved_name = str(resolved.get("name") or payload.get("target") or "").strip()
        bare_name = re.sub(r"^\d+\s+", "", resolved_name).strip() or None
        iau_number = re.match(r"^(\d+)\b", resolved_name)
        tokens = [
            payload.get("requested_target"), payload.get("target"), resolved.get("name"), bare_name,
            iau_number.group(1) if iau_number else None,
            resolved.get("pdes"), resolved.get("spkid"), *(resolved.get("aliases") or []),
        ]
        if any(str(token or "").strip().casefold() == needle for token in tokens):
            return payload
    return None


def get_orbit_track(
    target: str,
    start: str,
    *,
    days: int = 730,
    step_days: int = 5,
    timeout: int = 45,
    refresh: bool = False,
) -> dict[str, Any]:
    try:
        start_date = dt.date.fromisoformat(str(start))
    except ValueError as exc:
        raise ValueError("Start date must use YYYY-MM-DD") from exc
    days = max(2, min(int(days), 3650))
    step_days = max(1, min(int(step_days), 60))
    if math.ceil(days / step_days) > 600:
        step_days = max(step_days, math.ceil(days / 600))
    timeout = max(10, min(int(timeout), 90))
    stop_date = start_date + dt.timedelta(days=days)

    if not refresh:
        cached_by_label = _find_cached_track(str(target), start_date.isoformat(), days, step_days)
        if cached_by_label:
            return cached_by_label

    resolved = resolve_horizons_target(target, timeout=min(timeout, 30))
    cache_path = _cache_path(resolved.get("spkid") or resolved["command"], start_date.isoformat(), days, step_days)
    if cache_path.exists() and not refresh:
        cached = _read_cache(cache_path)
        if cached:
            return cached

    target_points, target_signature = _query_vectors(
        resolved["command"], start_date.isoformat(), stop_date.isoformat(), step_days, timeout=timeout
    )
    earth_points, earth_signature = _query_vectors(
        "399", start_date.isoformat(), stop_date.isoformat(), step_days, timeout=timeout
    )
    target_points, earth_points = _align_by_jd(target_points, earth_points)

    distances: list[float] = []
    for target_row, earth_row in zip(target_points, earth_points):
        dx = float(target_row["x"]) - float(earth_row["x"])
        dy = float(target_row["y"]) - float(earth_row["y"])
        dz = float(target_row["z"]) - float(earth_row["z"])
        distances.append(math.sqrt(dx * dx + dy * dy + dz * dz))
    nearest_index = min(range(len(distances)), key=distances.__getitem__)
    nearest_au = distances[nearest_index]

    payload = {
        "status": "success",
        "engine_version": VERSION,
        "source": "NASA/JPL Horizons",
        "source_mode": "live",
        "generated_at": utc_now(),
        "target": resolved["name"],
        "requested_target": str(target).strip(),
        "resolved_target": resolved,
        "target_command": resolved["command"],
        "start": start_date.isoformat(),
        "stop": stop_date.isoformat(),
        "days": days,
        "step_days": step_days,
        "reference_frame": "Sun-centred ecliptic J2000 / ICRF",
        "units": "AU and AU/day",
        "time_scale": "TDB",
        "target_points": target_points,
        "earth_points": earth_points,
        "nearest": {
            "index": nearest_index,
            "date": target_points[nearest_index].get("date"),
            "jd_tdb": target_points[nearest_index].get("jd"),
            "distance_au": nearest_au,
            "distance_km": nearest_au * AU_KM,
            "distance_ld": nearest_au * AU_KM / LD_KM,
            "sampling_note": "Minimum among sampled epochs; refine the time step for close encounters.",
        },
        "signatures": {
            "lookup": resolved.get("lookup_signature"),
            "target": target_signature,
            "earth": earth_signature,
        },
        "cache": {"hit": False, "path": cache_path.name, "max_age_seconds": CACHE_MAX_AGE_SECONDS},
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = cache_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temp_path.replace(cache_path)
    return payload


def _test_one(name: str, base_url: str, params: dict[str, Any], service_key: str, timeout: int) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        payload = request_json(base_url, params, timeout=timeout, attempts=2, user_agent=f"AsteroidArchiveDiagnostics/{VERSION}")
        signature = signature_info(payload, service_key)
        return {
            "service": name, "ok": True, "status": "online",
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "host": base_url.split("/")[2], "checked_at": utc_now(), **signature,
        }
    except Exception as exc:
        return {
            "service": name, "ok": False, "status": "offline",
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "host": base_url.split("/")[2], "error_type": network_error_label(exc),
            "error": str(exc), "checked_at": utc_now(),
        }


def test_nasa_services(*, timeout: int = 10) -> dict[str, Any]:
    """Test official services sequentially in compliance with JPL fair-use policy."""
    timeout = max(3, min(int(timeout), 30))
    started = time.perf_counter()
    results: dict[str, dict[str, Any]] = {}
    for name, base_url, params, service_key in SERVICE_TESTS:
        results[name] = _test_one(name, base_url, params, service_key, timeout)

    # A metadata-only Horizons request can succeed while vector generation fails;
    # therefore execute and parse a one-day Earth vector table as the final test.
    try:
        today = dt.date.today()
        vector_started = time.perf_counter()
        rows, signature = _query_vectors("399", today.isoformat(), (today + dt.timedelta(days=1)).isoformat(), 1, timeout=timeout)
        results["horizons"] = {
            "service": "horizons", "ok": bool(rows), "status": "online" if rows else "offline",
            "latency_ms": round((time.perf_counter() - vector_started) * 1000, 1),
            "host": "ssd.jpl.nasa.gov", "checked_at": utc_now(), "vector_rows": len(rows), **signature,
        }
    except Exception as exc:
        results["horizons"] = {
            "service": "horizons", "ok": False, "status": "offline",
            "host": "ssd.jpl.nasa.gov", "error_type": network_error_label(exc),
            "error": str(exc), "checked_at": utc_now(),
        }

    order = ["cad", "fireball", "sbdb", "sentry", "horizons_lookup", "horizons"]
    ordered = {name: results[name] for name in order}
    online = sum(1 for item in ordered.values() if item.get("ok"))
    warnings = [name for name, item in ordered.items() if item.get("version_match") is False]
    return {
        "status": "online" if online == len(ordered) else "partial" if online else "offline",
        "online_services": online, "total_services": len(ordered),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        "checked_at": utc_now(), "services": ordered,
        "api_version_warnings": warnings,
        "request_policy": "sequential",
    }


if __name__ == "__main__":
    print(json.dumps(test_nasa_services(timeout=8), ensure_ascii=False, indent=2))
