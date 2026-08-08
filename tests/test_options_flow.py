"""Tests for the per-mode bypassable zone pickers in the options flow."""

from __future__ import annotations

import pytest

from homeassistant.const import (
    ATTR_CODE_FORMAT,
    CONF_CODE,
    CONF_ENABLED,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.hikvision_axpro.const import (
    ALLOW_SUBSYSTEMS,
    CONF_AUTO_BYPASS_MODES,
    DOMAIN,
    USE_CODE_ARMING,
    conf_bypassable_zones,
)

from .conftest import setup_entry

pytestmark = pytest.mark.usefixtures("auto_enable_custom_integrations")


def base_input(**overrides) -> dict:
    """The settings half of the options form."""
    data = {
        CONF_HOST: "1.2.3.4",
        CONF_USERNAME: "admin",
        CONF_PASSWORD: "secret",
        CONF_ENABLED: False,
        ATTR_CODE_FORMAT: "NUMBER",
        CONF_CODE: "",
        USE_CODE_ARMING: False,
        CONF_SCAN_INTERVAL: 30,
        ALLOW_SUBSYSTEMS: False,
        CONF_AUTO_BYPASS_MODES: ["away"],
        "bypass_reenable_debounce": 10,
        "clear_all_bypasses_on_disarm": False,
    }
    data.update(overrides)
    return data


def bypass_entity(hass, zone_id: int) -> str:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"001122334455-bypass-{zone_id}"
    )
    assert entity_id
    return entity_id


async def test_enabled_modes_get_a_zone_picker(hass, panel):
    """A second step appears with one multiselect per enabled mode."""
    entry = await setup_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        base_input(**{CONF_AUTO_BYPASS_MODES: ["home", "away"]}),
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bypass_zones"
    keys = {str(key) for key in result["data_schema"].schema}
    assert keys == {conf_bypassable_zones("home"), conf_bypassable_zones("away")}


async def test_picked_entities_are_stored_as_zone_ids(hass, panel):
    """The picker shows entities; the entry keeps the zone behind them."""
    entry = await setup_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], base_input()
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {conf_bypassable_zones("away"): [bypass_entity(hass, 1)]},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    # Stored as a zone id, so renaming the entity cannot lose the setting.
    assert entry.data[conf_bypassable_zones("away")] == [1]


async def test_picker_only_offers_this_panel_entities(hass, panel):
    """The choices are limited to zones of this config entry."""
    entry = await setup_entry(hass)
    registry = er.async_get(hass)
    # An unrelated entity, and one from another integration.
    registry.async_get_or_create(
        "binary_sensor", "other_integration", "001122334455-bypass-9"
    )

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], base_input()
    )

    selector = next(iter(result["data_schema"].schema.values()))
    offered = set(selector.config["include_entities"])
    assert offered == {bypass_entity(hass, 1), bypass_entity(hass, 2)}


async def test_current_selection_is_prefilled_as_entities(hass, panel):
    """Reopening the options shows the stored zones as their entities."""
    entry = await setup_entry(hass, bypassable={"away": [2]})

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], base_input()
    )

    field = next(
        key
        for key in result["data_schema"].schema
        if str(key) == conf_bypassable_zones("away")
    )
    assert field.default() == [bypass_entity(hass, 2)]


async def test_disabling_a_mode_skips_the_picker_and_clears_it(hass, panel):
    """With auto-bypass off, no selection is kept to come back later."""
    entry = await setup_entry(hass, bypassable={"away": [1]})

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], base_input(**{CONF_AUTO_BYPASS_MODES: []})
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert conf_bypassable_zones("away") not in entry.data


async def test_turning_one_mode_off_leaves_the_others_alone(hass, panel):
    """Only the disabled mode loses its selection."""
    entry = await setup_entry(hass, bypassable={"away": [1], "home": [2]})

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], base_input(**{CONF_AUTO_BYPASS_MODES: ["home"]})
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {conf_bypassable_zones("home"): [bypass_entity(hass, 2)]},
    )
    await hass.async_block_till_done()

    assert entry.data[conf_bypassable_zones("home")] == [2]
    assert conf_bypassable_zones("away") not in entry.data


async def test_saved_selection_takes_effect_after_the_reload(hass, panel):
    """Saving the options re-arms the manager with the new zones."""
    entry = await setup_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], base_input()
    )
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {conf_bypassable_zones("away"): [bypass_entity(hass, 1)]},
    )
    await hass.async_block_till_done()

    from .conftest import get_manager

    assert get_manager(hass, entry).is_bypassable(1, "away")
    sensor = er.async_get(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, "001122334455-bypassable-away-1"
    )
    assert hass.states.get(sensor).state == "on"


async def test_picker_omits_zones_the_panel_forbids_bypassing(hass, panel):
    """A zone with "forbid bypass on arming" is not offered at all."""
    panel.zone_configs = [
        {"id": 1, "zoneName": "Front door", "armNoBypassEnabled": True},
        {"id": 2, "zoneName": "Curtain hall", "armNoBypassEnabled": False},
    ]
    entry = await setup_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], base_input()
    )

    selector = next(iter(result["data_schema"].schema.values()))
    offered = set(selector.config["include_entities"])
    assert offered == {bypass_entity(hass, 2)}


async def test_picker_omits_zone_types_that_are_never_bypassed(hass, panel):
    """Only instant zones can be auto-bypassed, so only they are offered."""
    panel.zones[1]["zoneType"] = "Delay"
    entry = await setup_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], base_input()
    )

    selector = next(iter(result["data_schema"].schema.values()))
    offered = set(selector.config["include_entities"])
    assert bypass_entity(hass, 1) not in offered
    assert bypass_entity(hass, 2) in offered
