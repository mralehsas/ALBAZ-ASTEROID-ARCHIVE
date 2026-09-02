#!/usr/bin/env python3
from pathlib import Path

path = Path(__file__).with_name("index.html")
text = path.read_text(encoding="utf-8")
original = text

replacements = [
    (
        "const payload = await fetchJson(isLocalServer() ? endpoint('object', { sstr: value }) : endpoint('sbdb', { sstr: value, 'phys-par': 'true', 'full-prec': 'true' }));",
        "const payload = await fetchJson(backendApiAvailable() ? endpoint('object', { sstr: value, refresh: '1' }) : endpoint('sbdb', { sstr: value, 'phys-par': 'true', 'full-prec': 'true' }));",
    ),
    (
        "record.profile = await fetchJson(isLocalServer() ? endpoint('object', { sstr: query }) : endpoint('sbdb', { sstr: query, 'phys-par': 'true', 'full-prec': 'true' }));",
        "record.profile = await fetchJson(backendApiAvailable() ? endpoint('object', { sstr: query, refresh: '1' }) : endpoint('sbdb', { sstr: query, 'phys-par': 'true', 'full-prec': 'true' }));",
    ),
    (
        "const profile = await fetchJson(isLocalServer() ? endpoint('object', { sstr: value }) : endpoint('sbdb', { sstr: value, 'phys-par': 'true', 'full-prec': 'true' }));",
        "const profile = await fetchJson(backendApiAvailable() ? endpoint('object', { sstr: value, refresh: '1' }) : endpoint('sbdb', { sstr: value, 'phys-par': 'true', 'full-prec': 'true' }));",
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
        """const start = $('#startNasaUpdateButton');
    if (start) {
      start.disabled = running || !backendApiAvailable();
      const startLabel = start.querySelector('b');
      if (startLabel) startLabel.textContent = consoleOnly ? t('refreshLiveNasa') : t('startNasaUpdate');
    }""",
    ),
    (
        """  async function startNasaUpdate(event) {
    event?.preventDefault();
    if (!backendApiAvailable()) { toast(t('engineLocalOnly'), 'error'); return; }
    try {
      const payload = await postJson(endpoint('updateStart'), engineConfig());""",
        """  async function startNasaUpdate(event) {
    event?.preventDefault();
    if (!backendApiAvailable()) { toast(t('engineLocalOnly'), 'error'); return; }
    const consoleOnly = state.engineState?.status === 'console_only';
    if (consoleOnly && !isLocalServer()) {
      await loadAllData();
      renderEngineState(state.engineState || state.health?.update || { status:'console_only', running:false, percent:0, stage:'LIVE', logs:[] });
      return;
    }
    try {
      const payload = await postJson(endpoint('updateStart'), engineConfig());""",
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
