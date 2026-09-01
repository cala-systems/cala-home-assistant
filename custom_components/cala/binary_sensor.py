"""Binary sensors for Cala water heaters.

These entities were previously created by the sensor platform. Because Home
Assistant derives an entity's domain from the platform that adds it rather than
from its class, they landed at ``sensor.*_boost_mode_on`` despite subclassing
BinarySensorEntity -- so they carried no binary device class and could not be
found by a ``binary_sensor`` registry lookup. They now live here, where they
belong. See _async_migrate_binary_sensors in __init__.py for the migration.

The sensor platform owns the MQTT subscription, so these entities take their
updates from a dispatcher signal instead of subscribing a second time.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import (
    BINARY_FIELDS,
    CONF_DEVICE_ID,
    DOMAIN,
    SIGNAL_AVAILABILITY,
    SIGNAL_PAYLOAD,
)
from .entity import CalaBase

_LOGGER = logging.getLogger(__name__)

BINARY_DEVICE_CLASSES = {
    "upper_element_on": BinarySensorDeviceClass.HEAT,
    "lower_element_on": BinarySensorDeviceClass.HEAT,
    "boost_mode_on": BinarySensorDeviceClass.RUNNING,
    "fan_on": BinarySensorDeviceClass.RUNNING,
}


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "on", "1", "yes"):
            return True
        if low in ("false", "off", "0", "no"):
            return False
    return None


class CalaBinarySensor(CalaBase, BinarySensorEntity):
    def __init__(self, device_id: str, device_name: str, key: str, name: str) -> None:
        super().__init__(device_id, device_name)
        self._key = key
        self._attr_name = f"{device_name} {name}"
        self._attr_unique_id = f"cala_{device_id}_{key}"
        self._attr_device_class = BINARY_DEVICE_CLASSES.get(key)
        self._attr_is_on = None
        self._seen = False

    @property
    def available(self) -> bool:
        """Available once the device has actually sent this field.

        Firmware builds differ in which fields they publish, and a field that
        never arrives would otherwise sit at Unknown forever while reporting
        itself available. Only the first sighting flips this, so an
        intermittently absent key keeps the last value rather than flapping.
        """
        return self._attr_available and self._seen

    @callback
    def update_from_payload(self, payload: dict[str, Any]) -> None:
        coerced = _coerce_bool(payload.get(self._key))
        if coerced is None:
            return
        self._attr_is_on = coerced
        self._seen = True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    device_id = entry.data[CONF_DEVICE_ID]
    device_name = entry.data.get("device_name") or "Cala Water Heater"

    binaries = [
        CalaBinarySensor(device_id, device_name, key, name)
        for key, name in BINARY_FIELDS.items()
    ]

    # boost_services flips this optimistically when the device accepts a command
    boost = next((b for b in binaries if b._key == "boost_mode_on"), None)
    if boost is not None:
        hass.data.setdefault(DOMAIN, {}).setdefault("boost_entities", {})[
            device_id
        ] = boost

    async_add_entities(binaries)

    @callback
    def _on_payload(payload: dict[str, Any]) -> None:
        for b in binaries:
            try:
                b.update_from_payload(payload)
                b.async_write_ha_state()
            except Exception:
                _LOGGER.exception("Error updating binary sensor %s", b._key)

    @callback
    def _on_availability(available: bool) -> None:
        for b in binaries:
            b._attr_available = available
            b.async_write_ha_state()

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_PAYLOAD.format(entry_id=entry.entry_id), _on_payload
        )
    )
    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            SIGNAL_AVAILABILITY.format(entry_id=entry.entry_id),
            _on_availability,
        )
    )
