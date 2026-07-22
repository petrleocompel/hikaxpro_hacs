"""The hikvision_axpro integration."""

import asyncio
from asyncio import timeout
import contextlib
from datetime import timedelta
import logging

import hikaxpro
import xmltodict

from homeassistant.components.alarm_control_panel import (
    SCAN_INTERVAL,
    AlarmControlPanelState,
)
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_CODE_FORMAT,
    CONF_CODE,
    CONF_ENABLED,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    SERVICE_RELOAD,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
import homeassistant.helpers.device_registry as dr
import homeassistant.helpers.entity_registry as er
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ALLOW_SUBSYSTEMS,
    AUTO_BYPASS_ON_ARM,
    DATA_COORDINATOR,
    DOMAIN,
    ENABLE_DEBUG_OUTPUT,
    USE_CODE_ARMING,
)
from .entity_id import migrate_invalid_entity_ids
from .model import (
    Arming,
    ExDevStatusResponse,
    ExtensionModule,
    JSONResponseStatus,
    Keypad,
    OutputConfList,
    OutputStatusFull,
    RelayStatusSearchResponse,
    RelaySwitchConf,
    Repeater,
    Siren,
    Status,
    SubSys,
    SubSystemResponse,
    Zone,
    ZoneConfig,
    ZonesConf,
    ZonesResponse,
)

PLATFORMS: list[Platform] = [
    Platform.ALARM_CONTROL_PANEL,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SWITCH,
]
_LOGGER = logging.getLogger(__name__)


def _filter_enabled(n: SubSys) -> bool:
    return n.enabled


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

    async def _handle_purge(service):
        """Handle purge of unwanted entitites."""
        _LOGGER.info("Service %s.purge called: destroying old entities", DOMAIN)
        dregistry: dr.DeviceRegistry = dr.async_get(hass)
        eregistry: er.EntityRegistry = er.async_get(hass)

        current_entries = hass.config_entries.async_entries(DOMAIN)
        for config in current_entries:
            devices = dregistry.devices.get_devices_for_config_entry_id(config.entry_id)
            entities: list[er.RegistryEntry] = []
            for device in devices:
                device_ent = eregistry.entities.get_entries_for_device_id(
                    device.id, True
                )
                entities.extend(device_ent)

            invalid_binary_sensors_as_sensor_unique_id_parts = [
                "-magnet-",
                "-magnet-shock-",
                "-magnet-open-",
                "-magnet-tilt-",
                "-tamper-",
                "-bypass-",
                "-armed-",
                "-alarm-",
                "-stayaway-",
                "-isviarepeater-",
                "-battery-low-",
            ]
            for entity in entities:
                if entity.domain == SENSOR_DOMAIN and any(
                    sub_string in entity.unique_id
                    for sub_string in invalid_binary_sensors_as_sensor_unique_id_parts
                ):
                    _LOGGER.info("Service %s.purge: removing entity", entity.entity_id)
                    eregistry.async_remove(entity.entity_id)

    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_RELOAD,
        _handle_reload,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        "purge",
        _handle_purge,
    )

    async def _service_bypass_zone(call):
        zone_id = int(call.data["zone_id"])
        coordinator = _coordinator_for_service(hass, call)
        await coordinator.async_bypass_zone(zone_id)

    async def _service_recover_bypass_zone(call):
        zone_id = int(call.data["zone_id"])
        coordinator = _coordinator_for_service(hass, call)
        await coordinator.async_recover_bypass_zone(zone_id)

    async def _service_arm_away_with_bypass(call):
        coordinator = _coordinator_for_service(hass, call)
        sub_id = call.data.get("sub_id")
        await coordinator.async_arm_away(sub_id=sub_id, with_bypass=True)

    async def _service_arm_home_with_bypass(call):
        coordinator = _coordinator_for_service(hass, call)
        sub_id = call.data.get("sub_id")
        await coordinator.async_arm_home(sub_id=sub_id, with_bypass=True)

    hass.services.async_register(DOMAIN, "bypass_zone", _service_bypass_zone)
    hass.services.async_register(
        DOMAIN, "recover_bypass_zone", _service_recover_bypass_zone
    )
    hass.services.async_register(
        DOMAIN, "arm_away_with_bypass", _service_arm_away_with_bypass
    )
    hass.services.async_register(
        DOMAIN, "arm_home_with_bypass", _service_arm_home_with_bypass
    )
    return True


