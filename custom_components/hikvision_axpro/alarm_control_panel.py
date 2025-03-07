"""Alarm control panel."""

from __future__ import annotations

import logging

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import Arming, HikAxProDataUpdateCoordinator, SubSys
from .const import ALLOW_SUBSYSTEMS, DATA_COORDINATOR, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up a Hikvision ax pro alarm control panel based on a config entry."""
    coordinator: HikAxProDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        # connections={},
        identifiers={(DOMAIN, coordinator.mac)},
        manufacturer="HikVision" if coordinator.device_model is not None else "Unknown",
        # suggested_area=zone.zone.,
        name=coordinator.device_name,
        # via_device=(DOMAIN, str(coordinator.mac)),
        model=coordinator.device_model,
    )
    panels = [HikAxProPanel(coordinator)]
    if bool(entry.data.get(ALLOW_SUBSYSTEMS, False)):
        panels.extend(
            HikAxProSubPanel(coordinator, sub_system)
            for sub_system in coordinator.sub_systems.values()
        )
    async_add_entities(panels, False)


class HikAxProPanel(CoordinatorEntity, AlarmControlPanelEntity):
    """Representation of Hikvision Ax Pro alarm panel."""

    _attr_code_arm_required = False

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_HOME
        | AlarmControlPanelEntityFeature.ARM_AWAY
    )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for this device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.unique_id)},
            manufacturer="Hikvision - Ax Pro",
            model=self.coordinator.device_model,
            name=self.coordinator.device_name,
        )

    @property
    def unique_id(self):
        """Return a unique id."""
        return self.coordinator.mac

    @property
    def name(self):
        """Return the name."""
        return self.coordinator.device_name
        # "HikvisionAxPro"

    @property
    def alarm_state(self):
        """Return the state of the device."""
        return self.coordinator.state

    @property
    def code_format(self) -> CodeFormat | None:
        """Return the code format."""
        return self.__get_code_format(self.coordinator.code_format)

    def __get_code_format(self, code_format_str) -> CodeFormat:
        """Return CodeFormat according to the given code format string."""
        code_format: CodeFormat | None = None

        if not self.coordinator.use_code:
            code_format = None
        elif code_format_str == "NUMBER":
            code_format = CodeFormat.NUMBER
        elif code_format_str == "TEXT":
            code_format = CodeFormat.TEXT

        return code_format

    async def async_alarm_disarm(self, code=None):
        """Send disarm command."""
        if self.coordinator.use_code:
            if not self.__is_code_valid(code):
                return

        await self.coordinator.async_disarm()

    async def async_alarm_arm_home(self, code=None):
        """Send arm home command."""
        if self.coordinator.use_code and self.coordinator.use_code_arming:
            if not self.__is_code_valid(code):
                return

        await self.coordinator.async_arm_home()

    async def async_alarm_arm_away(self, code=None):
        """Send arm away command."""
        if self.coordinator.use_code and self.coordinator.use_code_arming:
            if not self.__is_code_valid(code):
                return

        await self.coordinator.async_arm_away()

    def __is_code_valid(self, code):
        return code == self.coordinator.code


class HikAxProSubPanel(CoordinatorEntity, AlarmControlPanelEntity):
    """Representation of Hikvision Ax Pro alarm panel."""

    sys: SubSys
    coordinator: HikAxProDataUpdateCoordinator

    def __init__(self, coordinator: HikAxProDataUpdateCoordinator, sys: SubSys) -> None:
        """Initialize subpanel."""
        self.sys = sys
        super().__init__(coordinator=coordinator)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        new_sys = self.coordinator.sub_systems.get(self.sys.id)
        if new_sys is not None:
            self.sys = new_sys
        else:
            logging.warning("Area %s was not found", self.sys.id)
        self.async_write_ha_state()

    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_HOME
        | AlarmControlPanelEntityFeature.ARM_AWAY
    )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for this device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.mac)},
            manufacturer="Hikvision - Ax Pro",
            model=self.coordinator.device_model,
            name=self.coordinator.device_name,
        )

    @property
    def unique_id(self):
        """Return a unique id."""
        return "subsys-" + self.coordinator.mac + str(self.sys.id)

    @property
    def name(self):
        """Return the name."""
        return self.sys.name
        # "HikvisionAxPro"

    @property
    def alarm_state(self):
        """Return the state of the device."""
        if self.sys.alarm:
            return AlarmControlPanelState.TRIGGERED
        if self.sys.arming == Arming.AWAY:
            return AlarmControlPanelState.ARMED_AWAY
        if self.sys.arming == Arming.STAY:
            return AlarmControlPanelState.ARMED_HOME
        if self.sys.arming == Arming.VACATION:
            return AlarmControlPanelState.ARMED_VACATION
        if self.sys.arming == Arming.DISARM:
            return AlarmControlPanelState.DISARMED
        return None

    @property
    def code_format(self) -> CodeFormat | None:
        """Return the code format."""
        return self.__get_code_format(self.coordinator.code_format)

    def __get_code_format(self, code_format_str) -> CodeFormat:
        """Return CodeFormat according to the given code format string."""
        code_format: CodeFormat = None

        if not self.coordinator.use_code:
            code_format = None
        elif code_format_str == "NUMBER":
            code_format = CodeFormat.NUMBER
        elif code_format_str == "TEXT":
            code_format = CodeFormat.TEXT

        return code_format

    async def async_alarm_disarm(self, code=None):
        """Send disarm command."""
        if self.coordinator.use_code:
            if not self.__is_code_valid(code):
                return

        await self.coordinator.async_disarm(self.sys.id)

    async def async_alarm_arm_home(self, code=None):
        """Send arm home command."""
        if self.coordinator.use_code and self.coordinator.use_code_arming:
            if not self.__is_code_valid(code):
                return

        await self.coordinator.async_arm_home(self.sys.id)

    async def async_alarm_arm_away(self, code=None):
        """Send arm away command."""
        if self.coordinator.use_code and self.coordinator.use_code_arming:
            if not self.__is_code_valid(code):
                return

        await self.coordinator.async_arm_away(self.sys.id)

    def __is_code_valid(self, code):
        return code == self.coordinator.code
