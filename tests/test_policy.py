"""Tests for the pure policy functions."""

from __future__ import annotations

import pytest

from custom_components.hikvision_axpro.bypass_manager import (
    evaluate_arm_readiness,
    is_auto_bypass_eligible,
    zone_fault_reason,
    zone_in_area,
)
from custom_components.hikvision_axpro.const import (
    ARM_MODE_AWAY,
    ARM_MODE_HOME,
    ARM_MODE_VACATION,
)
from custom_components.hikvision_axpro.model import Zone

from .conftest import zone_payload


def make_zone(**kwargs) -> Zone:
    return Zone.from_dict(zone_payload(**kwargs))


# ---------------------------------------------------------------------------
# Fault definition


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({}, None),
        ({"status": "trigger"}, "open"),
        ({"alarm": True}, "open"),
        ({"magnet_open": True}, "open"),
        ({"status": "offline"}, "offline"),
        ({"status": "breakDown"}, "offline"),
        ({"status": "heartbeatAbnormal"}, "offline"),
        ({"tamper": True}, "tamper"),
        # tamper wins over open when both present
        ({"tamper": True, "status": "trigger"}, "tamper"),
        # low battery is a warning only (documented decision)
        ({"charge": "lowPower"}, None),
        # notRelated zones are ignored entirely
        ({"status": "notRelated", "tamper": True}, None),
    ],
)
def test_zone_fault_reason(fields, expected):
    assert zone_fault_reason(make_zone(**fields)) == expected


# ---------------------------------------------------------------------------
# Zone type whitelist


@pytest.mark.parametrize(
    ("zone_type", "eligible"),
    [
        # Only instant zones are eligible: the panel offers the "forbid
        # bypass on arming" option exclusively for them.
        ("Instant", True),
        ("Delay", False),
        ("Perimeter", False),
        ("Follow", False),
        ("24h", False),
        ("24hNoSound", False),
        ("Fire", False),
        ("Gas", False),
        ("Medical", False),
        ("Emergency", False),
        ("Key", False),
        ("Non-Alarm", False),
        ("Timeout", False),
    ],
)
def test_auto_bypass_zone_type_whitelist(zone_type, eligible):
    assert is_auto_bypass_eligible(make_zone(zone_type=zone_type)) is eligible


# ---------------------------------------------------------------------------
# Area membership


def test_zone_in_area():
    zone = make_zone(sub_system_no=2)
    assert zone_in_area(zone, None) is True
    assert zone_in_area(zone, 2) is True
    assert zone_in_area(zone, 1) is False


def test_zone_in_area_linkage_fallback():
    zone = Zone.from_dict(
        {**zone_payload(1), "subSystemNo": None, "linkageSubSystem": [1, 3]}
    )
    assert zone_in_area(zone, 3) is True
    assert zone_in_area(zone, 2) is False


# ---------------------------------------------------------------------------
# Readiness evaluation (single source of truth)


def test_readiness_all_healthy():
    zones = [make_zone(zone_id=1), make_zone(zone_id=2)]
    result = evaluate_arm_readiness(zones, set())
    assert result.ready is True
    assert result.blocking_zones == []
    assert result.zones_to_bypass == []


def test_readiness_faulted_bypassable_zone():
    zones = [make_zone(zone_id=1, magnet_open=True)]
    result = evaluate_arm_readiness(zones, {1})
    assert result.ready is True
    assert [z["zone_id"] for z in result.zones_to_bypass] == [1]


def test_readiness_faulted_non_bypassable_blocks():
    zones = [make_zone(zone_id=1, magnet_open=True)]
    result = evaluate_arm_readiness(zones, set())
    assert result.ready is False
    assert [z["zone_id"] for z in result.blocking_zones] == [1]


def test_readiness_ec04_dual_technology_entry():
    """Door open + curtain offline; curtain not bypassable => blocked."""
    zones = [
        make_zone(zone_id=1, name="Front door", magnet_open=True),
        make_zone(zone_id=2, name="Curtain hall", status="offline"),
    ]
    result = evaluate_arm_readiness(zones, {1})
    assert result.ready is False
    assert [z["zone_id"] for z in result.blocking_zones] == [2]
    assert [z["zone_id"] for z in result.zones_to_bypass] == [1]


def test_readiness_flag_on_excluded_type_still_blocks():
    """A bypassable flag on a 24h zone must not allow auto-bypass."""
    zones = [make_zone(zone_id=1, zone_type="24h", status="trigger")]
    result = evaluate_arm_readiness(zones, {1})
    assert result.ready is False


def test_readiness_skips_already_bypassed_zones():
    """Panel-side bypasses are not touched nor counted."""
    zones = [make_zone(zone_id=1, status="trigger", bypassed=True)]
    result = evaluate_arm_readiness(zones, set())
    assert result.ready is True
    assert result.zones_to_bypass == []


def test_readiness_home_skips_stay_bypassed_zones():
    """In home mode, zones the panel stay-bypasses itself are ignored."""
    zones = [make_zone(zone_id=1, magnet_open=True, stay_away=True)]
    assert evaluate_arm_readiness(zones, set(), ARM_MODE_HOME).ready is True
    # Away and vacation still consider the zone.
    assert evaluate_arm_readiness(zones, set(), ARM_MODE_AWAY).ready is False
    assert evaluate_arm_readiness(zones, set(), ARM_MODE_VACATION).ready is False
    # Default mode is away for backwards compatibility.
    assert evaluate_arm_readiness(zones, set()).ready is False


def test_readiness_home_still_blocks_on_regular_zone():
    """A faulted zone without the stay flag blocks home like any mode."""
    zones = [make_zone(zone_id=1, magnet_open=True, stay_away=False)]
    assert evaluate_arm_readiness(zones, set(), ARM_MODE_HOME).ready is False


def test_readiness_per_area_breakdown():
    zones = [
        make_zone(zone_id=1, sub_system_no=1, magnet_open=True),
        make_zone(zone_id=2, sub_system_no=2, status="offline"),
        make_zone(zone_id=3, sub_system_no=2),
    ]
    result = evaluate_arm_readiness(zones, {1})
    areas = result.per_area
    assert areas[1]["ready"] is True
    assert [z["zone_id"] for z in areas[1]["zones_to_bypass"]] == [1]
    assert areas[2]["ready"] is False
    assert [z["zone_id"] for z in areas[2]["blocking_zones"]] == [2]
