from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Unsubscribe from MQTT before tearing down platforms
    entry_data = (hass.data.get(DOMAIN) or {}).get(entry.entry_id) or {}
    unsub = entry_data.get("mqtt_unsubscribe")
    if callable(unsub):
        unsub()
    if entry.entry_id in (hass.data.get(DOMAIN) or {}):
        del hass.data[DOMAIN][entry.entry_id]
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
