from __future__ import annotations

from typing import cast

import logging

from homeassistant.components.siren import DOMAIN as SIREN_DOMAIN
from homeassistant.components.siren import (SirenEntity, SirenEntityFeature)
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.sensor import (SensorDeviceClass, SensorEntity,
                                             SensorStateClass)
from homeassistant.const import PERCENTAGE, UnitOfTemperature, SIGNAL_STRENGTH_DECIBELS_MILLIWATT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HikAxProDataUpdateCoordinator
from .const import DOMAIN
from .model import SirenStatus, SirenStatusEnum

_LOGGER = logging.getLogger(__name__)

class HikSirenBatteryInfo(CoordinatorEntity, SensorEntity):
    """Representation of Hikvision siren battery info."""

    coordinator: HikAxProDataUpdateCoordinator

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, siren: SirenStatus, entry_id: str
    ) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.siren = siren
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-siren-temp-{siren.id}"
        self._attr_icon = "mdi:battery"
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._device_class = SensorDeviceClass.BATTERY
        self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(self._ref_id) +  "-siren-" + str(siren.id))},
            manufacturer="HikVision",
            name=siren.name,
            via_device=(DOMAIN, str(coordinator.mac)),
        )
        self.entity_id = (
            f"{SENSOR_DOMAIN}.{coordinator.device_name}-siren-temperature-{siren.id}"
        )

    @property
    def name(self) -> str | None:
        return "Battery"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.sirens_status and self.coordinator.sirens_status[self.siren.id]:
            self._attr_native_value = cast(
                float, self.coordinator.sirens_status[self.siren.id].charge_value
            )
            self._attr_available = True
        else:
            self._attr_native_value = None
            self._attr_available = False
        self.async_write_ha_state()


class HikSirenTemperature(CoordinatorEntity, SensorEntity):
    """Representation of Hikvision siren temperature."""

    coordinator: HikAxProDataUpdateCoordinator

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, siren: SirenStatus, entry_id: str
    ) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.siren = siren
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-siren-batt-{siren.id}"
        self._attr_icon = "mdi:thermometer"
        # self._attr_name = f"{self.siren.name} Temperature"
        self._device_class = SensorDeviceClass.TEMPERATURE
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(self._ref_id) +  "-siren-" + str(siren.id))},
            manufacturer="HikVision",
            # suggested_area=siren.siren.,
            name=siren.name,
            via_device=(DOMAIN, str(coordinator.mac)),
        )
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_has_entity_name = True
        self.entity_id = (
            f"{SENSOR_DOMAIN}.{coordinator.device_name}-siren-battery-{siren.id}"
        )
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def name(self) -> str | None:
        return "Temperature"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.sirens_status and self.coordinator.sirens_status[self.siren.id]:
            self._attr_native_value = cast(
                float, self.coordinator.sirens_status[self.siren.id].temperature
            )
            self._attr_available = True
        else:
            self._attr_native_value = None
            self._attr_available = False
        self.async_write_ha_state()


class HikSirenSignalInfo(CoordinatorEntity, SensorEntity):
    """Representation of Hikvision siren signal status."""

    coordinator: HikAxProDataUpdateCoordinator

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, siren: SirenStatus, entry_id: str
    ) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.siren = siren
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-siren-signal-{siren.id}"
        self._attr_icon = "mdi:signal"
        self._device_class = SensorDeviceClass.SIGNAL_STRENGTH
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(self._ref_id) +  "-siren-" + str(siren.id))},
            manufacturer="HikVision",
            # suggested_area=siren.siren.,
            name=siren.name,
            via_device=(DOMAIN, str(coordinator.mac)),
        )
        self._attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_has_entity_name = True
        self.entity_id = (
            f"{SENSOR_DOMAIN}.{coordinator.device_name}-siren-signal-{siren.id}"
        )

    @property
    def name(self) -> str | None:
        return "Signal"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.sirens_status and self.coordinator.sirens_status[self.siren.id]:
            self._attr_native_value = cast(
                float, self.coordinator.sirens_status[self.siren.id].signal
            )
            self._attr_available = True
        else:
            self._attr_native_value = None
            self._attr_available = False
        self.async_write_ha_state()


class HikSirenSwitch(CoordinatorEntity, SirenEntity):
    """Representation of Hikvision siren switch."""

    coordinator: HikAxProDataUpdateCoordinator
    _attr_supported_features = SirenEntityFeature.TURN_ON | SirenEntityFeature.TURN_OFF

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, siren: SirenStatus, entry_id: str
    ) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.siren = siren
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-siren-switch-{siren.id}"
        #self._attr_icon = "mdi:switch"
        #self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(self._ref_id) +  "-siren-" + str(siren.id))},
            manufacturer="HikVision",
            name=siren.name,
            via_device=(DOMAIN, str(coordinator.mac)),
        )
        self.entity_id = (
            f"{SIREN_DOMAIN}.{coordinator.device_name}-siren-switch-{siren.id}"
        )
        status = siren.status
        self._available = status is not None
        if status is not None:
            self._attr_is_on = status == SirenStatusEnum.ON

    @property
    def name(self) -> str | None:
        return "Switch"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if not self.coordinator.sirens_status:
            return
        if not self.coordinator.sirens_status[self.siren.id]:
            return

        status = self.coordinator.sirens_status[self.siren.id]
        self._available = status is not None
        if status is not None:
            self._attr_is_on = status.status == SirenStatusEnum.ON
        else:
            self._attr_is_on = None
        self.async_write_ha_state()

    async def async_turn_on(self):
        """Turn the entity on."""
        _LOGGER.debug(
            "Sending ON request to SWITCH device %s (%s)",
        )
        try:
            res = await self.coordinator.siren_on(self.siren.id)
            if res:
                self._attr_is_on = True
                self._available = True
                self.async_write_ha_state()
            else:
                self._available = False
                _LOGGER.exception(
                    "Error turn on for switch %s", self.entity_id
                )
        except:
            self._available = False
            _LOGGER.exception(
                "Error turn on for switch %s", self.entity_id
            )

    async def async_turn_off(self):
        """Turn the entity on."""
        _LOGGER.debug(
            "Sending OFF request to SWITCH device %s (%s)",
        )
        try:
            res = await self.coordinator.siren_off(self.siren.id)
            if res:
                self._attr_is_on = False
                self._available = True
                self.async_write_ha_state()
            else:
                self._available = False
                _LOGGER.exception(
                    "Error turn on for switch %s", self.entity_id
                )
        except:
            self._available = False
            _LOGGER.exception(
                "Error turn on for switch %s", self.entity_id
            )
