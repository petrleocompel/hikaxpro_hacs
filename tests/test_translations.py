"""Consistency checks for strings.json and translations/*.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "hikvision_axpro"
TRANSLATIONS = COMPONENT / "translations"
REFERENCE_PREFIX = "[%key:"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Map dotted key paths to leaf values."""
    flat: dict[str, Any] = {}
    for key, value in data.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{path}."))
        else:
            flat[path] = value
    return flat


EN = _flatten(_load(TRANSLATIONS / "en.json"))
OTHER_LANGUAGES = sorted(
    path for path in TRANSLATIONS.glob("*.json") if path.name != "en.json"
)


@pytest.mark.parametrize("path", OTHER_LANGUAGES, ids=lambda path: path.name)
def test_translation_keys_match_en(path: Path) -> None:
    """Every translation has exactly the keys of en.json."""
    keys = set(_flatten(_load(path)))
    assert sorted(set(EN) - keys) == [], "missing keys"
    assert sorted(keys - set(EN)) == [], "extra keys"


def test_strings_keys_exist_in_en() -> None:
    """Non-reference keys of strings.json are present in en.json."""
    strings = _flatten(_load(COMPONENT / "strings.json"))
    missing = sorted(
        key
        for key, value in strings.items()
        if not (isinstance(value, str) and value.startswith(REFERENCE_PREFIX))
        and key not in EN
    )
    assert missing == []


def test_en_has_invalid_code_exception() -> None:
    """ServiceValidationError(translation_key="invalid_code") has a message."""
    message = EN.get("exceptions.invalid_code.message")
    assert isinstance(message, str)
    assert message.strip()
