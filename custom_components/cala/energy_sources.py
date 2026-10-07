"""Solar, grid and battery entities taken from HA's Energy dashboard settings.

The Energy settings already name the homeowner's power sensors, and HA
normalises their signs: a grid stat_rate is positive when importing and a
battery stat_rate is positive when discharging, even when the user configured
an inverted or two-sensor setup (HA then points stat_rate at a generated
sensor). So nothing here needs asking.
"""

import logging

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .const import (
    BATTERY_SIGN_POSITIVE_IS_DISCHARGING,
    CONF_BATTERY_POWER_ENTITY,
    CONF_BATTERY_POWER_SIGN,
    CONF_BATTERY_SOC_ENTITY,
    CONF_GRID_EXPORT_ENTITY,
    CONF_GRID_IMPORT_ENTITY,
    CONF_GRID_POWER_ENTITY,
    CONF_GRID_POWER_SIGN,
    CONF_GRID_STATUS_ENTITY,
    CONF_GRID_STATUS_INVERT,
    CONF_MANUAL_CONTEXT,
    CONF_SOLAR_PRODUCTION_ENTITY,
    DOMAIN,
    GRID_SIGN_POSITIVE_IS_IMPORT,
)

_LOGGER = logging.getLogger(__name__)

# Option keys that describe where the context comes from. In automatic mode
# these are replaced wholesale by the Energy-derived mapping.
CONTEXT_SOURCE_KEYS = (
    CONF_SOLAR_PRODUCTION_ENTITY,
    CONF_GRID_POWER_ENTITY,
    CONF_GRID_POWER_SIGN,
    CONF_GRID_IMPORT_ENTITY,
    CONF_GRID_EXPORT_ENTITY,
    CONF_GRID_STATUS_ENTITY,
    CONF_GRID_STATUS_INVERT,
    CONF_BATTERY_SOC_ENTITY,
    CONF_BATTERY_POWER_ENTITY,
    CONF_BATTERY_POWER_SIGN,
)

_LISTENER_KEY = "_energy_listener"
MAPPING_KEY = "energy_mapping"


def _entity_id(stat_id) -> str | None:
    """stat_rate/stat_soc as an entity id; external statistics (domain:id) have no live state."""
    if isinstance(stat_id, str) and stat_id and ":" not in stat_id:
        return stat_id
    return None


def _first(sources: list[dict], source_type: str, key: str) -> str | None:
    found = [
        entity_id
        for source in sources
        if source.get("type") == source_type
        and (entity_id := _entity_id(source.get(key)))
    ]
    if len(found) > 1:
        _LOGGER.info(
            "Energy settings list %d %s %s sensors; Cala uses the first, %s",
            len(found), source_type, key, found[0],
        )
    return found[0] if found else None


def mapping_from_energy_prefs(prefs: dict | None) -> dict:
    """Context options for the power sensors named in the Energy settings."""
    sources = (prefs or {}).get("energy_sources") or []
    mapping: dict = {}

    if solar := _first(sources, "solar", "stat_rate"):
        mapping[CONF_SOLAR_PRODUCTION_ENTITY] = solar

    if grid := _first(sources, "grid", "stat_rate"):
        mapping[CONF_GRID_POWER_ENTITY] = grid
        mapping[CONF_GRID_POWER_SIGN] = GRID_SIGN_POSITIVE_IS_IMPORT

    if battery := _first(sources, "battery", "stat_rate"):
        mapping[CONF_BATTERY_POWER_ENTITY] = battery
        mapping[CONF_BATTERY_POWER_SIGN] = BATTERY_SIGN_POSITIVE_IS_DISCHARGING

    if soc := _first(sources, "battery", "stat_soc"):
        mapping[CONF_BATTERY_SOC_ENTITY] = soc

    return mapping


def effective_context_options(opts: dict, energy_mapping: dict) -> dict:
    """The options the publisher should use: hand-mapped if asked for, else from Energy."""
    if opts.get(CONF_MANUAL_CONTEXT):
        return dict(opts)
    auto = {k: v for k, v in opts.items() if k not in CONTEXT_SOURCE_KEYS}
    auto.update(energy_mapping)
    return auto


async def async_energy_mapping(hass: HomeAssistant) -> dict:
    """Mapping from the current Energy settings, or {} if they can't be read."""
    try:
        from homeassistant.components.energy.data import async_get_manager

        manager = await async_get_manager(hass)
    except Exception as exc:  # noqa: BLE001 - Energy is optional
        _LOGGER.warning("Could not read the Energy dashboard settings: %s", exc)
        return {}
    return mapping_from_energy_prefs(manager.data)


async def async_setup_energy_listener(hass: HomeAssistant) -> None:
    """Reload automatic-mode entries when the Energy settings change (once per HA)."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(_LISTENER_KEY):
        return
    try:
        from homeassistant.components.energy.data import async_get_manager

        manager = await async_get_manager(hass)
    except Exception as exc:  # noqa: BLE001 - Energy is optional
        _LOGGER.debug("Energy settings unavailable, not watching them: %s", exc)
        return

    async def _on_energy_update() -> None:
        mapping = mapping_from_energy_prefs(manager.data)
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.state is not ConfigEntryState.LOADED:
                continue
            if (entry.options or {}).get(CONF_MANUAL_CONTEXT):
                continue
            current = domain_data.get(entry.entry_id, {}).get(MAPPING_KEY)
            if current == mapping:
                continue
            _LOGGER.info(
                "Energy settings changed; reloading Cala %s to publish %s",
                entry.title, mapping,
            )
            hass.config_entries.async_schedule_reload(entry.entry_id)

    manager.async_listen_updates(_on_energy_update)
    domain_data[_LISTENER_KEY] = True
