"""Binary Sensors.

Hikvision binary sensors.
"""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    DOMAIN as BINARY_SENSOR_DOMAIN,
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HikAxProDataUpdateCoordinator
from .bypass_manager import is_auto_bypass_eligible
from .const import (
    ARM_MODES,
    DATA_COORDINATOR,
    DOMAIN,
    SERVICE_BYPASS_ZONE,
    SERVICE_UNBYPASS_ZONE,
)
from .entity_id import build_entity_id
from .hik_device import HikDevice
from .model import (
    MOTION_DETECTOR_TYPES,
    DetectorType,
    Status,
    Zone,
    zone_device_model,
)
from .host_entities import build_host_binary_sensors
from .peripheral_entities import (
    build_peripheral_binary_sensors,
    register_peripheral_devices,
)
from .siren_entities import (
    build_siren_binary_sensors,
    register_siren_devices,
)

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
    register_siren_devices(device_registry, coordinator, entry.entry_id)
    register_peripheral_devices(device_registry, coordinator, entry.entry_id)
    devices.extend(build_siren_binary_sensors(coordinator, entry.entry_id))
    devices.extend(build_peripheral_binary_sensors(coordinator, entry.entry_id))
    devices.extend(build_host_binary_sensors(coordinator, entry.entry_id))

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
                    model=zone_device_model(zone.zone.model, detector_type),
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
                    model=zone_device_model(zone.zone.model, detector_type),
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
            if (
                detector_type in MOTION_DETECTOR_TYPES
                and zone.zone.status is not None
            ):
                devices.append(
                    HikMotionDetector(coordinator, zone.zone, entry.entry_id)
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
            if zone.zone.charge is not None:
                devices.append(
                    HikBinaryBatteryInfo(coordinator, zone.zone, entry.entry_id)
                )
            devices.extend(
                _zone_bypassable_sensors(coordinator, zone.zone, entry.entry_id)
            )

    devices.extend(
        HikReadyToArmSensor(coordinator, entry.entry_id, mode) for mode in ARM_MODES
    )
    _remove_stale_bypass_entities(hass, coordinator)

    _LOGGER.debug("setting up - sensors: %s", ",".join(x.name for x in devices))
    async_add_entities(devices, False)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(SERVICE_BYPASS_ZONE, None, "async_bypass")
    platform.async_register_entity_service(
        SERVICE_UNBYPASS_ZONE, None, "async_unbypass"
    )


def _zone_bypassable_sensors(
    coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str
) -> list[BinarySensorEntity]:
    """Per-mode bypassable readback for a zone that may be auto-bypassed.

    Only instant zones get them: the panel offers "forbid bypass on
    arming" exclusively for that type, so no other type is ever bypassed
    automatically and a sensor stuck at off would only be noise.
    """
    if not is_auto_bypass_eligible(zone):
        return []
    manager = coordinator.bypass_manager
    modes = manager.auto_bypass_modes if manager is not None else set(ARM_MODES)
    return [
        HikZoneBypassableSensor(coordinator, zone, entry_id, mode)
        for mode in ARM_MODES
        if mode in modes
    ]


def _remove_stale_bypass_entities(
    hass: HomeAssistant, coordinator: HikAxProDataUpdateCoordinator
) -> None:
    """Drop bypass entities that no longer apply.

    Covers a zone whose type changed on the panel, a mode whose
    auto-bypass was switched off, and the switches earlier builds used
    before the configuration moved into the integration options.
    """
    registry = er.async_get(hass)
    manager = coordinator.bypass_manager
    modes = manager.auto_bypass_modes if manager is not None else set(ARM_MODES)

    def remove(domain: str, unique_id: str) -> None:
        if stale_id := registry.async_get_entity_id(domain, DOMAIN, unique_id):
            _LOGGER.debug("Removing stale entity %s", stale_id)
            registry.async_remove(stale_id)

    for zone_id in list((coordinator.zones or {})):
        zone = coordinator.zones[zone_id]
        for mode in ARM_MODES:
            unique_id = f"{coordinator.mac_id}-bypassable-{mode}-{zone_id}"
            # The configuration now lives in the config entry, so the
            # per-zone switch is gone whatever the mode.
            remove("switch", unique_id)
            if is_auto_bypass_eligible(zone) and mode in modes:
                continue
            remove("binary_sensor", unique_id)
        remove("switch", f"{coordinator.mac_id}-bypassable-{zone_id}")

    # Mode-less ready-to-arm sensor used by earlier builds.
    remove("binary_sensor", f"{coordinator.mac_id}-ready-to-arm")


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
        self._attr_unique_id = f"{self.coordinator.mac_id}-magnet-{zone.id}"
        self.entity_id = build_entity_id(
            BINARY_SENSOR_DOMAIN, self._attr_unique_id, coordinator.mac_id, zone.name, "z"
        )
        self._attr_icon = "mdi:magnet"
        self._attr_device_class = BinarySensorDeviceClass.SAFETY
        self._attr_has_entity_name = True

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
        self._attr_unique_id = f"{self.coordinator.mac_id}-magnet-{zone.id}"
        self.entity_id = build_entity_id(
            BINARY_SENSOR_DOMAIN, self._attr_unique_id, coordinator.mac_id, zone.name, "z"
        )
        self._attr_device_class = BinarySensorDeviceClass.SAFETY
        self._attr_has_entity_name = True

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
        self._attr_unique_id = f"{self.coordinator.mac_id}-magnet-shock-{zone.id}"
        self.entity_id = build_entity_id(
            BINARY_SENSOR_DOMAIN, self._attr_unique_id, coordinator.mac_id, zone.name, "z"
        )
        self._attr_device_class = BinarySensorDeviceClass.SAFETY
        self._attr_has_entity_name = True

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
        self._attr_unique_id = f"{self.coordinator.mac_id}-magnet-open-{zone.id}"
        self.entity_id = build_entity_id(
            BINARY_SENSOR_DOMAIN, self._attr_unique_id, coordinator.mac_id, zone.name, "z"
        )
        self._attr_device_class = BinarySensorDeviceClass.SAFETY
        self._attr_has_entity_name = True

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
        self._attr_unique_id = f"{self.coordinator.mac_id}-magnet-tilt-{zone.id}"
        self.entity_id = build_entity_id(
            BINARY_SENSOR_DOMAIN, self._attr_unique_id, coordinator.mac_id, zone.name, "z"
        )
        self._attr_device_class = BinarySensorDeviceClass.SAFETY
        self._attr_has_entity_name = True

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


class HikMotionDetector(CoordinatorEntity, HikDevice, BinarySensorEntity):
    """Representation of Hikvision PIR / motion detector."""

    coordinator: HikAxProDataUpdateCoordinator

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, zone: Zone, entry_id: str
    ) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.mac_id}-motion-{zone.id}"
        self.entity_id = build_entity_id(
            BINARY_SENSOR_DOMAIN, self._attr_unique_id, coordinator.mac_id, zone.name, "z"
        )
        self._attr_device_class = BinarySensorDeviceClass.MOTION
        self._attr_has_entity_name = True

    @property
    def name(self) -> str | None:
        return "Motion"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if (
            self.coordinator.zones
            and self.coordinator.zones[self.zone.id]
            and self.coordinator.zones[self.zone.id].status is not None
        ):
            triggered = (
                self.coordinator.zones[self.zone.id].status is Status.TRIGGER
            )
            self._attr_is_on = triggered
            self._attr_available = True
        else:
            self._attr_is_on = None
            self._attr_available = False
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if (
            self.coordinator.zones
            and self.coordinator.zones[self.zone.id]
            and self.coordinator.zones[self.zone.id].status is not None
        ):
            return self.coordinator.zones[self.zone.id].status is Status.TRIGGER
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
        self._attr_unique_id = f"{self.coordinator.mac_id}-tamper-{zone.id}"
        self.entity_id = build_entity_id(
            BINARY_SENSOR_DOMAIN, self._attr_unique_id, coordinator.mac_id, zone.name, "z"
        )
        self._attr_icon = "mdi:electric-switch"
        self._attr_device_class = BinarySensorDeviceClass.TAMPER
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True

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
        self._attr_unique_id = f"{self.coordinator.mac_id}-bypass-{zone.id}"
        self.entity_id = build_entity_id(
            BINARY_SENSOR_DOMAIN, self._attr_unique_id, coordinator.mac_id, zone.name, "z"
        )
        self._attr_icon = "mdi:alarm-light-off"
        self._attr_device_class = BinarySensorDeviceClass.SAFETY
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True

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

    @property
    def extra_state_attributes(self):
        """Expose owner and reason of the current bypass."""
        manager = self.coordinator.bypass_manager
        if manager is None or not self.is_on:
            return None
        owned = manager.owns_zone(self.zone.id)
        return {
            "bypass_owner": "integration" if owned else "external",
            "bypass_reason": manager.bypass_reason(self.zone.id),
        }

    async def async_bypass(self):
        """Bypass this zone (service handler)."""
        if self.coordinator.bypass_manager is not None:
            await self.coordinator.bypass_manager.async_bypass_zone(self.zone.id)

    async def async_unbypass(self):
        """Restore this zone (service handler)."""
        if self.coordinator.bypass_manager is not None:
            await self.coordinator.bypass_manager.async_unbypass_zone(self.zone.id)


