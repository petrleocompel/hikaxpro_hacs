"""Integration-level tests for entity ID generation and migration."""

from __future__ import annotations

import re
from unittest.mock import patch

import pytest

from homeassistant.helpers import entity_registry as er

import custom_components.hikvision_axpro as integration_init
from custom_components.hikvision_axpro.const import DOMAIN

from .conftest import MockAxPro, make_entry, setup_entry, zone_payload

pytestmark = pytest.mark.usefixtures("auto_enable_custom_integrations")


def entity_id_of(hass, domain: str, unique_id: str) -> str:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id, f"entity {unique_id} not found"
    return entity_id


async def test_generated_ids_use_underscore_only_as_separator(hass, panel):
    """Generated ids are ``<device>_<what>`` slugs, never MAC soup."""
    await setup_entry(hass)
    registry = er.async_get(hass)

    entries = [
        reg
        for reg in registry.entities.values()
        if reg.platform == DOMAIN and reg.unique_id
    ]
    assert entries, "no entities were created"

    for reg in entries:
        _, object_id = reg.entity_id.split(".", 1)
        assert re.fullmatch(r"[a-z0-9]+(_[a-z0-9]+)*", object_id), reg.entity_id
        # The MAC is an internal identifier: it must never leak into an id.
        assert "00_11_22" not in object_id


async def test_entity_ids_are_device_zone_name_mac(hass, panel):
    """``<device>_z<zone>_<name>_<compact mac>``."""
    await setup_entry(hass)

    assert (
        entity_id_of(hass, "binary_sensor", "001122334455-tamper-1")
        == "binary_sensor.front_door_z1_tamper_001122334455"
    )
    assert (
        entity_id_of(hass, "binary_sensor", "001122334455-armed-1")
        == "binary_sensor.front_door_z1_armed_001122334455"
    )
    assert (
        entity_id_of(hass, "binary_sensor", "001122334455-bypass-2")
        == "binary_sensor.curtain_hall_z2_bypass_001122334455"
    )
    # Panel-level entities carry the panel name and no zone number.
    assert (
        entity_id_of(hass, "binary_sensor", "001122334455-ready-to-arm-away")
        == "binary_sensor.axpro_ready_to_arm_away_001122334455"
    )


async def test_same_zone_name_never_needs_a_dedup_suffix(hass, panel):
    """Two zones sharing a name stay distinct through the MAC and zone id."""
    panel.zones[1]["name"] = "Front door alarm"
    panel.zones[2]["name"] = "Front door alarm"  # same name as zone 1
    await setup_entry(hass)

    first = entity_id_of(hass, "binary_sensor", "001122334455-alarm-1")
    second = entity_id_of(hass, "binary_sensor", "001122334455-alarm-2")
    # The device name already ends in "alarm", so it is not repeated,
    # and the zone number is marked with "z" rather than trailing bare.
    assert first == "binary_sensor.front_door_alarm_z1_001122334455"
    assert second == "binary_sensor.front_door_alarm_z2_001122334455"
    # Identical zone names, yet no Home Assistant dedup suffix was added.
    assert not first.endswith("_2") and not second.endswith("_2")


async def test_migration_renames_invalid_registry_id_and_is_idempotent(
    hass, panel, monkeypatch
):
    """Invalid ids are renamed in place; a second run changes nothing."""
    entry = await setup_entry(hass)
    old_entity_id = entity_id_of(hass, "binary_sensor", "001122334455-tamper-1")

    # HA no longer accepts writing invalid ids directly; emulate a legacy
    # invalid entry by forcing the migration logic onto this entity.
    monkeypatch.setattr(
        integration_init,
        "has_invalid_object_id_chars",
        lambda entity_id: entity_id == old_entity_id,
    )
    monkeypatch.setattr(
        integration_init,
        "normalized_object_id",
        lambda value, fallback=None: "front_door_tamper_fixed",
    )

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    migrated = entity_id_of(hass, "binary_sensor", "001122334455-tamper-1")
    assert migrated == "binary_sensor.front_door_tamper_fixed"

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert entity_id_of(hass, "binary_sensor", "001122334455-tamper-1") == migrated


