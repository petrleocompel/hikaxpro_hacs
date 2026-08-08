"""Tests for the auto-bypass arming flow."""

from __future__ import annotations

import pytest

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.hikvision_axpro.const import (
    CONF_AUTO_BYPASS_MODES,
    DOMAIN,
    EVENT_ARMING_BLOCKED,
    EVENT_BYPASS_APPLIED,
)

from .conftest import get_coordinator, get_manager, setup_entry

pytestmark = pytest.mark.usefixtures("auto_enable_custom_integrations")

PANEL_ENTITY = "alarm_control_panel"


def panel_entity_id(hass) -> str:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        PANEL_ENTITY, DOMAIN, "001122334455"
    )
    assert entity_id
    return entity_id


async def arm_away(hass, blocking=True):
    await hass.services.async_call(
        PANEL_ENTITY,
        "alarm_arm_away",
        {"entity_id": panel_entity_id(hass)},
        blocking=blocking,
    )
    await hass.async_block_till_done()


async def test_arm_with_no_faults_sends_plain_arm(hass, panel):
    """Healthy zones => no bypass calls, arm goes through."""
    await setup_entry(hass)
    await arm_away(hass)
    assert panel.arm_calls == [("away", None)]
    assert panel.bypass_calls == []
    assert panel.area()["arming"] == "away"


async def test_arm_bypasses_faulted_bypassable_zone(hass, panel):
    """Open door marked bypassable is bypassed, then armed."""
    panel.set_zone(1, magnetOpenStatus=True)
    entry = await setup_entry(hass, bypassable={"away": [1]})
    manager = get_manager(hass, entry)

    events = async_capture_events(hass, EVENT_BYPASS_APPLIED)
    await arm_away(hass)

    assert panel.bypass_calls == [1]
    assert panel.zones[1]["bypassed"] is True
    assert panel.arm_calls == [("away", None)]
    assert manager.owns_zone(1)
    assert len(events) == 1
    assert events[0].data["zone_id"] == 1
    assert events[0].data["reason"] == "auto_arm"


async def test_arm_blocked_by_non_bypassable_zone(hass, panel):
    """Offline curtain not bypassable => abort, no arm."""
    panel.set_zone(1, magnetOpenStatus=True)
    panel.set_zone(2, status="offline")
    entry = await setup_entry(hass, bypassable={"away": [1]})
    manager = get_manager(hass, entry)

    events = async_capture_events(hass, EVENT_ARMING_BLOCKED)
    with pytest.raises(HomeAssistantError) as excinfo:
        await arm_away(hass)

    assert panel.arm_calls == []
    assert panel.bypass_calls == []
    assert "Curtain hall" in str(excinfo.value)
    assert len(events) == 1
    assert [z["zone_id"] for z in events[0].data["blocking_zones"]] == [2]
    assert panel.area()["arming"] == "disarm"


async def test_rollback_on_partial_bypass_failure(hass, panel):
    """Second bypass fails => first is rolled back, arming aborted."""
    panel.set_zone(1, magnetOpenStatus=True)
    panel.set_zone(2, status="trigger")
    panel.fail_bypass_zones.add(2)
    entry = await setup_entry(hass, bypassable={"away": [1, 2]})
    manager = get_manager(hass, entry)

    with pytest.raises(HomeAssistantError):
        await arm_away(hass)

    assert panel.arm_calls == []
    assert panel.zones[1]["bypassed"] is False  # rolled back
    assert 1 in panel.unbypass_calls
    assert not manager.owns_zone(1)
    assert not manager.owns_zone(2)


async def test_fresh_read_failure_aborts_arming(hass, panel):
    """Zone read failure at arm time => abort, panel untouched."""
    await setup_entry(hass)
    panel.zone_status_fail = True
    with pytest.raises(HomeAssistantError):
        await arm_away(hass)
    assert panel.arm_calls == []


async def test_auto_bypass_disabled_behaves_like_upstream(hass, panel):
    """With no mode enabled, no bypass logic runs at all."""
    panel.set_zone(1, magnetOpenStatus=True)  # faulted zone present
    entry = await setup_entry(
        hass, bypassable={"away": [1]}, **{CONF_AUTO_BYPASS_MODES: []}
    )
    manager = get_manager(hass, entry)

    await arm_away(hass)

    assert panel.bypass_calls == []
    assert panel.arm_calls == [("away", None)]


