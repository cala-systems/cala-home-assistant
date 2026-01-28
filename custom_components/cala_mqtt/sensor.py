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
    PERCENTAGE,
)

from .const import DOMAIN, DEVICE_MANUFACTURER, DEVICE_MODEL

_LOGGER = logging.getLogger(__name__)

# Matches what your firmware is actually reporting (from the log you pasted)
TELEMETRY_FIELDS = {
    "topTankTemp": {
        "name": "Top Tank Temp",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
    },
    "upperTankTemp": {
        "name": "Upper Tank Temp",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
    },
    "lowerTankTemp": {
        "name": "Lower Tank Temp",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
    },
    "ambientTemp": {
        "name": "Ambient Temp",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
    },
    "ambientHumidity": {
        "name": "Ambient Humidity",
        "unit": PERCENTAGE,
        "device_class": None,
    },
    "deliveryTemp": {
        "name": "Delivery Temp",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
    },
    "dischargeTemp": {
        "name": "Discharge Temp",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
    },
    "suctionLineTemp": {
        "name": "Suction Line Temp",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
    },
    "liquidLineTemp": {
        "name": "Liquid Line Temp",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
    },
    "energyUsed": {
        "name": "Energy Used",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
    },
    "compFreq": {
        "name": "Compressor Frequency",
        "unit": "Hz",
        "device_class": None,
    },
    "hotLiters": {
        "name": "Hot Liters Available",
        "unit": "L",
        "device_class": None,
    },
    "userMaxTemp": {
        "name": "User Max Temp",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
    },
    "userDesiredTemp": {
        "name": "User Desired Temp",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
    },
    "uptime": {
        "name": "Uptime",
        "unit": "s",
        "device_class": None,
    },
}

BINARY_FIELDS = {
    "upperElementPwr": "Upper Element Power",
    "lowerElementPwr": "Lower Element Power",
    "fanPwr": "Fan Power",
    "compPwr": "Compressor Power",
    "compRunning": "Compressor Running",
    "inBoostMode": "Boost Mode",
    "safetyLockout": "Safety Lockout",
}


def _extract_reported(payload: Any) -> dict[str, Any] | None:
    """Supports either flat telemetry or AWS shadow style state.reported."""
    if not isinstance(payload, dict):
        return None

    state = payload.get("state")
    if isinstance(state, dict):
        reported = state.get("reported")
        if isinstance(reported, dict):
            return reported

    # fallback: treat as already-flat telemetry dict
    return payload


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
    device_id = entry.data["device_id"]
    device_name = entry.data["device_name"]
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
        try:
            raw = msg.payload.decode("utf-8", errors="replace")
            payload = json.loads(raw)
        except Exception as e:
            _LOGGER.warning("Invalid JSON on %s: %s (%s)", state_topic, msg.payload, e)
            return

        reported = _extract_reported(payload)
        if not isinstance(reported, dict):
            return

        for s in sensors:
            s.update_from_payload(reported)
            s.async_write_ha_state()

        for b in binaries:
            b.update_from_payload(reported)
            b.async_write_ha_state()

    await mqtt.async_subscribe(hass, state_topic, message_received, qos=1)