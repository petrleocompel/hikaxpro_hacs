"""Tests for entity ID helpers and platform contracts."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from custom_components.hikvision_axpro.entity_id import (
    build_entity_id,
    has_invalid_object_id_chars,
    normalized_mac,
    normalized_object_id,
)
from custom_components.hikvision_axpro.model import DetectorType, zone_device_model

COMPONENT = (
    Path(__file__).resolve().parents[1] / "custom_components" / "hikvision_axpro"
)

PLATFORM_FILES = (
    "binary_sensor.py",
    "sensor.py",
    "switch.py",
    "button.py",
    "host_entities.py",
    "peripheral_entities.py",
    "siren_entities.py",
)

MAC = "a4d5c26bb859"


def test_normalized_mac_is_one_compact_token() -> None:
    """A MAC is one identifier, so it stays one token."""
    assert normalized_mac("A4:D5:C2:6B:B8:59") == MAC
    assert normalized_mac("a4-d5-c2-6b-b8-59") == MAC
    assert normalized_mac(MAC) == MAC
    assert normalized_mac(None) == ""


def test_normalized_object_id_slugifies() -> None:
    assert normalized_object_id("AX PRO") == "ax_pro"
    assert normalized_object_id("Main-home") == "main_home"
    assert re.fullmatch(r"[a-z0-9_]+", normalized_object_id("Český ***", "Zone 7"))


def test_normalized_object_id_falls_back_then_hashes() -> None:
    assert normalized_object_id("", fallback="Zone 7") == "zone_7"

    # Nothing sluggable at all: a deterministic id rather than an empty one.
    result = normalized_object_id("", fallback="")
    assert result.startswith("entity_")
    assert re.fullmatch(r"[a-z0-9_]+", result)
    assert normalized_object_id("", fallback="") == result


def test_has_invalid_object_id_chars() -> None:
    assert has_invalid_object_id_chars("sensor.AX PRO-temperature-0")
    assert has_invalid_object_id_chars("sensor.Main-home-battery-0")
    assert not has_invalid_object_id_chars("sensor.ax_pro_temperature_0")


def test_build_entity_id_is_device_zone_name_mac() -> None:
    """``<device>_z<zone>_<name>_<compact mac>`` for zone entities."""
    assert (
        build_entity_id("binary_sensor", f"{MAC}-tamper-1", MAC, "ingresso", "z")
        == "binary_sensor.ingresso_z1_tamper_a4d5c26bb859"
    )
    assert (
        build_entity_id("binary_sensor", f"{MAC}-magnet-shock-8", MAC, "garage", "z")
        == "binary_sensor.garage_z8_magnet_shock_a4d5c26bb859"
    )
    assert (
        build_entity_id("sensor", f"{MAC}-temp-12", MAC, "cucina_tenda", "z")
        == "sensor.cucina_tenda_z12_temp_a4d5c26bb859"
    )


def test_only_real_zone_numbers_are_marked_with_z() -> None:
    """A hub battery or a relay is not a zone, so it keeps a plain number."""
    assert (
        build_entity_id("sensor", f"{MAC}-hub-battery-1", MAC, "alarm")
        == "sensor.alarm_hub_battery_1_a4d5c26bb859"
    )
    assert (
        build_entity_id("switch", f"{MAC}-relay-2", MAC, "garage door")
        == "switch.garage_door_relay_2_a4d5c26bb859"
    )


def test_zone_number_is_marked_so_it_cannot_read_as_a_dedup_suffix() -> None:
    """``z1`` rather than a bare trailing ``_1``."""
    entity_id = build_entity_id(
        "binary_sensor", f"{MAC}-tamper-1", MAC, "ingresso", "z"
    )
    assert "_z1_" in entity_id
    # The MAC always closes the id, so nothing can trail as a suffix.
    assert entity_id.endswith(MAC)
    assert not re.search(r"_\d+$", entity_id)


def test_build_entity_id_does_not_repeat_the_device_name() -> None:
    """A device already saying it is not made to say it twice."""
    assert (
        build_entity_id(
            "binary_sensor", f"{MAC}-alarm-1", MAC, "Front door alarm", "z"
        )
        == "binary_sensor.front_door_alarm_z1_a4d5c26bb859"
    )
    # An area panel whose name already ends in its own number.
    assert (
        build_entity_id("alarm_control_panel", f"subsys-{MAC}-1", MAC, "Area 1")
        == "alarm_control_panel.area_1_subsys_a4d5c26bb859"
    )


def test_build_entity_id_without_a_zone_number() -> None:
    """Panel-level entities simply have no zone marker."""
    assert (
        build_entity_id("binary_sensor", f"{MAC}-ac-power", MAC, "alarm")
        == "binary_sensor.alarm_ac_power_a4d5c26bb859"
    )
    assert (
        build_entity_id("binary_sensor", f"{MAC}-ready-to-arm-away", MAC, "alarm")
        == "binary_sensor.alarm_ready_to_arm_away_a4d5c26bb859"
    )
    # The panel entity's unique_id is the MAC alone.
    assert build_entity_id("alarm_control_panel", MAC, MAC, "alarm") == (
        "alarm_control_panel.alarm_a4d5c26bb859"
    )


def test_build_entity_id_never_needs_a_dedup_suffix() -> None:
    """Two panels with identically named zones still get distinct ids."""
    other = "a4d5c26bb85a"
    first = build_entity_id("binary_sensor", f"{MAC}-tamper-1", MAC, "ingresso", "z")
    second = build_entity_id(
        "binary_sensor", f"{other}-tamper-1", other, "ingresso", "z"
    )
    assert first != second
    assert not first.endswith("_2") and not second.endswith("_2")


def test_generated_ids_use_underscore_only_as_separator() -> None:
    for unique_id in (f"{MAC}-tamper-1", f"{MAC}-magnet-shock-8", f"{MAC}-ac-power"):
        _, object_id = build_entity_id(
            "sensor", unique_id, MAC, "ingresso", "z"
        ).split(".", 1)
        assert re.fullmatch(r"[a-z0-9]+(_[a-z0-9]+)*", object_id)
        # The MAC stays one token instead of becoming six.
        assert MAC in object_id


def test_zone_device_model_always_str() -> None:
    assert zone_device_model("0x00001", None) == "Passive Infrared Detector"
    assert (
        zone_device_model(None, DetectorType.PIR_DETECTOR)
        == DetectorType.PIR_DETECTOR.value
    )
    assert isinstance(zone_device_model(None, DetectorType.SMOKE_DETECTOR), str)
    assert zone_device_model(None, None) == "Unknown"


@pytest.mark.parametrize("filename", PLATFORM_FILES)
def test_platforms_derive_entity_id_from_unique_id(filename: str) -> None:
    """No platform hand-rolls an entity id from a name."""
    content = (COMPONENT / filename).read_text(encoding="utf-8")
    assert "build_entity_id(" in content
    assert not re.search(r'self\.entity_id\s*=\s*f?["\']', content)


@pytest.mark.parametrize("filename", PLATFORM_FILES)
def test_unique_ids_are_compact_mac_scoped(filename: str) -> None:
    """unique_ids key off the compact MAC, not the panel name."""
    content = (COMPONENT / filename).read_text(encoding="utf-8")
    assert "device_name}-" not in content
    assert "coordinator.mac}-" not in content
