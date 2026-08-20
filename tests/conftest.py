"""Stub the homeassistant runtime so the cala modules import standalone.

Registers a `cala` package pointing at custom_components/cala without
executing the integration's __init__.py (which needs a full HA install).
"""

import sys
import types
from pathlib import Path

COMPONENT_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "cala"


def _stub_module(name: str, **attrs) -> types.ModuleType:
    mod = sys.modules.get(name)
    if mod is None:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


class HomeAssistantError(Exception):
    pass


class ConfigEntryNotReady(Exception):
    pass


def _callback(func):
    return func


_stub_module("homeassistant")
_stub_module(
    "homeassistant.exceptions",
    HomeAssistantError=HomeAssistantError,
    ConfigEntryNotReady=ConfigEntryNotReady,
)
_stub_module(
    "homeassistant.core",
    HomeAssistant=object,
    ServiceCall=object,
    callback=_callback,
)
_stub_module("homeassistant.config_entries", ConfigEntry=object)
_mqtt = _stub_module("homeassistant.components.mqtt")
_stub_module("homeassistant.components", mqtt=_mqtt)


class _EntityCategory:
    DIAGNOSTIC = "diagnostic"


class _StrConst:
    """Stand-in for HA's StrEnum unit/class constants.

    Only identity matters to the tests: the integration passes these straight
    through to `_attr_*`, so a distinct sentinel per member is enough.
    """

    def __init__(self, value: str) -> None:
        self.value = value

    def __repr__(self) -> str:
        return f"<{self.value}>"


class _UnitOfTemperature:
    CELSIUS = _StrConst("°C")
    FAHRENHEIT = _StrConst("°F")


class _UnitOfEnergy:
    KILO_WATT_HOUR = _StrConst("kWh")


class _UnitOfPower:
    KILO_WATT = _StrConst("kW")


class _UnitOfTime:
    SECONDS = _StrConst("s")


class _UnitOfVolume:
    LITERS = _StrConst("L")
    GALLONS = _StrConst("gal")


class _UnitOfVolumeFlowRate:
    LITERS_PER_MINUTE = _StrConst("L/min")
    GALLONS_PER_MINUTE = _StrConst("gal/min")


class _SensorDeviceClass:
    TEMPERATURE = _StrConst("temperature")
    POWER = _StrConst("power")
    ENERGY = _StrConst("energy")
    WATER = _StrConst("water")
    DURATION = _StrConst("duration")
    SIGNAL_STRENGTH = _StrConst("signal_strength")


class _SensorStateClass:
    MEASUREMENT = _StrConst("measurement")
    TOTAL = _StrConst("total")
    TOTAL_INCREASING = _StrConst("total_increasing")


class _Entity:
    hass = None

    def async_on_remove(self, func):
        return None

    def async_write_ha_state(self):
        return None


class _RestoreEntity(_Entity):
    async def async_added_to_hass(self):
        return None

    async def async_get_last_state(self):
        return None


import datetime as _datetime  # noqa: E402


def _utcnow():
    return _datetime.datetime.now(_datetime.timezone.utc)


_stub_module(
    "homeassistant.const",
    EntityCategory=_EntityCategory,
    UnitOfEnergy=_UnitOfEnergy,
    UnitOfPower=_UnitOfPower,
    UnitOfTemperature=_UnitOfTemperature,
    UnitOfTime=_UnitOfTime,
    UnitOfVolume=_UnitOfVolume,
    UnitOfVolumeFlowRate=_UnitOfVolumeFlowRate,
)
_stub_module(
    "homeassistant.components.sensor",
    SensorEntity=_Entity,
    SensorDeviceClass=_SensorDeviceClass,
    SensorStateClass=_SensorStateClass,
)
_stub_module("homeassistant.components.binary_sensor", BinarySensorEntity=_Entity)
_stub_module("homeassistant.helpers.storage", Store=object)
_stub_module("homeassistant.helpers.issue_registry")
_dispatcher = _stub_module(
    "homeassistant.helpers.dispatcher",
    async_dispatcher_send=lambda *args, **kwargs: None,
    async_dispatcher_connect=lambda *args, **kwargs: (lambda: None),
)
_stub_module(
    "homeassistant.helpers.restore_state", RestoreEntity=_RestoreEntity
)
_event = _stub_module(
    "homeassistant.helpers.event",
    async_track_state_change_event=lambda *args, **kwargs: (lambda: None),
    async_track_time_change=lambda *args, **kwargs: (lambda: None),
)
_stub_module(
    "homeassistant.helpers",
    dispatcher=_dispatcher,
    event=_event,
    issue_registry=sys.modules["homeassistant.helpers.issue_registry"],
    storage=sys.modules["homeassistant.helpers.storage"],
)
_dt = _stub_module("homeassistant.util.dt", utcnow=_utcnow)
_stub_module("homeassistant.util", dt=_dt)

if "cala" not in sys.modules:
    _pkg = types.ModuleType("cala")
    _pkg.__path__ = [str(COMPONENT_DIR)]
    sys.modules["cala"] = _pkg
