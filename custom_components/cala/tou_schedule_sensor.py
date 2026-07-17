"""Diagnostic sensor exposing the last published TOU schedule.

State is the publish timestamp; the schedule itself rides in attributes so
the cala-tou-card can prefill its editor. RestoreEntity re-seeds the store
after a restart, so the card keeps its prefill without a new publish.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DEVICE_MANUFACTURER, DEVICE_MODEL, DOMAIN
from .tou_services import active_feed_entity, configured_feed_entity
from .tou_store import (
    SIGNAL_TOU_SCHEDULE_RECORDED,
    get_published_schedule,
    seed_published_schedule,
)


class CalaTouScheduleSensor(RestoreEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:calendar-clock"
    _attr_should_poll = False

    def __init__(
        self, entry: ConfigEntry, device_id: str, device_name: str
    ) -> None:
        self._entry = entry
        self._device_id = device_id
        self._device_name = device_name
        self._attr_name = f"{device_name} TOU Schedule"
        self._attr_unique_id = f"cala_{device_id}_tou_schedule"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": DEVICE_MANUFACTURER,
            "model": DEVICE_MODEL,
            "serial_number": self._device_id,
        }

    @property
    def native_value(self) -> str | None:
        record = get_published_schedule(self.hass, self._device_id)
        return record["published_at"] if record else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        record = get_published_schedule(self.hass, self._device_id)
        feed_entity = active_feed_entity(self.hass, self._entry)
        return {
            "cala_tou_device": self._device_id,
            "schedule": record["schedule"] if record else None,
            # When a configured price feed currently owns the schedule the
            # card renders read-only; None when the card may edit freely.
            "feed_active_entity": feed_entity,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last and last.attributes.get("schedule"):
            published_at = (
                last.state
                if last.state not in ("unknown", "unavailable", "")
                else None
            )
            seed_published_schedule(
                self.hass,
                self._device_id,
                last.attributes["schedule"],
                published_at,
            )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_TOU_SCHEDULE_RECORDED.format(device_id=self._device_id),
                self._schedule_recorded,
            )
        )
        # Re-publish state when the feed entity changes so feed_active_entity
        # (and thus the card's read-only banner) stays current.
        feed_entity = configured_feed_entity(self._entry)
        if feed_entity:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [feed_entity], self._feed_changed
                )
            )

    @callback
    def _schedule_recorded(self) -> None:
        self.async_write_ha_state()

    @callback
    def _feed_changed(self, event) -> None:
        self.async_write_ha_state()
