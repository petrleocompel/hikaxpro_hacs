"""Binary Sensors.

Hikvision binary sensors.
"""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    DOMAIN as SENSOR_DOMAIN,
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HikAxProDataUpdateCoordinator
from .const import DATA_COORDINATOR, DOMAIN
from .hik_device import HikDevice
from .model import DetectorType, Zone, detector_model_to_name

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
            # Specific entity
            if (
                detector_type == DetectorType.WIRELESS_EXTERNAL_MAGNET_DETECTOR
                and zone.zone.magnet_open_status is not None
            ):
                devices.append(
                    HikWirelessExtMagnetDetector(coordinator, zone.zone, entry.entry_id)
                )
            if (
                detector_type
                in (
                    DetectorType.DOOR_MAGNETIC_CONTACT_DETECTOR,
                    DetectorType.SLIM_MAGNETIC_CONTACT,
                )
                and zone.zone.magnet_open_status is not None
            ):
                devices.append(
                    HikMagneticContactDetector(coordinator, zone.zone, entry.entry_id)
                )
            if (
                detector_type is DetectorType.MAGNET_SHOCK_DETECTOR
                and zone.zone.magnet_shock_current_status is not None
            ):
                if zone.zone.magnet_shock_current_status.magnet_tilt_status is not None:
                    devices.append(
                        HikMagnetTiltDetector(coordinator, zone.zone, entry.entry_id)
                    )
                if zone.zone.magnet_shock_current_status.magnet_open_status is not None:
                    devices.append(
                        HikMagnetOpenDetector(coordinator, zone.zone, entry.entry_id)
                    )
                if (
                    zone.zone.magnet_shock_current_status.magnet_shock_status
                    is not None
                ):
                    devices.append(
                        HikMagnetShockDetector(coordinator, zone.zone, entry.entry_id)
                    )
            if zone.zone.tamper_evident is not None:
                devices.append(
                    HikTamperDetection(coordinator, zone.zone, entry.entry_id)
                )
            if zone.zone.bypassed is not None:
                devices.append(
                    HikBypassDetection(coordinator, zone.zone, entry.entry_id)
                )
            if zone.zone.armed is not None:
                devices.append(HikArmedInfo(coordinator, zone.zone, entry.entry_id))
            if zone.zone.alarm is not None:
                devices.append(HikAlarmInfo(coordinator, zone.zone, entry.entry_id))
            if zone.zone.stay_away is not None:
                devices.append(HikStayAwayInfo(coordinator, zone.zone, entry.entry_id))
            if zone.zone.is_via_repeater is not None:
                devices.append(
                    HikIsViaRepeaterInfo(coordinator, zone.zone, entry.entry_id)
                )
    _LOGGER.debug("setting up - sensors: %s", ",".join(x.name for x in devices))
    async_add_entities(devices, False)


class HikWirelessExtMagnetDetector(CoordinatorEntity, HikDevice, BinarySensorEntity):
    """Representation of Hikvision external magnet detector."""

    coordinator: HikAxProDataUpdateCoordinator

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str
    ) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-magnet-{zone.id}"
        self._attr_icon = "mdi:magnet"
        self._device_class = BinarySensorDeviceClass.SAFETY
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
                self._attr_is_on = value
                self._attr_available = True
                self._attr_icon = "mdi:magnet-on"
            elif value is False:
                self._attr_is_on = value
                self._attr_available = True
                self._attr_icon = "mdi:magnet"
            else:
                self._attr_is_on = None
                self._attr_state = None
                self._attr_available = False
                self._attr_icon = "mdi:help"
        else:
            self._attr_is_on = None
            self._attr_state = None
            self._attr_available = False
            self._attr_icon = "mdi:help"
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            value = self.coordinator.zones[self.zone.id].magnet_open_status
            if value is True or value is False:
                return value
        return None


