from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import (
    UnitOfTemperature,
    UnitOfEnergy,
    UnitOfVolumeFlowRate,
    UnitOfVolume
)

from .const import DOMAIN, DEVICE_MANUFACTURER, DEVICE_MODEL

_LOGGER = logging.getLogger(__name__)

TELEMETRY_FIELDS = {
    "top_c": {
        "name": "Top Temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
    },
    "upper_c": {
        "name": "Upper Temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
    },
    "lower_c": {
        "name": "Lower Temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
    },
    "gallons_available": {
        "name": "Gallons Available",
        "unit": UnitOfVolume.GALLONS,
        "device_class": None,
    },
    "compressor_hz": {
        "name": "Compressor Frequency",
        "unit": "Hz",
        "device_class": None,
    },
    "energy_used_kwh": {
        "name": "Energy Used",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
    },
    "gallons_used": {
        "name": "Gallons Used",
        "unit": UnitOfVolume.GALLONS,
        "device_class": None,
    },

}

BINARY_FIELDS = {
    "upper_element_on": "Upper Element On",
    "lower_element_on": "Lower Element On",
    "boost_mode_on": "Boost Mode On",
}


def _payload_to_str(payload: Any) -> str:
    """
    Normalizing MQTT payload into a JSON string.
    """
    if payload is None:
        return ""

    if isinstance(payload, (bytes, bytearray)):
        return payload.decode("utf-8", errors="replace")

    if isinstance(payload, memoryview):
        return payload.tobytes().decode("utf-8", errors="replace")

    if isinstance(payload, str):
        return payload

    # Last resort: stringify whatever it is
    return str(payload)


class CalaBase:
    def __init__(self, device_id: str, device_name: str):
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": device_name,
            "manufacturer": DEVICE_MANUFACTURER,
            "model": DEVICE_MODEL,
        }


class CalaTelemetrySensor(CalaBase, SensorEntity):
    def __init__(self, device_id: str, device_name: str, key: str, meta: dict[str, Any]):
        super().__init__(device_id, device_name)
        self._key = key
        self._attr_name = f"{device_name} {meta['name']}"
        self._attr_unique_id = f"cala_{device_id}_{key}"
        self._attr_native_unit_of_measurement = meta.get("unit")
        self._attr_device_class = meta.get("device_class")
        self._attr_native_value = None

    def update_from_payload(self, payload: dict[str, Any]) -> None:
        if self._key in payload:
            self._attr_native_value = payload[self._key]


class CalaBinarySensor(CalaBase, BinarySensorEntity):
    def __init__(self, device_id: str, device_name: str, key: str, name: str):
        super().__init__(device_id, device_name)
        self._key = key
        self._attr_name = f"{device_name} {name}"
        self._attr_unique_id = f"cala_{device_id}_{key}"
        self._attr_is_on = False

    def update_from_payload(self, payload: dict[str, Any]) -> None:
        if self._key in payload:
            self._attr_is_on = bool(payload[self._key])


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    _LOGGER.error("CALA MQTT: sensor.py: async_setup_entry CALLED")
    device_id = entry.data["device_id"]
    device_name = entry.data["device_name"] or f"Cala Water Heater"
    state_topic = entry.data["state_topic"]

    sensors: list[SensorEntity] = [
        CalaTelemetrySensor(device_id, device_name, key, meta)
        for key, meta in TELEMETRY_FIELDS.items()
    ]
    binaries: list[BinarySensorEntity] = [
        CalaBinarySensor(device_id, device_name, key, name)
        for key, name in BINARY_FIELDS.items()
    ]

    async_add_entities(sensors + binaries)

    async def message_received(msg):
        raw = _payload_to_str(msg.payload)

        try:
            payload = json.loads(raw)
        except Exception as e:
            _LOGGER.warning("Invalid JSON on %s: %s (%s)", state_topic, raw, e)
            return

        if not isinstance(payload, dict):
            _LOGGER.warning("Unexpected payload type on %s: %s", state_topic, type(payload))
            return

        for s in sensors:
            s.update_from_payload(payload)
            s.async_write_ha_state()

        for b in binaries:
            b.update_from_payload(payload)
            b.async_write_ha_state()

    unsubscribe = await mqtt.async_subscribe(hass, state_topic, message_received, qos=0)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {}
    hass.data[DOMAIN][entry.entry_id]["mqtt_unsubscribe"] = unsubscribe
