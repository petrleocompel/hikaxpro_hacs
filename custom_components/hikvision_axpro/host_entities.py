"""Panel host / AC / hub-battery sensors from documented status APIs."""

from __future__ import annotations

from typing import Any, cast

from homeassistant.components.binary_sensor import (
    DOMAIN as BINARY_SENSOR_DOMAIN,
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.sensor import (
    DOMAIN as SENSOR_DOMAIN,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfElectricPotential
from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HikAxProDataUpdateCoordinator
from .const import DOMAIN
from .entity_id import build_entity_id


def build_host_binary_sensors(
    coordinator: HikAxProDataUpdateCoordinator, entry_id: str
) -> list[BinarySensorEntity]:
    """Create panel-level binary sensors when host/AC data is present."""
    entities: list[BinarySensorEntity] = []
    if coordinator.ac_power_status is not None:
        entities.append(HikAcPowerBinary(coordinator, entry_id))
    return entities


def build_host_sensors(
    coordinator: HikAxProDataUpdateCoordinator, entry_id: str
) -> list[SensorEntity]:
    """Create panel-level sensors when host/battery data is present."""
    entities: list[SensorEntity] = []
    batteries = coordinator.hub_batteries or []
    for battery in batteries:
        battery_id = battery.get("id", 0)
        entities.append(
            HikHubBatteryPercent(coordinator, entry_id, battery_id=int(battery_id))
        )
        if battery.get("status") is not None:
            entities.append(
                HikHubBatteryStatus(coordinator, entry_id, battery_id=int(battery_id))
            )
        if battery.get("voltage") is not None:
            entities.append(
                HikHubBatteryVoltage(coordinator, entry_id, battery_id=int(battery_id))
            )
    if coordinator.host_status is not None:
        entities.append(HikHostStatusSensor(coordinator, entry_id))
    return entities


class HikPanelEntity(CoordinatorEntity):
    """Entities attached to the main panel device."""

    coordinator: HikAxProDataUpdateCoordinator
    _ref_id: str

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator)
        self._ref_id = entry_id

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, str(self.coordinator.mac))},
            manufacturer="HikVision",
            name=self.coordinator.device_name or "AX Pro",
            model=self.coordinator.device_model,
        )


class HikAcPowerBinary(HikPanelEntity, BinarySensorEntity):
    """AC mains presence from acPowerStatus."""

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{coordinator.device_name}-ac-power"
        self._attr_name = "AC power"
        self._attr_has_entity_name = True
        self._attr_device_class = BinarySensorDeviceClass.POWER
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self.entity_id = build_entity_id(
            BINARY_SENSOR_DOMAIN, coordinator.device_name, "ac_power"
        )

    def _is_on(self) -> bool | None:
        data = self.coordinator.ac_power_status
        if not data:
            return None
        # Common shapes: {"AcPowerStatus":{"status":"normal"}} or flat status
        node = data.get("AcPowerStatus", data)
        status = node.get("status") if isinstance(node, dict) else None
        if status is None:
            return None
        return str(status).lower() in ("normal", "on", "ok", "true", "present")

    @callback
    def _handle_coordinator_update(self) -> None:
        value = self._is_on()
        self._attr_is_on = value
        self._attr_available = value is not None
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        return self._is_on()


class HikHostStatusSensor(HikPanelEntity, SensorEntity):
    """Compact host status summary (best-effort from host JSON)."""

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{coordinator.device_name}-host-status"
        self._attr_name = "Host status"
        self._attr_has_entity_name = True
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self.entity_id = build_entity_id(
            SENSOR_DOMAIN, coordinator.device_name, "host_status"
        )

    def _value(self) -> str | None:
        data = self.coordinator.host_status
        if not data:
            return None
        host = data.get("HostStatus", data)
        if not isinstance(host, dict):
            return str(host)
        for key in ("status", "hostStatus", "workStatus", "state"):
            if host.get(key) is not None:
                return str(host[key])
        # Fall back to a short fingerprint of known keys
        interesting = {
            k: host[k]
            for k in ("charge", "battery", "AC", "ac", "tamperEvident")
            if k in host
        }
        return str(interesting) if interesting else "ok"

    @callback
    def _handle_coordinator_update(self) -> None:
        value = self._value()
        self._attr_native_value = value
        self._attr_available = value is not None
        self.async_write_ha_state()


