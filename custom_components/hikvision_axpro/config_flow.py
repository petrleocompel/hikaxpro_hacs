"""Config flow for hikvision_axpro integration."""
import logging
from typing import Any

import voluptuous as vol

import hikaxpro

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.const import (
    CONF_CODE,
    CONF_ENABLED,
    ATTR_CODE_FORMAT,
    CONF_HOST,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
)
from homeassistant.components.alarm_control_panel import SCAN_INTERVAL
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    ALLOW_SUBSYSTEMS,
    ARM_MODES,
    DATA_BYPASS_MANAGER,
    CONF_AUTO_BYPASS_MODES,
    CONF_BYPASS_REENABLE_DEBOUNCE,
    CONF_CLEAR_ALL_ON_DISARM,
    DEFAULT_BYPASS_REENABLE_DEBOUNCE,
    DOMAIN,
    ENABLE_DEBUG_OUTPUT,
    USE_CODE_ARMING,
    conf_bypassable_zones,
    zone_id_from_bypass_unique_id,
)

_LOGGER = logging.getLogger(__name__)

AUTO_BYPASS_MODES_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=ARM_MODES,
        multiple=True,
        mode=SelectSelectorMode.LIST,
        translation_key="auto_bypass_modes",
    )
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_ENABLED, default=False): bool,
        vol.Optional(ATTR_CODE_FORMAT, default="NUMBER"): vol.In(["TEXT", "NUMBER"]),
        vol.Optional(CONF_CODE, default=""): str,
        vol.Optional(USE_CODE_ARMING, default=False): bool,
        vol.Required(CONF_SCAN_INTERVAL, default=SCAN_INTERVAL.total_seconds()): int,
        vol.Optional(ALLOW_SUBSYSTEMS, default=False): bool,
        vol.Optional(CONF_AUTO_BYPASS_MODES, default=[]): AUTO_BYPASS_MODES_SELECTOR,
        vol.Optional(
            CONF_BYPASS_REENABLE_DEBOUNCE, default=DEFAULT_BYPASS_REENABLE_DEBOUNCE
        ): vol.All(int, vol.Range(min=0, max=300)),
        vol.Optional(CONF_CLEAR_ALL_ON_DISARM, default=False): bool,
    }
)


CONFIGURE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_ENABLED, default=False): bool,
        vol.Optional(ATTR_CODE_FORMAT, default="NUMBER"): vol.In(["TEXT", "NUMBER"]),
        vol.Optional(CONF_CODE, default=""): str,
        vol.Optional(USE_CODE_ARMING, default=False): bool,
        vol.Required(CONF_SCAN_INTERVAL, default=SCAN_INTERVAL.total_seconds()): int,
        vol.Optional(ALLOW_SUBSYSTEMS, default=False): bool,
        vol.Optional(CONF_AUTO_BYPASS_MODES, default=[]): AUTO_BYPASS_MODES_SELECTOR,
        vol.Optional(
            CONF_BYPASS_REENABLE_DEBOUNCE, default=DEFAULT_BYPASS_REENABLE_DEBOUNCE
        ): vol.All(int, vol.Range(min=0, max=300)),
        vol.Optional(CONF_CLEAR_ALL_ON_DISARM, default=False): bool,
        vol.Optional(ENABLE_DEBUG_OUTPUT, default=False): bool,
    }
)


def schema_defaults(schema, dps_list=None, **defaults):
    """Create a new schema with default values filled in."""
    copy = schema.extend({})
    for field, field_type in copy.schema.items():
        if isinstance(field_type, vol.In):
            value = None
            for dps in dps_list or []:
                if dps.startswith(f"{defaults.get(field)} "):
                    value = dps
                    break

            if value in field_type.container:
                field.default = vol.default_factory(value)
                continue

        if field.schema in defaults:
            field.default = vol.default_factory(defaults[field])
    return copy


