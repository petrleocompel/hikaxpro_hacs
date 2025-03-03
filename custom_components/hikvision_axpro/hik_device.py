"""Hik device as base for all sensors from HikVision.

Understands zone and custom refID
"""

from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN
from .model import Zone


class HikDevice:
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
