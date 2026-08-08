"""Zone bypass policy for the hikvision_axpro integration.

Implements the auto-bypass-on-arming flow (per arming mode), ownership
tracking of integration-applied bypasses, automatic re-enable on
recovery, cleanup on disarm and reconciliation with panel state. The
ISAPI primitives live in ``isapi_bypass.py``; this module is pure
policy.
"""

from __future__ import annotations

from asyncio import Lock, timeout
from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .const import (
    ARM_MODE_AWAY,
    ARM_MODE_HOME,
    ARM_MODES,
    CONF_AUTO_BYPASS_MODES,
    CONF_BYPASS_REENABLE_DEBOUNCE,
    CONF_CLEAR_ALL_ON_DISARM,
    DEFAULT_BYPASS_REENABLE_DEBOUNCE,
    DOMAIN,
    EVENT_ARMING_BLOCKED,
    EVENT_BYPASS_APPLIED,
    EVENT_BYPASS_REMOVED,
    conf_bypassable_zones,
)
from .bypass_store import BypassStore, OwnedBypass
from .isapi_bypass import AxProBypassClient, BypassError
from .model import Arming, Status, Zone, ZoneType, ZonesResponse

if TYPE_CHECKING:
    from . import HikAxProDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Zone types eligible for auto-bypass. Only instant zones: the panel
# itself offers the "forbid bypass on arming" option exclusively for
# them, so every other type (delay, perimeter, follow, 24h, fire, gas,
# medical, emergency, key, non-alarm) is never bypassed automatically.
AUTO_BYPASS_ALLOWED_ZONE_TYPES = frozenset({ZoneType.INSTANT})

# Reconciliation grace period: an owned bypass applied more recently than
# this may legitimately not appear in the current poll snapshot yet.
RECONCILE_GRACE_SECONDS = 15

FRESH_READ_TIMEOUT = 10

FAULT_OPEN = "open"
FAULT_OFFLINE = "offline"
FAULT_TAMPER = "tamper"

REASON_AUTO_ARM = "auto_arm"
REASON_SERVICE = "service"
REASON_HEALTH_RECOVERED = "health_recovered"
REASON_DISARM = "disarm"
REASON_ROLLBACK = "rollback"
REASON_RECONCILED = "reconciled"


class ArmingBlockedError(HomeAssistantError):
    """Arming was aborted by the pre-arm bypass logic."""

    def __init__(self, message: str, zones: str = "") -> None:
        """Store a translated, zone-listing error."""
        full_message = f"{message}: {zones}" if zones else message
        super().__init__(
            full_message,
            translation_domain=DOMAIN,
            translation_key="arming_blocked",
            translation_placeholders={"reason": message, "zones": zones},
        )


def zone_fault_reason(zone: Zone) -> str | None:
    """Return why a zone is in fault, or None if healthy.

    A zone is faulted when triggered/open, offline or tampered. Low
    battery is deliberately a warning only: it neither blocks arming nor
    causes a bypass.
    """
    if zone.status == Status.NOT_RELATED:
        return None
    if zone.tamper_evident:
        return FAULT_TAMPER
    if zone.status in (Status.OFFLINE, Status.BREAK_DOWN, Status.HEART_BEAT_ABNORMAL):
        return FAULT_OFFLINE
    if zone.alarm or zone.status == Status.TRIGGER or zone.magnet_open_status:
        return FAULT_OPEN
    if zone.charge == "lowPower":
        _LOGGER.warning(
            "Zone %s (%s) reports low battery; not blocking arming", zone.id, zone.name
        )
    return None


def is_auto_bypass_eligible(zone: Zone) -> bool:
    """Return True if the zone type may be auto-bypassed."""
    return zone.zone_type in AUTO_BYPASS_ALLOWED_ZONE_TYPES


def zone_in_area(zone: Zone, sub_id: int | None) -> bool:
    """Return True if the zone belongs to the given area."""
    if sub_id is None:
        return True
    if zone.sub_system_no is not None:
        return zone.sub_system_no == sub_id
    return bool(zone.linkage_sub_system and sub_id in zone.linkage_sub_system)


