"""Hik device as base for all sensors from HikVision.

Understands zone and custom refID
"""

from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN
from .entity_id import build_entity_id
from .model import Zone


class HikDevice():
    """Hik device as base for all sensors from HikVision.

    Understands zone and custom refID
    """

    zone: Zone
    _ref_id: str

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, str(self._ref_id) + "-" + str(self.zone.id))},
            manufacturer="HikVision" if self.zone.model is not None else "Unknown",
            # suggested_area=zone.zone.,
            name=self.zone.name,
            # model="Unknown" if self.zone.model is not "0x00001" else self.zone.model,
            sw_version=self.zone.version,
        )

    @property
    def _object_id_device_name(self) -> str | None:
        """Device name to strip, falling back to the zone name.

        The registry device entry is only available once the entity has
        been added; before that the zone name is the device name this
        integration asks Home Assistant to create.
        """
        return super()._object_id_device_name or self.zone.name
