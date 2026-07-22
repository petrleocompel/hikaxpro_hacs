"""Keypad, repeater, and extension-module entities from exDevStatus."""

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
from .model import ExtensionModule, Keypad, Repeater, detector_model_to_name


def _ids(entry_id: str, kind: str, device_id: int) -> set[tuple[str, str]]:
    return {(DOMAIN, f"{entry_id}-{kind}-{device_id}")}


def register_peripheral_devices(
    device_registry: dr.DeviceRegistry,
    coordinator: HikAxProDataUpdateCoordinator,
    entry_id: str,
) -> None:
    """Register HA devices for keypads, repeaters, and extension modules."""
    for kid, keypad in coordinator.keypads.items():
        device_registry.async_get_or_create(
            config_entry_id=entry_id,
            identifiers=_ids(entry_id, "keypad", kid),
            manufacturer="HikVision",
            name=keypad.name or f"Keypad {kid}",
            via_device=(DOMAIN, str(coordinator.mac)),
            model=detector_model_to_name(keypad.model) if keypad.model else "Keypad",
            sw_version=keypad.version,
        )
    for rid, repeater in coordinator.repeaters.items():
        device_registry.async_get_or_create(
            config_entry_id=entry_id,
            identifiers=_ids(entry_id, "repeater", rid),
            manufacturer="HikVision",
            name=repeater.name or f"Repeater {rid}",
            via_device=(DOMAIN, str(coordinator.mac)),
            model=detector_model_to_name(repeater.model)
            if repeater.model
            else "Repeater",
            sw_version=repeater.version,
        )
    for eid, extension in coordinator.extensions.items():
        device_registry.async_get_or_create(
            config_entry_id=entry_id,
            identifiers=_ids(entry_id, "extension", eid),
            manufacturer="HikVision",
            name=extension.name or f"Extension {eid}",
            via_device=(DOMAIN, str(coordinator.mac)),
            model=detector_model_to_name(extension.model)
            if extension.model
            else (extension.type or "Extension"),
            sw_version=extension.version,
        )


def build_peripheral_binary_sensors(
    coordinator: HikAxProDataUpdateCoordinator, entry_id: str
) -> list[BinarySensorEntity]:
    """Create diagnostic binary sensors for peripherals."""
    entities: list[BinarySensorEntity] = []

    for keypad in coordinator.keypads.values():
        entities.extend(
            _bool_entities(
                coordinator,
                entry_id,
                kind="keypad",
                device_id=keypad.id,
                get=lambda c, i=keypad.id: c.keypads.get(i),
                specs=[
                    ("tamper", "Tamper", BinarySensorDeviceClass.TAMPER, lambda d: d.tamper_evident),
                    (
                        "isviarepeater",
                        "Via repeater",
                        BinarySensorDeviceClass.CONNECTIVITY,
                        lambda d: d.is_via_repeater,
                    ),
                    (
                        "online",
                        "Online",
                        BinarySensorDeviceClass.CONNECTIVITY,
                        lambda d: (d.status or "").lower() == "online",
                    ),
                    (
                        "battery-low",
                        "Battery low",
                        BinarySensorDeviceClass.BATTERY,
                        lambda d: d.charge == "lowPower",
                    ),
                ],
            )
        )

    for repeater in coordinator.repeaters.values():
        entities.extend(
            _bool_entities(
                coordinator,
                entry_id,
                kind="repeater",
                device_id=repeater.id,
                get=lambda c, i=repeater.id: c.repeaters.get(i),
                specs=[
                    ("tamper", "Tamper", BinarySensorDeviceClass.TAMPER, lambda d: d.tamper_evident),
                    (
                        "online",
                        "Online",
                        BinarySensorDeviceClass.CONNECTIVITY,
                        lambda d: (d.status or "").lower() == "online",
                    ),
                    (
                        "mains",
                        "Mains power",
                        BinarySensorDeviceClass.POWER,
                        lambda d: d.main_power_supply,
                    ),
                    (
                        "battery-low",
                        "Battery low",
                        BinarySensorDeviceClass.BATTERY,
                        lambda d: d.charge == "lowPower",
                    ),
                ],
            )
        )

    for extension in coordinator.extensions.values():
        entities.extend(
            _bool_entities(
                coordinator,
                entry_id,
                kind="extension",
                device_id=extension.id,
                get=lambda c, i=extension.id: c.extensions.get(i),
                specs=[
                    ("tamper", "Tamper", BinarySensorDeviceClass.TAMPER, lambda d: d.tamper_evident),
                    (
                        "online",
                        "Online",
                        BinarySensorDeviceClass.CONNECTIVITY,
                        lambda d: (d.status or "").lower() == "online",
                    ),
                    (
                        "battery-low",
                        "Battery low",
                        BinarySensorDeviceClass.BATTERY,
                        lambda d: d.charge == "lowPower",
                    ),
                ],
            )
        )
    return entities


