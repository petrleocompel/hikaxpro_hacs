"""The hikvision_axpro integration."""

import asyncio
from asyncio import timeout
import contextlib
from datetime import datetime, timedelta
import logging
import re

import hikaxpro
import xmltodict

from homeassistant.components import persistent_notification
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
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
import homeassistant.helpers.device_registry as dr
import homeassistant.helpers.entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .bypass_manager import BypassManager
from .bypass_store import BypassStore
from .const import (
    ALLOW_SUBSYSTEMS,
    ARM_MODE_AWAY,
    ARM_MODE_HOME,
    ARM_MODE_VACATION,
    CONF_AUTO_BYPASS_MODES,
    DATA_BYPASS_MANAGER,
    DATA_COORDINATOR,
    DOMAIN,
    ENABLE_DEBUG_OUTPUT,
    ISSUE_BYPASS_UNSUPPORTED,
    SERVICE_BYPASS_ZONE,
    SERVICE_CLEAR_ALL_BYPASSES,
    SERVICE_UNBYPASS_ZONE,
    USE_CODE_ARMING,
    zone_id_from_bypass_unique_id,
)
from .entity_id import (
    has_invalid_object_id_chars,
    normalized_mac,
    normalized_object_id,
)
from .isapi_bypass import AxProBypassClient
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
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SWITCH,
]
_LOGGER = logging.getLogger(__name__)

# The zone configuration (names, types, panel-side bypass restrictions)
# changes rarely; refresh it hourly instead of on every poll.
ZONE_CONFIG_REFRESH_INTERVAL = timedelta(hours=1)


def _migrated_unique_id(
    unique_id: str, device_name: str | None, mac: str, mac_id: str
) -> str | None:
    """Map a legacy unique_id onto the compact-MAC scheme, or None.

    Three legacy shapes are folded in:

    - keyed by the panel's ``deviceName``, which the user can change on
      the panel and which is not unique across two panels;
    - keyed by the MAC as the panel spells it, ``a4:d5:c2:6b:b8:59``,
      where the separators split one identifier into six tokens;
    - subsystem panels, which concatenated the MAC and the area number
      without a separator and so were ambiguous for any MAC ending in a
      digit.

    All become ``<compact mac>-<what>`` / ``subsys-<compact mac>-<area>``.
    """
    for prefix in (mac, mac_id, device_name):
        if not prefix:
            continue

        if unique_id == prefix:
            return mac_id

        subsys = f"subsys-{prefix}"
        if unique_id.startswith(subsys):
            area = unique_id[len(subsys) :].lstrip("-")
            if area.isdigit():
                return f"subsys-{mac_id}-{area}"
            return None

        if unique_id.startswith(f"{prefix}-"):
            return f"{mac_id}-{unique_id[len(prefix) + 1 :]}"

    return None


async def _async_migrate_unique_ids(
    hass: HomeAssistant, entry: ConfigEntry, device_name: str | None, mac: str
) -> None:
    """Re-key existing registry entries onto the MAC-scoped unique ids.

    Without this an upgrade would orphan every entity and create a
    duplicate set alongside it, losing history and breaking automations.
    """
    registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if not reg_entry.unique_id:
            continue
        new_unique_id = _migrated_unique_id(
            reg_entry.unique_id, device_name, mac, normalized_mac(mac)
        )
        if new_unique_id is None or new_unique_id == reg_entry.unique_id:
            continue
        if (
            existing := registry.async_get_entity_id(
                reg_entry.domain, DOMAIN, new_unique_id
            )
        ) and existing != reg_entry.entity_id:
            # A previous partial migration already created the target;
            # drop the stale duplicate rather than fail the setup.
            _LOGGER.warning(
                "Removing stale entity %s: %s is already used by %s",
                reg_entry.entity_id,
                new_unique_id,
                existing,
            )
            registry.async_remove(reg_entry.entity_id)
            continue
        _LOGGER.info(
            "Migrating unique_id for %s: %s -> %s",
            reg_entry.entity_id,
            reg_entry.unique_id,
            new_unique_id,
        )
        registry.async_update_entity(reg_entry.entity_id, new_unique_id=new_unique_id)


def _next_available_entity_id(
    registry: er.EntityRegistry,
    domain: str,
    object_id: str,
    current_entity_id: str,
) -> str:
    """Find a free entity_id using HA-style numeric suffixes."""
    candidate = f"{domain}.{object_id}"
    if candidate == current_entity_id:
        return candidate

    suffix = 2
    while registry.entities.get(candidate) is not None:
        candidate = f"{domain}.{object_id}_{suffix}"
        suffix += 1
    return candidate


