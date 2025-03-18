"""Binary Sensors.

Hikvision binary sensors.
"""

from __future__ import annotations

import logging
from typing import cast

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.sensor import (SensorDeviceClass, SensorEntity,
                                             SensorStateClass)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (PERCENTAGE,
                                 SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
                                 UnitOfTemperature)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HikAxProDataUpdateCoordinator
from .const import DATA_COORDINATOR, DOMAIN
from .hik_device import HikDevice
from .model import DetectorType, Status, Zone, detector_model_to_name
from .siren_entities import HikSirenBatteryInfo, HikSirenTemperature, HikSirenSignalInfo

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up a Hikvision ax pro alarm control panel based on a config entry."""

    coordinator: HikAxProDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]
    devices = []
    await coordinator.async_request_refresh()
    device_registry = dr.async_get(hass)

    _LOGGER.debug("Coordinator with sirens: %s", coordinator.sirens_status)
    if coordinator.sirens is not None:
        for [siren_id, siren] in coordinator.sirens.items():
            _LOGGER.debug("Adding siren with config: %s", siren)
            device_registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, str(entry.entry_id) + "-siren-" + str(siren_id))},
                manufacturer="HikVision",
                name=siren.name,
                via_device=(DOMAIN, str(coordinator.mac)),
            )
            siren_status = coordinator.sirens_status[siren.id]
            _LOGGER.debug("Adding siren status with config: %s", siren_status)
            devices.append(HikSirenTemperature(coordinator, siren_status, entry.entry_id))
            devices.append(HikSirenBatteryInfo(coordinator, siren_status, entry.entry_id))
            devices.append(HikSirenSignalInfo(coordinator, siren_status, entry.entry_id))

    if coordinator.zone_status is not None:
        for zone in coordinator.zone_status.zone_list:
            zone_config = coordinator.devices.get(zone.zone.id)
            detector_type: DetectorType | None
            if zone_config is not None:
                _LOGGER.debug("Adding device with zone config: %s", zone)
                _LOGGER.debug("+ config: %s", zone_config)
                detector_type = zone_config.detector_type
                device_registry.async_get_or_create(
                    config_entry_id=entry.entry_id,
                    # connections={},
                    identifiers={
                        (DOMAIN, str(entry.entry_id) + "-" + str(zone_config.id))
                    },
                    manufacturer="HikVision"
                    if zone.zone.model is not None
                    else "Unknown",
                    # suggested_area=zone.zone.,
                    name=zone_config.zone_name,
                    via_device=(DOMAIN, str(coordinator.mac)),
                    model=detector_model_to_name(zone.zone.model)
                    if zone.zone.model is not None
                    else detector_type,
                    sw_version=zone.zone.version,
                )
            else:
                _LOGGER.debug("Zone config empty")
                _LOGGER.debug("Adding device: %s", zone)
                detector_type = zone.zone.detector_type
                device_registry.async_get_or_create(
                    config_entry_id=entry.entry_id,
                    # connections={},
                    identifiers={
                        (DOMAIN, str(entry.entry_id) + "-" + str(zone.zone.id))
                    },
                    manufacturer="HikVision"
                    if zone.zone.model is not None
                    else "Unknown",
                    # suggested_area=zone.zone.,
                    name=zone.zone.name,
                    via_device=(DOMAIN, str(coordinator.mac)),
                    model=detector_model_to_name(zone.zone.model)
                    if zone.zone.model is not None
                    else detector_type,
                    sw_version=zone.zone.version,
                )

            _LOGGER.debug(
                "Compare %s is %s == %s",
                detector_type,
                detector_type is DetectorType.MAGNET_SHOCK_DETECTOR,
                detector_type == DetectorType.MAGNET_SHOCK_DETECTOR,
            )
            if detector_type == DetectorType.WIRELESS_TEMPERATURE_HUMIDITY_DETECTOR:
                devices.append(HikHumidity(coordinator, zone.zone, entry.entry_id))
            # Generic Attrs
            if zone.zone.temperature is not None:
                devices.append(HikTemperature(coordinator, zone.zone, entry.entry_id))

            if zone.zone.charge_value is not None:
                devices.append(HikBatteryInfo(coordinator, zone.zone, entry.entry_id))
            if zone.zone.signal is not None:
                devices.append(HikSignalInfo(coordinator, zone.zone, entry.entry_id))
            if zone.zone.status is not None:
                devices.append(HikStatusInfo(coordinator, zone.zone, entry.entry_id))
    _LOGGER.debug("setting up - sensors: %s", ",".join(x.name for x in devices))
    async_add_entities(devices, False)


class HikTemperature(CoordinatorEntity, HikDevice, SensorEntity):
    """Representation of Hikvision external magnet detector."""

    coordinator: HikAxProDataUpdateCoordinator

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str
    ) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-temp-{zone.id}"
        self._attr_icon = "mdi:thermometer"
        # self._attr_name = f"{self.zone.name} Temperature"
        self._device_class = SensorDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_has_entity_name = True
        self.entity_id = (
            f"{SENSOR_DOMAIN}.{coordinator.device_name}-temperature-{zone.id}"
        )
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def name(self) -> str | None:
        return "Temperature"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            self._attr_native_value = cast(
                float, self.coordinator.zones[self.zone.id].temperature
            )
            self._attr_available = True
        else:
            self._attr_native_value = None
            self._attr_available = False
        self.async_write_ha_state()


class HikHumidity(CoordinatorEntity, HikDevice, SensorEntity):
    """Representation of Hikvision external magnet detector."""

    coordinator: HikAxProDataUpdateCoordinator

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str
    ) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-humid-{zone.id}"
        self._attr_icon = "mdi:cloud-percent"
        # self._attr_name = f"{self.zone.name} Humidity"
        self._device_class = SensorDeviceClass.HUMIDITY
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_has_entity_name = True
        self.entity_id = f"{SENSOR_DOMAIN}.{coordinator.device_name}-humidity-{zone.id}"

    @property
    def name(self) -> str | None:
        return "Humidity"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            self._attr_native_value = cast(
                float, self.coordinator.zones[self.zone.id].humidity
            )
            self._attr_available = True
        else:
            self._attr_native_value = None
            self._attr_available = False
        self.async_write_ha_state()


class HikBatteryInfo(CoordinatorEntity, HikDevice, SensorEntity):
    """Representation of Hikvision battery status."""

    coordinator: HikAxProDataUpdateCoordinator

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str
    ) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-battery-{zone.id}"
        self._attr_icon = "mdi:battery"
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_has_entity_name = True
        self.entity_id = f"{SENSOR_DOMAIN}.{coordinator.device_name}-battery-{zone.id}"

    @property
    def name(self) -> str | None:
        return "Battery"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            self._attr_native_value = cast(
                float, self.coordinator.zones[self.zone.id].charge_value
            )
            self._attr_available = True
        else:
            self._attr_native_value = None
            self._attr_available = False
        self.async_write_ha_state()


class HikSignalInfo(CoordinatorEntity, HikDevice, SensorEntity):
    """Representation of Hikvision signal status."""

    coordinator: HikAxProDataUpdateCoordinator

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str
    ) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-signal-{zone.id}"
        self._attr_icon = "mdi:signal"
        self._device_class = SensorDeviceClass.SIGNAL_STRENGTH
        self._attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_has_entity_name = True
        self.entity_id = f"{SENSOR_DOMAIN}.{coordinator.device_name}-signal-{zone.id}"

    @property
    def name(self) -> str | None:
        return "Signal"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            self._attr_native_value = cast(
                float, self.coordinator.zones[self.zone.id].signal
            )
            self._attr_available = True
        else:
            self._attr_native_value = None
            self._attr_available = False
        self.async_write_ha_state()


class HikStatusInfo(CoordinatorEntity, HikDevice, SensorEntity):
    """Representation of Hikvision signal status."""

    coordinator: HikAxProDataUpdateCoordinator

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str
    ) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-status-{zone.id}"
        self._attr_has_entity_name = True
        self.entity_id = f"{SENSOR_DOMAIN}.{coordinator.device_name}-status-{zone.id}"
        if (
            self.coordinator.zones
            and self.coordinator.zones[self.zone.id]
            and self.coordinator.zones[self.zone.id].status is not None
        ):
            self._attr_native_value = self.coordinator.zones[self.zone.id].status.value

    @property
    def name(self) -> str | None:
        return "Status"

    @property
    def icon(self) -> str | None:
        """Return the icon to use in the frontend, if any."""
        if self._attr_native_value is not None:
            if self._attr_native_value is Status.OFFLINE.value:
                return "mdi:signal-off"
            if self._attr_native_value is Status.NOT_RELATED:
                return "mdi:help"
            if self._attr_native_value is Status.ONLINE.value:
                return "mdi:access-point-check"
            if self._attr_native_value is Status.TRIGGER.value:
                return "mdi:alarm-light"
            if self._attr_native_value is Status.BREAK_DOWN.value:
                return "mdi:image-broken-variant"
            if self._attr_native_value is Status.HEART_BEAT_ABNORMAL.value:
                return "mdi:heart-broken"
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if (
            self.coordinator.zones
            and self.coordinator.zones[self.zone.id]
            and self.coordinator.zones[self.zone.id].status is not None
        ):
            self._attr_native_value = self.coordinator.zones[self.zone.id].status.value
            self._attr_available = True
        else:
            self._attr_native_value = None
            self._attr_available = False
        self.async_write_ha_state()