def build_peripheral_sensors(
    coordinator: HikAxProDataUpdateCoordinator, entry_id: str
) -> list[SensorEntity]:
    """Create diagnostic sensors for peripherals."""
    entities: list[SensorEntity] = []

    for keypad in coordinator.keypads.values():
        entities.extend(
            _value_entities(
                coordinator,
                entry_id,
                kind="keypad",
                device_id=keypad.id,
                get=lambda c, i=keypad.id: c.keypads.get(i),
                specs=[
                    (
                        "temperature",
                        "Temperature",
                        SensorDeviceClass.TEMPERATURE,
                        UnitOfTemperature.CELSIUS,
                        SensorStateClass.MEASUREMENT,
                        lambda d: d.temperature,
                    ),
                    (
                        "signal",
                        "Signal",
                        SensorDeviceClass.SIGNAL_STRENGTH,
                        SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
                        SensorStateClass.MEASUREMENT,
                        lambda d: d.signal,
                    ),
                    (
                        "battery",
                        "Battery",
                        SensorDeviceClass.BATTERY,
                        PERCENTAGE,
                        SensorStateClass.MEASUREMENT,
                        lambda d: d.charge_value,
                    ),
                    ("status", "Status", None, None, None, lambda d: d.status),
                    ("charge", "Charge status", None, None, None, lambda d: d.charge),
                ],
            )
        )

    for repeater in coordinator.repeaters.values():
        entities.extend(
            _value_entities(
                coordinator,
                entry_id,
                kind="repeater",
                device_id=repeater.id,
                get=lambda c, i=repeater.id: c.repeaters.get(i),
                specs=[
                    (
                        "temperature",
                        "Temperature",
                        SensorDeviceClass.TEMPERATURE,
                        UnitOfTemperature.CELSIUS,
                        SensorStateClass.MEASUREMENT,
                        lambda d: d.temperature,
                    ),
                    (
                        "signal",
                        "Signal",
                        SensorDeviceClass.SIGNAL_STRENGTH,
                        SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
                        SensorStateClass.MEASUREMENT,
                        lambda d: d.signal,
                    ),
                    (
                        "battery",
                        "Battery",
                        SensorDeviceClass.BATTERY,
                        PERCENTAGE,
                        SensorStateClass.MEASUREMENT,
                        lambda d: d.charge_value,
                    ),
                    ("status", "Status", None, None, None, lambda d: d.status),
                    ("charge", "Charge status", None, None, None, lambda d: d.charge),
                ],
            )
        )

    for extension in coordinator.extensions.values():
        entities.extend(
            _value_entities(
                coordinator,
                entry_id,
                kind="extension",
                device_id=extension.id,
                get=lambda c, i=extension.id: c.extensions.get(i),
                specs=[
                    ("status", "Status", None, None, None, lambda d: d.status),
                    ("type", "Type", None, None, None, lambda d: d.type),
                    ("charge", "Charge status", None, None, None, lambda d: d.charge),
                ],
            )
        )
    return entities


def _bool_entities(coordinator, entry_id, *, kind, device_id, get, specs):
    entities = []
    device = get(coordinator)
    if device is None or device_id is None:
        return entities
    for key, name, device_class, value_fn in specs:
        # Only create when the field is present on first sample (or status-derived).
        sample = value_fn(device)
        if sample is None and key not in ("online", "battery-low"):
            continue
        if key == "battery-low" and getattr(device, "charge", None) is None:
            continue
        if key == "online" and getattr(device, "status", None) is None:
            continue
        entities.append(
            HikPeripheralBinary(
                coordinator,
                entry_id,
                kind=kind,
                device_id=device_id,
                key=key,
                name=name,
                device_class=device_class,
                get=get,
                value_fn=value_fn,
            )
        )
    return entities


def _value_entities(coordinator, entry_id, *, kind, device_id, get, specs):
    entities = []
    device = get(coordinator)
    if device is None or device_id is None:
        return entities
    for key, name, device_class, unit, state_class, value_fn in specs:
        sample = value_fn(device)
        if sample is None and key != "battery":
            continue
        if key == "battery" and getattr(device, "charge_value", None) is None and getattr(
            device, "charge", None
        ) is None:
            continue
        entities.append(
            HikPeripheralSensor(
                coordinator,
                entry_id,
                kind=kind,
                device_id=device_id,
                key=key,
                name=name,
                device_class=device_class,
                unit=unit,
                state_class=state_class,
                get=get,
                value_fn=value_fn,
            )
        )
    return entities