async def test_mode_not_enabled_skips_flow(hass, panel):
    """Auto-bypass enabled for away only: arming home is a plain arm."""
    panel.set_zone(1, magnetOpenStatus=True)
    entry = await setup_entry(
        hass, bypassable={"away": [1]}, **{CONF_AUTO_BYPASS_MODES: ["away"]}
    )
    manager = get_manager(hass, entry)

    await hass.services.async_call(
        PANEL_ENTITY,
        "alarm_arm_home",
        {"entity_id": panel_entity_id(hass)},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert panel.bypass_calls == []
    assert panel.arm_calls == [("stay", None)]


async def test_panel_arm_refusal_raises(hass, panel):
    """A refused arm command is surfaced as an error."""
    await setup_entry(hass)
    panel.refuse_arm = True
    with pytest.raises(HomeAssistantError):
        await arm_away(hass)


async def test_concurrent_arm_rejected(hass, panel):
    """A second arm while one is in progress is rejected."""
    entry = await setup_entry(hass)
    manager = get_manager(hass, entry)
    coordinator = get_coordinator(hass, entry)
    async with manager.arm_lock:
        with pytest.raises(HomeAssistantError):
            await coordinator.async_arm_away()
    assert panel.arm_calls == []


async def test_arm_home_also_runs_the_flow(hass, panel):
    """User decision #8: all exposed arm modes are intercepted."""
    panel.set_zone(1, magnetOpenStatus=True)
    entry = await setup_entry(hass, bypassable={"home": [1]})
    manager = get_manager(hass, entry)

    await hass.services.async_call(
        PANEL_ENTITY,
        "alarm_arm_home",
        {"entity_id": panel_entity_id(hass)},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert panel.bypass_calls == [1]
    assert panel.arm_calls == [("stay", None)]


async def test_arm_vacation_runs_the_flow(hass, panel):
    """Vacation arming is supported and intercepted like the others."""
    panel.set_zone(1, magnetOpenStatus=True)
    entry = await setup_entry(hass, bypassable={"vacation": [1]})
    manager = get_manager(hass, entry)

    await hass.services.async_call(
        PANEL_ENTITY,
        "alarm_arm_vacation",
        {"entity_id": panel_entity_id(hass)},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert panel.bypass_calls == [1]
    assert panel.arm_calls == [("vacation", None)]
    assert panel.area()["arming"] == "vacation"

    # The entity state reflects the vacation arming on the next poll.
    await get_coordinator(hass, entry).async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(panel_entity_id(hass))
    assert state.state in {"armed_vacation", "unknown"}


async def test_forbid_bypass_on_arming_zone_blocks(hass, panel):
    """Panel-side 'forbid bypass on arming' beats the HA bypassable flag.

    The flag simply cannot be set for such a zone, so a fault on it
    always blocks arming.
    """
    panel.zone_configs = [
        {"id": 1, "zoneName": "Front door", "armNoBypassEnabled": True}
    ]
    panel.set_zone(1, magnetOpenStatus=True)
    # Configured as bypassable, but the panel forbids bypassing it.
    entry = await setup_entry(hass, bypassable={"away": [1]})
    manager = get_manager(hass, entry)
    assert not manager.is_bypassable(1)

    with pytest.raises(HomeAssistantError):
        await arm_away(hass)

    assert panel.bypass_calls == []
    assert panel.arm_calls == []


async def test_arm_home_ignores_stay_bypassed_zone(hass, panel):
    """A faulted zone the panel stay-bypasses itself never blocks home."""
    panel.set_zone(1, magnetOpenStatus=True, stayAway=True)
    await setup_entry(hass)

    await hass.services.async_call(
        PANEL_ENTITY,
        "alarm_arm_home",
        {"entity_id": panel_entity_id(hass)},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert panel.bypass_calls == []
    assert panel.arm_calls == [("stay", None)]


async def test_arm_with_bypass_service_forces_the_flow(hass, panel):
    """arm_away_with_bypass bypasses even when the mode has auto-bypass off."""
    panel.set_zone(1, magnetOpenStatus=True)
    await setup_entry(
        hass, bypassable={"away": [1]}, **{CONF_AUTO_BYPASS_MODES: []}
    )

    await hass.services.async_call(
        DOMAIN, "arm_away_with_bypass", {}, blocking=True
    )
    await hass.async_block_till_done()

    assert panel.bypass_calls == [1]
    assert panel.area()["arming"] == "away"


async def test_arm_with_bypass_still_respects_the_zone_selection(hass, panel):
    """Forcing the flow does not bypass zones the user never picked."""
    panel.set_zone(1, magnetOpenStatus=True)
    await setup_entry(hass, **{CONF_AUTO_BYPASS_MODES: []})

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "arm_away_with_bypass", {}, blocking=True
        )
    assert panel.bypass_calls == []
