#!/usr/bin/env python3
from pathlib import Path
import re


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old in text:
        if text.count(old) != 1:
            raise SystemExit(f"{label}: expected one patch target, found {text.count(old)}")
        return text.replace(old, new, 1)
    if new in text:
        return text
    raise SystemExit(f"{label}: patch target not found")


def regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1)
    if count == 1:
        return updated
    if replacement in text:
        return text
    raise SystemExit(f"{label}: regex target not found")


api_path = Path("api_core.py")
api = api_path.read_text(encoding="utf-8")
api = replace_once(api, "import time\nimport urllib.error", "import time\nimport threading\nimport urllib.error", "threading import")
api = replace_once(api, "from update_engine import fetch_json", "from update_engine import fetch_json, run_update", "run_update import")
api = replace_once(
    api,
    "CACHE_TTL_SECONDS: Final[int] = 300\nCACHE: dict[str, tuple[float, bytes, str]] = {}",
    "CACHE_TTL_SECONDS: Final[int] = 300\nCACHE: dict[str, tuple[float, bytes, str]] = {}\nLIVE_REFRESH_COOLDOWN_SECONDS: Final[int] = 300\nLIVE_REFRESH_LOCK = threading.Lock()",
    "live refresh constants",
)

helpers = r'''

def _bounded_live_refresh_config(payload: dict[str, Any]) -> dict[str, Any]:
    def bounded_int(key: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(float(payload.get(key, default)))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    def bounded_float(key: str, default: float, minimum: float, maximum: float) -> float:
        try:
            value = float(payload.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    return {
        "days": bounded_int("days", 365, 1, 365),
        "distance_ld": bounded_float("distance_ld", 10.0, 0.1, 10.0),
        "approach_limit": bounded_int("approach_limit", 2000, 1, 2000),
        "fireball_limit": bounded_int("fireball_limit", 2000, 1, 2000),
        # Public web refresh is intentionally limited to the three core datasets.
        # Individual SBDB searches are persisted separately through /api/object?refresh=1.
        "profile_limit": 0,
        "include_profiles": False,
    }


def _web_live_cooldown_remaining() -> int:
    now = dt.datetime.now(dt.timezone.utc)
    for row in recent_update_runs(limit=20):
        if str(row.get("trigger_name") or "") != "web-live" or str(row.get("status") or "") != "success":
            continue
        finished = str(row.get("finished_at") or "").strip()
        if not finished:
            continue
        try:
            stamp = dt.datetime.fromisoformat(finished.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=dt.timezone.utc)
            age = max(0.0, (now - stamp.astimezone(dt.timezone.utc)).total_seconds())
        except (TypeError, ValueError):
            continue
        return max(0, int(LIVE_REFRESH_COOLDOWN_SECONDS - age))
    return 0


def _cloud_live_refresh(body: bytes) -> ApiResponse:
    if len(body or b"") > 32768:
        return error_response(HTTPStatus.BAD_REQUEST, "Refresh request is too large", "Maximum request body is 32 KiB")
    try:
        payload = json.loads((body or b"{}").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return error_response(HTTPStatus.BAD_REQUEST, "Invalid refresh request", str(exc))
    if not isinstance(payload, dict):
        return error_response(HTTPStatus.BAD_REQUEST, "Invalid refresh request", "JSON body must be an object")

    if not LIVE_REFRESH_LOCK.acquire(blocking=False):
        return json_response({
            "accepted": False,
            "persisted": False,
            "reason": "refresh_in_progress",
            "message": "A persisted NASA/JPL refresh is already running.",
            "counts": counts(),
        }, status=HTTPStatus.CONFLICT)

    try:
        remaining = _web_live_cooldown_remaining()
        if remaining > 0:
            return json_response({
                "accepted": False,
                "persisted": True,
                "reason": "cooldown",
                "retry_after_seconds": remaining,
                "message": "The archive was refreshed recently; the persisted copy is already current.",
                "counts": counts(),
                "recent_updates": recent_update_runs(limit=3),
            })

        config = _bounded_live_refresh_config(payload)
        try:
            result = run_update(config, trigger="web-live")
        except Exception as exc:
            return error_response(HTTPStatus.BAD_GATEWAY, "Persisted NASA/JPL refresh failed", str(exc))

        if str(result.get("status") or "") != "success":
            return json_response({
                "accepted": True,
                "persisted": False,
                "reason": str(result.get("status") or "incomplete"),
                "result": result,
                "counts": counts(),
            }, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        return json_response({
            "accepted": True,
            "persisted": True,
            "reason": "updated",
            "message": "NASA/JPL core datasets were refreshed and committed to SQLite.",
            "result": result,
            "counts": result.get("counts") or counts(),
            "recent_updates": recent_update_runs(limit=3),
            "state": cloud_update_snapshot(),
        })
    finally:
        LIVE_REFRESH_LOCK.release()
'''
api = replace_once(
    api,
    "\ndef handle_cloud_post(path: str, body: bytes = b\"\") -> ApiResponse:\n",
    helpers + "\n\ndef handle_cloud_post(path: str, body: bytes = b\"\") -> ApiResponse:\n",
    "cloud live helpers",
)
api = replace_once(
    api,
    "def handle_cloud_post(path: str, body: bytes = b\"\") -> ApiResponse:\n    if path == \"/api/update/start\":",
    "def handle_cloud_post(path: str, body: bytes = b\"\") -> ApiResponse:\n    if path == \"/api/update/live\":\n        return _cloud_live_refresh(body)\n    if path == \"/api/update/start\":",
    "cloud live route",
)
api_path.write_text(api, encoding="utf-8")

