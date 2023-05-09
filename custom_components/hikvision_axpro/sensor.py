from __future__ import annotations

import logging
from typing import cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfTemperature,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass, STATE_ON, STATE_OFF
from homeassistant.components.sensor import SensorEntity, DOMAIN as SENSOR_DOMAIN, SensorEntityDescription, SensorDeviceClass, SensorStateClass
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
            zone_config = coordinator.devices.get(zone.zone.id)
            detector_type: DetectorType | None
            if zone_config is not None:
                _LOGGER.debug("Adding device with zone config: %s", zone)
                _LOGGER.debug("+ config: %s", zone_config)
                device_registry.async_get_or_create(
                    config_entry_id=entry.entry_id,
                    # connections={},
                    identifiers={(DOMAIN, str(entry.entry_id) + "-" + str(zone_config.id))},
                    manufacturer="HikVision" if zone.zone.model is not None else "Unknown",
                    # suggested_area=zone.zone.,
                    name=zone_config.zone_name,
                    via_device=(DOMAIN, str(coordinator.mac)),
                    model=detector_model_to_name(zone.zone.model),
                    sw_version=zone.zone.version,
                )
                detector_type = zone_config.detector_type
            else:
                _LOGGER.debug("Adding device: %s", zone)
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
                detector_type = zone.zone.detector_type
            # Specific entity
            if detector_type == DetectorType.WIRELESS_EXTERNAL_MAGNET_DETECTOR:
                devices.append(HikWirelessExtMagnetDetector(coordinator, zone.zone, entry.entry_id))
            if detector_type == DetectorType.DOOR_MAGNETIC_CONTACT_DETECTOR \
                    or detector_type == DetectorType.SLIM_MAGNETIC_CONTACT \
                    or detector_type == DetectorType.MAGNET_SHOCK_DETECTOR:
                devices.append(HikMagneticContactDetector(coordinator, zone.zone, entry.entry_id))
            if detector_type == DetectorType.WIRELESS_TEMPERATURE_HUMIDITY_DETECTOR:
                devices.append(HikHumidity(coordinator, zone.zone, entry.entry_id))
            # Generic Attrs
            if zone.zone.temperature is not None:
                devices.append(HikTemperature(coordinator, zone.zone, entry.entry_id))
            if zone.zone.charge_value is not None:
                devices.append(HikBatteryInfo(coordinator, zone.zone, entry.entry_id))
            if zone.zone.signal is not None:
                devices.append(HikSignalInfo(coordinator, zone.zone, entry.entry_id))
            if zone.zone.tamper_evident is not None:
                devices.append(HikTamperDetection(coordinator, zone.zone, entry.entry_id))
            if zone.zone.bypassed is not None:
                devices.append(HikBypassDetection(coordinator, zone.zone, entry.entry_id))
            if zone.zone.armed is not None:
                devices.append(HikArmedInfo(coordinator, zone.zone, entry.entry_id))
            if zone.zone.alarm is not None:
                devices.append(HikAlarmInfo(coordinator, zone.zone, entry.entry_id))
            if zone.zone.stay_away is not None:
                devices.append(HikStayAwayInfo(coordinator, zone.zone, entry.entry_id))
            if zone.zone.is_via_repeater is not None:
                devices.append(HikIsViaRepeaterInfo(coordinator, zone.zone, entry.entry_id))
            if zone.zone.status is not None:
                devices.append(HikStatusInfo(coordinator, zone.zone, entry.entry_id))
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
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            value = self.coordinator.zones[self.zone.id].magnet_open_status
            if value is True:
                self._attr_state = STATE_OFF
                self._attr_icon = "mdi:magnet-on"
            elif value is False:
                self._attr_state = STATE_ON
                self._attr_icon = "mdi:magnet"
            else:
                self._attr_state = None
                self._attr_icon = "mdi:help"
        else:
            self._attr_state = None
            self._attr_icon = "mdi:help"
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            value = self.coordinator.zones[self.zone.id].status
            return value == Status.ONLINE
        else:
            return False


