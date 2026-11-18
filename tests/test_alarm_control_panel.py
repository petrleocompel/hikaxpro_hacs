"""Tests for alarm control panel code handling (#217)."""

from __future__ import annotations

import asyncio
import enum
import importlib
import importlib.util
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "hikvision_axpro"
PACKAGE = "hikvision_axpro_acp_test"

CODE = "1234"
SUB_SYS_ID = 3


class ServiceValidationError(Exception):
    """Stand-in for homeassistant.exceptions.ServiceValidationError."""

    def __init__(
        self,
        *args: object,
        translation_domain: str | None = None,
        translation_key: str | None = None,
        translation_placeholders: dict[str, str] | None = None,
    ) -> None:
        super().__init__(*args)
        self.translation_domain = translation_domain
        self.translation_key = translation_key
        self.translation_placeholders = translation_placeholders


class _CoordinatorEntity:
    """Stand-in for CoordinatorEntity: only keeps the coordinator."""

    def __init__(self, coordinator: Any) -> None:
        self.coordinator = coordinator


class _AlarmControlPanelEntityFeature(enum.IntFlag):
    ARM_HOME = 1
    ARM_AWAY = 2


class _AlarmControlPanelState(enum.StrEnum):
    ARMED_AWAY = "armed_away"
    ARMED_HOME = "armed_home"
    ARMED_VACATION = "armed_vacation"
    DISARMED = "disarmed"
    TRIGGERED = "triggered"


class _CodeFormat(enum.StrEnum):
    NUMBER = "number"
    TEXT = "text"


def _module(name: str, **attrs: Any) -> types.ModuleType:
    module = types.ModuleType(name)
    for attr, value in attrs.items():
        setattr(module, attr, value)
    return module


def _ha_stubs() -> dict[str, types.ModuleType]:
    """Minimal homeassistant modules needed to import alarm_control_panel."""
    device_registry = _module(
        "homeassistant.helpers.device_registry", async_get=MagicMock()
    )
    return {
        "homeassistant": _module("homeassistant"),
        "homeassistant.components": _module("homeassistant.components"),
        "homeassistant.components.alarm_control_panel": _module(
            "homeassistant.components.alarm_control_panel",
            AlarmControlPanelEntity=type("AlarmControlPanelEntity", (), {}),
            AlarmControlPanelEntityFeature=_AlarmControlPanelEntityFeature,
            AlarmControlPanelState=_AlarmControlPanelState,
            CodeFormat=_CodeFormat,
        ),
        "homeassistant.config_entries": _module(
            "homeassistant.config_entries", ConfigEntry=object
        ),
        "homeassistant.core": _module(
            "homeassistant.core", HomeAssistant=object, callback=lambda func: func
        ),
        "homeassistant.exceptions": _module(
            "homeassistant.exceptions", ServiceValidationError=ServiceValidationError
        ),
        "homeassistant.helpers": _module(
            "homeassistant.helpers", device_registry=device_registry
        ),
        "homeassistant.helpers.device_registry": device_registry,
        "homeassistant.helpers.entity": _module(
            "homeassistant.helpers.entity", DeviceInfo=dict
        ),
        "homeassistant.helpers.entity_platform": _module(
            "homeassistant.helpers.entity_platform", AddEntitiesCallback=object
        ),
        "homeassistant.helpers.update_coordinator": _module(
            "homeassistant.helpers.update_coordinator",
            CoordinatorEntity=_CoordinatorEntity,
        ),
    }


