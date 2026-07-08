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

if "cala" not in sys.modules:
    _pkg = types.ModuleType("cala")
    _pkg.__path__ = [str(COMPONENT_DIR)]
    sys.modules["cala"] = _pkg
