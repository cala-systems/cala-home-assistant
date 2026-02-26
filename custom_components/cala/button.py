from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import EntityCategory

from .const import DEVICE_MANUFACTURER, DEVICE_MODEL, DOMAIN, CONF_DEVICE_ID, CONF_DEVICE_NAME

_LOGGER = logging.getLogger(__name__)


class CalaReconnectButton(ButtonEntity):
    """Button that reloads the config entry in Settings -> Devices -> Cala -> [device] page"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry_id = entry.entry_id
        self._device_id = entry.data.get(CONF_DEVICE_ID, "unknown")
        device_name = entry.data.get(CONF_DEVICE_NAME) or "Cala Water Heater"

        self._attr_name = f"{device_name} Reconnect"
        self._attr_unique_id = f"cala_{self._device_id}_reconnect"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self.name.rsplit(" Reconnect", 1)[0],
            "manufacturer": DEVICE_MANUFACTURER,
            "model": DEVICE_MODEL,
        }

    async def async_press(self) -> None:
        """Reload the entry to re-run subscriptions and setup."""
        _LOGGER.info("Cala reconnect button pressed; reloading entry %s", self._entry_id)
        await self._hass.config_entries.async_reload(self._entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    async_add_entities([CalaReconnectButton(hass, entry)])
