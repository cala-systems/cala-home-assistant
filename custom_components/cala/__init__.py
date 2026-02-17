import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN
from .publish import publish_context

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

OPTION_KEYS = (
    "solar_production_entity",
    "battery_soc_entity",
)


def _entity_id_from_option(value):
    """Normalize option value to entity_id string (EntitySelector may return dict or string)."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get("entity_id") or value.get("id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.debug("CALA MQTT: __init__.py async_setup_entry called")
    device_id = entry.data.get("device_id", "?")
    opts = entry.options or {}
    _LOGGER.info(
        "Cala setup entry_id=%s device_id=%s options=%s",
        entry.entry_id,
        device_id,
        opts,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Build list of entity_ids from options (selector may store dict or string)
    tracked_entities = []
    for key in OPTION_KEYS:
        entity_id = _entity_id_from_option(opts.get(key))
        if entity_id:
            tracked_entities.append(entity_id)

    if not tracked_entities:
        _LOGGER.info(
            "Cala context: no option entities configured (solar/battery); state listener not registered"
        )
        return True

    _LOGGER.info(
        "Cala context: tracking %s for state changes → publish to cala/%s/context",
        tracked_entities,
        device_id,
    )

    @callback
    def _state_changed(event):
        data = event.data
        entity_id = data["entity_id"]
        old_state = data.get("old_state")
        new_state = data.get("new_state")
        _LOGGER.info(
            "Cala context: state change %s (%s → %s), publishing",
            entity_id,
            old_state.state if old_state else None,
            new_state.state if new_state else None,
        )
        hass.async_create_task(publish_context(hass, entry))

    unsub = async_track_state_change_event(
        hass,
        tracked_entities,
        _state_changed,
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = (
        hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}
    )
    hass.data[DOMAIN][entry.entry_id]["state_unsub"] = unsub

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry_data = (hass.data.get(DOMAIN) or {}).get(entry.entry_id) or {}
    # Remove state-change listener (context publishing)
    state_unsub = entry_data.get("state_unsub")
    if callable(state_unsub):
        state_unsub()
    # Unsubscribe from MQTT (sensor subscription)
    mqtt_unsub = entry_data.get("mqtt_unsubscribe")
    if callable(mqtt_unsub):
        mqtt_unsub()
    # Cancel connection timeout timer
    cancel_timeout = entry_data.get("timeout_timer")
    if callable(cancel_timeout):
        cancel_timeout()
    if entry.entry_id in (hass.data.get(DOMAIN) or {}):
        del hass.data[DOMAIN][entry.entry_id]
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
