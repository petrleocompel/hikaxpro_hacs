"""Persistent storage for the zone bypass feature.

Tracks the bypasses this integration applied itself, so they can be
recognised, reconciled and removed again across Home Assistant
restarts. Which zones *may* be bypassed is configuration, not state, and
lives in the config entry instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
SAVE_DELAY = 1.0


@dataclass
class OwnedBypass:
    """A bypass applied by this integration."""

    applied_at: datetime
    reason: str
    area: int | None = None
    arm_flow_id: str | None = None
    pending_unbypass: bool = False

    def as_dict(self) -> dict:
        """Serialize for storage."""
        return {
            "applied_at": self.applied_at.isoformat(),
            "reason": self.reason,
            "area": self.area,
            "arm_flow_id": self.arm_flow_id,
            "pending_unbypass": self.pending_unbypass,
        }

    @classmethod
    def from_dict(cls, data: dict) -> OwnedBypass:
        """Deserialize from storage."""
        applied_at = dt_util.parse_datetime(data.get("applied_at") or "")
        return cls(
            applied_at=applied_at or dt_util.utcnow(),
            reason=data.get("reason", "unknown"),
            area=data.get("area"),
            arm_flow_id=data.get("arm_flow_id"),
            pending_unbypass=bool(data.get("pending_unbypass", False)),
        )


@dataclass
class BypassData:
    """In-memory view of the stored bypass state."""

    owned_bypasses: dict[int, OwnedBypass] = field(default_factory=dict)
    last_auto_bypass: datetime | None = None


class BypassStore:
    """Typed wrapper over a Home Assistant Store."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the store for a config entry."""
        self._store: Store = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{entry_id}.bypass",
        )
        self.data = BypassData()

    async def async_load(self) -> None:
        """Load stored data, starting fresh if it cannot be read.

        Everything kept here is recoverable: the owned bypasses are
        re-derived by the reconciliation on the next poll. A missing,
        corrupt, or newer-than-expected file is therefore not worth
        failing the setup over.
        """
        try:
            raw = await self._store.async_load()
            if not raw:
                return
            self.data.owned_bypasses = {
                int(zone_id): OwnedBypass.from_dict(owned)
                for zone_id, owned in (raw.get("owned_bypasses") or {}).items()
            }
            last = raw.get("last_auto_bypass")
            self.data.last_auto_bypass = dt_util.parse_datetime(last) if last else None
        except Exception as err:  # noqa: BLE001 - never block setup on state
            _LOGGER.warning("Discarding unreadable bypass storage: %s", err)
            self.data = BypassData()

    def _as_dict(self) -> dict:
        return {
            "owned_bypasses": {
                str(zone_id): owned.as_dict()
                for zone_id, owned in self.data.owned_bypasses.items()
            },
            "last_auto_bypass": self.data.last_auto_bypass.isoformat()
            if self.data.last_auto_bypass
            else None,
        }

    async def async_save(self) -> None:
        """Save immediately (used as write-ahead before bypass commands)."""
        await self._store.async_save(self._as_dict())

    def async_delay_save(self) -> None:
        """Schedule a delayed save for non-critical mutations."""
        self._store.async_delay_save(self._as_dict, SAVE_DELAY)