async def test_migration_collision_falls_back_with_suffix(hass, panel, monkeypatch):
    """Collisions get a numeric suffix instead of failing setup."""
    entry = await setup_entry(hass)
    registry = er.async_get(hass)

    tamper = entity_id_of(hass, "binary_sensor", "001122334455-tamper-1")
    armed = entity_id_of(hass, "binary_sensor", "001122334455-armed-1")

    registry.async_update_entity(armed, new_entity_id="binary_sensor.taken_slug")
    registry.async_update_entity(tamper, new_entity_id="binary_sensor.needs_migration")

    monkeypatch.setattr(
        integration_init,
        "has_invalid_object_id_chars",
        lambda entity_id: entity_id == "binary_sensor.needs_migration",
    )
    monkeypatch.setattr(
        integration_init,
        "normalized_object_id",
        lambda value, fallback=None: "taken_slug",
    )

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert (
        entity_id_of(hass, "binary_sensor", "001122334455-tamper-1")
        == "binary_sensor.taken_slug_2"
    )


async def test_migration_leaves_existing_valid_ids_untouched(hass, panel):
    """Upgrading an existing installation does not rename anything valid."""
    entry = await setup_entry(hass)
    registry = er.async_get(hass)

    before = {
        reg.unique_id: reg.entity_id
        for reg in er.async_entries_for_config_entry(registry, entry.entry_id)
        if reg.unique_id
    }
    assert before

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    after = {
        reg.unique_id: reg.entity_id
        for reg in er.async_entries_for_config_entry(registry, entry.entry_id)
        if reg.unique_id
    }
    assert before == after


async def test_legacy_device_name_unique_ids_are_rekeyed_to_the_mac(hass, panel):
    """An install keyed by deviceName keeps its entities after the upgrade."""
    registry = er.async_get(hass)
    entry = make_entry(hass)
    legacy = registry.async_get_or_create(
        "binary_sensor",
        DOMAIN,
        "axpro-tamper-1",
        config_entry=entry,
        suggested_object_id="front_door_tamper",
    )
    registry.async_update_entity(legacy.entity_id, name="My tamper")

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Re-keyed in place: same registry row, so name and history survive.
    assert registry.async_get_entity_id(
        "binary_sensor", DOMAIN, "axpro-tamper-1"
    ) is None
    migrated = entity_id_of(hass, "binary_sensor", "001122334455-tamper-1")
    assert migrated == legacy.entity_id
    assert registry.async_get(migrated).name == "My tamper"


async def test_legacy_subsystem_unique_id_gets_a_separator(hass):
    """``subsys-<mac><area>`` is ambiguous and becomes ``subsys-<mac>-<area>``."""
    mock = MockAxPro(zones=[zone_payload(1, name="Front door", magnet_open=False)])
    registry = er.async_get(hass)

    with patch("hikaxpro.HikAxPro", return_value=mock):
        entry = make_entry(hass, allow_subsystems=True)
        registry.async_get_or_create(
            "alarm_control_panel",
            DOMAIN,
            "subsys-00:11:22:33:44:551",
            config_entry=entry,
            suggested_object_id="area_1",
        )

        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert (
        registry.async_get_entity_id(
            "alarm_control_panel", DOMAIN, "subsys-00:11:22:33:44:551"
        )
        is None
    )
    assert (
        entity_id_of(hass, "alarm_control_panel", "subsys-001122334455-1")
        == "alarm_control_panel.area_1"
    )