def _load_alarm_control_panel() -> tuple[types.ModuleType, types.ModuleType]:
    """Load alarm_control_panel.py (and the real model/const) without HA.

    Stubs only live in sys.modules while loading, so other test modules
    still see their own stubs.
    """
    package = _module(
        PACKAGE, __path__=[str(COMPONENT)], HikAxProDataUpdateCoordinator=object
    )
    with patch.dict(sys.modules, {**_ha_stubs(), PACKAGE: package}):
        model = importlib.import_module(f"{PACKAGE}.model")
        package.Arming = model.Arming
        package.SubSys = model.SubSys
        name = f"{PACKAGE}.alarm_control_panel"
        spec = importlib.util.spec_from_file_location(
            name, COMPONENT / "alarm_control_panel.py"
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module, model


acp, model = _load_alarm_control_panel()

PANEL_KINDS = ("panel", "sub_panel")
ARM_ACTIONS = (
    ("async_alarm_arm_home", "async_arm_home"),
    ("async_alarm_arm_away", "async_arm_away"),
)
ALL_ACTIONS = (("async_alarm_disarm", "async_disarm"), *ARM_ACTIONS)


def _coordinator(use_code: bool, use_code_arming: bool) -> MagicMock:
    """Coordinator mock with the configured code and async commands."""
    coordinator = MagicMock()
    coordinator.use_code = use_code
    coordinator.use_code_arming = use_code_arming
    coordinator.code = CODE
    coordinator.async_disarm = AsyncMock()
    coordinator.async_arm_home = AsyncMock()
    coordinator.async_arm_away = AsyncMock()
    return coordinator


def _make_panel(kind: str, coordinator: MagicMock) -> tuple[Any, tuple[int, ...]]:
    """Build a panel and the args it is expected to pass to coordinator commands."""
    if kind == "panel":
        return acp.HikAxProPanel(coordinator), ()
    sub_sys = model.SubSys(
        SUB_SYS_ID, model.Arming.DISARM, False, True, f"Area {SUB_SYS_ID}", 0
    )
    return acp.HikAxProSubPanel(coordinator, sub_sys), (SUB_SYS_ID,)


def _run(panel: Any, action: str, code: str | None) -> None:
    asyncio.run(getattr(panel, action)(code))


@pytest.mark.parametrize("kind", PANEL_KINDS)
@pytest.mark.parametrize(
    ("use_code", "use_code_arming", "expected"),
    (
        (False, False, False),
        (False, True, False),
        (True, False, False),
        (True, True, True),
    ),
)
def test_code_arm_required(
    kind: str, use_code: bool, use_code_arming: bool, expected: bool
) -> None:
    """Arming asks for a code only when both code options are enabled."""
    panel, _ = _make_panel(kind, _coordinator(use_code, use_code_arming))
    assert panel.code_arm_required is expected


@pytest.mark.parametrize("kind", PANEL_KINDS)
@pytest.mark.parametrize("use_code_arming", (False, True))
@pytest.mark.parametrize("code", ("0000", "", None))
def test_disarm_rejects_invalid_code(
    kind: str, use_code_arming: bool, code: str | None
) -> None:
    """A wrong or missing disarm code raises instead of silently returning."""
    coordinator = _coordinator(True, use_code_arming)
    panel, _ = _make_panel(kind, coordinator)
    with pytest.raises(ServiceValidationError) as err:
        _run(panel, "async_alarm_disarm", code)
    assert err.value.translation_domain == "hikvision_axpro"
    assert err.value.translation_key == "invalid_code"
    coordinator.async_disarm.assert_not_called()


@pytest.mark.parametrize("kind", PANEL_KINDS)
@pytest.mark.parametrize("use_code_arming", (False, True))
def test_disarm_with_valid_code(kind: str, use_code_arming: bool) -> None:
    """The correct code disarms (the sub panel passes its area id)."""
    coordinator = _coordinator(True, use_code_arming)
    panel, args = _make_panel(kind, coordinator)
    _run(panel, "async_alarm_disarm", CODE)
    coordinator.async_disarm.assert_awaited_once_with(*args)


@pytest.mark.parametrize("kind", PANEL_KINDS)
@pytest.mark.parametrize("use_code_arming", (False, True))
@pytest.mark.parametrize(("action", "command"), ALL_ACTIONS)
def test_no_code_configured(
    kind: str, use_code_arming: bool, action: str, command: str
) -> None:
    """With use_code off every action runs without a code."""
    coordinator = _coordinator(False, use_code_arming)
    panel, args = _make_panel(kind, coordinator)
    _run(panel, action, None)
    getattr(coordinator, command).assert_awaited_once_with(*args)


@pytest.mark.parametrize("kind", PANEL_KINDS)
@pytest.mark.parametrize(("action", "command"), ARM_ACTIONS)
def test_arm_without_code_when_arming_code_disabled(
    kind: str, action: str, command: str
) -> None:
    """use_code without use_code_arming arms with no code."""
    coordinator = _coordinator(True, False)
    panel, args = _make_panel(kind, coordinator)
    _run(panel, action, None)
    getattr(coordinator, command).assert_awaited_once_with(*args)


@pytest.mark.parametrize("kind", PANEL_KINDS)
@pytest.mark.parametrize(("action", "command"), ARM_ACTIONS)
@pytest.mark.parametrize("code", ("0000", "", None))
def test_arm_rejects_invalid_code_when_required(
    kind: str, action: str, command: str, code: str | None
) -> None:
    """With use_code_arming a wrong or missing code blocks arming."""
    coordinator = _coordinator(True, True)
    panel, _ = _make_panel(kind, coordinator)
    with pytest.raises(ServiceValidationError) as err:
        _run(panel, action, code)
    assert err.value.translation_domain == "hikvision_axpro"
    assert err.value.translation_key == "invalid_code"
    getattr(coordinator, command).assert_not_called()


@pytest.mark.parametrize("kind", PANEL_KINDS)
@pytest.mark.parametrize(("action", "command"), ARM_ACTIONS)
def test_arm_with_valid_code_when_required(
    kind: str, action: str, command: str
) -> None:
    """With use_code_arming the correct code arms."""
    coordinator = _coordinator(True, True)
    panel, args = _make_panel(kind, coordinator)
    _run(panel, action, CODE)
    getattr(coordinator, command).assert_awaited_once_with(*args)


def test_stubs_not_left_in_sys_modules() -> None:
    """Loading the panel must not leak HA stubs to other test modules."""
    exceptions = sys.modules.get("homeassistant.exceptions")
    assert getattr(exceptions, "ServiceValidationError", None) is not (
        ServiceValidationError
    )
    assert not any(name.startswith(PACKAGE) for name in sys.modules)