def _battery_node(
    coordinator: HikAxProDataUpdateCoordinator, battery_id: int
) -> dict[str, Any] | None:
    for battery in coordinator.hub_batteries or []:
        if int(battery.get("id", -1)) == battery_id:
            return battery
    return None


class HikHubBatteryPercent(HikPanelEntity, SensorEntity):
    """Hub battery percentage from /status/batteries."""

    def __init__(
        self,
        coordinator: HikAxProDataUpdateCoordinator,
        entry_id: str,
        *,
        battery_id: int,
    ) -> None:
        super().__init__(coordinator, entry_id)
        self._battery_id = battery_id
        self._attr_unique_id = f"{coordinator.device_name}-hub-battery-{battery_id}"
        self._attr_name = (
            "Hub battery" if battery_id in (0, 1) else f"Hub battery {battery_id}"
        )
        self._attr_has_entity_name = True
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self.entity_id = build_entity_id(
            SENSOR_DOMAIN, coordinator.device_name, "hub_battery", battery_id
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        node = _battery_node(self.coordinator, self._battery_id)
        percent = None if node is None else node.get("percent")
        if percent is None:
            self._attr_native_value = None
            self._attr_available = False
        else:
            self._attr_native_value = cast(float, percent)
            self._attr_available = True
        self.async_write_ha_state()


class HikHubBatteryStatus(HikPanelEntity, SensorEntity):
    """Hub battery categorical status."""

    def __init__(
        self,
        coordinator: HikAxProDataUpdateCoordinator,
        entry_id: str,
        *,
        battery_id: int,
    ) -> None:
        super().__init__(coordinator, entry_id)
        self._battery_id = battery_id
        self._attr_unique_id = (
            f"{coordinator.device_name}-hub-battery-status-{battery_id}"
        )
        self._attr_name = (
            "Hub battery status"
            if battery_id in (0, 1)
            else f"Hub battery {battery_id} status"
        )
        self._attr_has_entity_name = True
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self.entity_id = build_entity_id(
            SENSOR_DOMAIN, coordinator.device_name, "hub_battery_status", battery_id
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        node = _battery_node(self.coordinator, self._battery_id)
        status = None if node is None else node.get("status")
        self._attr_native_value = status
        self._attr_available = status is not None
        self.async_write_ha_state()


class HikHubBatteryVoltage(HikPanelEntity, SensorEntity):
    """Hub battery voltage."""

    def __init__(
        self,
        coordinator: HikAxProDataUpdateCoordinator,
        entry_id: str,
        *,
        battery_id: int,
    ) -> None:
        super().__init__(coordinator, entry_id)
        self._battery_id = battery_id
        self._attr_unique_id = (
            f"{coordinator.device_name}-hub-battery-voltage-{battery_id}"
        )
        self._attr_name = (
            "Hub battery voltage"
            if battery_id in (0, 1)
            else f"Hub battery {battery_id} voltage"
        )
        self._attr_has_entity_name = True
        self._attr_device_class = SensorDeviceClass.VOLTAGE
        self._attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self.entity_id = build_entity_id(
            SENSOR_DOMAIN, coordinator.device_name, "hub_battery_voltage", battery_id
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        node = _battery_node(self.coordinator, self._battery_id)
        voltage = None if node is None else node.get("voltage")
        if voltage is None:
            self._attr_native_value = None
            self._attr_available = False
        else:
            self._attr_native_value = cast(float, voltage)
            self._attr_available = True
        self.async_write_ha_state()