def _coordinator_for_service(
    hass: HomeAssistant, call
) -> "HikAxProDataUpdateCoordinator":
    """Resolve coordinator from optional config_entry_id or the first entry."""
    entry_id = call.data.get("config_entry_id")
    if entry_id is None:
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            raise ValueError("No hikvision_axpro config entries")
        entry_id = entries[0].entry_id
    return hass.data[DOMAIN][entry_id][DATA_COORDINATOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up hikvision_axpro from a config entry."""
    host = entry.data[CONF_HOST]
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    use_code = entry.data[CONF_ENABLED]
    code_format = entry.data[ATTR_CODE_FORMAT]
    code = entry.data[CONF_CODE]
    use_code_arming = entry.data[USE_CODE_ARMING]
    use_sub_systems = entry.data.get(ALLOW_SUBSYSTEMS, False)
    auto_bypass_on_arm = entry.data.get(AUTO_BYPASS_ON_ARM, False)
    axpro = hikaxpro.HikAxPro(
        host, username, password, user_level=hikaxpro.USER_LEVEL_ADMIN_OPERATOR
    )
    update_interval: float = entry.data.get(
        CONF_SCAN_INTERVAL, SCAN_INTERVAL.total_seconds()
    )

    if entry.data.get(ENABLE_DEBUG_OUTPUT):
        with contextlib.suppress(Exception):
            axpro.set_logging_level(logging.DEBUG)

    try:
        async with timeout(10):
            mac = await hass.async_add_executor_job(axpro.get_interface_mac_address, 1)
    except (TimeoutError, ConnectionError) as ex:
        raise ConfigEntryNotReady from ex

    coordinator = HikAxProDataUpdateCoordinator(
        hass,
        axpro,
        mac,
        use_code,
        code_format,
        use_code_arming,
        code,
        update_interval,
        use_sub_systems,
        auto_bypass_on_arm=auto_bypass_on_arm,
    )
    try:
        async with timeout(10):
            await hass.async_add_executor_job(coordinator.init_device)
    except (TimeoutError, ConnectionError) as ex:
        raise ConfigEntryNotReady from ex
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {DATA_COORDINATOR: coordinator}

    migrate_invalid_entity_ids(hass, entry)

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
    zone_status: ZonesResponse | None
    zones: dict[int, Zone] | None = None
    device_info: dict | None = None
    device_model: str | None = None
    device_name: str | None = None
    sub_systems: dict[int, SubSys] = {}
    """ Zones aka devices """
    devices: dict[int, ZoneConfig] = {}
    relays: dict[int, RelaySwitchConf] = {}
    relays_status: dict[int, OutputStatusFull] = {}
    sirens: dict[int, Siren] = {}
    keypads: dict[int, Keypad] = {}
    repeaters: dict[int, Repeater] = {}
    extensions: dict[int, ExtensionModule] = {}
    host_status: dict | None = None
    ac_power_status: dict | None = None
    hub_batteries: list[dict] = []
    use_sub_systems: bool
    auto_bypass_on_arm: bool

    def __init__(
        self,
        hass: HomeAssistant,
        axpro: hikaxpro.HikAxPro,
        mac,
        use_code,
        code_format,
        use_code_arming,
        code,
        update_interval: float,
        use_sub_systems=False,
        auto_bypass_on_arm=False,
    ) -> None:
        """Initialize global data updater and AXPro API."""
        self.axpro = axpro
        self.state = None
        self.zone_status = None
        self.host = axpro.host
        self.mac = mac
        self.use_code = use_code
        self.code_format = code_format
        self.use_code_arming = use_code_arming
        self.code = code
        self.use_sub_systems = use_sub_systems
        self.auto_bypass_on_arm = auto_bypass_on_arm
        self.sirens = {}
        self.keypads = {}
        self.repeaters = {}
        self.extensions = {}
        self.host_status = None
        self.ac_power_status = None
        self.hub_batteries = []
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )

    def _get_device_info(self):
        endpoint = self.axpro.build_url(
            f"http://{self.host}" + hikaxpro.consts.Endpoints.SystemDeviceInfo, False
        )
        response = self.axpro.make_request(endpoint, "GET", None, True)

        if response.status_code != 200:
            raise hikaxpro.errors.UnexpectedResponseCodeError(
                response.status_code, response.text
            )
        _LOGGER.debug(response.text)
        return xmltodict.parse(response.text)

    def init_device(self):
        """Init device information."""
        self.device_info = self._get_device_info()
        self.device_name = self.device_info["DeviceInfo"]["deviceName"]
        self.device_model = self.device_info["DeviceInfo"]["model"]
        _LOGGER.debug(self.device_info)
        self.load_devices()
        self.load_relays()
        self._update_data()

    def load_relays(self):
        """Load relays."""
        devices = self._load_relays()
        if devices is not None:
            self.relays = {}
            for item in devices.list:
                self.relays[item.output.id] = item.output

    def _load_relays(self) -> OutputConfList:
        endpoint = self.axpro.build_url(
            f"http://{self.host}" + hikaxpro.consts.Endpoints.OutputConfig, True
        )
        response = self.axpro.make_request(endpoint, "GET", None, True)

        if response.status_code != 200:
            raise hikaxpro.errors.UnexpectedResponseCodeError(
                response.status_code, response.text
            )
        _LOGGER.debug(response.text)
        return OutputConfList.from_dict(response.json())

    def load_ext_devices_status(self):
        """Load status of external devices."""
        statuses = self._load_ext_devices_status()
        if statuses is not None:
            self.relays_status = {}
            self.sirens = {}
            self.keypads = {}
            self.repeaters = {}
            self.extensions = {}
            if statuses.ex_dev_status is not None:
                if statuses.ex_dev_status.output_list is not None:
                    for item in statuses.ex_dev_status.output_list:
                        if item.output is not None and item.output.id is not None:
                            self.relays_status[item.output.id] = item.output
                if statuses.ex_dev_status.siren_list is not None:
                    for item in statuses.ex_dev_status.siren_list:
                        if item.siren is not None and item.siren.id is not None:
                            self.sirens[item.siren.id] = item.siren
                if statuses.ex_dev_status.keypad_list is not None:
                    for item in statuses.ex_dev_status.keypad_list:
                        if item.keypad is not None and item.keypad.id is not None:
                            self.keypads[item.keypad.id] = item.keypad
                if statuses.ex_dev_status.repeater_list is not None:
                    for item in statuses.ex_dev_status.repeater_list:
                        if item.repeater is not None and item.repeater.id is not None:
                            self.repeaters[item.repeater.id] = item.repeater
                if statuses.ex_dev_status.extension_list is not None:
                    for item in statuses.ex_dev_status.extension_list:
                        if (
                            item.extension_module is not None
                            and item.extension_module.id is not None
                        ):
                            self.extensions[item.extension_module.id] = (
                                item.extension_module
                            )

    def _load_ext_devices_status(self) -> ExDevStatusResponse:
        endpoint = self.axpro.build_url(
            f"http://{self.host}" + "/ISAPI/SecurityCP/status/exDevStatus", True
        )
        response = self.axpro.make_request(endpoint, "GET", None, True)

        if response.status_code != 200:
            raise hikaxpro.errors.UnexpectedResponseCodeError(
                response.status_code, response.text
            )
        _LOGGER.debug(response.text)
        return ExDevStatusResponse.from_dict(response.json())

    def load_devices(self):
        """Load devices from Zone Config."""
        devices = self._load_devices()
        if devices is not None:
            self.devices = {}
            for item in devices.list:
                self.devices[item.zone.id] = item.zone

    def _load_devices(self) -> ZonesConf:
        endpoint = self.axpro.build_url(
            f"http://{self.host}" + hikaxpro.consts.Endpoints.ZonesConfig, True
        )
        response = self.axpro.make_request(endpoint, "GET", None, True)

        if response.status_code != 200:
            raise hikaxpro.errors.UnexpectedResponseCodeError(
                response.status_code, response.text
            )
        _LOGGER.debug(response.text)
        return ZonesConf.from_dict(response.json())

    def _update_relays_status(self) -> RelayStatusSearchResponse:
        endpoint = self.axpro.build_url(
            f"http://{self.host}" + hikaxpro.consts.Endpoints.OutputStatus, True
        )
        response = self.axpro.make_request(
            endpoint,
            "POST",
            {
                "OutputCond": {
                    "searchID": "homeassistant",
                    "searchResultPosition": 1,
                    "maxResults": 50,
                    "moduleType": "localWired",
                }
            },
            True,
        )

        if response.status_code != 200:
            raise hikaxpro.errors.UnexpectedResponseCodeError(
                response.status_code, response.text
            )
        _LOGGER.debug(response.text)
        return RelayStatusSearchResponse.from_dict(response.json())

    def _update_data(self) -> None:
        """Fetch data from axpro via sync functions."""
        status = AlarmControlPanelState.DISARMED
        status_json = self.axpro.subsystem_status()
        try:
            subsys_resp = SubSystemResponse.from_dict(status_json)
            subsys_arr: list[SubSys] = []
            if subsys_resp is not None and subsys_resp.sub_sys_list is not None:
                subsys_arr = []
                for sublist in subsys_resp.sub_sys_list:
                    subsys_arr.append(sublist.sub_sys)

            subsys_arr = list(filter(_filter_enabled, subsys_arr))
            self.sub_systems = {}
            for subsys in subsys_arr:
                self.sub_systems[subsys.id] = subsys
                if self.use_sub_systems and subsys.id != 1:
                    continue
                if subsys.alarm:
                    status = AlarmControlPanelState.TRIGGERED
                elif subsys.arming == Arming.AWAY:
                    status = AlarmControlPanelState.ARMED_AWAY
                elif subsys.arming == Arming.STAY:
                    status = AlarmControlPanelState.ARMED_HOME
                elif subsys.arming == Arming.VACATION:
                    status = AlarmControlPanelState.ARMED_VACATION
            _LOGGER.debug("SubSystem status: %s", subsys_resp)
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
        # peripherals from exDevStatus
        devices_status = self._load_ext_devices_status()
        relays_status: dict[int, OutputStatusFull] = {}
        sirens: dict[int, Siren] = {}
        keypads: dict[int, Keypad] = {}
        repeaters: dict[int, Repeater] = {}
        extensions: dict[int, ExtensionModule] = {}
        if devices_status.ex_dev_status is not None:
            ex = devices_status.ex_dev_status
            if ex.output_list is not None:
                for item in ex.output_list:
                    if item.output is not None and item.output.id is not None:
                        relays_status[item.output.id] = item.output
            if ex.siren_list is not None:
                for item in ex.siren_list:
                    if item.siren is not None and item.siren.id is not None:
                        sirens[item.siren.id] = item.siren
            if ex.keypad_list is not None:
                for item in ex.keypad_list:
                    if item.keypad is not None and item.keypad.id is not None:
                        keypads[item.keypad.id] = item.keypad
            if ex.repeater_list is not None:
                for item in ex.repeater_list:
                    if item.repeater is not None and item.repeater.id is not None:
                        repeaters[item.repeater.id] = item.repeater
            if ex.extension_list is not None:
                for item in ex.extension_list:
                    if (
                        item.extension_module is not None
                        and item.extension_module.id is not None
                    ):
                        extensions[item.extension_module.id] = item.extension_module
        self.relays_status = relays_status
        self.sirens = sirens
        self.keypads = keypads
        self.repeaters = repeaters
        self.extensions = extensions
        _LOGGER.debug("Relay status: %s", relays_status)
        _LOGGER.debug(
            "Peripherals sirens=%s keypads=%s repeaters=%s extensions=%s",
            list(sirens),
            list(keypads),
            list(repeaters),
            list(extensions),
        )
        self._update_host_diagnostics()

    def _update_host_diagnostics(self) -> None:
        """Best-effort poll of host / AC / hub battery status APIs."""
        try:
            self.host_status = self.axpro.host_status()
        except Exception:  # noqa: BLE001 - panel firmware varies
            _LOGGER.debug("host status unavailable", exc_info=True)
            self.host_status = None

        try:
            endpoint = self.axpro.build_url(
                f"http://{self.host}/ISAPI/SecurityCP/status/acPowerStatus", True
            )
            response = self.axpro.make_request(endpoint, "GET", None, True)
            if response.status_code == 200:
                self.ac_power_status = response.json()
            else:
                self.ac_power_status = None
        except Exception:  # noqa: BLE001
            _LOGGER.debug("AC power status unavailable", exc_info=True)
            self.ac_power_status = None

        try:
            endpoint = self.axpro.build_url(
                f"http://{self.host}" + hikaxpro.consts.Endpoints.BatteriesStatus,
                True,
            )
            response = self.axpro.make_request(endpoint, "GET", None, True)
            batteries: list[dict] = []
            if response.status_code == 200:
                payload = response.json()
                for item in payload.get("BatteryList") or []:
                    battery = item.get("Battery") if isinstance(item, dict) else None
                    if isinstance(battery, dict):
                        batteries.append(battery)
            self.hub_batteries = batteries
        except Exception:  # noqa: BLE001
            _LOGGER.debug("hub batteries unavailable", exc_info=True)
            self.hub_batteries = []

    async def _async_update_data(self) -> None:
        """Fetch data from Axpro."""
        try:
            async with timeout(10):
                await self.hass.async_add_executor_job(self._update_data)
        except ConnectionError as error:
            raise UpdateFailed(error) from error

    async def async_arm_home(self, sub_id: int | None = None, with_bypass: bool = False):
        """Arm alarm panel in home state."""
        if with_bypass or self.auto_bypass_on_arm:
            await self.async_bypass_blocking_zones()
        is_success = await self.hass.async_add_executor_job(self.axpro.arm_home, sub_id)

        if is_success:
            await self._async_update_data()
            await self.async_request_refresh()

    async def async_arm_away(self, sub_id: int | None = None, with_bypass: bool = False):
        """Arm alarm panel in away state."""
        if with_bypass or self.auto_bypass_on_arm:
            await self.async_bypass_blocking_zones()
        is_success = await self.hass.async_add_executor_job(self.axpro.arm_away, sub_id)

        if is_success:
            await self._async_update_data()
            await self.async_request_refresh()

    async def async_disarm(self, sub_id: int | None = None):
        """Disarm alarm control panel."""
        is_success = await self.hass.async_add_executor_job(self.axpro.disarm, sub_id)

        if is_success:
            await self._async_update_data()
            await self.async_request_refresh()

    def _zones_blocking_arm(self) -> list[int]:
        """Return zone IDs that typically prevent arming when left open/triggered."""
        if not self.zones:
            return []
        blocking: list[int] = []
        for zone_id, zone in self.zones.items():
            if zone.bypassed:
                continue
            open_magnet = zone.magnet_open_status is True
            triggered = zone.status is Status.TRIGGER
            alarming = zone.alarm is True
            if open_magnet or triggered or alarming:
                blocking.append(zone_id)
        return blocking

    async def async_bypass_blocking_zones(self) -> None:
        """Bypass zones that look open/triggered before arming."""
        for zone_id in self._zones_blocking_arm():
            await self.async_bypass_zone(zone_id)

    async def async_bypass_zone(self, zone_id: int) -> bool:
        """Bypass a single zone."""
        is_success = await self.hass.async_add_executor_job(
            self.axpro.bypass_zone, zone_id
        )
        if is_success:
            await self._async_update_data()
            await self.async_request_refresh()
        return is_success

    async def async_recover_bypass_zone(self, zone_id: int) -> bool:
        """Clear bypass on a single zone."""
        is_success = await self.hass.async_add_executor_job(
            self.axpro.recover_bypass_zone, zone_id
        )
        if is_success:
            await self._async_update_data()
            await self.async_request_refresh()
        return is_success

    def _relay_call(self, relay_id: int, is_enabled: bool) -> JSONResponseStatus:
        endpoint = self.axpro.build_url(
            f"http://{self.host}"
            + hikaxpro.consts.Endpoints.OutputControl.replace("{}", str(relay_id)),
            True,
        )
        response = self.axpro.make_request(
            endpoint,
            "PUT",
            {"OutputsCtrl": {"switch": "open" if is_enabled else "close"}},
            True,
        )
        if response.status_code != 200:
            raise hikaxpro.errors.UnexpectedResponseCodeError(
                response.status_code, response.text
            )
        _LOGGER.debug(response.text)
        return JSONResponseStatus.from_dict(response.json())

    async def relay_on(self, relay_id: int):
        """Turn on relay by ID."""
        response: JSONResponseStatus = await self.hass.async_add_executor_job(
            self._relay_call, relay_id, True
        )
        return response.status_code == 1

    async def relay_off(self, relay_id: int):
        """Turn off relay by ID."""
        response: JSONResponseStatus = await self.hass.async_add_executor_job(
            self._relay_call, relay_id, False
        )
        return response.status_code == 1
