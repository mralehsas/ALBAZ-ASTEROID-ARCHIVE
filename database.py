#!/usr/bin/env python3
"""Structured SQLite storage for Asteroid Archive v0.7.

The schema separates NASA/JPL source datasets while preserving each original JSON
record for forward compatibility. No missing value is invented: absent upstream
values remain NULL. Derived values belong in the UI/report layer and are labelled
as estimates.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from runtime_paths import BUNDLE_DATA_DIR, DB_PATH
VALID_DATASETS = {"approaches", "fireballs", "sentry", "objects", "meteorites", "impact_structures"}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=20000")
    return db


def initialize(path: Path = DB_PATH) -> None:
    with connect(path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS objects (
                object_id INTEGER PRIMARY KEY AUTOINCREMENT,
                spkid TEXT UNIQUE,
                designation TEXT,
                fullname TEXT,
                shortname TEXT,
                object_kind TEXT,
                neo INTEGER,
                pha INTEGER,
                orbit_class_code TEXT,
                orbit_class_name TEXT,
                source TEXT NOT NULL DEFAULT 'NASA/JPL SBDB',
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_objects_designation ON objects(designation);
            CREATE INDEX IF NOT EXISTS idx_objects_fullname ON objects(fullname);

            CREATE TABLE IF NOT EXISTS physical_properties (
                object_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                title TEXT,
                value_text TEXT,
                value_num REAL,
                sigma TEXT,
                units TEXT,
                notes TEXT,
                reference TEXT,
                quality TEXT NOT NULL DEFAULT 'published',
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(object_id, name),
                FOREIGN KEY(object_id) REFERENCES objects(object_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS orbital_elements (
                object_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                title TEXT,
                label TEXT,
                value_text TEXT,
                value_num REAL,
                sigma TEXT,
                units TEXT,
                epoch TEXT,
                quality TEXT NOT NULL DEFAULT 'published',
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(object_id, name),
                FOREIGN KEY(object_id) REFERENCES objects(object_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS close_approaches (
                record_key TEXT PRIMARY KEY,
                designation TEXT,
                fullname TEXT,
                close_date TEXT,
                jd TEXT,
                distance_au REAL,
                distance_min_au REAL,
                distance_max_au REAL,
                relative_velocity_kms REAL,
                vinf_kms REAL,
                time_uncertainty TEXT,
                absolute_magnitude REAL,
                diameter_km REAL,
                diameter_sigma_km REAL,
                orbit_id TEXT,
                body TEXT,
                source_mode TEXT,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ca_date ON close_approaches(close_date);
            CREATE INDEX IF NOT EXISTS idx_ca_designation ON close_approaches(designation);
            CREATE INDEX IF NOT EXISTS idx_ca_distance ON close_approaches(distance_au);

            CREATE TABLE IF NOT EXISTS fireballs (
                event_key TEXT PRIMARY KEY,
                event_date TEXT,
                radiated_energy_1e10j REAL,
                impact_energy_kt REAL,
                latitude REAL,
                latitude_dir TEXT,
                longitude REAL,
                longitude_dir TEXT,
                altitude_km REAL,
                velocity_kms REAL,
                vx REAL,
                vy REAL,
                vz REAL,
                source_mode TEXT,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_fireball_date ON fireballs(event_date DESC);
            CREATE INDEX IF NOT EXISTS idx_fireball_energy ON fireballs(impact_energy_kt DESC);

            CREATE TABLE IF NOT EXISTS sentry_risks (
                designation TEXT PRIMARY KEY,
                fullname TEXT,
                method TEXT,
                cumulative_probability REAL,
                palermo_cumulative REAL,
                palermo_max REAL,
                torino_max REAL,
                potential_impacts INTEGER,
                impact_energy_mt REAL,
                impact_velocity_kms REAL,
                absolute_magnitude REAL,
                diameter_km REAL,
                mass_kg REAL,
                first_observation TEXT,
                last_observation TEXT,
                source_mode TEXT,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sentry_probability ON sentry_risks(cumulative_probability DESC);

            CREATE TABLE IF NOT EXISTS meteorites (
                record_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                name_ar TEXT,
                status TEXT,
                event_kind TEXT,
                event_year INTEGER,
                country TEXT,
                country_ar TEXT,
                region TEXT,
                classification TEXT,
                mass_kg REAL,
                mass_text TEXT,
                latitude REAL,
                longitude REAL,
                linked_asteroid TEXT,
                source_name TEXT,
                source_url TEXT,
                quality TEXT,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_meteorites_name ON meteorites(name);
            CREATE INDEX IF NOT EXISTS idx_meteorites_year ON meteorites(event_year DESC);
            CREATE INDEX IF NOT EXISTS idx_meteorites_country ON meteorites(country);
            CREATE INDEX IF NOT EXISTS idx_meteorites_class ON meteorites(classification);

            CREATE TABLE IF NOT EXISTS impact_structures (
                record_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                name_ar TEXT,
                category TEXT,
                country TEXT,
                country_ar TEXT,
                region TEXT,
                latitude REAL,
                longitude REAL,
                diameter_km REAL,
                diameter_text TEXT,
                age_ma REAL,
                age_text TEXT,
                target_type TEXT,
                impactor_type TEXT,
                buried INTEGER,
                confirmed INTEGER,
                source_name TEXT,
                source_url TEXT,
                quality TEXT,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_impacts_name ON impact_structures(name);
            CREATE INDEX IF NOT EXISTS idx_impacts_country ON impact_structures(country);
            CREATE INDEX IF NOT EXISTS idx_impacts_diameter ON impact_structures(diameter_km DESC);
            CREATE INDEX IF NOT EXISTS idx_impacts_age ON impact_structures(age_ma DESC);

            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS update_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                trigger_name TEXT NOT NULL,
                config_json TEXT NOT NULL,
                counts_json TEXT,
                error_text TEXT,
                log_json TEXT NOT NULL DEFAULT '[]'
            );
            CREATE INDEX IF NOT EXISTS idx_update_runs_started ON update_runs(started_at DESC);
            """
        )
        db.execute("PRAGMA user_version=7")


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _bool_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    text = str(value).strip().lower()
    if text in {"y", "yes", "true", "1"}:
        return 1
    if text in {"n", "no", "false", "0"}:
        return 0
    return None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _signed_coordinate(value: Any, direction: Any) -> float | None:
    number = _float(value)
    if number is None:
        return None
    return -abs(number) if str(direction or "").upper() in {"S", "W"} else abs(number)