class HikZoneBypassableSensor(CoordinatorEntity, HikDevice, BinarySensorEntity):
    """Whether this zone is set as bypassable for one arming mode.

    Read-only: which zones may be auto-bypassed is chosen once in the
    integration options, not per zone. The sensor is off when the panel
    itself forbids bypassing the zone on arming
    (``armNoBypassEnabled``) or when its type is not eligible, because
    the panel-side setting always wins over the HA-side configuration.
    """

    coordinator: HikAxProDataUpdateCoordinator

    def __init__(
        self,
        coordinator: HikAxProDataUpdateCoordinator,
        zone: Zone,
        entry_id: str,
        mode: str,
    ) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.zone = zone
        self._ref_id = entry_id
        self._mode = mode
        self._attr_unique_id = f"{coordinator.mac_id}-bypassable-{mode}-{zone.id}"
        self.entity_id = build_entity_id(
            BINARY_SENSOR_DOMAIN, self._attr_unique_id, coordinator.mac_id, zone.name, "z"
        )
        self._attr_icon = "mdi:shield-off-outline"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True

    @property
    def name(self) -> str | None:
        return f"Bypassable on {self._mode} arming"

    @property
    def is_on(self) -> bool | None:
        """Return true if the zone may be auto-bypassed in this mode."""
        manager = self.coordinator.bypass_manager
        if manager is None:
            return None
        return manager.is_bypassable(self.zone.id, self._mode)

    @property
    def available(self) -> bool:
        manager = self.coordinator.bypass_manager
        return manager is not None and manager.bypass_supported

    @property
    def extra_state_attributes(self):
        """Explain why a configured zone is not effective, if it is not."""
        manager = self.coordinator.bypass_manager
        if manager is None:
            return None
        attrs = {"arming_mode": self._mode}
        configured = manager.is_configured_bypassable(self.zone.id, self._mode)
        attrs["configured"] = configured
        if configured and manager.zone_forbids_bypass(self.zone.id):
            attrs["forbidden_by_panel_config"] = True
        if configured and not manager.zone_bypass_allowed(self.zone.id):
            attrs["ineffective_reason"] = (
                "forbidden_by_panel_config"
                if manager.zone_forbids_bypass(self.zone.id)
                else "zone_type_not_eligible"
            )
        if manager.owns_zone(self.zone.id):
            attrs["bypass_owner"] = "integration"
            attrs["bypass_reason"] = manager.bypass_reason(self.zone.id)
        return attrs


