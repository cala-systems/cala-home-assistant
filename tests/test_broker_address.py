"""Unit tests for the pairing broker-address chooser."""

import asyncio
import sys
import types

from cala.broker_address import (
    FALLBACK_HOSTNAME,
    async_default_broker,
    lan_address_for_device,
)

LAN = {
    "name": "eth0",
    "enabled": True,
    "ipv4": [{"address": "192.168.1.20", "network_prefix": 24}],
}
DOCKER = {
    "name": "hassio",
    "enabled": True,
    "ipv4": [{"address": "172.30.232.1", "network_prefix": 23}],
}
DISABLED_LAN = {**LAN, "enabled": False}


def test_picks_adapter_on_device_subnet():
    assert lan_address_for_device([DOCKER, LAN], "192.168.1.171") == "192.168.1.20"


def test_ignores_disabled_adapters():
    assert lan_address_for_device([DISABLED_LAN, DOCKER], "192.168.1.171") is None


def test_no_match_when_device_off_all_subnets():
    assert lan_address_for_device([LAN, DOCKER], "10.0.0.5") is None


def test_hostname_device_host_gives_no_match():
    assert lan_address_for_device([LAN], "cala.local") is None
    assert lan_address_for_device([LAN], "") is None
    assert lan_address_for_device([LAN], None) is None


def test_tolerates_malformed_adapter_entries():
    adapters = [
        {"enabled": True, "ipv4": [{"address": None, "network_prefix": 24}]},
        {"enabled": True, "ipv4": [{"address": "192.168.1.9"}]},
        {"enabled": True, "ipv4": [{"address": "bad", "network_prefix": 24}]},
        {"enabled": True},
        LAN,
    ]
    assert lan_address_for_device(adapters, "192.168.1.171") == "192.168.1.20"


def _install_network_stub(adapters=None, source_ip=None, adapters_exc=None):
    async def async_get_adapters(hass):
        if adapters_exc:
            raise adapters_exc
        return adapters or []

    async def async_get_source_ip(hass):
        return source_ip

    mod = types.ModuleType("homeassistant.components.network")
    mod.async_get_adapters = async_get_adapters
    mod.async_get_source_ip = async_get_source_ip
    sys.modules["homeassistant.components.network"] = mod
    setattr(sys.modules["homeassistant.components"], "network", mod)
    return mod


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_default_prefers_subnet_match_over_source_ip():
    _install_network_stub(adapters=[DOCKER, LAN], source_ip="172.30.232.1")
    assert _run(async_default_broker(None, "192.168.1.171")) == "192.168.1.20"


def test_default_falls_back_to_source_ip_without_match():
    _install_network_stub(adapters=[DOCKER], source_ip="172.30.232.1")
    assert _run(async_default_broker(None, "192.168.1.171")) == "172.30.232.1"


def test_default_falls_back_to_hostname_without_any_ip():
    _install_network_stub(adapters=[], source_ip=None)
    assert _run(async_default_broker(None, "192.168.1.171")) == FALLBACK_HOSTNAME


def test_adapter_failure_still_uses_source_ip():
    _install_network_stub(adapters_exc=RuntimeError("boom"), source_ip="192.168.1.20")
    assert _run(async_default_broker(None, "192.168.1.171")) == "192.168.1.20"
