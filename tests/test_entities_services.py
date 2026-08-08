"""Tests for services, the bypassable readback sensor and ready sensor."""

from __future__ import annotations

from datetime import timedelta

import pytest

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.hikvision_axpro.const import (
    CONF_AUTO_BYPASS_MODES,
    DOMAIN,
    SERVICE_BYPASS_ZONE,
    SERVICE_CLEAR_ALL_BYPASSES,
    SERVICE_UNBYPASS_ZONE,
    conf_bypassable_zones,
)

from .conftest import get_coordinator, get_manager, make_entry, setup_entry

pytestmark = pytest.mark.usefixtures("auto_enable_custom_integrations")


def entity_id_of(hass, domain, unique_id) -> str:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id, f"entity {unique_id} not found"
    return entity_id


# ---------------------------------------------------------------------------
# Services


async def test_bypass_and_unbypass_services(hass, panel):
    """Bypass/unbypass a zone by targeting its bypass sensor."""
    entry = await setup_entry(hass)
    manager = get_manager(hass, entry)
    bypass_sensor = entity_id_of(
        hass, "binary_sensor", "001122334455-bypass-1"
    )

    await hass.services.async_call(
        DOMAIN, SERVICE_BYPASS_ZONE, {"entity_id": bypass_sensor}, blocking=True
    )
    await hass.async_block_till_done()
    assert panel.zones[1]["bypassed"] is True
    # User decision #5: service bypasses are owned by the integration.
    assert manager.owns_zone(1)
    assert manager.bypass_reason(1) == "service"

    await hass.services.async_call(
        DOMAIN, SERVICE_UNBYPASS_ZONE, {"entity_id": bypass_sensor}, blocking=True
    )
    await hass.async_block_till_done()
    assert panel.zones[1]["bypassed"] is False
    assert not manager.owns_zone(1)


async def test_bypass_service_failure_raises(hass, panel):
    """A failed service bypass surfaces an explicit error."""
    await setup_entry(hass)
    panel.fail_bypass_zones.add(1)
    bypass_sensor = entity_id_of(
        hass, "binary_sensor", "001122334455-bypass-1"
    )

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, SERVICE_BYPASS_ZONE, {"entity_id": bypass_sensor}, blocking=True
        )