async def _async_migrate_invalid_entity_ids(
    hass: HomeAssistant, entry: ConfigEntry
) -> list[tuple[str, str]]:
    """Rename entity IDs that are no longer valid object ids.

    Existing installations keep whatever entity_id the registry already
    holds: only ids Home Assistant would reject (characters outside
    ``[a-z0-9_]``, such as the ``-`` separators older releases wrote)
    are rewritten, and the user is told which ones changed.
    """
    registry = er.async_get(hass)
    renames: list[tuple[str, str]] = []

    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if not has_invalid_object_id_chars(reg_entry.entity_id):
            continue
        if "." not in reg_entry.entity_id:
            continue

        domain, object_id = reg_entry.entity_id.split(".", 1)
        target_object_id = normalized_object_id(object_id, fallback=reg_entry.unique_id)
        target_entity_id = _next_available_entity_id(
            registry,
            domain,
            target_object_id,
            reg_entry.entity_id,
        )
        if target_entity_id == reg_entry.entity_id:
            continue

        registry.async_update_entity(
            reg_entry.entity_id,
            new_entity_id=target_entity_id,
        )
        renames.append((reg_entry.entity_id, target_entity_id))
        _LOGGER.info(
            "Migrated invalid entity ID for %s: %s -> %s",
            DOMAIN,
            reg_entry.entity_id,
            target_entity_id,
        )

    if renames:
        rename_list = "\n".join(f"- {old} -> {new}" for old, new in renames)
        persistent_notification.async_create(
            hass,
            (
                "The integration renamed invalid entity IDs so they stay valid "
                "Home Assistant object ids. Update automations, scripts, scenes, "
                "and dashboards that reference the old IDs.\n\n"
                f"{rename_list}"
            ),
            title="Hikvision AX Pro entity IDs updated",
            notification_id=f"{DOMAIN}_entity_id_migration_{entry.entry_id}",
        )

    return renames


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
        manager = _bypass_manager_for_service(hass, call)
        for zone_id in _zone_ids_from_call(hass, call):
            await manager.async_bypass_zone(zone_id)

    async def _service_unbypass_zone(call):
        manager = _bypass_manager_for_service(hass, call)
        for zone_id in _zone_ids_from_call(hass, call):
            await manager.async_unbypass_zone(zone_id)

    async def _service_clear_all_bypasses(call):
        manager = _bypass_manager_for_service(hass, call)
        await manager.async_clear_all(_subsystem_id_from_call(hass, call))

    async def _service_arm_away_with_bypass(call):
        coordinator = _coordinator_for_service(hass, call)
        sub_id = call.data.get("sub_id")
        await coordinator.async_arm_away(sub_id=sub_id, with_bypass=True)

    async def _service_arm_home_with_bypass(call):
        coordinator = _coordinator_for_service(hass, call)
        sub_id = call.data.get("sub_id")
        await coordinator.async_arm_home(sub_id=sub_id, with_bypass=True)

    hass.services.async_register(DOMAIN, SERVICE_BYPASS_ZONE, _service_bypass_zone)
    hass.services.async_register(DOMAIN, SERVICE_UNBYPASS_ZONE, _service_unbypass_zone)
    # Backward-compatible alias used by older automations.
    hass.services.async_register(
        DOMAIN, "recover_bypass_zone", _service_unbypass_zone
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CLEAR_ALL_BYPASSES, _service_clear_all_bypasses
    )
    hass.services.async_register(
        DOMAIN, "arm_away_with_bypass", _service_arm_away_with_bypass
    )
    hass.services.async_register(
        DOMAIN, "arm_home_with_bypass", _service_arm_home_with_bypass
    )

    async def _service_control_siren(call):
        coordinator = _coordinator_for_service(hass, call)
        siren_id = int(call.data["siren_id"])
        enabled = bool(call.data["enabled"])
        if enabled:
            await coordinator.siren_on(siren_id)
        else:
            await coordinator.siren_off(siren_id)

    hass.services.async_register(DOMAIN, "control_siren", _service_control_siren)

    async def _service_one_key_alarm(call):
        coordinator = _coordinator_for_service(hass, call)
        enabled = bool(call.data.get("enabled", True))
        if enabled:
            await coordinator.one_key_alarm_on()
        else:
            await coordinator.one_key_alarm_off()

    hass.services.async_register(DOMAIN, "one_key_alarm", _service_one_key_alarm)
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


