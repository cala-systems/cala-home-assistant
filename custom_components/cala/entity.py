"""Shared entity base for the Cala platforms."""

from __future__ import annotations

from .const import DEVICE_MANUFACTURER, DEVICE_MODEL, DOMAIN


class CalaBase:
    def __init__(self, device_id: str, device_name: str) -> None:
        self._device_id = device_id
        self._device_name = device_name
        self._attr_available = True

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": DEVICE_MANUFACTURER,
            "model": DEVICE_MODEL,
            "serial_number": self._device_id,
        }
