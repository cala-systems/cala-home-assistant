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


def _callback(func):
    return func


_stub_module("homeassistant")
_stub_module("homeassistant.exceptions", HomeAssistantError=HomeAssistantError)
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


_stub_module("homeassistant.const", EntityCategory=_EntityCategory)
_stub_module("homeassistant.components.sensor", SensorEntity=_Entity)
_dispatcher = _stub_module(
    "homeassistant.helpers.dispatcher",
    async_dispatcher_send=lambda *args, **kwargs: None,
    async_dispatcher_connect=lambda *args, **kwargs: (lambda: None),
)
_stub_module(
    "homeassistant.helpers.restore_state", RestoreEntity=_RestoreEntity
)
_stub_module("homeassistant.helpers", dispatcher=_dispatcher)
_dt = _stub_module("homeassistant.util.dt", utcnow=_utcnow)
_stub_module("homeassistant.util", dt=_dt)

if "cala" not in sys.modules:
    _pkg = types.ModuleType("cala")
    _pkg.__path__ = [str(COMPONENT_DIR)]
    sys.modules["cala"] = _pkg
