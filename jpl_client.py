#!/usr/bin/env python3
"""Shared, serialized HTTP client for official NASA/JPL services.

The SSD/CNEOS fair-use policy requires one API request at a time.  Every live
request made by Asteroid Archive passes through the process-wide lock below.
"""
from __future__ import annotations

import json
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Final

VERSION: Final[str] = "0.7.2"
REQUEST_LOCK = threading.RLock()

EXPECTED_API_VERSIONS: Final[dict[str, str]] = {
    "cad": "1.5",
    "fireball": "1.2",
    "sbdb": "1.3",
    "sentry": "2.0",
    "horizons": "1.3",
    "horizons_lookup": "1.1",
}

# JPL documentation currently lists Horizons API 1.3, while the live vector
# endpoint can still return signature 1.2. Both responses use the same vector
# table format consumed by this program. Treat 1.2 as a compatible live
# response instead of falsely reporting a network outage.
COMPATIBLE_API_VERSIONS: Final[dict[str, frozenset[str]]] = {
    service: frozenset({version}) for service, version in EXPECTED_API_VERSIONS.items()
}
COMPATIBLE_API_VERSIONS["horizons"] = frozenset({"1.2", "1.3"})


def network_error_label(exc: BaseException) -> str:
    text = str(exc).lower()
    if "api version mismatch" in text or "unsupported api version" in text:
        return "API_VERSION"
    reason = getattr(exc, "reason", None)
    if isinstance(reason, socket.gaierror) or "name resolution" in text or "getaddrinfo" in text:
        return "DNS"
    if isinstance(reason, ssl.SSLError) or isinstance(exc, ssl.SSLError) or "certificate" in text or "ssl" in text:
        return "SSL"
    if isinstance(reason, TimeoutError) or isinstance(exc, TimeoutError) or "timed out" in text:
        return "TIMEOUT"
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    return "NETWORK"


def signature_info(payload: dict[str, Any], service: str) -> dict[str, Any]:
    signature = payload.get("signature") if isinstance(payload.get("signature"), dict) else {}
    actual = str(signature.get("version") or "").strip() or None
    expected = EXPECTED_API_VERSIONS.get(service)
    compatible_versions = COMPATIBLE_API_VERSIONS.get(service, frozenset({expected}) if expected else frozenset())
    return {
        "source": signature.get("source") or "NASA/JPL",
        "version": actual,
        "expected_version": expected,
        "compatible_versions": sorted(compatible_versions),
        "version_match": (actual == expected) if actual and expected else None,
        "version_compatible": (actual in compatible_versions) if actual and compatible_versions else None,
    }



def ensure_signature(payload: dict[str, Any], service: str) -> dict[str, Any]:
    """Require a known-compatible API signature before parsing service data.

    Exact equality with the documentation version is recorded as ``version_match``.
    A live JPL response may temporarily expose an older compatible signature; in
    that case parsing continues and ``version_compatible`` remains true.
    """
    info = signature_info(payload, service)
    if info.get("version_compatible") is not True:
        accepted = ", ".join(info.get("compatible_versions") or []) or "none"
        raise RuntimeError(
            f"NASA/JPL {service} unsupported API version: "
            f"expected compatible version(s) {accepted}, received {info.get('version') or 'missing'}"
        )
    return info

def request_json(
    base_url: str,
    params: dict[str, Any] | None = None,
    *,
    timeout: int = 45,
    attempts: int = 3,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Perform one serialized GET request and decode a JSON object."""
    filtered = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
    query = urllib.parse.urlencode(filtered, doseq=True)
    url = f"{base_url}?{query}" if query else base_url
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent or f"AsteroidArchive/{VERSION} (+local scientific archive)",
            "Accept": "application/json",
        },
    )
    timeout = max(3, min(int(timeout), 120))
    attempts = max(1, min(int(attempts), 5))
    last_error: BaseException | None = None

    # NASA/JPL asks clients not to make simultaneous API requests.
    with REQUEST_LOCK:
        for attempt in range(1, attempts + 1):
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    status = int(getattr(response, "status", 200))
                    raw = response.read()
                if status != 200:
                    raise RuntimeError(f"HTTP {status}")
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("NASA/JPL returned non-object JSON")
                if payload.get("error"):
                    raise RuntimeError(str(payload.get("error")))
                if payload.get("code") and payload.get("message"):
                    raise RuntimeError(str(payload.get("message")))
                return payload
            except urllib.error.HTTPError as exc:
                last_error = exc
                retryable = exc.code in {408, 429, 500, 502, 503, 504}
                if not retryable or attempt >= attempts:
                    try:
                        detail = exc.read().decode("utf-8", errors="replace")[:1000]
                    except Exception:
                        detail = str(exc)
                    raise RuntimeError(f"NASA/JPL request failed [{network_error_label(exc)}]: {detail}") from exc
            except (urllib.error.URLError, TimeoutError, ssl.SSLError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt >= attempts:
                    raise RuntimeError(f"NASA/JPL connection failed [{network_error_label(exc)}]: {exc}") from exc
            except ValueError:
                raise
            except RuntimeError:
                raise
            time.sleep(min(4.0, 0.6 * (2 ** (attempt - 1))))

    raise RuntimeError(f"NASA/JPL connection failed: {last_error}")
