"""The hikvision_axpro integration."""
import asyncio
import logging
from datetime import timedelta
from typing import Optional
from collections.abc import Callable

import hikaxpro
import xmltodict

from async_timeout import timeout

from homeassistant.components.alarm_control_panel import SCAN_INTERVAL
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_CODE_FORMAT,
    CONF_ENABLED,
    CONF_HOST,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_CODE,
    CONF_SCAN_INTERVAL,
    Platform,
    STATE_ALARM_ARMED_HOME,
    STATE_ALARM_ARMED_VACATION,
    STATE_ALARM_ARMED_AWAY,
    STATE_ALARM_DISARMED,
    STATE_ALARM_TRIGGERED, SERVICE_RELOAD
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DATA_COORDINATOR, DOMAIN, USE_CODE_ARMING
from .model import ZonesResponse, Zone, SubSystemResponse, SubSys, Arming

PLATFORMS: list[Platform] = [Platform.ALARM_CONTROL_PANEL, Platform.SENSOR]
_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigEntry):
    """Set up the hikvision_axpro integration component."""
    hass.data.setdefault(DOMAIN, {})

    async def _handle_reload(service):
        """Handle reload service call."""
        _LOGGER.info("Service %s.reload called: reloading integration", DOMAIN)

        current_entries = hass.config_entries.async_entries(DOMAIN)

        reload_tasks = [
            hass.config_entries.async_reload(entry.entry_id)
            for entry in current_entries
        ]

        await asyncio.gather(*reload_tasks)

    hass.helpers.service.async_register_admin_service(
        DOMAIN,
        SERVICE_RELOAD,
        _handle_reload,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up hikvision_axpro from a config entry."""
    host = entry.data[CONF_HOST]
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    use_code = entry.data[CONF_ENABLED]
    code_format = entry.data[ATTR_CODE_FORMAT]
    code = entry.data[CONF_CODE]
    use_code_arming = entry.data[USE_CODE_ARMING]
    axpro = hikaxpro.HikAxPro(host, username, password)
    update_interval: float = entry.data.get(CONF_SCAN_INTERVAL, SCAN_INTERVAL.total_seconds())

    try:
        async with timeout(10):
            mac = await hass.async_add_executor_job(axpro.get_interface_mac_address, 1)
    except (asyncio.TimeoutError, ConnectionError) as ex:
        raise ConfigEntryNotReady from ex

    coordinator = HikAxProDataUpdateCoordinator(
        hass,
        axpro,
        mac,
        use_code,
        code_format,
        use_code_arming,
        code,
        update_interval
    )
    try:
        async with timeout(10):
            await hass.async_add_executor_job(coordinator.init_device)
    except (asyncio.TimeoutError, ConnectionError) as ex:
        raise ConfigEntryNotReady from ex
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {DATA_COORDINATOR: coordinator}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def update_listener(hass: HomeAssistant, config_entry: ConfigEntry):
    """Update listener."""
    await hass.config_entries.async_reload(config_entry.entry_id)


class HikAxProDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching ax pro data."""
    axpro: hikaxpro.HikAxPro
    zone_status: Optional[ZonesResponse]
    zones: Optional[dict[int, Zone]] = None
    device_info: Optional[dict] = None
    device_model: Optional[str] = None
    device_name: Optional[str] = None
    sub_systems: list[SubSys] = []

    def __init__(
        self,
        hass,
        axpro: hikaxpro.HikAxPro,
        mac,
        use_code,
        code_format,
        use_code_arming,
        code,
        update_interval: float
    ):
        self.axpro = axpro
        self.state = None
        self.zone_status = None
        self.host = axpro.host
        self.mac = mac
        self.use_code = use_code
        self.code_format = code_format
        self.use_code_arming = use_code_arming
        self.code = code
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=update_interval))

    def _get_device_info(self):
        endpoint = self.axpro.buildUrl(f"http://{self.host}/ISAPI/System/deviceInfo", False)
        response = self.axpro.makeRequest(endpoint, "GET", False)

        if response.status_code != 200:
            raise hikaxpro.errors.UnexpectedResponseCodeError(response.status_code, response.text)
        _LOGGER.debug(response.text)
        return xmltodict.parse(response.text)

    def init_device(self):
        self.device_info = self._get_device_info()
        self.device_name = self.device_info['DeviceInfo']['deviceName']
        self.device_model = self.device_info['DeviceInfo']['model']
        _LOGGER.debug(self.device_info)
        self._update_data()

    def _update_data(self) -> None:
        """Fetch data from axpro via sync functions."""
        status = STATE_ALARM_DISARMED
        status_json = self.axpro.subsystem_status()
        try:
            subsys_resp = SubSystemResponse.from_dict(status_json)
            subsys_arr: list[SubSys] = []
            if subsys_resp is not None and subsys_resp.sub_sys_list is not None:
                subsys_arr = []
                for sublist in subsys_resp.sub_sys_list:
                    subsys_arr.append(sublist.sub_sys)
            func: Callable[[SubSys], bool] = lambda n: n.enabled
            subsys_arr = list(filter(func, subsys_arr))
            self.sub_systems = subsys_arr
            for subsys in subsys_arr:
                if subsys.alarm:
                    status = STATE_ALARM_TRIGGERED
                    break
                if subsys.arming == Arming.AWAY:
                    status = STATE_ALARM_ARMED_AWAY
                    break
                if subsys.arming == Arming.STAY:
                    status = STATE_ALARM_ARMED_HOME
                    break
                if subsys.arming == Arming.VACATION:
                    status = STATE_ALARM_ARMED_VACATION
                    break
        except:
            _LOGGER.warning("Error getting status: %s", status_json)
        _LOGGER.debug("Axpro status: %s", status)
        self.state = status

        zone_response = self.axpro.zone_status()
        zone_status = ZonesResponse.from_dict(zone_response)
        self.zone_status = zone_status
        zones = {}
        for zone in zone_status.zone_list:
            zones[zone.zone.id] = zone.zone
        self.zones = zones
        _LOGGER.debug("Zones: %s", zone_response)

    async def _async_update_data(self) -> None:
        """Fetch data from Axpro."""
        try:
            async with timeout(10):
                await self.hass.async_add_executor_job(self._update_data)
        except ConnectionError as error:
            raise UpdateFailed(error) from error

    async def async_arm_home(self, sub_id: Optional[int] = None):
        """Arm alarm panel in home state."""
        # TODO modify AXPRO
        if sub_id is not None:
            is_success = await self.hass.async_add_executor_job(self._arm_home(sub_id=sub_id))
        else:
            is_success = await self.hass.async_add_executor_job(self.axpro.arm_home)

        if is_success:
            await self._async_update_data()
            await self.async_request_refresh()

    async def async_arm_away(self, sub_id: Optional[int] = None):
        """Arm alarm panel in away state"""
        # TODO modify AXPRO
        if sub_id is not None:
            is_success = await self.hass.async_add_executor_job(self._arm_away(sub_id=sub_id))
        else:
            is_success = await self.hass.async_add_executor_job(self.axpro.arm_away)

        if is_success:
            await self._async_update_data()
            await self.async_request_refresh()

    async def async_disarm(self, sub_id: Optional[int] = None):
        """Disarm alarm control panel."""
        # TODO modify AXPRO
        if sub_id is not None:
            is_success = await self.hass.async_add_executor_job(self._disarm(sub_id=sub_id))
        else:
            is_success = await self.hass.async_add_executor_job(self.axpro.disarm)

        if is_success:
            await self._async_update_data()
            await self.async_request_refresh()

    def _arm_home(self, sub_id: int):
        endpoint = self.axpro.buildUrl(f"http://{self.host}{hikaxpro.consts.Endpoints.Alarm_ArmHome.replace('0xffffffff', str(sub_id))}", True)
        response = self.axpro.makeRequest(endpoint, hikaxpro.consts.Method.PUT)

        if response.status_code != 200:
            raise hikaxpro.errors.UnexpectedResponseCodeError(response.status_code, response.text)

        return response.status_code == 200

    def _arm_away(self, sub_id: int):
        endpoint = self.axpro.buildUrl(f"http://{self.host}{hikaxpro.consts.Endpoints.Alarm_ArmAway.replace('0xffffffff', str(sub_id))}", True)
        response = self.axpro.makeRequest(endpoint, hikaxpro.consts.Method.PUT)

        if response.status_code != 200:
            raise hikaxpro.errors.UnexpectedResponseCodeError(response.status_code, response.text)

        return response.status_code == 200

    def _disarm(self, sub_id: int):
        endpoint = self.axpro.buildUrl(f"http://{self.host}{hikaxpro.consts.Endpoints.Alarm_Disarm.replace('0xffffffff', str(sub_id))}", True)
        response = self.axpro.makeRequest(endpoint, hikaxpro.consts.Method.PUT)

        if response.status_code != 200:
            raise hikaxpro.errors.UnexpectedResponseCodeError(response.status_code, response.text)

        return response.status_code == 200
