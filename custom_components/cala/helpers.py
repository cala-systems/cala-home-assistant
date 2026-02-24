"""Shared helpers for the Cala integration."""

from homeassistant.helpers.device_registry import async_get as async_get_device_registry
from homeassistant.helpers.entity_registry import (
    async_entries_for_device,
    async_get as async_get_entity_registry,
)

from .const import DOMAIN

BOOST_UNIQUE_ID_SUFFIX = "_boost_mode_on"


def get_boost_entity_id(hass, device_id: str) -> str | None:
    """Find the boost_mode_on binary sensor entity_id for a device."""
    ent_reg = async_get_entity_registry(hass)
    unique_id = f"cala_{device_id}_boost_mode_on"
    for platform in ("sensor", "cala"):
        entity_id = ent_reg.async_get_entity_id("binary_sensor", platform, unique_id)
        if entity_id:
            return entity_id
    dev_reg = async_get_device_registry(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, device_id)})
    if device:
        for entry in async_entries_for_device(ent_reg, device.id):
            if entry.unique_id and entry.unique_id.endswith(BOOST_UNIQUE_ID_SUFFIX):
                return entry.entity_id
    device_id_norm = device_id.lower().replace("-", "_")
    for entry in ent_reg.entities.values():
        if (
            entry.domain == "binary_sensor"
            and entry.unique_id
            and entry.unique_id.lower().endswith(BOOST_UNIQUE_ID_SUFFIX)
            and (
                device_id.lower() in entry.unique_id.lower()
                or device_id_norm in entry.unique_id.lower()
            )
        ):
            return entry.entity_id
    return None
