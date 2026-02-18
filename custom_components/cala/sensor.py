from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import (
    UnitOfTemperature,
    UnitOfEnergy,
    UnitOfTime,
    UnitOfVolume
)

from .const import DOMAIN, DEVICE_MANUFACTURER, DEVICE_MODEL, ConnectionStatus

_LOGGER = logging.getLogger(__name__)

CONNECTION_TIMEOUT_S = 300  # 5 minutes without data → offline

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
    "delivery_c": {
        "name": "Delivery Temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
    },
    "ambient_c": {
        "name": "Ambient Temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
    },

    "uptime_sec": {
        "name": "Uptime",
        "unit": UnitOfTime.SECONDS,
        "device_class": SensorDeviceClass.DURATION,
    },
    "wifi_ip": {
        "name": "WiFi IP",
        "unit": None,
        "device_class": None,
    },
    "wifi_ssid": {
        "name": "WiFi SSID",
        "unit": None,
        "device_class": None,
    },
    "wifi_rssi_dbm": {
        "name": "WiFi Signal",
        "unit": "dBm",
        "device_class": SensorDeviceClass.SIGNAL_STRENGTH,
    },
    "fw_version": {
        "name": "Firmware Version",
        "unit": None,
        "device_class": None,
    },
}

BINARY_FIELDS = {
    "upper_element_on": "Upper Element On",
    "lower_element_on": "Lower Element On",
    "boost_mode_on": "Boost Mode On",
    "fan_on": "Fan On",
    "fan_speed_high": "Fan Speed High",
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


class CalaConnectionStatus(CalaBase, SensorEntity):
    """Sensor reporting device connection state: Pending → Connected → Offline."""

    def __init__(
        self, device_id: str, device_name: str, initial_state: ConnectionStatus = ConnectionStatus.OFFLINE
    ):
        super().__init__(device_id, device_name)
        self._attr_name = f"{device_name} Connection"
        self._attr_unique_id = f"cala_{device_id}_connection"
        self._attr_native_value = initial_state
        self._attr_device_class = SensorDeviceClass.ENUM
        self._attr_options = [ConnectionStatus.PENDING, ConnectionStatus.CONNECTED, ConnectionStatus.OFFLINE]

    def set_state(self, state: ConnectionStatus) -> None:
        """Set connection state."""
        self._attr_native_value = state


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
    _LOGGER.debug("CALA MQTT: sensor.py: async_setup_entry called")
    device_id = entry.data["device_id"]
    device_name = entry.data["device_name"] or "Cala Water Heater"
    state_topic = entry.data["state_topic"]

    # Pending = just paired (HTTP sent), Offline = restart/reload
    initial_state = (
        ConnectionStatus.PENDING
        if entry.data.get("_connection_initial_state") == ConnectionStatus.PENDING
        else ConnectionStatus.OFFLINE
    )
    if initial_state == ConnectionStatus.PENDING:
        data = {k: v for k, v in entry.data.items() if k != "_connection_initial_state"}
        hass.config_entries.async_update_entry(entry, data=data)

    connection_status = CalaConnectionStatus(device_id, device_name, initial_state)
    sensors: list[SensorEntity] = [
        CalaTelemetrySensor(device_id, device_name, key, meta)
        for key, meta in TELEMETRY_FIELDS.items()
    ]
    binaries: list[BinarySensorEntity] = [
        CalaBinarySensor(device_id, device_name, key, name)
        for key, name in BINARY_FIELDS.items()
    ]
    all_data_entities = sensors + binaries

    async_add_entities([connection_status] + sensors + binaries)

    timeout_timer_handle = None

    @callback
    def _on_timeout() -> None:
        nonlocal timeout_timer_handle
        timeout_timer_handle = None
        connection_status.set_state(ConnectionStatus.OFFLINE)
        connection_status.async_write_ha_state()
        for e in all_data_entities:
            e._attr_available = False
            e.async_write_ha_state()
        _LOGGER.info("Cala device %s: no data for %ds, set offline", device_id, CONNECTION_TIMEOUT_S)

    def message_received(msg):
        nonlocal timeout_timer_handle
        raw = _payload_to_str(msg.payload)

        try:
            payload = json.loads(raw)
        except Exception as e:
            _LOGGER.warning("Invalid JSON on %s: %s (%s)", state_topic, raw, e)
            return

        if not isinstance(payload, dict):
            _LOGGER.warning("Unexpected payload type on %s: %s", state_topic, type(payload))
            return

        _LOGGER.debug("Received payload on %s: %s", state_topic, payload)

        def _process_on_event_loop() -> None:
            nonlocal timeout_timer_handle
            if connection_status._attr_native_value in (ConnectionStatus.PENDING, ConnectionStatus.OFFLINE):
                was_offline = connection_status._attr_native_value == ConnectionStatus.OFFLINE
                connection_status.set_state(ConnectionStatus.CONNECTED)
                connection_status.async_write_ha_state()
                if was_offline:
                    for e in all_data_entities:
                        e._attr_available = True

            if timeout_timer_handle is not None:
                timeout_timer_handle.cancel()
            timeout_timer_handle = hass.loop.call_later(CONNECTION_TIMEOUT_S, _on_timeout)

            for s in sensors:
                try:
                    s.update_from_payload(payload)
                    s.async_write_ha_state()
                except Exception as e:
                    _LOGGER.warning("Error updating sensor %s: %s", s._key, e)

            for b in binaries:
                try:
                    b.update_from_payload(payload)
                    b.async_write_ha_state()
                except Exception as e:
                    _LOGGER.warning("Error updating binary sensor %s: %s", b._key, e)

        hass.loop.call_soon_threadsafe(_process_on_event_loop)

    unsubscribe = await mqtt.async_subscribe(hass, state_topic, message_received, qos=0)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}
    hass.data[DOMAIN][entry.entry_id]["mqtt_unsubscribe"] = unsubscribe
    hass.data[DOMAIN][entry.entry_id]["timeout_timer"] = lambda: (
        timeout_timer_handle.cancel() if timeout_timer_handle is not None else None
    )
