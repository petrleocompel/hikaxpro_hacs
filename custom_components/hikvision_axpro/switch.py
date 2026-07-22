from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.helpers import device_registry as dr
from homeassistant.components.switch import SwitchEntity, DOMAIN as SWITCH_DOMAIN, SwitchDeviceClass, \
    SwitchEntityDescription

from . import HikAxProDataUpdateCoordinator
from .const import DATA_COORDINATOR, DOMAIN
from .entity_id import build_entity_id
from .model import RelaySwitchConf, detector_model_to_name, relay_status_is_on

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Hikvision AX Pro switches (relays and siren control)."""
    coordinator: HikAxProDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    await coordinator.async_request_refresh()
    device_registry = dr.async_get(hass)
    devices = []
    if coordinator.relays is not None:
        for [switch_id, switch] in coordinator.relays.items():
            _LOGGER.debug("Adding switch with config: %s", switch)
            device_registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, str(entry.entry_id) + "-relay-" + str(switch_id))},
                manufacturer="HikVision",
                name=switch.name,
                via_device=(DOMAIN, str(coordinator.mac)),
            )
            devices.append(HikRelaySwitch(coordinator, switch, entry.entry_id))
    for siren_id, siren in coordinator.sirens.items():
        # Skip devices already marked unsupported after a prior control attempt.
        if coordinator.siren_control_supported.get(siren_id) is False:
            continue
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, str(entry.entry_id) + "-siren-" + str(siren_id))},
            manufacturer="HikVision",
            name=siren.name or f"Siren {siren_id}",
            via_device=(DOMAIN, str(coordinator.mac)),
            model=detector_model_to_name(siren.model) if siren.model else "Siren",
            sw_version=siren.version,
        )
        devices.append(HikSirenSwitch(coordinator, siren_id, entry.entry_id))
    _LOGGER.debug("setting up - switches: %s", devices)
    async_add_entities(devices, False)



class HikRelaySwitch(CoordinatorEntity, SwitchEntity):
    """Representation of Hikvision external magnet detector."""
    coordinator: HikAxProDataUpdateCoordinator

    def __init__(self, coordinator: HikAxProDataUpdateCoordinator, switch: RelaySwitchConf, entry_id: str) -> None:
        """Create the entity with a DataUpdateCoordinator."""
        super().__init__(coordinator)
        self.switch = switch
        self._ref_id = entry_id
        self._attr_unique_id = f"{self.coordinator.device_name}-relay-{switch.id}"
        self.entity_id = build_entity_id(
            SWITCH_DOMAIN, coordinator.device_name, "relay", switch.id
        )
        #self._attr_icon = "mdi:switch"
        #self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(self._ref_id) +  "-relay-" + str(switch.id))},
            manufacturer="HikVision",
            # suggested_area=zone.zone.,
            name=switch.name,
            via_device=(DOMAIN, str(coordinator.mac)),
        )

        self._attr_device_class = SwitchDeviceClass.SWITCH

        status = self.coordinator.relays_status.get(switch.id)
        self._available = status is not None
        if status is not None:
            self._attr_is_on = relay_status_is_on(status.status)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        status = self.coordinator.relays_status.get(self.switch.id)
        self._available = status is not None
        if status is not None:
            self._attr_is_on = relay_status_is_on(status.status)
        else:
            self._attr_is_on = None
        self.async_write_ha_state()

    async def async_turn_on(self):
        """Turn the entity on."""
        _LOGGER.debug(
            "Sending ON request to SWITCH device %s (%s)",
        )
        try:
            res = await self.coordinator.relay_on(self.switch.id)
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
            res = await self.coordinator.relay_off(self.switch.id)
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