class HikMagneticContactDetector(CoordinatorEntity, HikDevice, BinarySensorEntity):
    """Representation of Hikvision external magnet detector."""

    coordinator: HikAxProDataUpdateCoordinator

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str
    ) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-magnet-{zone.id}"
        self._device_class = BinarySensorDeviceClass.SAFETY
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
                self._attr_is_on = value
                self._attr_available = True
                self._attr_icon = "mdi:magnet-on"
            elif value is False:
                self._attr_is_on = value
                self._attr_available = True
                self._attr_icon = "mdi:magnet"
            else:
                self._attr_is_on = None
                self._attr_state = None
                self._attr_available = False
                self._attr_icon = "mdi:help"
        else:
            self._attr_is_on = None
            self._attr_state = None
            self._attr_available = False
            self._attr_icon = "mdi:help"
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            value = self.coordinator.zones[self.zone.id].magnet_open_status
            if value is True or value is False:
                return value
        return None


class HikMagnetShockDetector(CoordinatorEntity, HikDevice, BinarySensorEntity):
    """Representation of Hikvision external magnet detector."""

    coordinator: HikAxProDataUpdateCoordinator

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str
    ) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-magnet-shock-{zone.id}"
        self._device_class = BinarySensorDeviceClass.SAFETY
        self._attr_has_entity_name = True
        self.entity_id = (
            f"{SENSOR_DOMAIN}.{coordinator.device_name}-magnet-shock-{zone.id}"
        )

    @property
    def name(self) -> str | None:
        return "Magnet shock detection"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if (
            self.coordinator.zones
            and self.coordinator.zones[self.zone.id]
            and self.coordinator.zones[self.zone.id].magnet_shock_current_status
        ):
            value = self.coordinator.zones[
                self.zone.id
            ].magnet_shock_current_status.magnet_shock_status
            if value is True:
                self._attr_is_on = value
                self._attr_available = True
                self._attr_icon = "mdi:magnet-on"
            elif value is False:
                self._attr_is_on = value
                self._attr_available = True
                self._attr_icon = "mdi:magnet"
            else:
                self._attr_is_on = None
                self._attr_available = False
                self._attr_icon = "mdi:help"
        else:
            self._attr_is_on = None
            self._attr_available = False
            self._attr_icon = "mdi:help"
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if (
            self.coordinator.zones
            and self.coordinator.zones[self.zone.id]
            and self.coordinator.zones[self.zone.id].magnet_shock_current_status
        ):
            return self.coordinator.zones[
                self.zone.id
            ].magnet_shock_current_status.magnet_shock_status
        else:
            return None


class HikMagnetOpenDetector(CoordinatorEntity, HikDevice, BinarySensorEntity):
    """Representation of Hikvision external magnet detector."""

    coordinator: HikAxProDataUpdateCoordinator

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str
    ) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-magnet-open-{zone.id}"
        self._device_class = BinarySensorDeviceClass.SAFETY
        self._attr_has_entity_name = True
        self.entity_id = (
            f"{SENSOR_DOMAIN}.{coordinator.device_name}-magnet-open-{zone.id}"
        )

    @property
    def name(self) -> str | None:
        return "Magnet open detection"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if (
            self.coordinator.zones
            and self.coordinator.zones[self.zone.id]
            and self.coordinator.zones[self.zone.id].magnet_shock_current_status
        ):
            value = self.coordinator.zones[
                self.zone.id
            ].magnet_shock_current_status.magnet_open_status
            if value is True:
                self._attr_is_on = value
                self._attr_available = True
                self._attr_icon = "mdi:magnet-on"
            elif value is False:
                self._attr_is_on = value
                self._attr_available = True
                self._attr_icon = "mdi:magnet"
            else:
                self._attr_is_on = None
                self._attr_available = False
                self._attr_icon = "mdi:help"
        else:
            self._attr_is_on = None
            self._attr_available = False
            self._attr_icon = "mdi:help"
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if (
            self.coordinator.zones
            and self.coordinator.zones[self.zone.id]
            and self.coordinator.zones[self.zone.id].magnet_shock_current_status
        ):
            return self.coordinator.zones[
                self.zone.id
            ].magnet_shock_current_status.magnet_open_status
        else:
            return None