class AxProHub:
    """Helper class for validation and setup ops."""

    def __init__(
        self, host: str, username: str, password: str, hass: HomeAssistant
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.axpro = hikaxpro.HikAxPro(host, username, password)
        self.hass = hass

    async def authenticate(self) -> bool:
        """Check the provided credentials by connecting to ax pro."""
        is_connect_success = await self.hass.async_add_executor_job(self.axpro.connect)
        return is_connect_success


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """

    if data[CONF_ENABLED]:
        if data[ATTR_CODE_FORMAT] is None or (
            data[ATTR_CODE_FORMAT] != "NUMBER" and data[ATTR_CODE_FORMAT] != "TEXT"
        ):
            raise InvalidCodeFormat

        if (
            data[CONF_CODE] is None
            or data[CONF_CODE] == ""
            or (data[ATTR_CODE_FORMAT] == "NUMBER" and not str.isdigit(data[CONF_CODE]))
        ):
            raise InvalidCode


    hub = AxProHub(data[CONF_HOST], data[CONF_USERNAME], data[CONF_PASSWORD], hass)

    if data.get(ENABLE_DEBUG_OUTPUT):
        try:
            hub.axpro.set_logging_level(logging.DEBUG)
        except:
            pass


    if not await hub.authenticate():
        raise InvalidAuth

    return {"title": f"Hikvision_axpro_{data['host']}"}


class AxProConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for hikvision_axpro."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get options flow for this handler."""
        return AxProOptionsFlowHandler()

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}

        try:
            info = await validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except InvalidCodeFormat:
            errors["base"] = "invalid_code_format"
        except InvalidCode:
            errors["base"] = "invalid_code"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class AxProOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for AxPro integration."""

    def __init__(self):
        """Initialize AxPro options flow."""
        self._pending: dict[str, Any] = {}
        self._title: str = ""

    def _zone_bypass_entities(self) -> dict[str, int]:
        """Map this panel's bypassable zone entities to their zone id.

        Only entities belonging to this config entry are offered, so the
        picker can never reach another panel's zones, and only zones the
        panel would actually let us bypass on arming: a zone whose type
        is not eligible, or whose "forbid bypass on arming" setting is
        on, is left out rather than offered and then silently ignored.
        """
        registry = er.async_get(self.hass)
        manager = (
            self.hass.data.get(DOMAIN, {})
            .get(self.config_entry.entry_id, {})
            .get(DATA_BYPASS_MANAGER)
        )
        entities: dict[str, int] = {}
        for reg_entry in er.async_entries_for_config_entry(
            registry, self.config_entry.entry_id
        ):
            zone_id = zone_id_from_bypass_unique_id(reg_entry.unique_id)
            if zone_id is None:
                continue
            if manager is not None and not manager.zone_bypass_allowed(zone_id):
                continue
            entities[reg_entry.entity_id] = zone_id
        return entities

    def _bypass_zones_schema(self, modes: list[str]) -> vol.Schema:
        """One entity multiselect per arming mode with auto-bypass on."""
        available = self._zone_bypass_entities()
        by_zone = {zone_id: entity_id for entity_id, zone_id in available.items()}
        selector = EntitySelector(
            EntitySelectorConfig(
                multiple=True,
                include_entities=sorted(available),
            )
        )
        fields: dict[Any, Any] = {}
        for mode in ARM_MODES:
            if mode not in modes:
                continue
            key = conf_bypassable_zones(mode)
            # Stored as zone ids so a renamed entity never loses its
            # configuration; shown as the entities they belong to.
            current = [
                by_zone[zone_id]
                for zone_id in self.config_entry.data.get(key) or []
                if zone_id in by_zone
            ]
            fields[vol.Optional(key, default=current)] = selector
        return vol.Schema(fields)

    async def async_step_bypass_zones(self, user_input=None):
        """Pick which zones the auto-bypass may bypass, per arming mode."""
        modes = [
            mode
            for mode in ARM_MODES
            if mode in (self._pending.get(CONF_AUTO_BYPASS_MODES) or [])
        ]

        if user_input is None:
            return self.async_show_form(
                step_id="bypass_zones",
                data_schema=self._bypass_zones_schema(modes),
                last_step=True,
            )

        available = self._zone_bypass_entities()
        data = dict(self._pending)
        for mode in ARM_MODES:
            key = conf_bypassable_zones(mode)
            if mode not in modes:
                # Auto-bypass is off for this mode: forget its selection
                # rather than keeping a hidden one that would come back.
                data.pop(key, None)
                continue
            data[key] = sorted(
                {
                    available[entity_id]
                    for entity_id in user_input.get(key) or []
                    if entity_id in available
                }
            )
        return self._save(data)

    def _save(self, data: dict[str, Any]):
        """Persist the collected options onto the config entry."""
        _LOGGER.debug("Saving options %s %s", self._title, data)
        self.hass.config_entries.async_update_entry(self.config_entry, data=data)
        return self.async_create_entry(title=self._title, data=data)

    def _zone_step_follows(self, defaults: dict[str, Any]) -> bool:
        """Whether submitting the first page opens the zone picker.

        Drives the button label: Home Assistant renders "Next" instead
        of "Submit" when the form says it is not the last step.
        """
        return bool(defaults.get(CONF_AUTO_BYPASS_MODES))

    async def async_step_init(self, user_input=None):
        """Manage basic options."""
        defaults = self.config_entry.data.copy()
        defaults.update(user_input or {})

        if user_input is None:
            return self.async_show_form(
                step_id="init",
                data_schema=schema_defaults(CONFIGURE_SCHEMA, **defaults),
                last_step=not self._zone_step_follows(defaults),
            )
        errors = {}

        try:
            info = await validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except InvalidCodeFormat:
            errors["base"] = "invalid_code_format"
        except InvalidCode:
            errors["base"] = "invalid_code"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            # Carry over settings the form does not expose (the stored
            # bypassable zone ids), then let the next step revise them.
            data = {**self.config_entry.data, **user_input}
            self._pending = data
            self._title = info["title"]
            if user_input.get(CONF_AUTO_BYPASS_MODES):
                return await self.async_step_bypass_zones()
            for mode in ARM_MODES:
                data.pop(conf_bypassable_zones(mode), None)
            return self._save(data)

        return self.async_show_form(
            step_id="init",
            data_schema=schema_defaults(CONFIGURE_SCHEMA, None, **defaults),
            last_step=not self._zone_step_follows(defaults),
            errors=errors
        )



class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class InvalidCodeFormat(HomeAssistantError):
    """Error to indicate code format is wrong."""


class InvalidCode(HomeAssistantError):
    """Error to indicate the code is in wrong format"""
