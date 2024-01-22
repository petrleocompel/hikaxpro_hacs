"""Constants for the hikvision_axpro integration."""

from typing import Final

DOMAIN: Final[str] = "hikvision_axpro"

DATA_COORDINATOR: Final[str] = "hikaxpro"

USE_CODE_ARMING: Final[str] = "use_code_arming"

ALLOW_SUBSYSTEMS: Final[str] = "allow_subsystems"

INTERNAL_API: Final[str] = "internal_api"

ENABLE_DEBUG_OUTPUT: Final[str] = "debug"


# Sensor entity description constants
ENTITY_DESC_KEY_BATTERY: Final[str] = "battery"
ENTITY_DESC_KEY_MAGNET_PRESENCE: Final[str] = "magnet_presence"
ENTITY_DESC_KEY_MAGNET_SHOCK: Final[str] = "magnet_shock"
ENTITY_DESC_KEY_MAGNET_TILT: Final[str] = "magnet_tilt"
ENTITY_DESC_KEY_SIGNAL_STRENGTH: Final[str] = "signal_strength"
ENTITY_DESC_KEY_HUMIDITY: Final[str] = "humidity"
ENTITY_DESC_KEY_TEMPERATURE: Final[str] = "temperature"
