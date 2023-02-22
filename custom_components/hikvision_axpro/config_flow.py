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

from .const import DOMAIN, USE_CODE_ARMING

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_ENABLED, default=False): bool,
        vol.Optional(ATTR_CODE_FORMAT, default="NUMBER"): vol.In(["TEXT", "NUMBER"]),
        vol.Optional(CONF_CODE, default=""): str,
        vol.Optional(USE_CODE_ARMING, default=False): bool,
        vol.Required(CONF_SCAN_INTERVAL, default=SCAN_INTERVAL.total_seconds()): int
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
        vol.Required(CONF_SCAN_INTERVAL, default=SCAN_INTERVAL.total_seconds()): int
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
        return AxProOptionsFlowHandler(config_entry)

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

    def __init__(self, config_entry):
        """Initialize AxPro options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage basic options."""
        defaults = self.config_entry.data.copy()
        defaults.update(user_input or {})

        if user_input is None:
            return self.async_show_form(
                step_id="init",
                data_schema=schema_defaults(CONFIGURE_SCHEMA, **defaults),
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
            _LOGGER.debug("Saving options %s %s",info["title"], user_input)

            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=user_input,
            )
            return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=schema_defaults(CONFIGURE_SCHEMA, None, **defaults),
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