def _zone_issue(zone: Zone, fault: str) -> dict[str, Any]:
    return {
        "zone_id": zone.id,
        "zone_name": zone.name,
        "area": zone.sub_system_no,
        "fault": fault,
    }


@dataclass
class ReadinessResult:
    """Outcome of the arm readiness evaluation."""

    blocking_zones: list[dict[str, Any]] = field(default_factory=list)
    zones_to_bypass: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        """True when no non-bypassable zone is in fault."""
        return not self.blocking_zones

    @property
    def per_area(self) -> dict[int, dict[str, Any]]:
        """Per-area breakdown for multi-partition systems."""
        areas: dict[int, dict[str, Any]] = {}

        def bucket(area: int | None) -> dict[str, Any]:
            key = area if area is not None else 0
            return areas.setdefault(
                key, {"ready": True, "blocking_zones": [], "zones_to_bypass": []}
            )

        for issue in self.blocking_zones:
            entry = bucket(issue["area"])
            entry["blocking_zones"].append(issue)
            entry["ready"] = False
        for issue in self.zones_to_bypass:
            bucket(issue["area"])["zones_to_bypass"].append(issue)
        return areas


def evaluate_arm_readiness(
    zones: list[Zone], bypassable_ids: set[int], mode: str = ARM_MODE_AWAY
) -> ReadinessResult:
    """Evaluate whether arming in ``mode`` would succeed.

    Single source of truth. Faulted zones split into
    ``zones_to_bypass`` (marked bypassable and of an eligible type) and
    ``blocking_zones`` (everything else). Already-bypassed zones are
    skipped and never touched. In home (stay) mode, zones the panel
    itself bypasses on stay arming (``stayAway``) are ignored.
    """
    result = ReadinessResult()
    for zone in zones:
        if zone.bypassed:
            continue
        if mode == ARM_MODE_HOME and zone.stay_away:
            continue
        fault = zone_fault_reason(zone)
        if fault is None:
            continue
        if zone.id in bypassable_ids and is_auto_bypass_eligible(zone):
            result.zones_to_bypass.append(_zone_issue(zone, fault))
        else:
            result.blocking_zones.append(_zone_issue(zone, fault))
    return result