class HikPeripheralBinary(CoordinatorEntity, BinarySensorEntity):
    """Binary attribute for a keypad/repeater/extension."""

    coordinator: HikAxProDataUpdateCoordinator

    def __init__(
        self,
        coordinator: HikAxProDataUpdateCoordinator,
        entry_id: str,
        *,
        kind: str,
        device_id: int,
        key: str,
        name: str,
        device_class: BinarySensorDeviceClass,
        get: Callable,
        value_fn: Callable,
    ) -> None:
        super().__init__(coordinator)
        self._ref_id = entry_id
        self._kind = kind
        self._device_id = device_id
        self._get = get
        self._value_fn = value_fn
        self._attr_unique_id = f"{coordinator.device_name}-{kind}-{device_id}-{key}"
        self._attr_name = name
        self._attr_has_entity_name = True
        self._attr_device_class = device_class
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self.entity_id = build_entity_id(
            BINARY_SENSOR_DOMAIN, coordinator.device_name, kind, device_id, key
        )

    def _current(self):
        return self._get(self.coordinator)

    @property
    def device_info(self) -> DeviceInfo:
        device = self._current()
        name = getattr(device, "name", None) or f"{self._kind} {self._device_id}"
        model = getattr(device, "model", None)
        return DeviceInfo(
            identifiers=_ids(self._ref_id, self._kind, self._device_id),
            manufacturer="HikVision",
            name=name,
            via_device=(DOMAIN, str(self.coordinator.mac)),
            model=detector_model_to_name(model) if model else self._kind.title(),
            sw_version=getattr(device, "version", None),
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        device = self._current()
        if device is None:
            self._attr_is_on = None
            self._attr_available = False
        else:
            self._attr_is_on = self._value_fn(device)
            self._attr_available = True
        self.async_write_ha_state()


class HikPeripheralSensor(CoordinatorEntity, SensorEntity):
    """Sensor attribute for a keypad/repeater/extension."""

    coordinator: HikAxProDataUpdateCoordinator

    def __init__(
        self,
        coordinator: HikAxProDataUpdateCoordinator,
        entry_id: str,
        *,
        kind: str,
        device_id: int,
        key: str,
        name: str,
        device_class: SensorDeviceClass | None,
        unit: str | None,
        state_class: SensorStateClass | None,
        get: Callable,
        value_fn: Callable,
    ) -> None:
        super().__init__(coordinator)
        self._ref_id = entry_id
        self._kind = kind
        self._device_id = device_id
        self._get = get
        self._value_fn = value_fn
        self._attr_unique_id = f"{coordinator.device_name}-{kind}-{device_id}-{key}"
        self._attr_name = name
        self._attr_has_entity_name = True
        if device_class is not None:
            self._attr_device_class = device_class
        if unit is not None:
            self._attr_native_unit_of_measurement = unit
        if state_class is not None:
            self._attr_state_class = state_class
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self.entity_id = build_entity_id(
            SENSOR_DOMAIN, coordinator.device_name, kind, device_id, key
        )

    def _current(self):
        return self._get(self.coordinator)

    @property
    def device_info(self) -> DeviceInfo:
        device = self._current()
        name = getattr(device, "name", None) or f"{self._kind} {self._device_id}"
        model = getattr(device, "model", None)
        return DeviceInfo(
            identifiers=_ids(self._ref_id, self._kind, self._device_id),
            manufacturer="HikVision",
            name=name,
            via_device=(DOMAIN, str(self.coordinator.mac)),
            model=detector_model_to_name(model) if model else self._kind.title(),
            sw_version=getattr(device, "version", None),
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        device = self._current()
        if device is None:
            self._attr_native_value = None
            self._attr_available = False
        else:
            value = self._value_fn(device)
            if value is None:
                self._attr_native_value = None
                self._attr_available = False
            else:
                if self._attr_device_class in (
                    SensorDeviceClass.BATTERY,
                    SensorDeviceClass.TEMPERATURE,
                    SensorDeviceClass.SIGNAL_STRENGTH,
                ):
                    self._attr_native_value = cast(float, value)
                else:
                    self._attr_native_value = value
                self._attr_available = True
        self.async_write_ha_state()
