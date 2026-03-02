from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    ATTR_DEVICE_ID,
    SERVICE_START_BOOST,
    SERVICE_STOP_BOOST,
    ConnectionStatus,
)

from .boost_services import get_boost_entity_id
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

        entry = self._hass.config_entries.async_get_entry(self._entry_id)
        if entry is not None:
            data = dict(entry.data)
            data["_connection_initial_state"] = ConnectionStatus.PENDING
            self._hass.config_entries.async_update_entry(entry, data=data)

        await self._hass.config_entries.async_reload(self._entry_id)

class BoostButton(ButtonEntity):
    """Button that shows Start 24h Boost when off, Stop Boost when on."""

    def __init__(
        self,
        hass: HomeAssistant,
        device_id: str,
        boost_entity_id: str | None,
    ):
        self._hass = hass
        self._device_id = device_id
        self._boost_entity_id = boost_entity_id
        self._attr_name = "Start 24h Boost"
        self._attr_unique_id = f"{device_id}_boost_24h"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            manufacturer="Cala",
            model="HPWH",
            name=f"Cala {device_id}",
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to boost state changes."""
        if not self._boost_entity_id:
            _LOGGER.warning(
                "Cala button: device_id=%s no boost_entity_id, button will always show Start",
                self._device_id,
            )
            return

        initial_state = self._hass.states.get(self._boost_entity_id)
        _LOGGER.debug(
            "Cala button: device_id=%s subscribing to %s, initial_state=%s",
            self._device_id,
            self._boost_entity_id,
            initial_state.state if initial_state else "None",
        )
        # Set initial name/icon from current boost state
        self._update_name_and_icon(initial_state is not None and initial_state.state == "on")
        self._sync_entity_registry()

        @callback
        def _boost_state_changed(event):
            new_state = event.data.get("new_state")
            old_state = event.data.get("old_state")
            _LOGGER.debug(
                "Cala button: boost state changed device_id=%s %s -> %s",
                self._device_id,
                old_state.state if old_state else "None",
                new_state.state if new_state else "None",
            )
            # Update entity state
            self._update_name_and_icon(new_state is not None and new_state.state == "on")
            self.async_write_ha_state()
            self._sync_entity_registry()

        self.async_on_remove(
            async_track_state_change_event(
                self._hass,
                self._boost_entity_id,
                _boost_state_changed,
            )
        )

    def _boost_is_on(self) -> bool:
        """Return True if boost mode is currently on."""
        if not self._boost_entity_id:
            return False
        state = self._hass.states.get(self._boost_entity_id)
        return state is not None and state.state == "on"

    def _update_name_and_icon(self, boost_on: bool) -> None:
        """Set name and icon based on boost state."""
        if boost_on:
            self._attr_name = "Stop Boost"
            self._attr_icon = "mdi:stop-circle"
        else:
            self._attr_name = "Start 24h Boost"
            self._attr_icon = "mdi:play-circle"

    def _sync_entity_registry(self) -> None:
        """Update entity registry with current name/icon so device page displays correctly."""
        if self.entity_id:
            ent_reg = async_get_entity_registry(self._hass)
            ent_reg.async_update_entity(
                self.entity_id,
                name=self._attr_name,
                icon=self._attr_icon,
            )

    @property
    def name(self) -> str:
        """Return the name based on boost state."""
        return "Stop Boost" if self._boost_is_on() else "Start 24h Boost"

    @property
    def icon(self) -> str | None:
        """Return the icon based on boost state."""
        return "mdi:stop-circle" if self._boost_is_on() else "mdi:play-circle"

    async def async_press(self) -> None:
        """Start or stop boost based on current state."""
        boost_on = self._boost_is_on()
        _LOGGER.debug(
            "Cala button: async_press device_id=%s boost_is_on=%s -> %s",
            self._device_id,
            boost_on,
            SERVICE_STOP_BOOST if boost_on else SERVICE_START_BOOST,
        )
        if boost_on:
            await self._hass.services.async_call(
                DOMAIN,
                SERVICE_STOP_BOOST,
                {ATTR_DEVICE_ID: self._device_id},
                blocking=True,
            )
            return

        await self._hass.services.async_call(
            DOMAIN,
            SERVICE_START_BOOST,
            {
                ATTR_DEVICE_ID: self._device_id,
                "duration": 24,
            },
            blocking=True,
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
):
    device_id = entry.data[CONF_DEVICE_ID]
    boost_entity_id = get_boost_entity_id(hass, device_id)
    _LOGGER.info(
        "Cala button: async_setup_entry device_id=%s boost_entity_id=%s",
        device_id,
        boost_entity_id,
    )

    async_add_entities(
        [
            CalaReconnectButton(hass, entry),
            BoostButton(hass, device_id, boost_entity_id),
        ]
    )