def replace_close_approaches(records: Iterable[dict[str, Any]], *, path: Path = DB_PATH) -> int:
    rows = list(records)
    now = utc_now()
    initialize(path)
    with connect(path) as db:
        db.execute("DELETE FROM close_approaches")
        db.executemany(
            """
            INSERT INTO close_approaches(
                record_key, designation, fullname, close_date, jd, distance_au,
                distance_min_au, distance_max_au, relative_velocity_kms, vinf_kms,
                time_uncertainty, absolute_magnitude, diameter_km, diameter_sigma_km,
                orbit_id, body, source_mode, payload_json, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    f"{r.get('des') or r.get('fullname') or 'object'}|{r.get('cd') or i}",
                    r.get("des"), r.get("fullname"), r.get("cd"), r.get("jd"),
                    _float(r.get("dist")), _float(r.get("dist_min")), _float(r.get("dist_max")),
                    _float(r.get("v_rel")), _float(r.get("v_inf")), r.get("t_sigma_f"),
                    _float(r.get("h")), _float(r.get("diameter")), _float(r.get("diameter_sigma")),
                    r.get("orbit_id"), r.get("body") or "Earth", r.get("source_mode"), _json(r), now,
                )
                for i, r in enumerate(rows)
            ],
        )
    return len(rows)


def replace_fireballs(records: Iterable[dict[str, Any]], *, path: Path = DB_PATH) -> int:
    rows = list(records)
    now = utc_now()
    initialize(path)
    with connect(path) as db:
        db.execute("DELETE FROM fireballs")
        db.executemany(
            """
            INSERT INTO fireballs(
                event_key, event_date, radiated_energy_1e10j, impact_energy_kt,
                latitude, latitude_dir, longitude, longitude_dir, altitude_km,
                velocity_kms, vx, vy, vz, source_mode, payload_json, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    f"{r.get('date') or i}|{r.get('lat') or ''}{r.get('lat-dir') or ''}|{r.get('lon') or ''}{r.get('lon-dir') or ''}",
                    r.get("date"), _float(r.get("energy")), _float(r.get("impact-e")),
                    _signed_coordinate(r.get("lat"), r.get("lat-dir")), r.get("lat-dir"),
                    _signed_coordinate(r.get("lon"), r.get("lon-dir")), r.get("lon-dir"),
                    _float(r.get("alt")), _float(r.get("vel")), _float(r.get("vx")),
                    _float(r.get("vy")), _float(r.get("vz")), r.get("source_mode"), _json(r), now,
                )
                for i, r in enumerate(rows)
            ],
        )
    return len(rows)


