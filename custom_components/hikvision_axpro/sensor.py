from __future__ import annotations

import logging
from typing import cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import TEMP_CELSIUS, DEVICE_CLASS_HUMIDITY, PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass, STATE_ON, STATE_OFF
from homeassistant.components.sensor import SensorEntity, DEVICE_CLASS_TEMPERATURE, DOMAIN as SENSOR_DOMAIN
from homeassistant.helpers import device_registry as dr

from homeassistant.helpers.typing import StateType


from . import HikAxProDataUpdateCoordinator
from .const import DATA_COORDINATOR, DOMAIN
from .model import DetectorType, Zone, Status, detector_model_to_name

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up a Hikvision ax pro alarm control panel based on a config entry."""

    coordinator: HikAxProDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    devices = []
    await coordinator.async_request_refresh()
    device_registry = dr.async_get(hass)
    if coordinator.zone_status is not None:
        for zone in coordinator.zone_status.zone_list:
            device_registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                # connections={},
                identifiers={(DOMAIN, str(entry.entry_id) + "-" + str(zone.zone.id))},
                manufacturer="HikVision" if zone.zone.model is not None else "Unknown",
                # suggested_area=zone.zone.,
                name=zone.zone.name,
                via_device=(DOMAIN, str(coordinator.mac)),
                model=detector_model_to_name(zone.zone.model),
                sw_version=zone.zone.version,
            )
            if zone.zone.detector_type == DetectorType.WIRELESS_EXTERNAL_MAGNET_DETECTOR:
                devices.append(HikWirelessExtMagnetDetector(coordinator, zone.zone, entry.entry_id))
            if zone.zone.temperature is not None:
                devices.append(HikTemperature(coordinator, zone.zone, entry.entry_id))
            if zone.zone.detector_type == DetectorType.WIRELESS_TEMPERATURE_HUMIDITY_DETECTOR:
                devices.append(HikHumidity(coordinator, zone.zone, entry.entry_id))
    _LOGGER.debug("devices: %s", devices)
    async_add_entities(devices, False)


class HikDevice:

    zone: Zone
    _ref_id: str

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, str(self._ref_id) + "-" + str(self.zone.id))},
            manufacturer="HikVision" if self.zone.model is not None else "Unknown",
            # suggested_area=zone.zone.,
            name=self.zone.name,
            # model="Unknown" if self.zone.model is not "0x00001" else self.zone.model,
            sw_version=self.zone.version,
        )


class HikWirelessExtMagnetDetector(CoordinatorEntity, HikDevice, BinarySensorEntity):
    """Representation of Hikvision external magnet detector."""
    coordinator: HikAxProDataUpdateCoordinator

    def __init__(self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-magnet-{zone.id}"
        self._attr_icon = "mdi:magnet"
        #self._attr_name = f"Magnet presence"
        self._device_class = BinarySensorDeviceClass.PRESENCE
        self._attr_has_entity_name = True
        self.entity_id = f"{SENSOR_DOMAIN}.{coordinator.device_name}-magnet-{zone.id}"

    @property
    def name(self) -> str | None:
        return "Magnet presence"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            value = self.coordinator.zones[self.zone.id].magnet_open_status
            self._attr_state = STATE_ON if value is True else STATE_OFF
        else:
            self._attr_state = None

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            value = self.coordinator.zones[self.zone.id].status
            return value == Status.ONLINE
        else:
            return False


class HikTemperature(CoordinatorEntity, HikDevice, SensorEntity):
    """Representation of Hikvision external magnet detector."""
    coordinator: HikAxProDataUpdateCoordinator

    def __init__(self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-temp-{zone.id}"
        self._attr_icon = "mdi:thermometer"
        #self._attr_name = f"{self.zone.name} Temperature"
        self._device_class = DEVICE_CLASS_TEMPERATURE
        self._attr_native_unit_of_measurement = TEMP_CELSIUS
        self._attr_has_entity_name = True
        self.entity_id = f"{SENSOR_DOMAIN}.{coordinator.device_name}-temperature-{zone.id}"

    @property
    def name(self) -> str | None:
        return "Temperature"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> StateType:
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            value = self.coordinator.zones[self.zone.id].temperature
            return cast(float, value)
        else:
            return None


class HikHumidity(CoordinatorEntity, HikDevice, SensorEntity):
    """Representation of Hikvision external magnet detector."""
    coordinator: HikAxProDataUpdateCoordinator

    def __init__(self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-humid-{zone.id}"
        self._attr_icon = "mdi:cloud-percent"
        #self._attr_name = f"{self.zone.name} Humidity"
        self._device_class = DEVICE_CLASS_HUMIDITY
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_has_entity_name = True
        self.entity_id = f"{SENSOR_DOMAIN}.{coordinator.device_name}-humidity-{zone.id}"

    @property
    def name(self) -> str | None:
        return "Humidity"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> StateType:
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            value = self.coordinator.zones[self.zone.id].humidity
            return cast(float, value)
        else:
            return None

