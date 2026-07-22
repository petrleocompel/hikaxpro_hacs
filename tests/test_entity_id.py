"""Tests for entity ID helpers and platform contracts."""

from __future__ import annotations

import importlib.util
import re
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "hikvision_axpro"


def _install_ha_stubs() -> None:
    """Minimal homeassistant stubs so entity_id can load without full HA."""
    _ha = types.ModuleType("homeassistant")
    _ha_config_entries = types.ModuleType("homeassistant.config_entries")
    _ha_core = types.ModuleType("homeassistant.core")
    _ha_helpers = types.ModuleType("homeassistant.helpers")
    _ha_entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    _ha_util = types.ModuleType("homeassistant.util")

    def _fake_slugify(text: str) -> str:
        text = (text or "").lower()
        text = re.sub(r"[^a-z0-9]+", "_", text)
        return text.strip("_")

    _ha_util.slugify = _fake_slugify
    _ha_config_entries.ConfigEntry = object
    _ha_core.HomeAssistant = object
    _ha_entity_registry.async_get = MagicMock()
    _ha_entity_registry.async_entries_for_config_entry = MagicMock(return_value=[])
    _ha_helpers.entity_registry = _ha_entity_registry

    sys.modules.setdefault("homeassistant", _ha)
    sys.modules.setdefault("homeassistant.config_entries", _ha_config_entries)
    sys.modules.setdefault("homeassistant.core", _ha_core)
    sys.modules.setdefault("homeassistant.helpers", _ha_helpers)
    sys.modules.setdefault(
        "homeassistant.helpers.entity_registry", _ha_entity_registry
    )
    sys.modules.setdefault("homeassistant.util", _ha_util)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_install_ha_stubs()
entity_id = _load_module("hikvision_axpro_entity_id", COMPONENT / "entity_id.py")
model = _load_module("hikvision_axpro_model", COMPONENT / "model.py")

build_entity_id = entity_id.build_entity_id
has_invalid_object_id_chars = entity_id.has_invalid_object_id_chars
normalized_object_id = entity_id.normalized_object_id
DetectorType = model.DetectorType
zone_device_model = model.zone_device_model


def test_normalized_object_id_slugifies() -> None:
    assert normalized_object_id("AX PRO") == "ax_pro"
    assert normalized_object_id("Main-home") == "main_home"
    assert re.fullmatch(r"[a-z0-9_]+", normalized_object_id("Český ***", "Zone 7"))


def test_normalized_object_id_fallback_hash() -> None:
    result = normalized_object_id("***", fallback="")
    assert result.startswith("entity_")
    assert re.fullmatch(r"[a-z0-9_]+", result)


def test_has_invalid_object_id_chars() -> None:
    assert has_invalid_object_id_chars("sensor.AX PRO-temperature-0")
    assert has_invalid_object_id_chars("sensor.Main-home-battery-0")
    assert not has_invalid_object_id_chars("sensor.ax_pro_temperature_0")


def test_build_entity_id_shape() -> None:
    assert (
        build_entity_id("sensor", "AX PRO", "temperature", 0)
        == "sensor.ax_pro_temperature_0"
    )
    assert (
        build_entity_id("binary_sensor", "AX PRO", "magnet-shock", 8)
        == "binary_sensor.ax_pro_magnet_shock_8"
    )


def test_zone_device_model_always_str() -> None:
    assert zone_device_model("0x00001", None) == "Passive Infrared Detector"
    assert (
        zone_device_model(None, DetectorType.PIR_DETECTOR)
        == DetectorType.PIR_DETECTOR.value
    )
    assert isinstance(zone_device_model(None, DetectorType.SMOKE_DETECTOR), str)
    assert zone_device_model(None, None) == "Unknown"


@pytest.mark.parametrize(
    "filename",
    ("binary_sensor.py", "sensor.py", "switch.py"),
)
def test_platforms_do_not_assign_raw_device_name_entity_id(filename: str) -> None:
    content = (COMPONENT / filename).read_text(encoding="utf-8")
    assert "build_entity_id(" in content
    assert not re.search(
        r'self\.entity_id\s*=\s*f?["\'].*coordinator\.device_name',
        content,
    )