index_path = Path("index.html")
index = index_path.read_text(encoding="utf-8")
index = replace_once(
    index,
    "updateHistory: '/api/update/history',\n      updateStart: '/api/update/start',",
    "updateHistory: '/api/update/history',\n      updateLive: '/api/update/live',\n      updateStart: '/api/update/start',",
    "frontend endpoint map",
)
index = regex_once(
    index,
    r"startNasaUpdate: 'بدء تحديث NASA/JPL'(?:, refreshLiveNasa: 'تحديث البيانات الحية NASA/JPL')+",
    "startNasaUpdate: 'بدء تحديث NASA/JPL', refreshLiveNasa: 'تحديث الأرشيف NASA/JPL — حفظ فعلي'",
    "Arabic persisted label",
)
index = regex_once(
    index,
    r"startNasaUpdate: 'Start NASA/JPL update'(?:, refreshLiveNasa: 'Refresh live NASA/JPL data')+",
    "startNasaUpdate: 'Start NASA/JPL update', refreshLiveNasa: 'Refresh NASA/JPL archive — persisted'",
    "English persisted label",
)
old_cloud = """    if (consoleOnly && !isLocalServer()) {
      await loadAllData();
      renderEngineState(state.engineState || state.health?.update || { status:'console_only', running:false, percent:0, stage:'LIVE', logs:[] });
      return;
    }"""
new_cloud = """    if (consoleOnly && !isLocalServer()) {
      const startButton = $('#startNasaUpdateButton');
      if (startButton) startButton.disabled = true;
      setLoading(true);
      setStatus(state.lang === 'ar' ? 'جارٍ تنزيل بيانات NASA/JPL وحفظها في SQLite…' : 'Downloading NASA/JPL data and committing it to SQLite…');
      try {
        const payload = await postJson(endpoint('updateLive'), engineConfig());
        await loadAllData({ announce:false });
        await refreshUpdateHistory();
        const saved = payload.counts || payload.result?.counts || {};
        if (payload.accepted === false && payload.reason === 'cooldown') {
          toast(state.lang === 'ar'
            ? `الأرشيف محدث حديثًا ومحفوظ في SQLite. أعد المحاولة بعد ${payload.retry_after_seconds || 0} ثانية.`
            : `The archive was refreshed recently and is persisted in SQLite. Retry in ${payload.retry_after_seconds || 0} seconds.`);
        } else {
          toast(state.lang === 'ar'
            ? `تم حفظ التحديث فعليًا في SQLite: ${saved.approaches || 0} اقتراب، ${saved.fireballs || 0} كرة نارية، ${saved.sentry || 0} Sentry.`
            : `Persisted to SQLite: ${saved.approaches || 0} approaches, ${saved.fireballs || 0} fireballs, ${saved.sentry || 0} Sentry objects.`);
        }
      } catch (error) {
        toast(`${t('updateFailed')}: ${error.message}`, 'error');
      } finally {
        setLoading(false);
        renderEngineState(state.engineState || state.health?.update || { status:'console_only', running:false, percent:0, stage:'console', logs:[] });
      }
      return;
    }"""
index = replace_once(index, old_cloud, new_cloud, "cloud persisted frontend branch")
index_path.write_text(index, encoding="utf-8")
print("persistent cloud refresh patch applied")