async def test_clear_all_bypasses_service(hass, panel):
    """Clear all removes every bypass regardless of owner."""
    entry = await setup_entry(hass)
    panel.zones[1]["bypassed"] = True  # external
    panel.zones[2]["bypassed"] = True  # external
    panel_entity = entity_id_of(hass, "alarm_control_panel", "001122334455")

    await hass.services.async_call(
        DOMAIN,
        SERVICE_CLEAR_ALL_BYPASSES,
        {"entity_id": panel_entity},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert panel.zones[1]["bypassed"] is False
    assert panel.zones[2]["bypassed"] is False


# ---------------------------------------------------------------------------
# Bypassable readback sensor


async def test_bypassable_sensor_reflects_the_configuration(hass, panel):
    """Read-only: on for a configured zone, off for the others."""
    entry = await setup_entry(hass, bypassable={"away": [1]})
    manager = get_manager(hass, entry)

    configured = entity_id_of(
        hass, "binary_sensor", "001122334455-bypassable-away-1"
    )
    other = entity_id_of(
        hass, "binary_sensor", "001122334455-bypassable-away-2"
    )
    assert hass.states.get(configured).state == "on"
    assert hass.states.get(other).state == "off"
    assert manager.is_bypassable(1, "away")
    assert not manager.is_bypassable(2, "away")


async def test_no_bypassable_switch_is_created(hass, panel):
    """The configuration moved to the options: no per-zone switch exists."""
    await setup_entry(hass, bypassable={"away": [1]})
    registry = er.async_get(hass)
    assert not registry.async_get_entity_id(
        "switch", DOMAIN, "001122334455-bypassable-away-1"
    )


async def test_bypassable_sensors_are_independent_per_mode(hass, panel):
    entry = await setup_entry(hass, bypassable={"home": [1]})
    manager = get_manager(hass, entry)
    away = entity_id_of(hass, "binary_sensor", "001122334455-bypassable-away-1")
    home = entity_id_of(hass, "binary_sensor", "001122334455-bypassable-home-1")
    vacation = entity_id_of(
        hass, "binary_sensor", "001122334455-bypassable-vacation-1"
    )

    assert hass.states.get(home).state == "on"
    assert hass.states.get(away).state == "off"
    assert hass.states.get(vacation).state == "off"

    assert manager.is_bypassable(1, "home")
    assert not manager.is_bypassable(1, "away")
    assert not manager.is_bypassable(1, "vacation")


async def test_bypassable_sensors_created_only_for_allowed_modes(hass, panel):
    """Disallowed modes do not expose a per-zone bypassable sensor."""
    await setup_entry(hass, **{CONF_AUTO_BYPASS_MODES: ["away"]})
    registry = er.async_get(hass)

    assert registry.async_get_entity_id(
        "binary_sensor", DOMAIN, "001122334455-bypassable-away-1"
    )
    assert not registry.async_get_entity_id(
        "binary_sensor", DOMAIN, "001122334455-bypassable-home-1"
    )
    assert not registry.async_get_entity_id(
        "binary_sensor", DOMAIN, "001122334455-bypassable-vacation-1"
    )


async def test_configuration_survives_a_reload(hass, panel):
    """The selection lives in the config entry, so a restart keeps it."""
    entry = await setup_entry(hass, bypassable={"home": [1]})

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    reloaded = get_manager(hass, entry)
    assert reloaded.is_bypassable(1, "home")
    assert not reloaded.is_bypassable(1, "away")
    sensor = entity_id_of(
        hass, "binary_sensor", "001122334455-bypassable-home-1"
    )
    assert hass.states.get(sensor).state == "on"


async def test_bypassable_sensor_off_when_panel_forbids(hass, panel):
    """'Forbid bypass on arming' (panel config) wins over the options."""
    panel.zone_configs = [
        {"id": 1, "zoneName": "Front door", "armNoBypassEnabled": True},
        {"id": 2, "zoneName": "Curtain hall", "armNoBypassEnabled": False},
    ]
    entry = await setup_entry(hass, bypassable={"away": [1, 2]})
    manager = get_manager(hass, entry)

    forbidden = entity_id_of(
        hass, "binary_sensor", "001122334455-bypassable-away-1"
    )
    normal = entity_id_of(
        hass, "binary_sensor", "001122334455-bypassable-away-2"
    )
    assert hass.states.get(forbidden).state == "off"
    assert hass.states.get(normal).state == "on"
    assert not manager.is_bypassable(1, "away")

    # The user's choice is not rewritten, only reported as ineffective.
    assert manager.is_configured_bypassable(1, "away")
    attrs = hass.states.get(forbidden).attributes
    assert attrs["configured"] is True
    assert attrs["ineffective_reason"] == "forbidden_by_panel_config"


async def test_panel_forbid_change_picked_up_on_hourly_refresh(hass, panel):
    """Enabling the panel setting takes effect at the hourly config refresh."""
    entry = await setup_entry(hass, bypassable={"away": [1]})
    coordinator = get_coordinator(hass, entry)
    manager = get_manager(hass, entry)
    assert manager.is_bypassable(1, "away")
    sensor = entity_id_of(
        hass, "binary_sensor", "001122334455-bypassable-away-1"
    )

    panel.zone_configs = [
        {"id": 1, "zoneName": "Front door", "armNoBypassEnabled": True}
    ]

    # Within the hour the config is not re-fetched: nothing changes yet.
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert manager.is_bypassable(1, "away")

    # Backdate the last fetch so the hourly refresh is due.
    coordinator._last_zone_config_fetch -= timedelta(hours=2)
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert not manager.is_bypassable(1, "away")
    assert hass.states.get(sensor).state == "off"


async def test_stale_bypassable_sensor_removed_on_zone_type_change(hass, panel):
    """A sensor left over from a zone type change is removed on reload."""
    entry = await setup_entry(hass)
    registry = er.async_get(hass)
    for mode in ("away", "home", "vacation"):
        assert registry.async_get_entity_id(
            "binary_sensor", DOMAIN, f"001122334455-bypassable-{mode}-1"
        )

    panel.zones[1]["zoneType"] = "Delay"  # no longer eligible
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    for mode in ("away", "home", "vacation"):
        assert not registry.async_get_entity_id(
            "binary_sensor", DOMAIN, f"001122334455-bypassable-{mode}-1"
        )


async def test_legacy_bypassable_switch_is_removed(hass, panel):
    """The per-zone switch of earlier builds is cleaned out of the registry."""
    registry = er.async_get(hass)
    entry = make_entry(hass)
    for unique_id in (
        "001122334455-bypassable-away-1",
        "001122334455-bypassable-1",
    ):
        registry.async_get_or_create(
            "switch", DOMAIN, unique_id, config_entry=entry
        )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    for unique_id in (
        "001122334455-bypassable-away-1",
        "001122334455-bypassable-1",
    ):
        assert not registry.async_get_entity_id("switch", DOMAIN, unique_id)


async def test_configured_zone_that_became_ineligible_is_inert(hass, panel):
    """A zone type change makes the configuration ineffective, not lost."""
    entry = await setup_entry(hass, bypassable={"away": [1], "home": [1]})
    manager = get_manager(hass, entry)
    assert manager.is_bypassable(1, "away")
    assert manager.is_bypassable(1, "home")

    panel.zones[1]["zoneType"] = "Delay"
    await get_coordinator(hass, entry).async_refresh()
    await hass.async_block_till_done()

    assert not manager.is_bypassable(1, "away")
    assert not manager.is_bypassable(1, "home")
    assert entry.data[conf_bypassable_zones("away")] == [1]


async def test_no_bypassable_sensor_for_excluded_zone_types(hass, panel):
    """No readback sensor for zone types that are never auto-bypassed."""
    panel.zones[3] = {
        "id": 3,
        "name": "Smoke",
        "status": "online",
        "tamperEvident": False,
        "bypassed": False,
        "armed": False,
        "alarm": False,
        "subSystemNo": 1,
        "zoneType": "Fire",
    }
    await setup_entry(hass)
    registry = er.async_get(hass)
    assert registry.async_get_entity_id(
        "binary_sensor", DOMAIN, "001122334455-bypassable-away-1"
    )
    assert not registry.async_get_entity_id(
        "binary_sensor", DOMAIN, "001122334455-bypassable-away-3"
    )


# ---------------------------------------------------------------------------
# Ready-to-arm sensor


async def test_ready_sensor_reflects_evaluation(hass, panel):
    entry = await setup_entry(hass)
    sensor = entity_id_of(
        hass, "binary_sensor", "001122334455-ready-to-arm-away"
    )
    assert hass.states.get(sensor).state == "on"

    panel.set_zone(2, status="offline")  # non-bypassable fault
    await get_coordinator(hass, entry).async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(sensor)
    assert state.state == "off"
    assert [z["zone_id"] for z in state.attributes["blocking_zones"]] == [2]
    assert state.attributes["areas"]["1"]["ready"] is False


async def test_ready_sensor_counts_configured_zones_as_bypassable(hass, panel):
    """A faulted but configured zone is listed to bypass, not as blocking."""
    panel.set_zone(1, magnetOpenStatus=True)
    entry = await setup_entry(hass, bypassable={"away": [1]})
    sensor = entity_id_of(
        hass, "binary_sensor", "001122334455-ready-to-arm-away"
    )
    await get_coordinator(hass, entry).async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(sensor)
    assert state.state == "on"
    assert [z["zone_id"] for z in state.attributes["zones_to_bypass"]] == [1]


async def test_ready_sensor_blocks_on_an_unconfigured_faulted_zone(hass, panel):
    """Without the option set, the same fault blocks arming."""
    panel.set_zone(1, magnetOpenStatus=True)
    entry = await setup_entry(hass)
    sensor = entity_id_of(
        hass, "binary_sensor", "001122334455-ready-to-arm-away"
    )
    await get_coordinator(hass, entry).async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state == "off"


async def test_ready_sensor_uses_the_mode_specific_selection(hass, panel):
    panel.set_zone(1, magnetOpenStatus=True)
    entry = await setup_entry(hass, bypassable={"home": [1]})
    await get_coordinator(hass, entry).async_refresh()
    await hass.async_block_till_done()

    away = entity_id_of(hass, "binary_sensor", "001122334455-ready-to-arm-away")
    home = entity_id_of(hass, "binary_sensor", "001122334455-ready-to-arm-home")

    assert hass.states.get(away).state == "off"
    assert hass.states.get(home).state == "on"


async def test_ready_sensor_created_for_every_mode(hass, panel):
    """One ready sensor per arming mode, regardless of auto-bypass config."""
    await setup_entry(hass, **{CONF_AUTO_BYPASS_MODES: []})
    for unique_id in (
        "001122334455-ready-to-arm-away",
        "001122334455-ready-to-arm-home",
        "001122334455-ready-to-arm-vacation",
    ):
        entity_id_of(hass, "binary_sensor", unique_id)


async def test_ready_sensor_applies_the_mode_gate_first(hass, panel):
    """A disallowed mode ignores the selection and still blocks."""
    panel.set_zone(1, magnetOpenStatus=True)
    entry = await setup_entry(
        hass, bypassable={"home": [1]}, **{CONF_AUTO_BYPASS_MODES: ["away"]}
    )
    await get_coordinator(hass, entry).async_refresh()
    await hass.async_block_till_done()

    home = entity_id_of(hass, "binary_sensor", "001122334455-ready-to-arm-home")
    assert hass.states.get(home).state == "off"


async def test_home_ready_sensor_ignores_stay_bypassed_zone(hass, panel):
    """A stay-bypassed faulted zone blocks away but not home."""
    panel.set_zone(2, status="offline", stayAway=True)
    entry = await setup_entry(hass)
    await get_coordinator(hass, entry).async_refresh()
    await hass.async_block_till_done()

    away = entity_id_of(hass, "binary_sensor", "001122334455-ready-to-arm-away")
    home = entity_id_of(hass, "binary_sensor", "001122334455-ready-to-arm-home")
    assert hass.states.get(away).state == "off"
    assert hass.states.get(home).state == "on"
    assert hass.states.get(home).attributes["evaluated_mode"] == "home"


async def test_panel_diagnostic_attributes(hass, panel):
    """The panel exposes bypassed zones and owned bypasses."""
    entry = await setup_entry(hass, bypassable={"away": [1]})
    panel.set_zone(1, magnetOpenStatus=True)
    await get_coordinator(hass, entry).async_arm_away()
    # Entity states update on the next poll cycle.
    await get_coordinator(hass, entry).async_refresh()
    await hass.async_block_till_done()

    panel_entity = entity_id_of(hass, "alarm_control_panel", "001122334455")
    attrs = hass.states.get(panel_entity).attributes
    assert [z["zone_id"] for z in attrs["bypassed_zones"]] == [1]
    assert "1" in {str(k) for k in attrs["owned_bypasses"]}
    assert attrs["last_auto_bypass"] is not None

    bypass_sensor = entity_id_of(
        hass, "binary_sensor", "001122334455-bypass-1"
    )
    sensor_attrs = hass.states.get(bypass_sensor).attributes
    assert sensor_attrs["bypass_owner"] == "integration"
    assert sensor_attrs["bypass_reason"] == "auto_arm"


async def test_unreadable_bypass_storage_does_not_block_setup(hass, panel):
    """Everything stored is recoverable, so a bad file is just discarded."""
    store = Store[dict](hass, 99, "hikvision_axpro.test-entry.bypass")
    await store.async_save({"owned_bypasses": "not-a-dict"})

    entry = await setup_entry(hass, bypassable={"away": [1]})

    manager = get_manager(hass, entry)
    assert manager.store.data.owned_bypasses == {}
    # The configuration lives in the entry, so it is unaffected.
    assert manager.is_bypassable(1, "away")
