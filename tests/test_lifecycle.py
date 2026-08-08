"""Tests for recovery, disarm cleanup, reconciliation and restart.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.hikvision_axpro.const import DOMAIN, EVENT_BYPASS_REMOVED

from .conftest import get_coordinator, get_manager, setup_entry

pytestmark = pytest.mark.usefixtures("auto_enable_custom_integrations")

DEBOUNCE = 10


async def poll(hass, entry):
    await get_coordinator(hass, entry).async_refresh()
    await hass.async_block_till_done()


async def elapse(hass, seconds):
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


async def arm_away_with_open_door(hass, panel, entry):
    """Arm away with zone 1 open+bypassable; returns with zone 1 owned.

    The entry must have been set up with zone 1 bypassable on away.
    """
    manager = get_manager(hass, entry)
    panel.set_zone(1, magnetOpenStatus=True)
    registry = er.async_get(hass)
    panel_id = registry.async_get_entity_id(
        "alarm_control_panel", DOMAIN, "001122334455"
    )
    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_away",
        {"entity_id": panel_id},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert manager.owns_zone(1)
    return manager


async def test_reenable_after_recovery_and_debounce(hass, panel):
    """Door closes while armed => bypass removed after debounce."""
    entry = await setup_entry(hass, bypassable={"away": [1]})
    manager = await arm_away_with_open_door(hass, panel, entry)
    events = async_capture_events(hass, EVENT_BYPASS_REMOVED)

    panel.set_zone(1, magnetOpenStatus=False)
    await poll(hass, entry)
    assert panel.zones[1]["bypassed"] is True  # debounce not elapsed yet

    await elapse(hass, DEBOUNCE + 2)

    assert panel.zones[1]["bypassed"] is False
    assert not manager.owns_zone(1)
    removal_events = [e for e in events if e.data["reason"] == "health_recovered"]
    assert len(removal_events) == 1

    # The zone is active again; reopening does not re-bypass it.
    panel.set_zone(1, magnetOpenStatus=True)
    await poll(hass, entry)
    assert panel.bypass_calls == [1]
    assert panel.zones[1]["bypassed"] is False


async def test_no_reenable_while_unhealthy(hass, panel):
    """The bypass is never removed while the zone is still open."""
    entry = await setup_entry(hass, bypassable={"away": [1]})
    manager = await arm_away_with_open_door(hass, panel, entry)

    await poll(hass, entry)
    await elapse(hass, DEBOUNCE * 10)

    assert panel.zones[1]["bypassed"] is True
    assert manager.owns_zone(1)
    assert panel.unbypass_calls == []


async def test_flapping_door_resets_debounce(hass, panel):
    """Reopening during the debounce window cancels the re-enable."""
    entry = await setup_entry(hass, bypassable={"away": [1]})
    manager = await arm_away_with_open_door(hass, panel, entry)

    panel.set_zone(1, magnetOpenStatus=False)
    await poll(hass, entry)
    panel.set_zone(1, magnetOpenStatus=True)  # reopened before debounce elapsed
    await poll(hass, entry)
    await elapse(hass, DEBOUNCE + 2)

    assert panel.zones[1]["bypassed"] is True
    assert manager.owns_zone(1)


async def test_fresh_read_guard_before_reenable(hass, panel):
    """A zone that reopens right before the timer fires is kept bypassed."""
    entry = await setup_entry(hass, bypassable={"away": [1]})
    manager = await arm_away_with_open_door(hass, panel, entry)

    panel.set_zone(1, magnetOpenStatus=False)
    await poll(hass, entry)
    # Reopen WITHOUT a poll: only the fresh read at re-enable time can see it.
    panel.set_zone(1, magnetOpenStatus=True)
    await elapse(hass, DEBOUNCE + 2)

    assert panel.zones[1]["bypassed"] is True
    assert manager.owns_zone(1)
    assert panel.unbypass_calls == []


async def test_offline_zone_recovery(hass, panel):
    """A zone bypassed because offline is restored once back online."""
    entry = await setup_entry(hass, bypassable={"away": [1]})
    manager = get_manager(hass, entry)
    panel.set_zone(1, status="offline")
    coordinator = get_coordinator(hass, entry)
    await coordinator.async_arm_away()
    assert manager.owns_zone(1)

    panel.set_zone(1, status="online")
    await poll(hass, entry)
    await elapse(hass, DEBOUNCE + 2)

    assert panel.zones[1]["bypassed"] is False
    assert not manager.owns_zone(1)


async def test_cleanup_on_ha_disarm(hass, panel):
    """Disarming through HA removes owned bypasses."""
    entry = await setup_entry(hass, bypassable={"away": [1]})
    manager = await arm_away_with_open_door(hass, panel, entry)
    events = async_capture_events(hass, EVENT_BYPASS_REMOVED)

    await get_coordinator(hass, entry).async_disarm()
    await hass.async_block_till_done()

    assert panel.zones[1]["bypassed"] is False
    assert not manager.owns_zone(1)
    assert [e.data["reason"] for e in events] == ["disarm"]


async def test_cleanup_on_external_disarm(hass, panel):
    """A disarm from keypad/Hik-Connect also triggers cleanup."""
    entry = await setup_entry(hass, bypassable={"away": [1]})
    manager = await arm_away_with_open_door(hass, panel, entry)

    panel.disarm()  # external: not through HA
    await poll(hass, entry)
    await hass.async_block_till_done()

    assert panel.zones[1]["bypassed"] is False
    assert not manager.owns_zone(1)


async def test_external_bypass_not_touched_on_disarm(hass, panel):
    """Cleanup only removes integration-owned bypasses."""
    entry = await setup_entry(hass, bypassable={"away": [1]})
    manager = await arm_away_with_open_door(hass, panel, entry)
    panel.zones[2]["bypassed"] = True  # applied via keypad/Hik-Connect

    await get_coordinator(hass, entry).async_disarm()
    await hass.async_block_till_done()

    assert panel.zones[1]["bypassed"] is False
    assert panel.zones[2]["bypassed"] is True


async def test_clear_all_on_disarm_option(hass, panel):
    """Option: cleanup extends to all bypasses when enabled."""
    entry = await setup_entry(
        hass, bypassable={"away": [1]}, **{"clear_all_bypasses_on_disarm": True}
    )
    manager = await arm_away_with_open_door(hass, panel, entry)
    panel.zones[2]["bypassed"] = True

    await get_coordinator(hass, entry).async_disarm()
    await hass.async_block_till_done()

    assert panel.zones[1]["bypassed"] is False
    assert panel.zones[2]["bypassed"] is False
    assert not manager.owns_zone(2)  # never took ownership of it


async def test_refused_unbypass_retried_on_disarm(hass, panel):
    """Firmware refusing unbypass while armed; disarm is the safety net."""
    entry = await setup_entry(hass, bypassable={"away": [1]})
    manager = await arm_away_with_open_door(hass, panel, entry)

    panel.fail_unbypass_zones.add(1)
    panel.set_zone(1, magnetOpenStatus=False)
    await poll(hass, entry)
    await elapse(hass, DEBOUNCE + 2)

    assert panel.zones[1]["bypassed"] is True  # refused
    assert manager.owns_zone(1)
    assert manager.store.data.owned_bypasses[1].pending_unbypass is True

    panel.fail_unbypass_zones.clear()
    await get_coordinator(hass, entry).async_disarm()
    await hass.async_block_till_done()

    assert panel.zones[1]["bypassed"] is False
    assert not manager.owns_zone(1)


async def test_reconciliation_of_externally_removed_bypass(hass, panel):
    """An owned bypass removed via keypad is dropped without errors."""
    entry = await setup_entry(hass, bypassable={"away": [1]})
    manager = await arm_away_with_open_door(hass, panel, entry)
    events = async_capture_events(hass, EVENT_BYPASS_REMOVED)

    # Removed externally; backdate ownership past the reconcile grace period.
    panel.zones[1]["bypassed"] = False
    manager.store.data.owned_bypasses[1].applied_at -= timedelta(seconds=60)
    await poll(hass, entry)

    assert not manager.owns_zone(1)
    assert panel.unbypass_calls == []  # no blind unbypass
    assert [e.data["reason"] for e in events] == ["reconciled"]


async def test_ownership_survives_restart(hass, panel):
    """Owned bypasses are rebuilt from storage after a reload."""
    entry = await setup_entry(hass, bypassable={"away": [1]})
    await arm_away_with_open_door(hass, panel, entry)

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    manager = get_manager(hass, entry)
    assert manager.owns_zone(1)
    assert panel.zones[1]["bypassed"] is True

    # The recovery logic resumes without manual intervention.
    panel.set_zone(1, magnetOpenStatus=False)
    await poll(hass, entry)
    await elapse(hass, DEBOUNCE + 2)
    assert panel.zones[1]["bypassed"] is False
    assert not manager.owns_zone(1)