def replace_sentry(records: Iterable[dict[str, Any]], *, path: Path = DB_PATH) -> int:
    rows = list(records)
    now = utc_now()
    initialize(path)
    with connect(path) as db:
        db.execute("DELETE FROM sentry_risks")
        db.executemany(
            """
            INSERT INTO sentry_risks(
                designation, fullname, method, cumulative_probability, palermo_cumulative,
                palermo_max, torino_max, potential_impacts, impact_energy_mt,
                impact_velocity_kms, absolute_magnitude, diameter_km, mass_kg,
                first_observation, last_observation, source_mode, payload_json, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    str(r.get("des") or r.get("id") or i), r.get("fullname"), r.get("method"),
                    _float(r.get("ip")), _float(r.get("ps_cum")), _float(r.get("ps_max")),
                    _float(r.get("ts_max")), _int(r.get("n_imp")), _float(r.get("energy")),
                    _float(r.get("v_imp")), _float(r.get("h")), _float(r.get("diameter")),
                    _float(r.get("mass")), r.get("first_obs"), r.get("last_obs"),
                    r.get("source_mode"), _json(r), now,
                )
                for i, r in enumerate(rows)
            ],
        )
    return len(rows)


def upsert_object_profile(payload: dict[str, Any], *, path: Path = DB_PATH) -> int:
    initialize(path)
    obj = payload.get("object") if isinstance(payload.get("object"), dict) else {}
    orbit = payload.get("orbit") if isinstance(payload.get("orbit"), dict) else {}
    spkid = str(obj.get("spkid") or obj.get("des") or obj.get("fullname") or "").strip()
    if not spkid:
        raise ValueError("SBDB response does not contain an object identifier")
    orbit_class = obj.get("orbit_class") if isinstance(obj.get("orbit_class"), dict) else {}
    now = utc_now()
    with connect(path) as db:
        db.execute(
            """
            INSERT INTO objects(
                spkid, designation, fullname, shortname, object_kind, neo, pha,
                orbit_class_code, orbit_class_name, payload_json, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(spkid) DO UPDATE SET
                designation=excluded.designation, fullname=excluded.fullname,
                shortname=excluded.shortname, object_kind=excluded.object_kind,
                neo=excluded.neo, pha=excluded.pha,
                orbit_class_code=excluded.orbit_class_code,
                orbit_class_name=excluded.orbit_class_name,
                payload_json=excluded.payload_json, updated_at=excluded.updated_at
            """,
            (
                spkid, obj.get("des"), obj.get("fullname"), obj.get("shortname"),
                obj.get("kind") or obj.get("prefix"), _bool_int(obj.get("neo")), _bool_int(obj.get("pha")),
                orbit_class.get("code"), orbit_class.get("name"), _json(payload), now,
            ),
        )
        object_id = int(db.execute("SELECT object_id FROM objects WHERE spkid=?", (spkid,)).fetchone()[0])
        db.execute("DELETE FROM physical_properties WHERE object_id=?", (object_id,))
        db.execute("DELETE FROM orbital_elements WHERE object_id=?", (object_id,))

        phys = payload.get("phys_par") if isinstance(payload.get("phys_par"), list) else []
        for index, item in enumerate(phys):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("title") or item.get("desc") or f"phys_{index}")
            db.execute(
                """
                INSERT INTO physical_properties(
                    object_id, name, title, value_text, value_num, sigma, units,
                    notes, reference, quality, payload_json, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    object_id, name, item.get("title") or item.get("desc"),
                    None if item.get("value") is None else str(item.get("value")), _float(item.get("value")),
                    None if item.get("sigma") is None else str(item.get("sigma")), item.get("units"),
                    item.get("notes"), item.get("ref") or item.get("reference"), "published", _json(item), now,
                ),
            )

        elements = orbit.get("elements") if isinstance(orbit.get("elements"), list) else []
        for index, item in enumerate(elements):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("label") or item.get("title") or f"element_{index}")
            db.execute(
                """
                INSERT INTO orbital_elements(
                    object_id, name, title, label, value_text, value_num, sigma,
                    units, epoch, quality, payload_json, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    object_id, name, item.get("title"), item.get("label"),
                    None if item.get("value") is None else str(item.get("value")), _float(item.get("value")),
                    None if item.get("sigma") is None else str(item.get("sigma")), item.get("units"),
                    str(orbit.get("epoch") or "") or None, "published", _json(item), now,
                ),
            )
    return object_id


def replace_meteorites(records: Iterable[dict[str, Any]], *, path: Path = DB_PATH) -> int:
    rows = list(records)
    now = utc_now()
    initialize(path)
    with connect(path) as db:
        db.execute("DELETE FROM meteorites")
        db.executemany(
            """
            INSERT INTO meteorites(
                record_id,name,name_ar,status,event_kind,event_year,country,country_ar,region,
                classification,mass_kg,mass_text,latitude,longitude,linked_asteroid,source_name,
                source_url,quality,payload_json,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    str(r.get("record_id") or f"meteorite-{i}"), r.get("name"), r.get("name_ar"),
                    r.get("status"), r.get("event_kind"), _int(r.get("year")), r.get("country"),
                    r.get("country_ar"), r.get("region"), r.get("classification"), _float(r.get("mass_kg")),
                    r.get("mass_text"), _float(r.get("latitude")), _float(r.get("longitude")),
                    r.get("linked_asteroid"), r.get("source_name"), r.get("source_url"),
                    r.get("quality") or "published", _json(r), now,
                )
                for i, r in enumerate(rows)
            ],
        )
    return len(rows)


