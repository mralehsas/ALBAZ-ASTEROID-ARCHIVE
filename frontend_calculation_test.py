#!/usr/bin/env python3
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INDEX = (ROOT / "index.html").read_text(encoding="utf-8")


class InputParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.inputs: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "input":
            self.inputs.append({str(k): str(v) for k, v in attrs if k and v is not None})


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def numeric_default_is_step_valid(attrs: dict[str, str]) -> bool:
    if attrs.get("type") not in {"number", "range"}:
        return True
    if "value" not in attrs or "step" not in attrs or attrs.get("step") == "any":
        return True
    try:
        value = Decimal(attrs["value"])
        step = Decimal(attrs["step"])
        base = Decimal(attrs.get("min", "0"))
    except (InvalidOperation, ValueError):
        return True
    if step <= 0:
        return False
    quotient = (value - base) / step
    return quotient == quotient.to_integral_value()


def test_numeric_defaults_do_not_block_native_form_submit() -> None:
    parser = InputParser()
    parser.feed(INDEX)
    invalid = [
        attrs.get("id", "<unnamed>")
        for attrs in parser.inputs
        if not numeric_default_is_step_valid(attrs)
    ]
    assert_true(not invalid, f"Numeric defaults violate min/step and can block submit: {invalid}")


def test_analyzer_scientific_formula_contract() -> None:
    for fragment in (
        "const volume = Math.PI / 6 * d ** 3;",
        "const mass = volume * density;",
        "const energy = 0.5 * mass * (speedKm * 1000) ** 2;",
        "const mt = energy / TNT_J_PER_MEGATON;",
        "const TNT_J_PER_MEGATON = 4.184e15;",
    ):
        assert_true(fragment in INDEX, f"Analyzer scientific formula contract changed: {fragment}")


def test_remote_selected_object_orbit_uses_available_backend() -> None:
    start = INDEX.find("async function openSelectedOrbit()")
    end = INDEX.find("\n  function flattenObject", start)
    assert_true(start >= 0 and end > start, "openSelectedOrbit function not found")
    block = INDEX[start:end]
    assert_true(
        "if (backendApiAvailable()) await loadHorizonsTrack();" in block,
        "Selected-object orbit does not invoke Horizons through the configured web backend",
    )
    assert_true(
        "if (isLocalServer()) await loadHorizonsTrack();" not in block,
        "Selected-object orbit is still restricted to localhost",
    )


def test_manual_horizons_path_remains_backend_capable() -> None:
    start = INDEX.find("async function loadHorizonsTrack(event)")
    end = INDEX.find("\n  function projectOrbitPoint", start)
    assert_true(start >= 0 and end > start, "loadHorizonsTrack function not found")
    block = INDEX[start:end]
    assert_true("if (!backendApiAvailable())" in block, "Horizons lost backend availability guard")
    assert_true("endpoint('horizonsTrack'" in block, "Horizons backend endpoint missing")
    assert_true("target_points" in block and "earth_points" in block, "Horizons vector payload handling changed")


def run() -> None:
    tests = [
        test_numeric_defaults_do_not_block_native_form_submit,
        test_analyzer_scientific_formula_contract,
        test_remote_selected_object_orbit_uses_available_backend,
        test_manual_horizons_path_remains_backend_capable,
    ]
    passed = 0
    for test in tests:
        test()
        passed += 1
        print(f"PASS {test.__name__}")
    print(f"frontend calculation tests: {passed}/{len(tests)} PASS")


if __name__ == "__main__":
    run()