async def test_unique_id_migration_drops_a_duplicate_instead_of_failing(hass, panel):
    """A half-migrated registry does not break setup."""
    registry = er.async_get(hass)
    entry = make_entry(hass)
    registry.async_get_or_create(
        "binary_sensor",
        DOMAIN,
        "axpro-tamper-1",
        config_entry=entry,
        suggested_object_id="stale_tamper",
    )
    already_migrated = registry.async_get_or_create(
        "binary_sensor",
        DOMAIN,
        "001122334455-tamper-1",
        config_entry=entry,
        suggested_object_id="front_door_tamper",
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get("binary_sensor.stale_tamper") is None
    assert (
        entity_id_of(hass, "binary_sensor", "001122334455-tamper-1")
        == already_migrated.entity_id
    )


async def test_user_renamed_entity_id_survives_setup(hass, panel):
    """A user-chosen entity_id is never overwritten by the generator."""
    entry = await setup_entry(hass)
    registry = er.async_get(hass)

    tamper = entity_id_of(hass, "binary_sensor", "001122334455-tamper-1")
    registry.async_update_entity(tamper, new_entity_id="binary_sensor.my_own_name")

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert (
        entity_id_of(hass, "binary_sensor", "001122334455-tamper-1")
        == "binary_sensor.my_own_name"
    )


async def test_colon_mac_unique_ids_are_compacted(hass, panel):
    """``a4:d5:...-tamper-1`` becomes ``a4d5...-tamper-1`` in place."""
    registry = er.async_get(hass)
    entry = make_entry(hass)
    legacy = registry.async_get_or_create(
        "binary_sensor",
        DOMAIN,
        "00:11:22:33:44:55-tamper-1",
        config_entry=entry,
        suggested_object_id="front_door_tamper",
    )
    registry.async_update_entity(legacy.entity_id, name="My tamper")

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert (
        registry.async_get_entity_id(
            "binary_sensor", DOMAIN, "00:11:22:33:44:55-tamper-1"
        )
        is None
    )
    migrated = entity_id_of(hass, "binary_sensor", "001122334455-tamper-1")
    assert migrated == legacy.entity_id
    assert registry.async_get(migrated).name == "My tamper"


async def test_colon_mac_panel_unique_id_is_compacted(hass, panel):
    """The panel entity was keyed by the bare MAC; it is compacted too."""
    registry = er.async_get(hass)
    entry = make_entry(hass)
    legacy = registry.async_get_or_create(
        "alarm_control_panel",
        DOMAIN,
        "00:11:22:33:44:55",
        config_entry=entry,
        suggested_object_id="villa_1_alarm",
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert (
        registry.async_get_entity_id(
            "alarm_control_panel", DOMAIN, "00:11:22:33:44:55"
        )
        is None
    )
    # The hand-picked entity_id survives the re-key.
    assert (
        entity_id_of(hass, "alarm_control_panel", "001122334455")
        == legacy.entity_id
        == "alarm_control_panel.villa_1_alarm"
    )


async def test_two_panels_with_identical_zone_names(hass):
    """The reason the MAC is in the id: two panels, same zone names."""
    names = ["ingresso", "bagno_pt", "cucina"]
    registry = er.async_get(hass)

    for entry_id, mac in (
        ("panel-a", "a4:d5:c2:6b:b8:59"),
        ("panel-b", "a4:d5:c2:6b:b8:5a"),
    ):
        mock = MockAxPro(
            zones=[zone_payload(i, name=n) for i, n in enumerate(names, start=1)]
        )
        mock.get_interface_mac_address = lambda _iface, _mac=mac: _mac
        with patch("hikaxpro.HikAxPro", return_value=mock):
            entry = make_entry(hass, entry_id=entry_id)
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

    rows = [
        reg
        for reg in registry.entities.values()
        if reg.platform == DOMAIN and "-tamper-" in reg.unique_id
    ]
    # Nothing dropped by a unique_id collision: 3 zones x 2 panels.
    assert len(rows) == 6
    assert len({reg.unique_id for reg in rows}) == 6

    entity_ids = {reg.entity_id for reg in rows}
    assert len(entity_ids) == 6
    assert entity_ids == {
        "binary_sensor.ingresso_z1_tamper_a4d5c26bb859",
        "binary_sensor.ingresso_z1_tamper_a4d5c26bb85a",
        "binary_sensor.bagno_pt_z2_tamper_a4d5c26bb859",
        "binary_sensor.bagno_pt_z2_tamper_a4d5c26bb85a",
        "binary_sensor.cucina_z3_tamper_a4d5c26bb859",
        "binary_sensor.cucina_z3_tamper_a4d5c26bb85a",
    }
