#!/usr/bin/env python3
from pathlib import Path

path = Path(__file__).with_name("index.html")
text = path.read_text(encoding="utf-8")
original = text

replacements = [
    (
        """      isLocalServer()\n        ? endpoint('object', { sstr: value })\n        : endpoint('sbdb', { sstr: value, 'phys-par': 'true', 'full-prec': 'true' })""",
        """      backendApiAvailable()\n        ? endpoint('object', { sstr: value, refresh: '1' })\n        : endpoint('sbdb', { sstr: value, 'phys-par': 'true', 'full-prec': 'true' })""",
    ),
    (
        "profileLimit: 'الملفات العلمية ذات الأولوية', includeProfiles: 'تحديث ملفات SBDB العلمية للأجرام الأقرب', startNasaUpdate: 'بدء تحديث NASA/JPL',",
        "profileLimit: 'الملفات العلمية ذات الأولوية', includeProfiles: 'تحديث ملفات SBDB العلمية للأجرام الأقرب', startNasaUpdate: 'بدء تحديث NASA/JPL', refreshLiveNasa: 'تحديث البيانات الحية NASA/JPL',",
    ),
    (
        "profileLimit: 'Priority scientific profiles', includeProfiles: 'Update SBDB profiles for the nearest objects', startNasaUpdate: 'Start NASA/JPL update',",
        "profileLimit: 'Priority scientific profiles', includeProfiles: 'Update SBDB profiles for the nearest objects', startNasaUpdate: 'Start NASA/JPL update', refreshLiveNasa: 'Refresh live NASA/JPL data',",
    ),
    (
        "const start = $('#startNasaUpdateButton'); if (start) start.disabled = running || consoleOnly || !isLocalServer();",
        """const start = $('#startNasaUpdateButton');\n    if (start) {\n      start.disabled = running || !backendApiAvailable();\n      const startLabel = start.querySelector('b');\n      if (startLabel) startLabel.textContent = consoleOnly ? t('refreshLiveNasa') : t('startNasaUpdate');\n    }""",
    ),
    (
        """  async function startNasaUpdate(event) {\n    event?.preventDefault();\n    if (!backendApiAvailable()) { toast(t('engineLocalOnly'), 'error'); return; }\n    try {\n      const payload = await postJson(endpoint('updateStart'), engineConfig());""",
        """  async function startNasaUpdate(event) {\n    event?.preventDefault();\n    if (!backendApiAvailable()) { toast(t('engineLocalOnly'), 'error'); return; }\n    const consoleOnly = state.engineState?.status === 'console_only';\n    if (consoleOnly && !isLocalServer()) {\n      await loadAllData();\n      renderEngineState(state.engineState || state.health?.update || { status:'console_only', running:false, percent:0, stage:'LIVE', logs:[] });\n      return;\n    }\n    try {\n      const payload = await postJson(endpoint('updateStart'), engineConfig());""",
    ),
]

for old, new in replacements:
    if old in text:
        if text.count(old) != 1:
            raise SystemExit(f"Refusing non-unique patch target: {old[:80]!r}")
        text = text.replace(old, new, 1)
    elif new not in text:
        raise SystemExit(f"Patch target not found and replacement absent: {old[:120]!r}")

if text != original:
    path.write_text(text, encoding="utf-8")
    print("patched index.html")
else:
    print("index.html already patched")
