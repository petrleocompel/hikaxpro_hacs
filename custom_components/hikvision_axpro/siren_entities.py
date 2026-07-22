"""Siren entities built from exDevStatus SirenList."""

from __future__ import annotations

from typing import Callable, cast

from homeassistant.components.binary_sensor import (
    DOMAIN as BINARY_SENSOR_DOMAIN,
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.sensor import (
    DOMAIN as SENSOR_DOMAIN,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfTemperature,
)
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HikAxProDataUpdateCoordinator
from .const import DOMAIN
from .entity_id import build_entity_id
from .model import Siren, detector_model_to_name


def _siren_identifiers(entry_id: str, siren_id: int) -> set[tuple[str, str]]:
    return {(DOMAIN, f"{entry_id}-siren-{siren_id}")}


def register_siren_devices(
    device_registry: dr.DeviceRegistry,
    coordinator: HikAxProDataUpdateCoordinator,
    entry_id: str,
) -> None:
    """Register HA devices for each siren."""
    for siren_id, siren in coordinator.sirens.items():
        device_registry.async_get_or_create(
            config_entry_id=entry_id,
            identifiers=_siren_identifiers(entry_id, siren_id),
            manufacturer="HikVision",
            name=siren.name or f"Siren {siren_id}",
            via_device=(DOMAIN, str(coordinator.mac)),
            model=detector_model_to_name(siren.model) if siren.model else "Siren",
            sw_version=siren.version,
        )


def build_siren_binary_sensors(
    coordinator: HikAxProDataUpdateCoordinator, entry_id: str
) -> list[BinarySensorEntity]:
    """Create binary sensors for sirens present in coordinator data."""
    entities: list[BinarySensorEntity] = []
    for siren in coordinator.sirens.values():
        if siren.tamper_evident is not None:
            entities.append(
                HikSirenBinary(
                    coordinator,
                    siren,
                    entry_id,
                    key="tamper",
                    name="Tamper",
                    device_class=BinarySensorDeviceClass.TAMPER,
                    value_fn=lambda s: s.tamper_evident,
                )
            )
        if siren.is_via_repeater is not None:
            entities.append(
                HikSirenBinary(
                    coordinator,
                    siren,
                    entry_id,
                    key="isviarepeater",
                    name="Via repeater",
                    device_class=BinarySensorDeviceClass.CONNECTIVITY,
                    value_fn=lambda s: s.is_via_repeater,
                )
            )
        if siren.abnormal_or_not is not None:
            entities.append(
                HikSirenBinary(
                    coordinator,
                    siren,
                    entry_id,
                    key="abnormal",
                    name="Abnormal",
                    device_class=BinarySensorDeviceClass.PROBLEM,
                    value_fn=lambda s: s.abnormal_or_not,
                )
            )
        if siren.main_power_supply is not None:
            entities.append(
                HikSirenBinary(
                    coordinator,
                    siren,
                    entry_id,
                    key="mains",
                    name="Mains power",
                    device_class=BinarySensorDeviceClass.POWER,
                    value_fn=lambda s: s.main_power_supply,
                )
            )
        if siren.status is not None:
            entities.append(
                HikSirenBinary(
                    coordinator,
                    siren,
                    entry_id,
                    key="sounding",
                    name="Sounding",
                    device_class=BinarySensorDeviceClass.SOUND,
                    value_fn=lambda s: (s.status or "").lower() == "on",
                )
            )
        if siren.charge is not None:
            entities.append(
                HikSirenBinary(
                    coordinator,
                    siren,
                    entry_id,
                    key="battery-low",
                    name="Battery low",
                    device_class=BinarySensorDeviceClass.BATTERY,
                    value_fn=lambda s: s.charge == "lowPower",
                    diagnostic=True,
                )
            )
    return entities


def build_siren_sensors(
    coordinator: HikAxProDataUpdateCoordinator, entry_id: str
) -> list[SensorEntity]:
    """Create sensors for sirens present in coordinator data."""
    entities: list[SensorEntity] = []
    for siren in coordinator.sirens.values():
        if siren.temperature is not None:
            entities.append(
                HikSirenSensor(
                    coordinator,
                    siren,
                    entry_id,
                    key="temperature",
                    name="Temperature",
                    device_class=SensorDeviceClass.TEMPERATURE,
                    unit=UnitOfTemperature.CELSIUS,
                    state_class=SensorStateClass.MEASUREMENT,
                    value_fn=lambda s: s.temperature,
                )
            )
        if siren.signal is not None:
            entities.append(
                HikSirenSensor(
                    coordinator,
                    siren,
                    entry_id,
                    key="signal",
                    name="Signal",
                    device_class=SensorDeviceClass.SIGNAL_STRENGTH,
                    unit=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
                    state_class=SensorStateClass.MEASUREMENT,
                    value_fn=lambda s: s.signal,
                    diagnostic=True,
                )
            )
        if siren.charge_value is not None or siren.charge is not None:
            entities.append(
                HikSirenSensor(
                    coordinator,
                    siren,
                    entry_id,
                    key="battery",
                    name="Battery",
                    device_class=SensorDeviceClass.BATTERY,
                    unit=PERCENTAGE,
                    state_class=SensorStateClass.MEASUREMENT,
                    value_fn=lambda s: s.charge_value,
                    diagnostic=True,
                )
            )
        if siren.charge is not None:
            entities.append(
                HikSirenSensor(
                    coordinator,
                    siren,
                    entry_id,
                    key="charge",
                    name="Charge status",
                    value_fn=lambda s: s.charge,
                    diagnostic=True,
                )
            )
        if siren.status is not None:
            entities.append(
                HikSirenSensor(
                    coordinator,
                    siren,
                    entry_id,
                    key="status",
                    name="Status",
                    value_fn=lambda s: s.status,
                    diagnostic=True,
                )
            )
    return entities


class HikSirenEntity(CoordinatorEntity):
    """Shared siren device wiring."""

    coordinator: HikAxProDataUpdateCoordinator
    siren_id: int
    _ref_id: str

    def __init__(
        self,
        coordinator: HikAxProDataUpdateCoordinator,
        siren: Siren,
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        assert siren.id is not None
        self.siren_id = siren.id
        self._ref_id = entry_id

    def _current(self) -> Siren | None:
        return self.coordinator.sirens.get(self.siren_id)

    @property
    def device_info(self) -> DeviceInfo:
        siren = self._current()
        name = (siren.name if siren else None) or f"Siren {self.siren_id}"
        return DeviceInfo(
            identifiers=_siren_identifiers(self._ref_id, self.siren_id),
            manufacturer="HikVision",
            name=name,
            via_device=(DOMAIN, str(self.coordinator.mac)),
            model=detector_model_to_name(siren.model)
            if siren and siren.model
            else "Siren",
            sw_version=siren.version if siren else None,
        )


class HikSirenBinary(HikSirenEntity, BinarySensorEntity):
    """Binary attribute of a siren."""

    def __init__(
        self,
        coordinator: HikAxProDataUpdateCoordinator,
        siren: Siren,
        entry_id: str,
        *,
        key: str,
        name: str,
        value_fn: Callable[[Siren], bool | None],
        device_class: BinarySensorDeviceClass | None = None,
        diagnostic: bool = False,
    ) -> None:
        super().__init__(coordinator, siren, entry_id)
        self._key = key
        self._value_fn = value_fn
        self._attr_unique_id = (
            f"{coordinator.device_name}-siren-{self.siren_id}-{key}"
        )
        self._attr_name = name
        self._attr_has_entity_name = True
        if device_class is not None:
            self._attr_device_class = device_class
        if diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self.entity_id = build_entity_id(
            BINARY_SENSOR_DOMAIN,
            coordinator.device_name,
            "siren",
            self.siren_id,
            key,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        siren = self._current()
        if siren is None:
            self._attr_is_on = None
            self._attr_available = False
        else:
            self._attr_is_on = self._value_fn(siren)
            self._attr_available = True
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        siren = self._current()
        if siren is None:
            return None
        return self._value_fn(siren)


class HikSirenSensor(HikSirenEntity, SensorEntity):
    """Numeric/text attribute of a siren."""

    def __init__(
        self,
        coordinator: HikAxProDataUpdateCoordinator,
        siren: Siren,
        entry_id: str,
        *,
        key: str,
        name: str,
        value_fn: Callable[[Siren], object | None],
        device_class: SensorDeviceClass | None = None,
        unit: str | None = None,
        state_class: SensorStateClass | None = None,
        diagnostic: bool = False,
    ) -> None:
        super().__init__(coordinator, siren, entry_id)
        self._key = key
        self._value_fn = value_fn
        # Avoid reading unset _attr_device_class (HA Entity CachedProperties).
        self._cast_numeric = device_class in (
            SensorDeviceClass.BATTERY,
            SensorDeviceClass.TEMPERATURE,
            SensorDeviceClass.SIGNAL_STRENGTH,
        )
        self._attr_unique_id = (
            f"{coordinator.device_name}-siren-{self.siren_id}-{key}"
        )
        self._attr_name = name
        self._attr_has_entity_name = True
        if device_class is not None:
            self._attr_device_class = device_class
        if unit is not None:
            self._attr_native_unit_of_measurement = unit
        if state_class is not None:
            self._attr_state_class = state_class
        if diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self.entity_id = build_entity_id(
            SENSOR_DOMAIN, coordinator.device_name, "siren", self.siren_id, key
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        siren = self._current()
        if siren is None:
            self._attr_native_value = None
            self._attr_available = False
        else:
            value = self._value_fn(siren)
            if value is None:
                self._attr_native_value = None
                self._attr_available = False
            else:
                if self._cast_numeric:
                    self._attr_native_value = cast(float, value)
                else:
                    self._attr_native_value = value  # type: ignore[assignment]
                self._attr_available = True
        self.async_write_ha_state()