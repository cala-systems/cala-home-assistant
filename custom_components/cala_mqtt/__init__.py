from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_state_change

from .const import DOMAIN
from .publish import publish_context 

PLATFORMS = ["sensor"]

OPTION_KEYS = {
    "solar_production_entity",
    "grid_import_entity",
    "grid_export_entity",
    "battery_soc_entity",
}



async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Only proceed if options are configured
    opts = entry.options
    tracked_entities = [opts.get(k) for k in OPTION_KEYS if opts.get(k)]

    if not tracked_entities:
        return True  # nothing configured, nothing to do

    async def _state_changed(event):
        await publish_context(hass, entry)

    unsub = async_track_state_change(
        hass,
        tracked_entities,
        _state_changed,
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "state_unsub": unsub,
    }

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
