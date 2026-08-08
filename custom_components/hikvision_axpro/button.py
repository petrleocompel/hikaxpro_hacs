"""Button entities for Hikvision AX Pro panel controls."""

from __future__ import annotations

import logging

from homeassistant.components.button import (
    DOMAIN as BUTTON_DOMAIN,
    ButtonEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HikAxProDataUpdateCoordinator
from .const import DATA_COORDINATOR, DOMAIN
from .entity_id import build_entity_id

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up panel buttons when HostControlCap allows them."""
    coordinator: HikAxProDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]
    entities: list[ButtonEntity] = []
    if coordinator.one_key_alarm_supported is True:
        entities.append(HikOneKeyAlarmButton(coordinator, entry.entry_id))
        entities.append(HikOneKeyAlarmClearButton(coordinator, entry.entry_id))
    _LOGGER.debug("setting up buttons: %s", entities)
    async_add_entities(entities, False)


class HikOneKeyAlarmButton(CoordinatorEntity, ButtonEntity):
    """Trigger one-key / panic alarm (HostControlCap.isSptOneKeyAlarmCtrl)."""

    coordinator: HikAxProDataUpdateCoordinator

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator)
        self._ref_id = entry_id
        self._attr_has_entity_name = True
        self._attr_name = "One-key alarm"
        self._attr_icon = "mdi:alarm-light"
        self._attr_unique_id = f"{coordinator.mac_id}-one-key-alarm"
        self.entity_id = build_entity_id(
            BUTTON_DOMAIN, self._attr_unique_id, coordinator.mac_id, coordinator.device_name
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(coordinator.mac))},
            manufacturer="HikVision",
            name=coordinator.device_name or "AX Pro",
            model=coordinator.device_model,
        )

    @property
    def available(self) -> bool:
        return self.coordinator.one_key_alarm_supported is True

    async def async_press(self) -> None:
        """Sound the panel one-key alarm."""
        await self.coordinator.one_key_alarm_on()
        await self.coordinator.async_request_refresh()


class HikOneKeyAlarmClearButton(CoordinatorEntity, ButtonEntity):
    """Clear / silence one-key alarm."""

    coordinator: HikAxProDataUpdateCoordinator

    def __init__(
        self, coordinator: HikAxProDataUpdateCoordinator, entry_id: str
    ) -> None:
        super().__init__(coordinator)
        self._ref_id = entry_id
        self._attr_has_entity_name = True
        self._attr_name = "Clear one-key alarm"
        self._attr_icon = "mdi:alarm-light-off"
        self._attr_unique_id = f"{coordinator.mac_id}-one-key-alarm-clear"
        self.entity_id = build_entity_id(
            BUTTON_DOMAIN, self._attr_unique_id, coordinator.mac_id, coordinator.device_name
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(coordinator.mac))},
            manufacturer="HikVision",
            name=coordinator.device_name or "AX Pro",
            model=coordinator.device_model,
        )

    @property
    def available(self) -> bool:
        return self.coordinator.one_key_alarm_supported is True

    async def async_press(self) -> None:
        """Silence the one-key alarm."""
        await self.coordinator.one_key_alarm_off()
        await self.coordinator.async_request_refresh()
