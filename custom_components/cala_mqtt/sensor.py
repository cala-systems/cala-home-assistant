from __future__ import annotations

import json
import logging

from homeassistant.components import mqtt
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import (
    UnitOfTemperature,
    UnitOfEnergy,
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
        "unit": "gal",
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
}

BINARY_FIELDS = {
    "upper_element_on": "Upper Element",
    "lower_element_on": "Lower Element",
    "boost_mode_on": "Boost Mode",
}


class CalaBase:
    def __init__(self, device_id: str, device_name: str):
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": device_name,
            "manufacturer": DEVICE_MANUFACTURER,
            "model": DEVICE_MODEL,
        }


class CalaTelemetrySensor(CalaBase, SensorEntity):
    def __init__(self, device_id, device_name, key, meta):
        super().__init__(device_id, device_name)

        self._key = key
        self._attr_name = f"{device_name} {meta['name']}"
        self._attr_unique_id = f"cala_{device_id}_{key}"
        self._attr_native_unit_of_measurement = meta["unit"]
        self._attr_device_class = meta.get("device_class")
        self._attr_native_value = None

    def update_from_payload(self, payload: dict):
        if self._key in payload:
            self._attr_native_value = payload[self._key]


class CalaBinarySensor(CalaBase, BinarySensorEntity):
    def __init__(self, device_id, device_name, key, name):
        super().__init__(device_id, device_name)

        self._key = key
        self._attr_name = f"{device_name} {name}"
        self._attr_unique_id = f"cala_{device_id}_{key}"
        self._attr_is_on = False

    def update_from_payload(self, payload: dict):
        if self._key in payload:
            self._attr_is_on = bool(payload[self._key])


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
):
    device_id = entry.data["device_id"]
    device_name = entry.data["device_name"]
    state_topic = entry.data["state_topic"]

    sensors: list[SensorEntity] = []
    binaries: list[BinarySensorEntity] = []

    for key, meta in TELEMETRY_FIELDS.items():
        sensors.append(
            CalaTelemetrySensor(device_id, device_name, key, meta)
        )

    for key, name in BINARY_FIELDS.items():
        binaries.append(
            CalaBinarySensor(device_id, device_name, key, name)
        )

    async_add_entities(sensors + binaries)

    async def message_received(msg):
        try:
            payload = json.loads(msg.payload)
        except Exception as e:
            _LOGGER.warning("Invalid JSON on %s: %s (%s)", state_topic, msg.payload, e)
            return

        for s in sensors:
            s.update_from_payload(payload)
            s.async_write_ha_state()

        for b in binaries:
            b.update_from_payload(payload)
            b.async_write_ha_state()

    await mqtt.async_subscribe(hass, state_topic, message_received, qos=1)