class HikMagneticContactDetector(CoordinatorEntity, HikDevice, BinarySensorEntity):
    """Representation of Hikvision external magnet detector."""
    coordinator: HikAxProDataUpdateCoordinator

    def __init__(self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-magnet-{zone.id}"
        self._device_class = BinarySensorDeviceClass.PRESENCE
        self._attr_has_entity_name = True
        self.entity_id = f"{SENSOR_DOMAIN}.{coordinator.device_name}-magnet-{zone.id}"

    @property
    def name(self) -> str | None:
        return "Magnet presence"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            value = self.coordinator.zones[self.zone.id].magnet_open_status
            if value is True:
                self._attr_state = STATE_OFF
                self._attr_icon = "mdi:magnet-on"
            elif value is False:
                self._attr_state = STATE_ON
                self._attr_icon = "mdi:magnet"
            else:
                self._attr_state = None
                self._attr_icon = "mdi:help"
        else:
            self._attr_state = None
            self._attr_icon = "mdi:help"
        self.async_write_ha_state()

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
        self._device_class = SensorDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_has_entity_name = True
        self.entity_id = f"{SENSOR_DOMAIN}.{coordinator.device_name}-temperature-{zone.id}"
        self.entity_description = SensorEntityDescription(
            SensorDeviceClass.TEMPERATURE,
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        )

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
        self._device_class = SensorDeviceClass.HUMIDITY
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_has_entity_name = True
        self.entity_id = f"{SENSOR_DOMAIN}.{coordinator.device_name}-humidity-{zone.id}"
        self.entity_description = SensorEntityDescription(
            SensorDeviceClass.HUMIDITY,
            device_class=SensorDeviceClass.HUMIDITY,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
        )

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


class HikBatteryInfo(CoordinatorEntity, HikDevice, SensorEntity):
    """Representation of Hikvision battery status."""
    coordinator: HikAxProDataUpdateCoordinator

    def __init__(self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-battery-{zone.id}"
        self._attr_icon = "mdi:battery"
        self._device_class = SensorDeviceClass.BATTERY
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True
        self.entity_id = f"{SENSOR_DOMAIN}.{coordinator.device_name}-battery-{zone.id}"
        self.entity_description = SensorEntityDescription(
            SensorDeviceClass.BATTERY,
            device_class=SensorDeviceClass.BATTERY,
            entity_category=EntityCategory.DIAGNOSTIC,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
        )

    @property
    def name(self) -> str | None:
        return "Battery"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> StateType:
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            value = self.coordinator.zones[self.zone.id].charge_value
            return cast(float, value)
        else:
            return None


class HikSignalInfo(CoordinatorEntity, HikDevice, SensorEntity):
    """Representation of Hikvision signal status."""
    coordinator: HikAxProDataUpdateCoordinator

    def __init__(self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-signal-{zone.id}"
        self._attr_icon = "mdi:signal"
        self._device_class = SensorDeviceClass.SIGNAL_STRENGTH
        self._attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True
        self.entity_id = f"{SENSOR_DOMAIN}.{coordinator.device_name}-signal-{zone.id}"
        self.entity_description = SensorEntityDescription(
            SensorDeviceClass.SIGNAL_STRENGTH,
            device_class=SensorDeviceClass.SIGNAL_STRENGTH,
            entity_category=EntityCategory.DIAGNOSTIC,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        )

    @property
    def name(self) -> str | None:
        return "Signal"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    @property
    def native_value(self) -> StateType:
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            value = self.coordinator.zones[self.zone.id].signal
            return cast(float, value)
        else:
            return None


class HikStatusInfo(CoordinatorEntity, HikDevice, SensorEntity):
    """Representation of Hikvision signal status."""
    coordinator: HikAxProDataUpdateCoordinator

    def __init__(self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-status-{zone.id}"
        self._attr_has_entity_name = True
        self.entity_id = f"{SENSOR_DOMAIN}.{coordinator.device_name}-status-{zone.id}"
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]\
            and self.coordinator.zones[self.zone.id].status is not None:
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
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]\
            and self.coordinator.zones[self.zone.id].status is not None:
            self._attr_native_value = self.coordinator.zones[self.zone.id].status.value
        else:
            self._attr_native_value = None
        self.async_write_ha_state()


class HikTamperDetection(CoordinatorEntity, HikDevice, BinarySensorEntity):
    """Representation of Hikvision tamper detection."""
    coordinator: HikAxProDataUpdateCoordinator

    def __init__(self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-tamper-{zone.id}"
        self._attr_icon = "mdi:electric-switch"
        self._device_class = BinarySensorDeviceClass.TAMPER
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True
        self.entity_id = f"{SENSOR_DOMAIN}.{coordinator.device_name}-tamper-{zone.id}"

    @property
    def name(self) -> str | None:
        return "Tamper"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            value = self.coordinator.zones[self.zone.id].tamper_evident
            self._attr_state = STATE_ON if value is True else STATE_OFF
        else:
            self._attr_state = None

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            return self.coordinator.zones[self.zone.id].tamper_evident
        else:
            return False


class HikBypassDetection(CoordinatorEntity, HikDevice, BinarySensorEntity):
    """Representation of Hikvision bypass detection."""
    coordinator: HikAxProDataUpdateCoordinator

    def __init__(self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-bypass-{zone.id}"
        self._attr_icon = "mdi:alarm-light-off"
        self._device_class = BinarySensorDeviceClass.SAFETY
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True
        self.entity_id = f"{SENSOR_DOMAIN}.{coordinator.device_name}-bypass-{zone.id}"

    @property
    def name(self) -> str | None:
        return "Bypass"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            value = self.coordinator.zones[self.zone.id].bypassed
            self._attr_state = STATE_ON if value is True else STATE_OFF
        else:
            self._attr_state = None

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            return self.coordinator.zones[self.zone.id].bypassed
        else:
            return False


class HikArmedInfo(CoordinatorEntity, HikDevice, BinarySensorEntity):
    """Representation of Hikvision armed status."""
    coordinator: HikAxProDataUpdateCoordinator

    def __init__(self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-armed-{zone.id}"
        self._attr_icon = "mdi:lock"
        self._device_class = BinarySensorDeviceClass.LOCK
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True
        self.entity_id = f"{SENSOR_DOMAIN}.{coordinator.device_name}-armed-{zone.id}"

    @property
    def name(self) -> str | None:
        return "Armed"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            value = self.coordinator.zones[self.zone.id].armed
            self._attr_state = STATE_ON if value is True else STATE_OFF
        else:
            self._attr_state = None

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            return self.coordinator.zones[self.zone.id].armed
        else:
            return False


class HikAlarmInfo(CoordinatorEntity, HikDevice, BinarySensorEntity):
    """Representation of Hikvision alarm status."""
    coordinator: HikAxProDataUpdateCoordinator

    def __init__(self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-alarm-{zone.id}"
        self._attr_icon = "mdi:alarm-light"
        self._device_class = BinarySensorDeviceClass.LOCK
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True
        self.entity_id = f"{SENSOR_DOMAIN}.{coordinator.device_name}-alarm-{zone.id}"

    @property
    def name(self) -> str | None:
        return "Alarm"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            value = self.coordinator.zones[self.zone.id].alarm
            self._attr_state = STATE_ON if value is True else STATE_OFF
        else:
            self._attr_state = None

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            return self.coordinator.zones[self.zone.id].alarm
        else:
            return False


class HikStayAwayInfo(CoordinatorEntity, HikDevice, BinarySensorEntity):
    """Representation of Hikvision Stay away status."""
    coordinator: HikAxProDataUpdateCoordinator

    def __init__(self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-stayaway-{zone.id}"
        self._attr_icon = "mdi:shield-lock-outline"
        self._device_class = BinarySensorDeviceClass.LOCK
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True
        self.entity_id = f"{SENSOR_DOMAIN}.{coordinator.device_name}-stayaway-{zone.id}"

    @property
    def name(self) -> str | None:
        return "Stay away"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            value = self.coordinator.zones[self.zone.id].stay_away
            self._attr_state = STATE_ON if value is True else STATE_OFF
        else:
            self._attr_state = None

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            return self.coordinator.zones[self.zone.id].stay_away
        else:
            return False


class HikIsViaRepeaterInfo(CoordinatorEntity, HikDevice, BinarySensorEntity):
    """Representation of Hikvision is via repeater status."""
    coordinator: HikAxProDataUpdateCoordinator

    def __init__(self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-isviarepeater-{zone.id}"
        self._attr_icon = "mdi:google-circles-extended"
        self._device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True
        self.entity_id = f"{SENSOR_DOMAIN}.{coordinator.device_name}-isviarepeater-{zone.id}"

    @property
    def name(self) -> str | None:
        return "Is via repeater"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            value = self.coordinator.zones[self.zone.id].is_via_repeater
            self._attr_state = STATE_ON if value is True else STATE_OFF
        else:
            self._attr_state = None

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            return self.coordinator.zones[self.zone.id].is_via_repeater
        else:
            return False
