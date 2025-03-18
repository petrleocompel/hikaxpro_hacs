"""Sirens.

Hikvision sirens.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HikAxProDataUpdateCoordinator
from .const import DATA_COORDINATOR, DOMAIN

from .siren_entities import HikSirenSwitch
from .model import detector_model_to_name

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
            siren_status = coordinator.sirens_status[siren.id]
            device_registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, str(entry.entry_id) + "-siren-" + str(siren_id))},
                manufacturer="HikVision",
                model=detector_model_to_name(siren_status.model),
                name=siren.name,
                via_device=(DOMAIN, str(coordinator.mac)),
            )
            siren_status = coordinator.sirens_status[siren.id]
            _LOGGER.debug("Adding siren status with config: %s", siren_status)

            siren_capabilities = coordinator.siren_capabilities
            if siren_capabilities is not None and siren_capabilities.support_siren_ctrl_id_list is not None:
                if siren.id in siren_capabilities.support_siren_ctrl_id_list:
                    devices.append(HikSirenSwitch(coordinator, siren_status, entry.entry_id))

    _LOGGER.debug("setting up - sirens: %s", ",".join(x.name for x in devices))
    async_add_entities(devices, False)