def replace_impact_structures(records: Iterable[dict[str, Any]], *, path: Path = DB_PATH) -> int:
    rows = list(records)
    now = utc_now()
    initialize(path)
    with connect(path) as db:
        db.execute("DELETE FROM impact_structures")
        db.executemany(
            """
            INSERT INTO impact_structures(
                record_id,name,name_ar,category,country,country_ar,region,latitude,longitude,
                diameter_km,diameter_text,age_ma,age_text,target_type,impactor_type,buried,confirmed,
                source_name,source_url,quality,payload_json,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    str(r.get("record_id") or f"impact-{i}"), r.get("name"), r.get("name_ar"),
                    r.get("category"), r.get("country"), r.get("country_ar"), r.get("region"),
                    _float(r.get("latitude")), _float(r.get("longitude")), _float(r.get("diameter_km")),
                    r.get("diameter_text"), _float(r.get("age_ma")), r.get("age_text"), r.get("target_type"),
                    r.get("impactor_type"), _bool_int(r.get("buried")), _bool_int(r.get("confirmed")),
                    r.get("source_name"), r.get("source_url"), r.get("quality") or "published", _json(r), now,
                )
                for i, r in enumerate(rows)
            ],
        )
    return len(rows)


def _decode_rows(rows: Iterable[sqlite3.Row], field: str = "payload_json") -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        try:
            result.append(json.loads(row[field]))
        except (TypeError, json.JSONDecodeError):
            continue
    return result


def read_dataset(dataset: str, *, limit: int = 5000, path: Path = DB_PATH) -> list[dict[str, Any]]:
    if dataset not in VALID_DATASETS or not path.exists():
        return []
    initialize(path)
    limit = max(1, min(int(limit), 20000))
    with connect(path) as db:
        if dataset == "approaches":
            rows = db.execute("SELECT payload_json FROM close_approaches ORDER BY close_date ASC LIMIT ?", (limit,)).fetchall()
        elif dataset == "fireballs":
            rows = db.execute("SELECT payload_json FROM fireballs ORDER BY event_date DESC LIMIT ?", (limit,)).fetchall()
        elif dataset == "sentry":
            rows = db.execute("SELECT payload_json FROM sentry_risks ORDER BY cumulative_probability DESC LIMIT ?", (limit,)).fetchall()
        elif dataset == "meteorites":
            rows = db.execute("SELECT payload_json FROM meteorites ORDER BY event_year DESC, name ASC LIMIT ?", (limit,)).fetchall()
        elif dataset == "impact_structures":
            rows = db.execute("SELECT payload_json FROM impact_structures ORDER BY diameter_km DESC, name ASC LIMIT ?", (limit,)).fetchall()
        else:
            rows = db.execute("SELECT payload_json FROM objects ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    return _decode_rows(rows)


def get_object_profile(query: str, *, path: Path = DB_PATH) -> dict[str, Any] | None:
    if not path.exists():
        return None
    initialize(path)
    q = str(query or "").strip()
    if not q:
        return None
    pattern = f"%{q}%"
    with connect(path) as db:
        row = db.execute(
            """
            SELECT payload_json FROM objects
            WHERE spkid=? OR designation=? OR fullname LIKE ? OR shortname LIKE ?
            ORDER BY CASE WHEN spkid=? OR designation=? THEN 0 ELSE 1 END, updated_at DESC
            LIMIT 1
            """,
            (q, q, pattern, pattern, q, q),
        ).fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, json.JSONDecodeError):
        return None
    payload["archive_cache"] = {"hit": True, "stored_locally": True}
    return payload


def list_object_profiles(query: str = "", *, limit: int = 100, path: Path = DB_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    initialize(path)
    limit = max(1, min(int(limit), 1000))
    pattern = f"%{str(query).strip()}%"
    with connect(path) as db:
        rows = db.execute(
            """
            SELECT spkid, designation, fullname, shortname, object_kind, neo, pha,
                   orbit_class_code, orbit_class_name, updated_at
            FROM objects
            WHERE ?='' OR designation LIKE ? OR fullname LIKE ? OR shortname LIKE ? OR spkid LIKE ?
            ORDER BY updated_at DESC LIMIT ?
            """,
            (str(query).strip(), pattern, pattern, pattern, pattern, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def set_metadata(key: str, value: Any, *, path: Path = DB_PATH) -> None:
    initialize(path)
    text = value if isinstance(value, str) else _json(value)
    now = utc_now()
    with connect(path) as db:
        db.execute(
            """
            INSERT INTO metadata(key,value,updated_at) VALUES(?,?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, text, now),
        )