def _bypass_manager_for_service(hass: HomeAssistant, call) -> BypassManager:
    """Resolve the bypass manager backing a service call."""
    manager = _coordinator_for_service(hass, call).bypass_manager
    if manager is None:
        raise HomeAssistantError("Bypass manager not available")
    return manager


def _zone_ids_from_call(hass: HomeAssistant, call) -> list[int]:
    """Resolve one or more zone IDs from `zone_id` or bypass entity targets."""
    if call.data.get("zone_id") is not None:
        return [int(call.data["zone_id"])]

    target = call.data.get("entity_id")
    if target is None:
        raise HomeAssistantError("Missing zone_id or target entity_id")

    entity_ids = [target] if isinstance(target, str) else list(target)
    registry = er.async_get(hass)
    zone_ids: list[int] = []
    for entity_id in entity_ids:
        reg_entry = registry.async_get(entity_id)
        if reg_entry is None:
            raise HomeAssistantError(f"Unknown entity_id: {entity_id}")
        zone_id = zone_id_from_bypass_unique_id(reg_entry.unique_id)
        if zone_id is None:
            raise HomeAssistantError(
                f"Entity {entity_id} is not a zone bypass binary sensor"
            )
        zone_ids.append(zone_id)
    return zone_ids


def _subsystem_id_from_call(hass: HomeAssistant, call) -> int | None:
    """Resolve optional subsystem id from an alarm_control_panel entity target."""
    target = call.data.get("entity_id")
    if target is None:
        return None

    entity_id = target if isinstance(target, str) else (target[0] if target else None)
    if not entity_id:
        return None

    registry = er.async_get(hass)
    reg_entry = registry.async_get(entity_id)
    if reg_entry is None or not reg_entry.unique_id:
        return None

    match = re.fullmatch(r"subsys-.*-(\d+)", reg_entry.unique_id)
    return int(match.group(1)) if match else None


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
    )
    try:
        async with timeout(10):
            await hass.async_add_executor_job(coordinator.init_device)
    except (TimeoutError, ConnectionError) as ex:
        raise ConfigEntryNotReady from ex
    bypass_store = BypassStore(hass, entry.entry_id)
    await bypass_store.async_load()

    bypass_manager = BypassManager(
        hass, entry, coordinator, AxProBypassClient(axpro), bypass_store
    )
    # A firmware that reports the per-zone bypass state supports the
    # bypass control endpoint; detected from already-fetched data.
    bypass_supported = any(
        zone.bypassed is not None for zone in (coordinator.zones or {}).values()
    )
    bypass_manager.bypass_supported = bypass_supported
    coordinator.bypass_manager = bypass_manager
    bypass_manager.async_report_ineffective_config()
    if not bypass_supported:
        _LOGGER.warning(
            "Panel %s does not report zone bypass states; "
            "bypass features are disabled",
            coordinator.device_name,
        )
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"{ISSUE_BYPASS_UNSUPPORTED}_{entry.entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_BYPASS_UNSUPPORTED,
            translation_placeholders={"device": coordinator.device_name or ""},
        )
    else:
        ir.async_delete_issue(
            hass, DOMAIN, f"{ISSUE_BYPASS_UNSUPPORTED}_{entry.entry_id}"
        )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_COORDINATOR: coordinator,
        DATA_BYPASS_MANAGER: bypass_manager,
    }

    entry.async_on_unload(entry.add_update_listener(update_listener))

    await _async_migrate_unique_ids(hass, entry, coordinator.device_name, mac)
    await _async_migrate_invalid_entity_ids(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Second pass: entities created during platform setup (new unique
    # ids, or entity ids restored from deleted registry entries) can
    # still carry ids the first pass never saw.
    await _async_migrate_invalid_entity_ids(hass, entry)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data = hass.data[DOMAIN].pop(entry.entry_id)
        manager: BypassManager | None = data.get(DATA_BYPASS_MANAGER)
        if manager is not None:
            manager.async_unload()

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
    siren_control_supported: dict[int, bool] = {}
    host_control_cap: dict | None = None
    one_key_alarm_supported: bool | None = None
    siren_ctrl_supported: bool | None = None
    use_sub_systems: bool
    bypass_manager: "BypassManager | None" = None

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
    ) -> None:
        """Initialize global data updater and AXPro API."""
        self.axpro = axpro
        self.state = None
        self.zone_status = None
        self.host = axpro.host
        self.mac = mac
        # Compact form used to scope unique ids; ``mac`` stays as the
        # panel reports it and keys the device registry entries.
        self.mac_id = normalized_mac(mac)
        self.use_code = use_code
        self.code_format = code_format
        self.use_code_arming = use_code_arming
        self.code = code
        self.use_sub_systems = use_sub_systems
        self._last_zone_config_fetch: datetime | None = None
        self.sirens = {}
        self.keypads = {}
        self.repeaters = {}
        self.extensions = {}
        self.host_status = None
        self.ac_power_status = None
        self.hub_batteries = []
        self.siren_control_supported = {}
        self.host_control_cap = None
        self.one_key_alarm_supported = None
        self.siren_ctrl_supported = None
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
        self.load_host_control_capabilities()
        self._update_data()

    def load_host_control_capabilities(self) -> None:
        """Load HostControlCap (siren / one-key alarm support flags)."""
        try:
            endpoint = self.axpro.build_url(
                f"http://{self.host}" + hikaxpro.consts.Endpoints.HostCapabilities,
                True,
            )
            response = self.axpro.make_request(endpoint, "GET", None, True)
            if response.status_code != 200:
                _LOGGER.debug(
                    "HostControlCap unavailable: HTTP %s", response.status_code
                )
                return
            payload = response.json()
            cap = payload.get("HostControlCap") if isinstance(payload, dict) else None
            if not isinstance(cap, dict):
                return
            self.host_control_cap = cap
            if "isSptOneKeyAlarmCtrl" in cap:
                self.one_key_alarm_supported = bool(cap.get("isSptOneKeyAlarmCtrl"))
            if "isSptSirenCtrl" in cap:
                self.siren_ctrl_supported = bool(cap.get("isSptSirenCtrl"))
            _LOGGER.debug(
                "HostControlCap one_key=%s siren_ctrl=%s",
                self.one_key_alarm_supported,
                self.siren_ctrl_supported,
            )
        except Exception:  # noqa: BLE001 - firmware varies
            _LOGGER.debug("HostControlCap load failed", exc_info=True)

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
        self._last_zone_config_fetch = dt_util.utcnow()
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
        # Refresh the zone configuration hourly, so panel-side setting
        # changes (e.g. "forbid bypass on arming") are picked up without
        # a reload while keeping the poll cycle light. A failed refresh
        # keeps the previous configuration and is retried next poll.
        if (
            self._last_zone_config_fetch is None
            or dt_util.utcnow() - self._last_zone_config_fetch
            >= ZONE_CONFIG_REFRESH_INTERVAL
        ):
            try:
                self.load_devices()
            except Exception as err:  # noqa: BLE001 - keep polling alive
                _LOGGER.warning(
                    "Zone configuration refresh failed; keeping the previous "
                    "one: %s",
                    err,
                )
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
        if self.bypass_manager is not None:
            await self.bypass_manager.async_on_data_refreshed()

    async def _async_arm(
        self, arm_command, sub_id: int | None, mode: str, with_bypass: bool = False
    ) -> None:
        """Run the pre-arm bypass flow, then send the arm command."""
        manager = self.bypass_manager
        if manager is None:
            is_success = await self.hass.async_add_executor_job(arm_command, sub_id)
        else:
            if manager.arm_lock.locked():
                raise HomeAssistantError(
                    "Another arming or bypass operation is already in progress",
                    translation_domain=DOMAIN,
                    translation_key="arming_in_progress",
                )
            async with manager.arm_lock:
                await manager.async_prepare_arming(sub_id, mode, with_bypass)
                is_success = await self.hass.async_add_executor_job(
                    arm_command, sub_id
                )

        if not is_success:
            raise HomeAssistantError(
                "The panel refused the arm command",
                translation_domain=DOMAIN,
                translation_key="arm_refused",
            )
        await self._async_update_data()
        await self.async_request_refresh()

    def _arm_vacation(self, sub_id: int | None):
        """Send the vacation arm command (not exposed by hikaxpro)."""
        sid = "0xffffffff" if sub_id is None else str(sub_id)
        endpoint = self.axpro.build_url(
            f"http://{self.host}/ISAPI/SecurityCP/control/arm/{sid}?ways=vacation",
            True,
        )
        response = self.axpro.make_request(endpoint, "PUT", None, True)
        if response.status_code != 200:
            raise hikaxpro.errors.UnexpectedResponseCodeError(
                response.status_code, response.text
            )
        return bool(response.json())

    async def async_arm_home(self, sub_id: int | None = None, with_bypass: bool = False):
        """Arm alarm panel in home state.

        ``with_bypass`` runs the pre-arm bypass flow even when home
        arming is not in the auto-bypass modes.
        """
        await self._async_arm(self.axpro.arm_home, sub_id, ARM_MODE_HOME, with_bypass)

    async def async_arm_away(self, sub_id: int | None = None, with_bypass: bool = False):
        """Arm alarm panel in away state.

        ``with_bypass`` runs the pre-arm bypass flow even when away
        arming is not in the auto-bypass modes.
        """
        await self._async_arm(self.axpro.arm_away, sub_id, ARM_MODE_AWAY, with_bypass)

    async def async_arm_vacation(self, sub_id: int | None = None):
        """Arm alarm panel in vacation state."""
        await self._async_arm(self._arm_vacation, sub_id, ARM_MODE_VACATION)

    async def async_disarm(self, sub_id: int | None = None):
        """Disarm alarm control panel."""
        is_success = await self.hass.async_add_executor_job(self.axpro.disarm, sub_id)

        if not is_success:
            raise HomeAssistantError(
                "The panel refused the disarm command",
                translation_domain=DOMAIN,
                translation_key="disarm_refused",
            )
        if self.bypass_manager is not None:
            await self.bypass_manager.async_on_disarm(sub_id)
        await self._async_update_data()
        await self.async_request_refresh()

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

    def _siren_call(self, siren_id: int, is_enabled: bool) -> JSONResponseStatus:
        endpoint = self.axpro.build_url(
            f"http://{self.host}/ISAPI/SecurityCP/control/siren/{siren_id}",
            True,
        )
        response = self.axpro.make_request(
            endpoint,
            "PUT",
            {"SirenCtrl": {"switch": "open" if is_enabled else "close"}},
            True,
        )
        if response.status_code != 200:
            raise hikaxpro.errors.UnexpectedResponseCodeError(
                response.status_code, response.text
            )
        _LOGGER.debug(response.text)
        return JSONResponseStatus.from_dict(response.json())

    async def siren_on(self, siren_id: int) -> bool:
        """Turn on / open a siren by ID."""
        try:
            response: JSONResponseStatus = await self.hass.async_add_executor_job(
                self._siren_call, siren_id, True
            )
            ok = response.status_code == 1
            if ok:
                self.siren_control_supported[siren_id] = True
            return ok
        except hikaxpro.errors.UnexpectedResponseCodeError as err:
            if "notSupport" in str(err):
                self.siren_control_supported[siren_id] = False
                _LOGGER.warning(
                    "Siren %s control not supported by this panel/device", siren_id
                )
                return False
            raise

    async def siren_off(self, siren_id: int) -> bool:
        """Turn off / close a siren by ID."""
        try:
            response: JSONResponseStatus = await self.hass.async_add_executor_job(
                self._siren_call, siren_id, False
            )
            ok = response.status_code == 1
            if ok:
                self.siren_control_supported[siren_id] = True
            return ok
        except hikaxpro.errors.UnexpectedResponseCodeError as err:
            if "notSupport" in str(err):
                self.siren_control_supported[siren_id] = False
                _LOGGER.warning(
                    "Siren %s control not supported by this panel/device", siren_id
                )
                return False
            raise

    def _one_key_alarm_call(self, is_enabled: bool) -> JSONResponseStatus:
        """PUT /ISAPI/SecurityCP/control/oneKeyAlarm with OneKeyAlarm.switch."""
        endpoint = self.axpro.build_url(
            f"http://{self.host}/ISAPI/SecurityCP/control/oneKeyAlarm",
            True,
        )
        response = self.axpro.make_request(
            endpoint,
            "PUT",
            {"OneKeyAlarm": {"switch": "open" if is_enabled else "close"}},
            True,
        )
        if response.status_code != 200:
            raise hikaxpro.errors.UnexpectedResponseCodeError(
                response.status_code, response.text
            )
        _LOGGER.debug(response.text)
        return JSONResponseStatus.from_dict(response.json())

    async def one_key_alarm_on(self) -> bool:
        """Trigger panel one-key / panic alarm when supported."""
        if self.one_key_alarm_supported is False:
            _LOGGER.warning("One-key alarm not supported by this panel")
            return False
        response: JSONResponseStatus = await self.hass.async_add_executor_job(
            self._one_key_alarm_call, True
        )
        ok = response.status_code == 1
        if ok:
            self.one_key_alarm_supported = True
        return ok

    async def one_key_alarm_off(self) -> bool:
        """Clear / close one-key alarm when supported."""
        if self.one_key_alarm_supported is False:
            _LOGGER.warning("One-key alarm not supported by this panel")
            return False
        response: JSONResponseStatus = await self.hass.async_add_executor_job(
            self._one_key_alarm_call, False
        )
        ok = response.status_code == 1
        if ok:
            self.one_key_alarm_supported = True
        return ok
