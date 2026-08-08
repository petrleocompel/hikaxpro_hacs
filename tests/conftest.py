"""Shared fixtures: a mock AX Pro panel with in-memory state."""

from __future__ import annotations

from unittest.mock import patch

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
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hikvision_axpro.const import (
    ALLOW_SUBSYSTEMS,
    DATA_COORDINATOR,
    DOMAIN,
    USE_CODE_ARMING,
)

pytest_plugins = "pytest_homeassistant_custom_component"

DEVICE_INFO_XML = (
    '<DeviceInfo xmlns="http://www.hikvision.com/ver20/XMLSchema">'
    "<deviceName>axpro</deviceName><model>AX PRO</model></DeviceInfo>"
)


@pytest.fixture
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading the custom component.

    Applied via ``pytestmark`` in the integration-level test modules so
    that the pure-function tests do not pull in the ``hass`` fixture.
    """
    yield


def zone_payload(
    zone_id: int = 1,
    name: str | None = None,
    status: str = "online",
    bypassed: bool = False,
    armed: bool = False,
    alarm: bool = False,
    tamper: bool = False,
    sub_system_no: int = 1,
    zone_type: str = "Instant",
    magnet_open: bool | None = None,
    charge: str | None = None,
    stay_away: bool | None = None,
) -> dict:
    """Build a raw zone status dict as the panel returns it."""
    payload = {
        "id": zone_id,
        "name": name or f"Zone {zone_id}",
        "status": status,
        "tamperEvident": tamper,
        "bypassed": bypassed,
        "armed": armed,
        "alarm": alarm,
        "subSystemNo": sub_system_no,
        "zoneType": zone_type,
    }
    if magnet_open is not None:
        payload["magnetOpenStatus"] = magnet_open
    if charge is not None:
        payload["charge"] = charge
    if stay_away is not None:
        payload["stayAway"] = stay_away
    return payload


class MockResponse:
    """Minimal requests.Response stand-in."""

    def __init__(self, status_code: int = 200, text: str = "", json_data=None):
        self.status_code = status_code
        self.text = text or (str(json_data) if json_data is not None else "")
        self._json = json_data

    def json(self):
        return self._json


class MockAxPro:
    """In-memory AX Pro panel implementing the hikaxpro client API."""

    host = "1.2.3.4"

    def __init__(self, zones: list[dict] | None = None, subsystems=None):
        self.zones: dict[int, dict] = {z["id"]: z for z in (zones or [])}
        # Optional per-zone configuration payloads (ZonesConfig endpoint),
        # e.g. {"id": 1, "zoneName": "Front door"}
        self.zone_configs: list[dict] = []
        self.subsystems = subsystems or [
            {
                "id": 1,
                "arming": "disarm",
                "alarm": False,
                "enabled": True,
                "name": "Area 1",
                "delayTime": 0,
            }
        ]
        self.refuse_arm = False
        self.zone_status_fail = False
        self.arm_calls: list[tuple[str, int | None]] = []

    # --- helpers for tests -------------------------------------------------
    def set_zone(self, zone_id: int, **fields) -> None:
        self.zones[zone_id].update(fields)

    def area(self, sub_id: int = 1) -> dict:
        return next(s for s in self.subsystems if s["id"] == sub_id)

    # --- hikaxpro client API ------------------------------------------------
    def get_interface_mac_address(self, interface_id):
        return "00:11:22:33:44:55"

    def set_logging_level(self, level):
        pass

    def connect(self):
        return True

    @staticmethod
    def build_url(endpoint, is_json=False):
        prefix = "&" if "?" in endpoint else "?"
        return f"{endpoint}{prefix}format=json" if is_json else endpoint

    def subsystem_status(self):
        return {"SubSysList": [{"SubSys": dict(sub)} for sub in self.subsystems]}

    def zone_status(self):
        if self.zone_status_fail:
            raise ConnectionError("zone status unavailable")
        return {"ZoneList": [{"Zone": dict(zone)} for zone in self.zones.values()]}

    def _arm(self, mode, sub_id):
        self.arm_calls.append((mode, sub_id))
        if self.refuse_arm:
            return False
        for sub in self.subsystems:
            if sub_id is None or sub["id"] == sub_id:
                sub["arming"] = mode
        return True

    def arm_home(self, sub_id=None):
        return self._arm("stay", sub_id)

    def arm_away(self, sub_id=None):
        return self._arm("away", sub_id)

    def disarm(self, sub_id=None):
        for sub in self.subsystems:
            if sub_id is None or sub["id"] == sub_id:
                sub["arming"] = "disarm"
        return True

    def make_request(self, endpoint, method, data=None, is_json=False):
        if "control/arm/" in endpoint:
            # Used by the integration for arm modes hikaxpro does not
            # expose (vacation).
            sid = endpoint.split("control/arm/")[1].split("?")[0]
            sub_id = None if sid == "0xffffffff" else int(sid)
            ways = endpoint.split("ways=")[1].split("&")[0]
            if not self._arm(ways, sub_id):
                return MockResponse(json_data={})
            return MockResponse(json_data={"statusCode": 1})
        if "status/zones" in endpoint:
            if self.zone_status_fail:
                raise ConnectionError("zone status unavailable")
            return MockResponse(json_data=self.zone_status())
        if "deviceInfo" in endpoint:
            return MockResponse(text=DEVICE_INFO_XML)
        if "Configuration/zones" in endpoint:
            return MockResponse(
                json_data={"List": [{"Zone": dict(cfg)} for cfg in self.zone_configs]}
            )
        if "Configuration/outputs" in endpoint:
            return MockResponse(json_data={"List": []})
        if "exDevStatus" in endpoint:
            return MockResponse(json_data={})
        return MockResponse(status_code=404, text=f"no mock for {endpoint}")


@pytest.fixture
def panel():
    """A default panel: door zone 1 + PIR zone 2."""
    mock = MockAxPro(
        zones=[
            zone_payload(1, name="Front door", magnet_open=False),
            zone_payload(2, name="Curtain hall"),
        ]
    )
    with patch("hikaxpro.HikAxPro", return_value=mock):
        yield mock


def make_entry(
    hass, entry_id: str = "test-entry", **overrides
) -> MockConfigEntry:
    """Create and register a config entry with sane defaults."""
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
    }
    data.update(overrides)
    entry = MockConfigEntry(domain=DOMAIN, data=data, entry_id=entry_id)
    entry.add_to_hass(hass)
    return entry


async def setup_entry(hass, **overrides) -> MockConfigEntry:
    """Set up the integration and wait for it to settle."""
    entry = make_entry(hass, **overrides)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def get_coordinator(hass, entry):
    return hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