class HikReadyToArmSensor(CoordinatorEntity, BinarySensorEntity):
    """Whether arming in one mode would currently succeed.

    On when no zone is in fault or every faulted zone is set bypassable;
    off when at least one faulted zone would block arming. One sensor
    exists per arming mode, independent of the auto-bypass
    configuration. Advisory: computed from polled data with the same
    evaluation used at arm time; the authoritative check runs
    synchronously when arming.
    """

    coordinator: HikAxProDataUpdateCoordinator

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, entry_id: str, mode: str
    ) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._mode = mode
        self._attr_unique_id = f"{coordinator.mac_id}-ready-to-arm-{mode}"
        self.entity_id = build_entity_id(
            BINARY_SENSOR_DOMAIN, self._attr_unique_id, coordinator.mac_id, coordinator.device_name
        )
        self._attr_icon = "mdi:shield-check"
        self._attr_has_entity_name = True

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    @property
    def name(self) -> str | None:
        return f"Ready to arm {self._mode}"

    @property
    def device_info(self) -> DeviceInfo:
        """Attach to the panel device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.mac)},
            manufacturer="Hikvision - Ax Pro",
            model=self.coordinator.device_model,
            name=self.coordinator.device_name,
        )

    @property
    def is_on(self) -> bool | None:
        """Return true when arming would succeed under the logic."""
        manager = self.coordinator.bypass_manager
        if manager is None or self.coordinator.zones is None:
            return None
        return manager.current_readiness(self._mode).ready

    @property
    def extra_state_attributes(self):
        """Expose the evaluation details."""
        manager = self.coordinator.bypass_manager
        if manager is None:
            return None
        result = manager.current_readiness(self._mode)
        return {
            "blocking_zones": result.blocking_zones,
            "zones_to_bypass": result.zones_to_bypass,
            "areas": {
                str(area): breakdown for area, breakdown in result.per_area.items()
            },
            "evaluated_mode": self._mode,
            "advisory": True,
        }


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
        self._attr_unique_id = f"{self.coordinator.mac_id}-armed-{zone.id}"
        self.entity_id = build_entity_id(
            BINARY_SENSOR_DOMAIN, self._attr_unique_id, coordinator.mac_id, zone.name, "z"
        )
        self._attr_icon = "mdi:lock"
        self._attr_device_class = BinarySensorDeviceClass.LOCK
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True

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
        self._attr_unique_id = f"{self.coordinator.mac_id}-alarm-{zone.id}"
        self.entity_id = build_entity_id(
            BINARY_SENSOR_DOMAIN, self._attr_unique_id, coordinator.mac_id, zone.name, "z"
        )
        self._attr_icon = "mdi:alarm-light"
        self._attr_device_class = BinarySensorDeviceClass.LOCK
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True

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
        self._attr_unique_id = f"{self.coordinator.mac_id}-stayaway-{zone.id}"
        self.entity_id = build_entity_id(
            BINARY_SENSOR_DOMAIN, self._attr_unique_id, coordinator.mac_id, zone.name, "z"
        )
        self._attr_icon = "mdi:shield-lock-outline"
        self._attr_device_class = BinarySensorDeviceClass.LOCK
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True

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
        self._attr_unique_id = f"{self.coordinator.mac_id}-isviarepeater-{zone.id}"
        self.entity_id = build_entity_id(
            BINARY_SENSOR_DOMAIN, self._attr_unique_id, coordinator.mac_id, zone.name, "z"
        )
        self._attr_icon = "mdi:google-circles-extended"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True

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
        self._attr_unique_id = f"{self.coordinator.mac_id}-battery-low-{zone.id}"
        self.entity_id = build_entity_id(
            BINARY_SENSOR_DOMAIN, self._attr_unique_id, coordinator.mac_id, zone.name, "z"
        )
        self._attr_icon = "mdi:battery"
        self._attr_device_class = BinarySensorDeviceClass.BATTERY
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_has_entity_name = True

    @property
    def name(self) -> str | None:
        return "Battery low"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
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
        self.async_write_ha_state()

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