class BypassManager:
    """Coordinates bypass policy for one panel (config entry)."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: HikAxProDataUpdateCoordinator,
        client: AxProBypassClient,
        store: BypassStore,
    ) -> None:
        """Initialize the manager."""
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.client = client
        self.store = store
        self.bypass_supported = True
        self.arm_lock = Lock()
        self._healthy_since: dict[int, datetime] = {}
        self._reenable_unsub: dict[int, CALLBACK_TYPE] = {}
        self._last_arming: dict[int, Arming | None] = {}
        self._reported_ineffective: dict[str, set[int]] = {}

    # ------------------------------------------------------------------
    # Configuration views

    @property
    def auto_bypass_modes(self) -> set[str]:
        """Arming modes for which the auto-bypass logic is enabled."""
        modes = self.entry.data.get(CONF_AUTO_BYPASS_MODES) or []
        return {mode for mode in modes if mode in ARM_MODES}

    def _configured_bypassable(self, mode: str) -> set[int]:
        """Zone ids the user picked for one mode, ungated.

        The configuration lives in the config entry: it is chosen once in
        the integration options rather than per zone, so it survives a
        zone going offline and never depends on entity state.
        """
        if mode not in ARM_MODES:
            mode = ARM_MODE_AWAY
        configured = self.entry.data.get(conf_bypassable_zones(mode)) or []
        ids: set[int] = set()
        for zone_id in configured:
            try:
                ids.add(int(zone_id))
            except (TypeError, ValueError):
                _LOGGER.warning(
                    "Ignoring unusable bypassable zone %r configured for %s arming",
                    zone_id,
                    mode,
                )
        return ids

    def zone_bypass_allowed(self, zone_id: int) -> bool:
        """Whether panel config and zone type allow bypassing this zone.

        The panel-side "forbid bypass on arming" setting and the zone
        type always win over the HA-side configuration.
        """
        if self.zone_forbids_bypass(zone_id):
            return False
        zone = (self.coordinator.zones or {}).get(zone_id)
        return zone is None or is_auto_bypass_eligible(zone)

    def bypassable_zone_ids(self, mode: str, force: bool = False) -> set[int]:
        """Effective bypassable zone ids for one arming mode.

        ``force`` ignores the per-mode auto-bypass switch, for the
        explicit ``arm_*_with_bypass`` services: the user asked for the
        bypass on this call, so only the panel-side restrictions apply.
        """
        if not force and mode not in self.auto_bypass_modes:
            return set()
        return {
            zone_id
            for zone_id in self._configured_bypassable(mode)
            if self.zone_bypass_allowed(zone_id)
        }

    @property
    def debounce_seconds(self) -> int:
        """How long a zone must stay healthy before re-enable."""
        return int(
            self.entry.data.get(
                CONF_BYPASS_REENABLE_DEBOUNCE, DEFAULT_BYPASS_REENABLE_DEBOUNCE
            )
        )

    @property
    def clear_all_on_disarm(self) -> bool:
        """Whether disarm cleanup extends to all bypasses."""
        return bool(self.entry.data.get(CONF_CLEAR_ALL_ON_DISARM, False))

    def is_bypassable(self, zone_id: int, mode: str = ARM_MODE_AWAY) -> bool:
        """Whether the zone may actually be auto-bypassed in one mode.

        False when the mode itself has auto-bypass switched off, when the
        zone was not picked for that mode, or when the panel forbids it.
        """
        return zone_id in self.bypassable_zone_ids(mode)

    def is_configured_bypassable(
        self, zone_id: int, mode: str = ARM_MODE_AWAY
    ) -> bool:
        """Whether the user picked the zone for one mode, ignoring gating."""
        return zone_id in self._configured_bypassable(mode)

    def zone_forbids_bypass(self, zone_id: int) -> bool:
        """Whether the panel config forbids bypassing this zone on arming.

        The panel-side "forbid bypass on arming" (``armNoBypassEnabled``)
        zone setting always wins over the HA-side bypassable flag: the
        flag is kept off and its switch is not editable.
        """
        config = (self.coordinator.devices or {}).get(zone_id)
        return config is not None and bool(config.arm_no_bypass_enabled)

    def async_report_ineffective_config(self) -> None:
        """Warn about configured zones the panel will not let us bypass.

        The configuration is the user's, so it is never rewritten behind
        their back: a zone the panel forbids simply has no effect, and
        the reason is logged once per polling cycle change.
        """
        ineffective: dict[str, set[int]] = {}
        for mode in self.auto_bypass_modes:
            blocked = {
                zone_id
                for zone_id in self._configured_bypassable(mode)
                if not self.zone_bypass_allowed(zone_id)
            }
            if blocked:
                ineffective[mode] = blocked
        if ineffective == self._reported_ineffective:
            return
        self._reported_ineffective = ineffective
        for mode, blocked in ineffective.items():
            _LOGGER.warning(
                "Zones %s are configured as bypassable on %s arming but the "
                "panel config or their zone type forbids bypassing them; "
                "they will be treated as blocking",
                sorted(blocked),
                mode,
            )

    # ------------------------------------------------------------------
    # State views for entities

    def current_readiness(self, mode: str = ARM_MODE_AWAY) -> ReadinessResult:
        """Readiness for the given mode computed from the latest poll."""
        zones = list((self.coordinator.zones or {}).values())
        bypassable = self.bypassable_zone_ids(mode)
        return evaluate_arm_readiness(zones, bypassable, mode)

    def owns_zone(self, zone_id: int) -> bool:
        """Whether the current bypass of the zone was applied by us."""
        return zone_id in self.store.data.owned_bypasses

    def bypass_reason(self, zone_id: int) -> str | None:
        """Reason of the owned bypass on a zone, if any."""
        owned = self.store.data.owned_bypasses.get(zone_id)
        return owned.reason if owned else None

    def diagnostics(self, sub_id: int | None = None) -> dict[str, Any]:
        """Diagnostic attributes for the alarm panel    ."""
        zones = (self.coordinator.zones or {}).values()
        bypassed = [
            {"zone_id": zone.id, "zone_name": zone.name, "area": zone.sub_system_no}
            for zone in zones
            if zone.bypassed and zone_in_area(zone, sub_id)
        ]
        owned = {
            zone_id: {
                "reason": rec.reason,
                "applied_at": rec.applied_at.isoformat(),
                "pending_unbypass": rec.pending_unbypass,
                "healthy_since": self._healthy_since[zone_id].isoformat()
                if zone_id in self._healthy_since
                else None,
            }
            for zone_id, rec in self.store.data.owned_bypasses.items()
            if sub_id is None or rec.area in (None, sub_id)
        }
        return {
            "bypassed_zones": bypassed,
            "owned_bypasses": owned,
            "last_auto_bypass": self.store.data.last_auto_bypass.isoformat()
            if self.store.data.last_auto_bypass
            else None,
        }

    # ------------------------------------------------------------------
    # Arming flow

    async def async_prepare_arming(
        self, sub_id: int | None, mode: str, force: bool = False
    ) -> None:
        """Run the pre-arm bypass flow; raise ArmingBlockedError to abort.

        Must be called while holding ``arm_lock``. No-op when the
        auto-bypass option is disabled for the requested mode, unless
        ``force`` is set by an explicit arm-with-bypass service call.
        """
        if not force and mode not in self.auto_bypass_modes:
            return
        if not self.bypass_supported:
            _LOGGER.debug("Bypass unsupported by firmware; skipping pre-arm flow")
            return

        zones = await self._async_fresh_zones()
        area_zones = [zone for zone in zones if zone_in_area(zone, sub_id)]
        result = evaluate_arm_readiness(
            area_zones, self.bypassable_zone_ids(mode, force), mode
        )

        if result.blocking_zones:
            self._fire_arming_blocked(sub_id, result.blocking_zones, [])
            raise ArmingBlockedError(
                "Arming blocked by faulted non-bypassable zones",
                zones=self._zone_list_str(result.blocking_zones),
            )

        arm_flow_id = uuid4().hex[:8]
        applied: list[dict[str, Any]] = []
        for issue in result.zones_to_bypass:
            zone_id: int = issue["zone_id"]
            # Write-ahead: persist ownership before the command so a crash
            # can only leave a tracked-but-unapplied entry, which the
            # reconciliation drops silently.
            self.store.data.owned_bypasses[zone_id] = OwnedBypass(
                applied_at=dt_util.utcnow(),
                reason=REASON_AUTO_ARM,
                area=issue["area"] if sub_id is None else sub_id,
                arm_flow_id=arm_flow_id,
            )
            await self.store.async_save()
            try:
                await self.hass.async_add_executor_job(self.client.bypass, zone_id)
            except BypassError as err:
                _LOGGER.error("Bypass of zone %s failed: %s", zone_id, err)
                self.store.data.owned_bypasses.pop(zone_id, None)
                await self._async_rollback(applied)
                failed = [dict(issue, error=str(err))]
                self._fire_arming_blocked(sub_id, [], failed)
                raise ArmingBlockedError(
                    f"Bypass of zone {issue['zone_name']} failed",
                    zones=str(issue["zone_name"]),
                ) from err
            applied.append(issue)
            self._fire_bypass_event(EVENT_BYPASS_APPLIED, issue, REASON_AUTO_ARM)

        if applied:
            self.store.data.last_auto_bypass = dt_util.utcnow()
            await self.store.async_save()

    async def _async_rollback(self, applied: list[dict[str, Any]]) -> None:
        """Best-effort removal of bypasses applied in this flow."""
        for issue in reversed(applied):
            zone_id: int = issue["zone_id"]
            try:
                await self.hass.async_add_executor_job(self.client.unbypass, zone_id)
            except BypassError as err:
                _LOGGER.error(
                    "Rollback: could not unbypass zone %s, will retry on disarm: %s",
                    zone_id,
                    err,
                )
                owned = self.store.data.owned_bypasses.get(zone_id)
                if owned:
                    owned.pending_unbypass = True
            else:
                self.store.data.owned_bypasses.pop(zone_id, None)
                self._fire_bypass_event(EVENT_BYPASS_REMOVED, issue, REASON_ROLLBACK)
        await self.store.async_save()

    async def _async_fresh_zones(self) -> list[Zone]:
        """Synchronously read fresh zone states; abort arming on failure."""
        try:
            async with timeout(FRESH_READ_TIMEOUT):
                raw = await self.hass.async_add_executor_job(
                    self.client.fetch_zone_status
                )
            response = ZonesResponse.from_dict(raw)
        except Exception as err:
            raise ArmingBlockedError(
                f"Fresh zone state read failed: {err}"
            ) from err
        return [wrap.zone for wrap in response.zone_list]

    # ------------------------------------------------------------------
    # Services

    def _require_supported(self) -> None:
        if not self.bypass_supported:
            raise HomeAssistantError(
                "The panel firmware does not support zone bypass",
                translation_domain=DOMAIN,
                translation_key="bypass_unsupported",
            )

    async def async_bypass_zone(self, zone_id: int, reason: str = REASON_SERVICE) -> None:
        """Bypass a zone on user request; the bypass is integration-owned."""
        self._require_supported()
        async with self.arm_lock:
            self.store.data.owned_bypasses[zone_id] = OwnedBypass(
                applied_at=dt_util.utcnow(), reason=reason, area=self._zone_area(zone_id)
            )
            await self.store.async_save()
            try:
                await self.hass.async_add_executor_job(self.client.bypass, zone_id)
            except BypassError as err:
                self.store.data.owned_bypasses.pop(zone_id, None)
                await self.store.async_save()
                raise HomeAssistantError(
                    f"Bypass of zone {zone_id} failed: {err}",
                    translation_domain=DOMAIN,
                    translation_key="bypass_failed",
                    translation_placeholders={"zone": str(zone_id), "error": str(err)},
                ) from err
            self._fire_bypass_event(
                EVENT_BYPASS_APPLIED, self._issue_for(zone_id), reason
            )
        await self.coordinator.async_request_refresh()

    async def async_unbypass_zone(
        self, zone_id: int, reason: str = REASON_SERVICE
    ) -> None:
        """Restore a zone on user request."""
        self._require_supported()
        async with self.arm_lock:
            try:
                await self.hass.async_add_executor_job(self.client.unbypass, zone_id)
            except BypassError as err:
                raise HomeAssistantError(
                    f"Unbypass of zone {zone_id} failed: {err}",
                    translation_domain=DOMAIN,
                    translation_key="unbypass_failed",
                    translation_placeholders={"zone": str(zone_id), "error": str(err)},
                ) from err
            self.store.data.owned_bypasses.pop(zone_id, None)
            self._healthy_since.pop(zone_id, None)
            self._cancel_reenable(zone_id)
            await self.store.async_save()
            self._fire_bypass_event(
                EVENT_BYPASS_REMOVED, self._issue_for(zone_id), reason
            )
        await self.coordinator.async_request_refresh()

    async def async_clear_all(self, sub_id: int | None = None) -> None:
        """Remove every bypass in the area, regardless of owner."""
        self._require_supported()
        async with self.arm_lock:
            zones = await self._async_fresh_zones_or_error()
            errors: list[str] = []
            for zone in zones:
                if not zone.bypassed or not zone_in_area(zone, sub_id):
                    continue
                try:
                    await self.hass.async_add_executor_job(self.client.unbypass, zone.id)
                except BypassError as err:
                    _LOGGER.error("Could not unbypass zone %s: %s", zone.id, err)
                    errors.append(f"{zone.name}: {err}")
                    continue
                self.store.data.owned_bypasses.pop(zone.id, None)
                self._healthy_since.pop(zone.id, None)
                self._cancel_reenable(zone.id)
                self._fire_bypass_event(
                    EVENT_BYPASS_REMOVED, _zone_issue(zone, ""), REASON_SERVICE
                )
            await self.store.async_save()
            if errors:
                raise HomeAssistantError(
                    "Some bypasses could not be removed: " + "; ".join(errors)
                )
        await self.coordinator.async_request_refresh()

    async def _async_fresh_zones_or_error(self) -> list[Zone]:
        try:
            return await self._async_fresh_zones()
        except ArmingBlockedError as err:
            raise HomeAssistantError(str(err)) from err

    # ------------------------------------------------------------------
    # Lifecycle: disarm cleanup, reconciliation, recovery

    async def async_on_disarm(self, sub_id: int | None) -> None:
        """Remove owned bypasses after a disarm."""
        if not self.store.data.owned_bypasses and not self.clear_all_on_disarm:
            return
        async with self.arm_lock:
            await self._async_disarm_cleanup(sub_id)

    async def _async_disarm_cleanup(self, sub_id: int | None) -> None:
        try:
            zones = {zone.id: zone for zone in await self._async_fresh_zones()}
        except ArmingBlockedError as err:
            _LOGGER.warning("Disarm cleanup: fresh read failed, will retry: %s", err)
            return

        for zone_id in list(self.store.data.owned_bypasses):
            zone = zones.get(zone_id)
            in_area = zone is None or zone_in_area(zone, sub_id)
            if not in_area:
                continue
            if zone is None or not zone.bypassed:
                # Already removed on the panel side: reconcile silently.
                self.store.data.owned_bypasses.pop(zone_id, None)
                continue
            try:
                await self.hass.async_add_executor_job(self.client.unbypass, zone_id)
            except BypassError as err:
                _LOGGER.error(
                    "Disarm cleanup: could not unbypass zone %s: %s", zone_id, err
                )
                owned = self.store.data.owned_bypasses.get(zone_id)
                if owned:
                    owned.pending_unbypass = True
                continue
            self.store.data.owned_bypasses.pop(zone_id, None)
            self._fire_bypass_event(
                EVENT_BYPASS_REMOVED, _zone_issue(zone, ""), REASON_DISARM
            )
            self._healthy_since.pop(zone_id, None)
            self._cancel_reenable(zone_id)

        if self.clear_all_on_disarm:
            for zone in zones.values():
                if not zone.bypassed or not zone_in_area(zone, sub_id):
                    continue
                if zone.id in self.store.data.owned_bypasses:
                    continue
                try:
                    await self.hass.async_add_executor_job(self.client.unbypass, zone.id)
                except BypassError as err:
                    _LOGGER.error(
                        "Disarm cleanup (all): could not unbypass zone %s: %s",
                        zone.id,
                        err,
                    )
                    continue
                self._fire_bypass_event(
                    EVENT_BYPASS_REMOVED, _zone_issue(zone, ""), REASON_DISARM
                )
        await self.store.async_save()

    async def async_on_data_refreshed(self) -> None:
        """React to a completed polling cycle."""
        self._detect_external_disarm()
        if self.arm_lock.locked():
            return
        self.async_report_ineffective_config()
        await self._async_reconcile()
        self._observe_recovery()

    def _detect_external_disarm(self) -> None:
        """Trigger cleanup when an area was disarmed outside HA."""
        current: dict[int, Arming | None] = {
            sub_id: sub.arming for sub_id, sub in self.coordinator.sub_systems.items()
        }
        for sub_id, arming in current.items():
            previous = self._last_arming.get(sub_id)
            if (
                previous is not None
                and previous != Arming.DISARM
                and arming == Arming.DISARM
            ):
                _LOGGER.debug("Area %s disarmed externally; scheduling cleanup", sub_id)
                self.hass.async_create_task(self.async_on_disarm(sub_id))
        self._last_arming = current

    async def _async_reconcile(self) -> None:
        """Drop tracking of bypasses removed on the panel side."""
        zones = self.coordinator.zones or {}
        now = dt_util.utcnow()
        changed = False
        for zone_id in list(self.store.data.owned_bypasses):
            owned = self.store.data.owned_bypasses[zone_id]
            if (now - owned.applied_at).total_seconds() < RECONCILE_GRACE_SECONDS:
                continue
            zone = zones.get(zone_id)
            if zone is None or zone.bypassed:
                continue
            _LOGGER.info(
                "Owned bypass of zone %s was removed on the panel; updating tracking",
                zone_id,
            )
            self.store.data.owned_bypasses.pop(zone_id, None)
            self._healthy_since.pop(zone_id, None)
            self._cancel_reenable(zone_id)
            self._fire_bypass_event(
                EVENT_BYPASS_REMOVED, self._issue_for(zone_id), REASON_RECONCILED
            )
            changed = True
        if changed:
            self.store.async_delay_save()

    def _observe_recovery(self) -> None:
        """Track health of owned bypasses and schedule re-enable."""
        zones = self.coordinator.zones or {}
        now = dt_util.utcnow()
        for zone_id in list(self.store.data.owned_bypasses):
            zone = zones.get(zone_id)
            if zone is None:
                continue
            fault = zone_fault_reason(zone)
            if fault is not None:
                # Still in fault: never re-enable; reset debounce.
                if self._healthy_since.pop(zone_id, None) is not None:
                    _LOGGER.info(
                        "Bypassed zone %s (%s) went back to fault (%s); "
                        "re-enable cancelled",
                        zone_id,
                        zone.name,
                        fault,
                    )
                self._cancel_reenable(zone_id)
                continue
            if not self._zone_area_armed(zone):
                _LOGGER.debug(
                    "Bypassed zone %s healthy but its area is not armed; "
                    "leaving it to the disarm cleanup",
                    zone_id,
                )
                continue
            if zone_id not in self._healthy_since:
                self._healthy_since[zone_id] = now
                _LOGGER.info(
                    "Bypassed zone %s (%s) recovered while armed; "
                    "re-enabling in %s seconds if it stays healthy",
                    zone_id,
                    zone.name,
                    self.debounce_seconds,
                )
            since = self._healthy_since[zone_id]
            remaining = self.debounce_seconds - (now - since).total_seconds()
            if remaining <= 0:
                self._cancel_reenable(zone_id)
                self.hass.async_create_task(self._async_try_reenable(zone_id))
            elif zone_id not in self._reenable_unsub:
                self._schedule_reenable(zone_id, remaining)

    def _schedule_reenable(self, zone_id: int, delay: float) -> None:
        @callback
        def _fire(_now: datetime) -> None:
            self._reenable_unsub.pop(zone_id, None)
            self.hass.async_create_task(self._async_try_reenable(zone_id))

        self._reenable_unsub[zone_id] = async_call_later(self.hass, delay + 0.5, _fire)

    def _cancel_reenable(self, zone_id: int) -> None:
        if unsub := self._reenable_unsub.pop(zone_id, None):
            unsub()

    async def _async_try_reenable(self, zone_id: int) -> None:
        """Remove an owned bypass once the zone proved healthy."""
        if self.arm_lock.locked():
            return  # an arm/bypass flow is running; the next poll retries
        async with self.arm_lock:
            owned = self.store.data.owned_bypasses.get(zone_id)
            if owned is None:
                return
            if zone_id not in self._healthy_since:
                # The zone went unhealthy again before the timer fired.
                return
            # Never act on stale data: re-read the zone right before removal.
            try:
                raw = await self.hass.async_add_executor_job(
                    self.client.get_zone_raw, zone_id
                )
            except BypassError as err:
                _LOGGER.warning(
                    "Re-enable of zone %s postponed, fresh state read failed "
                    "(next poll retries): %s",
                    zone_id,
                    err,
                )
                return
            if raw is None:
                _LOGGER.warning(
                    "Re-enable of zone %s postponed: zone missing from the "
                    "panel status response",
                    zone_id,
                )
                return
            zone = Zone.from_dict(raw)
            if not zone.bypassed:
                # Already restored externally; reconciliation on next poll.
                return
            fault = zone_fault_reason(zone)
            if fault is not None:
                _LOGGER.info(
                    "Re-enable of zone %s aborted: fresh read shows it in "
                    "fault again (%s)",
                    zone_id,
                    fault,
                )
                self._healthy_since.pop(zone_id, None)
                return
            if not self._zone_area_armed(zone):
                return
            try:
                await self.hass.async_add_executor_job(self.client.unbypass, zone_id)
            except BypassError as err:
                _LOGGER.warning(
                    "Panel refused to unbypass zone %s while armed; "
                    "will retry and clean up on disarm: %s",
                    zone_id,
                    err,
                )
                owned.pending_unbypass = True
                await self.store.async_save()
                return
            self.store.data.owned_bypasses.pop(zone_id, None)
            self._healthy_since.pop(zone_id, None)
            await self.store.async_save()
            _LOGGER.info(
                "Zone %s (%s) re-enabled after recovery: it is armed again",
                zone_id,
                zone.name,
            )
            self._fire_bypass_event(
                EVENT_BYPASS_REMOVED, _zone_issue(zone, ""), REASON_HEALTH_RECOVERED
            )
        await self.coordinator.async_request_refresh()

    def _zone_area_armed(self, zone: Zone) -> bool:
        """Whether the area the zone belongs to is currently armed."""
        area = zone.sub_system_no
        if area is not None and area in self.coordinator.sub_systems:
            arming = self.coordinator.sub_systems[area].arming
            return arming not in (Arming.DISARM, None)
        state = self.coordinator.state
        return state is not None and str(state) not in ("disarmed",)

    def async_unload(self) -> None:
        """Cancel timers on entry unload."""
        for zone_id in list(self._reenable_unsub):
            self._cancel_reenable(zone_id)

    # ------------------------------------------------------------------
    # Helpers

    def _zone_area(self, zone_id: int) -> int | None:
        zone = (self.coordinator.zones or {}).get(zone_id)
        return zone.sub_system_no if zone else None

    def _issue_for(self, zone_id: int) -> dict[str, Any]:
        zone = (self.coordinator.zones or {}).get(zone_id)
        if zone is not None:
            return _zone_issue(zone, "")
        return {"zone_id": zone_id, "zone_name": None, "area": None, "fault": ""}

    def _fire_bypass_event(
        self, event: str, issue: dict[str, Any], reason: str
    ) -> None:
        self.hass.bus.async_fire(
            event,
            {
                "entry_id": self.entry.entry_id,
                "device_name": self.coordinator.device_name,
                "zone_id": issue["zone_id"],
                "zone_name": issue["zone_name"],
                "area": issue["area"],
                "reason": reason,
            },
        )

    def _fire_arming_blocked(
        self,
        sub_id: int | None,
        blocking: list[dict[str, Any]],
        failed: list[dict[str, Any]],
    ) -> None:
        self.hass.bus.async_fire(
            EVENT_ARMING_BLOCKED,
            {
                "entry_id": self.entry.entry_id,
                "device_name": self.coordinator.device_name,
                "area": sub_id,
                "blocking_zones": blocking,
                "failed_bypass_zones": failed,
            },
        )

    @staticmethod
    def _zone_list_str(issues: list[dict[str, Any]]) -> str:
        return ", ".join(
            f"{issue['zone_name']} ({issue['fault']})" for issue in issues
        )