def metadata(*, path: Path = DB_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    initialize(path)
    with connect(path) as db:
        return {str(row["key"]): str(row["value"]) for row in db.execute("SELECT key,value FROM metadata")}


def counts(*, path: Path = DB_PATH) -> dict[str, int]:
    names = {
        "approaches": "close_approaches",
        "fireballs": "fireballs",
        "sentry": "sentry_risks",
        "objects": "objects",
        "physical_properties": "physical_properties",
        "orbital_elements": "orbital_elements",
        "meteorites": "meteorites",
        "impact_structures": "impact_structures",
    }
    if not path.exists():
        return {key: 0 for key in names}
    initialize(path)
    with connect(path) as db:
        return {key: int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for key, table in names.items()}


def begin_update_run(trigger: str, config: dict[str, Any], *, path: Path = DB_PATH) -> int:
    initialize(path)
    with connect(path) as db:
        cur = db.execute(
            "INSERT INTO update_runs(started_at,status,trigger_name,config_json) VALUES(?,?,?,?)",
            (utc_now(), "running", trigger, _json(config)),
        )
        return int(cur.lastrowid)


def finish_update_run(
    run_id: int,
    status: str,
    counts_value: dict[str, Any] | None,
    logs: list[dict[str, Any]],
    error: str | None = None,
    *,
    path: Path = DB_PATH,
) -> None:
    initialize(path)
    with connect(path) as db:
        db.execute(
            """
            UPDATE update_runs
            SET finished_at=?, status=?, counts_json=?, error_text=?, log_json=?
            WHERE run_id=?
            """,
            (utc_now(), status, _json(counts_value or {}), error, _json(logs), int(run_id)),
        )


def recent_update_runs(*, limit: int = 10, path: Path = DB_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    initialize(path)
    with connect(path) as db:
        rows = db.execute(
            "SELECT * FROM update_runs ORDER BY run_id DESC LIMIT ?", (max(1, min(int(limit), 100)),)
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for key in ("config_json", "counts_json", "log_json"):
            try:
                item[key.removesuffix("_json")] = json.loads(item.get(key) or ("[]" if key == "log_json" else "{}"))
            except json.JSONDecodeError:
                item[key.removesuffix("_json")] = [] if key == "log_json" else {}
            item.pop(key, None)
        result.append(item)
    return result


def seed_if_empty(*, path: Path = DB_PATH) -> bool:
    """Load bundled reference records when their respective local tables are empty."""
    initialize(path)
    changed = False
    current = counts(path=path)

    bootstrap = BUNDLE_DATA_DIR / "bootstrap.json"
    if bootstrap.exists() and not (current.get("approaches") or current.get("fireballs") or current.get("sentry")):
        try:
            payload = json.loads(bootstrap.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if payload:
            replace_close_approaches(payload.get("closeApproaches") or [], path=path)
            replace_fireballs(payload.get("fireballs") or [], path=path)
            replace_sentry(payload.get("sentry") or [], path=path)
            set_metadata("bootstrap_loaded_at", utc_now(), path=path)
            set_metadata("bootstrap_note", payload.get("note") or "bundled reference data", path=path)
            changed = True

    earth_history = BUNDLE_DATA_DIR / "earth_history.json"
    if earth_history.exists() and not (current.get("meteorites") and current.get("impact_structures")):
        try:
            payload = json.loads(earth_history.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if payload:
            replace_meteorites(payload.get("meteorites") or [], path=path)
            replace_impact_structures(payload.get("impact_structures") or [], path=path)
            set_metadata("earth_history_loaded_at", utc_now(), path=path)
            set_metadata("earth_history_note_ar", payload.get("note_ar") or "", path=path)
            set_metadata("earth_history_note_en", payload.get("note_en") or "", path=path)
            changed = True
    return changed


# Compatibility alias used by early v0.2 helper scripts.
def replace_dataset(dataset: str, records: Iterable[dict[str, Any]], *, path: Path = DB_PATH) -> int:
    if dataset == "approaches":
        return replace_close_approaches(records, path=path)
    if dataset == "fireballs":
        return replace_fireballs(records, path=path)
    if dataset == "sentry":
        return replace_sentry(records, path=path)
    if dataset == "meteorites":
        return replace_meteorites(records, path=path)
    if dataset == "impact_structures":
        return replace_impact_structures(records, path=path)
    raise ValueError(f"Unsupported dataset: {dataset}")


if __name__ == "__main__":
    initialize()
    print(DB_PATH)
    print(json.dumps(counts(), ensure_ascii=False, indent=2))


def backup_database(*, path: Path = DB_PATH) -> Path:
    """Create a consistent SQLite backup beside the live database."""
    initialize(path)
    backup_path = path.with_suffix(path.suffix + ".preupdate")
    if backup_path.exists():
        backup_path.unlink()
    source = connect(path)
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()
    return backup_path


def restore_database(backup_path: Path, *, path: Path = DB_PATH) -> None:
    """Restore a consistent backup into the live SQLite file."""
    if not backup_path.exists():
        return
    source = sqlite3.connect(backup_path)
    target = connect(path)
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()


def remove_database_backup(backup_path: Path | None) -> None:
    if backup_path and backup_path.exists():
        backup_path.unlink()