class HikMagnetTiltDetector(CoordinatorEntity, HikDevice, BinarySensorEntity):
    """Representation of Hikvision external magnet detector."""

    coordinator: HikAxProDataUpdateCoordinator

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str
    ) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-magnet-tilt-{zone.id}"
        self._device_class = BinarySensorDeviceClass.SAFETY
        self._attr_has_entity_name = True
        self.entity_id = (
            f"{SENSOR_DOMAIN}.{coordinator.device_name}-magnet-tilt-{zone.id}"
        )

    @property
    def name(self) -> str | None:
        return "Magnet tilt detection"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if (
            self.coordinator.zones
            and self.coordinator.zones[self.zone.id]
            and self.coordinator.zones[self.zone.id].magnet_shock_current_status
        ):
            value = self.coordinator.zones[
                self.zone.id
            ].magnet_shock_current_status.magnet_tilt_status
            if value is True:
                self._attr_is_on = value
                self._attr_available = True
                self._attr_icon = "mdi:magnet-on"
            elif value is False:
                self._attr_is_on = value
                self._attr_available = True
                self._attr_icon = "mdi:magnet"
            else:
                self._attr_is_on = None
                self._attr_available = False
                self._attr_icon = "mdi:help"
        else:
            self._attr_is_on = None
            self._attr_available = False
            self._attr_icon = "mdi:help"
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if (
            self.coordinator.zones
            and self.coordinator.zones[self.zone.id]
            and self.coordinator.zones[self.zone.id].magnet_shock_current_status
        ):
            return self.coordinator.zones[
                self.zone.id
            ].magnet_shock_current_status.magnet_tilt_status
        else:
            return None


class HikTamperDetection(CoordinatorEntity, HikDevice, BinarySensorEntity):
    """Representation of Hikvision tamper detection."""

    coordinator: HikAxProDataUpdateCoordinator

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str
    ) -> None:
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
            self._attr_is_on = value
            self._attr_available = True
        else:
            self._attr_state = None
            self._attr_available = False

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

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str
    ) -> None:
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
            self._attr_is_on = value
            self._attr_available = True
        else:
            self._attr_is_on = None
            self._attr_available = False

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

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str
    ) -> None:
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
            self._attr_is_on = value
            self._attr_available = True
        else:
            self._attr_is_on = None
            self._attr_available = False

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

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str
    ) -> None:
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
            self._attr_is_on = value
            self._attr_available = True
        else:
            self._attr_is_on = None
            self._attr_available = False

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

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str
    ) -> None:
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
            self._attr_is_on = value
            self._attr_available = True
        else:
            self._attr_is_on = None
            self._attr_available = False

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

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str
    ) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-isviarepeater-{zone.id}"
        self._attr_icon = "mdi:google-circles-extended"
        self._device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True
        self.entity_id = (
            f"{SENSOR_DOMAIN}.{coordinator.device_name}-isviarepeater-{zone.id}"
        )

    @property
    def name(self) -> str | None:
        return "Is via repeater"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            value = self.coordinator.zones[self.zone.id].is_via_repeater
            self._attr_is_on = value
            self._attr_available = True
        else:
            self._attr_is_on = None
            self._attr_available = False

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if self.coordinator.zones and self.coordinator.zones[self.zone.id]:
            return self.coordinator.zones[self.zone.id].is_via_repeater
        else:
            return False


class HikBinaryBatteryInfo(CoordinatorEntity, HikDevice, BinarySensorEntity):
    """Representation of Hikvision binary battery info."""

    coordinator: HikAxProDataUpdateCoordinator

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str
    ) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-battery-low-{zone.id}"
        self._attr_icon = "mdi:battery"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True
        self.entity_id = (
            f"{SENSOR_DOMAIN}.{coordinator.device_name}-battery-low-{zone.id}"
        )

    @property
    def name(self) -> str | None:
        return "Battery low"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
        if (
            self.coordinator.zones
            and self.coordinator.zones[self.zone.id]
            and self.coordinator.zones[self.zone.id].charge is not None
        ):
            value = self.coordinator.zones[self.zone.id].charge == "lowPower"
            self._attr_is_on = value
            self._attr_available = True
        else:
            self._attr_is_on = None
            self._attr_available = False

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if (
            self.coordinator.zones
            and self.coordinator.zones[self.zone.id]
            and self.coordinator.zones[self.zone.id].charge is not None
        ):
            return self.coordinator.zones[self.zone.id].charge == "lowPower"
        else:
            return False
