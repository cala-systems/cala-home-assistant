"""Choose the MQTT broker address pushed to a Cala device during pairing.

The device connects to whatever address it is handed, so it has to be one
the device can actually reach. HA's own source IP is not always that: on
Supervisor and Docker installs it can be a container-network address
(172.30.x.x) that never routes from the LAN. Prefer the adapter address
that shares a subnet with the device itself.
"""

from __future__ import annotations

import ipaddress
import logging

_LOGGER = logging.getLogger(__name__)

FALLBACK_HOSTNAME = "homeassistant.local"


def lan_address_for_device(adapters, device_host: str | None) -> str | None:
    """Return the enabled adapter IPv4 address on the device's subnet.

    `adapters` is the list from `homeassistant.components.network
    .async_get_adapters`. Returns None when the device host is not an IPv4
    literal or no adapter shares its subnet.
    """
    try:
        device_ip = ipaddress.ip_address((device_host or "").strip())
    except ValueError:
        return None
    if device_ip.version != 4:
        return None

    for adapter in adapters or []:
        if not adapter.get("enabled"):
            continue
        for entry in adapter.get("ipv4") or []:
            address = entry.get("address")
            prefix = entry.get("network_prefix")
            if not address or prefix is None:
                continue
            try:
                network = ipaddress.ip_network(f"{address}/{prefix}", strict=False)
            except ValueError:
                continue
            if device_ip in network:
                return address
    return None


async def async_default_broker(hass, device_host: str | None) -> str:
    """Best-guess broker address for the pairing form's Advanced section.

    Order: adapter address on the device's subnet, then HA's source IP,
    then the mDNS hostname. Every step is best-effort; the field stays
    editable in the UI.
    """
    try:
        from homeassistant.components.network import (
            async_get_adapters,
            async_get_source_ip,
        )
    except Exception:  # noqa: BLE001 - network helper unavailable
        _LOGGER.debug("Network helper unavailable", exc_info=True)
        return FALLBACK_HOSTNAME

    try:
        match = lan_address_for_device(await async_get_adapters(hass), device_host)
        if match:
            return match
    except Exception:  # noqa: BLE001 - any failure falls through
        _LOGGER.debug("Could not enumerate network adapters", exc_info=True)

    try:
        source_ip = await async_get_source_ip(hass)
    except Exception:  # noqa: BLE001 - any failure falls through
        _LOGGER.debug("Could not determine source IP", exc_info=True)
        source_ip = None

    if source_ip:
        _LOGGER.warning(
            "No Home Assistant network adapter shares a subnet with the Cala "
            "device at %s; defaulting the broker address to %s. If the device "
            "pairs but never connects, re-pair with the broker set to Home "
            "Assistant's LAN IP under Advanced.",
            device_host or "(unknown)",
            source_ip,
        )
        return source_ip
    return FALLBACK_HOSTNAME
