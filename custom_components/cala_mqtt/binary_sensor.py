from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


class CalaConnectedBinarySensor(BinarySensorEntity):
    _attr_name = "Cala Connected"
    _attr_unique_id = "cala_connected"
    _attr_is_on = True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    async_add_entities([CalaConnectedBinarySensor()])
