from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    UnitOfEnergy,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store

from .const import CONNECTION_STATUS, DEVICE_MANUFACTURER, DEVICE_MODEL, DOMAIN, ConnectionStatus

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
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "wifi_ip": {
        "name": "WiFi IP",
        "unit": None,
        "device_class": None,
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "wifi_ssid": {
        "name": "WiFi SSID",
        "unit": None,
        "device_class": None,
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "wifi_rssi_dbm": {
        "name": "WiFi Signal",
        "unit": "dBm",
        "device_class": SensorDeviceClass.SIGNAL_STRENGTH,
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "fw_version": {
        "name": "Firmware Version",
        "unit": None,
        "device_class": None,
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
}

STORAGE_VERSION = 1
STORAGE_KEY = "cala_totalizer"

BINARY_FIELDS = {
    "upper_element_on": "Upper Element On",
    "lower_element_on": "Lower Element On",
    "boost_mode_on": "Boost Mode On",
    "fan_on": "Fan On",
    "fan_speed_high": "Fan Speed High",
}


def _payload_to_str(payload: Any) -> str:
    """Normalize MQTT payload into a string."""
    if payload is None:
        return ""

    if isinstance(payload, (bytes, bytearray)):
        return payload.decode("utf-8", errors="replace")

    if isinstance(payload, memoryview):
        return payload.tobytes().decode("utf-8", errors="replace")

    if isinstance(payload, str):
        return payload
    return str(payload)


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        # allow strings like "12.0"
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return None
    s = str(value).strip()
    return s if s else None


def _coerce_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "t", "yes", "y", "on", "1"):
            return True
        if v in ("false", "f", "no", "n", "off", "0"):
            return False
    return None


def _coerce_telemetry_value(key: str, value: Any) -> Any:
    """Return a safe scalar for HA state, or None to ignore."""
    if key in ("wifi_ip", "wifi_ssid", "fw_version"):
        return _coerce_str(value)
    if key in ("uptime_sec",):
        return _coerce_int(value)
    if key in ("wifi_rssi_dbm",):
        return _coerce_int(value)
    # everything else in TELEMETRY_FIELDS is numeric
    return _coerce_float(value)


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
        }


class CalaConnectionStatus(CalaBase, SensorEntity):
    """Sensor reporting device connection state: Pending → Connected → Offline."""

    def __init__(
        self,
        device_id: str,
        device_name: str,
        initial: ConnectionStatus,
    ) -> None:
        super().__init__(device_id, device_name)
        self._attr_name = f"{device_name} Connection"
        self._attr_unique_id = f"cala_{device_id}_connection"
        self._attr_native_value = initial.value
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    def set_state(self, state: ConnectionStatus) -> None:
        self._attr_native_value = state.value


class CalaTelemetrySensor(CalaBase, SensorEntity):
    def __init__(self, device_id: str, device_name: str, key: str, meta: dict[str, Any]) -> None:
        super().__init__(device_id, device_name)
        self._key = key
        self._attr_name = f"{device_name} {meta['name']}"
        self._attr_unique_id = f"cala_{device_id}_{key}"
        self._attr_native_unit_of_measurement = meta.get("unit")
        self._attr_device_class = meta.get("device_class")
        self._attr_entity_category = meta.get("entity_category")
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_value = None

    def update_from_payload(self, payload: dict[str, Any]) -> None:
        raw = payload.get(self._key)
        coerced = _coerce_telemetry_value(self._key, raw)
        # If coercion fails, ignore this update
        if coerced is None:
            return
        self._attr_native_value = coerced


class CalaBinarySensor(CalaBase, BinarySensorEntity):
    def __init__(self, device_id: str, device_name: str, key: str, name: str) -> None:
        super().__init__(device_id, device_name)
        self._key = key
        self._attr_name = f"{device_name} {name}"
        self._attr_unique_id = f"cala_{device_id}_{key}"
        self._attr_is_on = None

    def update_from_payload(self, payload: dict[str, Any]) -> None:
        raw = payload.get(self._key)
        coerced = _coerce_bool(raw)
        if coerced is None:
            return
        self._attr_is_on = coerced


class CalaTotalizer:
    def __init__(self, hass: HomeAssistant, device_id: str) -> None:
        self._hass = hass
        self._device_id = device_id
        self._store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{device_id}")
        self._last_energy: float | None = None
        self._last_gallons: float | None = None
        self._today_energy: float = 0.0
        self._today_gallons: float = 0.0
        self._last_date: str | None = None

    async def _load(self) -> None:
        data = await self._store.async_load() or {}
        self._last_energy = _coerce_float(data.get("last_energy"))
        self._last_gallons = _coerce_float(data.get("last_gallons"))
        self._today_energy = float(data.get("today_energy") or 0.0)
        self._today_gallons = float(data.get("today_gallons") or 0.0)
        self._last_date = data.get("last_date") or date.today().isoformat()

    async def _save(self) -> None:
        await self._store.async_save(
            {
                "last_energy": self._last_energy,
                "last_gallons": self._last_gallons,
                "today_energy": self._today_energy,
                "today_gallons": self._today_gallons,
                "last_date": self._last_date,
            }
        )

    def _rollover_if_needed(self) -> None:
        today = date.today().isoformat()
        if self._last_date != today:
            self._today_energy = 0.0
            self._today_gallons = 0.0
            self._last_date = today

    def update(self, energy_total: float | None, gallons_total: float | None) -> None:
        self._rollover_if_needed()

        if energy_total is not None:
            if self._last_energy is not None and energy_total >= self._last_energy:
                self._today_energy += energy_total - self._last_energy
            self._last_energy = energy_total

        if gallons_total is not None:
            if self._last_gallons is not None and gallons_total >= self._last_gallons:
                self._today_gallons += gallons_total - self._last_gallons
            self._last_gallons = gallons_total

        self._hass.async_create_task(self._save())

    @callback
    def _on_midnight(self, now: datetime) -> None:
        self._today_energy = 0.0
        self._today_gallons = 0.0
        self._last_date = date.today().isoformat()
        self._hass.async_create_task(self._save())

    def energy_today(self) -> float | None:
        return self._today_energy if self._last_energy is not None else None

    def today_last_reset(self) -> datetime | None:
        if self._last_date is None:
            return None
        return datetime.combine(date.fromisoformat(self._last_date), datetime.min.time())

    def energy_cumulative(self) -> float | None:
        return self._last_energy

    def water_today(self) -> float | None:
        return self._today_gallons if self._last_gallons is not None else None

    def water_cumulative(self) -> float | None:
        return self._last_gallons

    def register_midnight_listener(self) -> None:
        async_track_time_change(self._hass, self._on_midnight, hour=0, minute=0, second=0)


class CalaEnergyTodaySensor(CalaBase, SensorEntity):
    def __init__(self, device_id: str, device_name: str, totalizer: CalaTotalizer):
        super().__init__(device_id, device_name)
        self._totalizer = totalizer
        self._attr_name = f"{device_name} Energy Today"
        self._attr_unique_id = f"cala_{device_id}_energy_today"
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_value = None
        self._attr_last_reset = None

    def update_value(self) -> None:
        self._attr_native_value = self._totalizer.energy_today()
        self._attr_last_reset = self._totalizer.today_last_reset()


class CalaEnergyCumulativeSensor(CalaBase, SensorEntity):
    def __init__(self, device_id: str, device_name: str, totalizer: CalaTotalizer):
        super().__init__(device_id, device_name)
        self._totalizer = totalizer
        self._attr_name = f"{device_name} Energy Total"
        self._attr_unique_id = f"cala_{device_id}_energy_cumulative"
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_native_value = None

    def update_value(self) -> None:
        self._attr_native_value = self._totalizer.energy_cumulative()


class CalaWaterTodaySensor(CalaBase, SensorEntity):
    def __init__(self, device_id: str, device_name: str, totalizer: CalaTotalizer):
        super().__init__(device_id, device_name)
        self._totalizer = totalizer
        self._attr_name = f"{device_name} Water Today"
        self._attr_unique_id = f"cala_{device_id}_water_today"
        self._attr_native_unit_of_measurement = UnitOfVolume.GALLONS
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_value = None
        self._attr_last_reset = None

    def update_value(self) -> None:
        self._attr_native_value = self._totalizer.water_today()
        self._attr_last_reset = self._totalizer.today_last_reset()


class CalaWaterCumulativeSensor(CalaBase, SensorEntity):
    def __init__(self, device_id: str, device_name: str, totalizer: CalaTotalizer):
        super().__init__(device_id, device_name)
        self._totalizer = totalizer
        self._attr_name = f"{device_name} Water Total"
        self._attr_unique_id = f"cala_{device_id}_water_cumulative"
        self._attr_native_unit_of_measurement = UnitOfVolume.GALLONS
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_native_value = None

    def update_value(self) -> None:
        self._attr_native_value = self._totalizer.water_cumulative()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    _LOGGER.debug("CALA MQTT: sensor.py: async_setup_entry called")
    device_id = entry.data["device_id"]
    device_name = entry.data.get("device_name") or "Cala Water Heater"
    state_topic = entry.data["state_topic"]

    availability_topic = entry.data.get("availability_topic") or f"cala/{device_id}/availability"

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
    totalizer = CalaTotalizer(hass, device_id)
    await totalizer._load()
    totalizer.register_midnight_listener()
    totalizer_sensors: list[SensorEntity] = [
        CalaEnergyTodaySensor(device_id, device_name, totalizer),
        CalaEnergyCumulativeSensor(device_id, device_name, totalizer),
        CalaWaterTodaySensor(device_id, device_name, totalizer),
        CalaWaterCumulativeSensor(device_id, device_name, totalizer),
    ]
    all_data_entities = sensors + binaries + totalizer_sensors

    async_add_entities([connection_status] + sensors + binaries + totalizer_sensors)
    _set_entities_available(connection_status._attr_native_value == ConnectionStatus.CONNECTED.value)

    timeout_timer_handle = None

    def _set_entities_available(available: bool) -> None:
        for e in all_data_entities:
            e._attr_available = available
            e.async_write_ha_state()

    @callback
    def _on_timeout() -> None:
        nonlocal timeout_timer_handle
        timeout_timer_handle = None
        connection_status.set_state(ConnectionStatus.OFFLINE)
        connection_status.async_write_ha_state()
        _set_entities_available(False)
        _LOGGER.info(
            "Cala device %s: no valid telemetry for %ds, set offline",
            device_id,
            CONNECTION_TIMEOUT_S,
        )

    def _refresh_timeout() -> None:
        nonlocal timeout_timer_handle
        if timeout_timer_handle is not None:
            timeout_timer_handle.cancel()
        timeout_timer_handle = hass.loop.call_later(CONNECTION_TIMEOUT_S, _on_timeout)

    def _mark_connected_if_needed() -> None:
        # Called only after we processed a valid dict payload
        if connection_status._attr_native_value in (
            ConnectionStatus.PENDING.value,
            ConnectionStatus.OFFLINE.value,
        ):
            was_offline = connection_status._attr_native_value == ConnectionStatus.OFFLINE.value
            connection_status.set_state(ConnectionStatus.CONNECTED)
            connection_status.async_write_ha_state()
            if was_offline:
                _set_entities_available(True)

    def availability_received(msg) -> None:
        """
        Availability is authoritative for online/offline. It must never raise.
        Accepted: 'online' / 'offline' (case-insensitive), anything else is ignored.
        """
        try:
            raw = _payload_to_str(msg.payload).strip().lower()
            if raw not in ("online", "offline"):
                _LOGGER.debug("Ignoring availability payload on %s: %r", availability_topic, raw)
                return

            if raw == "offline":
                nonlocal timeout_timer_handle
                if timeout_timer_handle is not None:
                    timeout_timer_handle.cancel()
                    timeout_timer_handle = None
                if connection_status._attr_native_value != ConnectionStatus.OFFLINE:
                    _LOGGER.info("Cala device %s availability=offline", device_id)
                connection_status.set_state(ConnectionStatus.OFFLINE)
                connection_status.async_write_ha_state()
                _set_entities_available(False)
                return

            # online
            if connection_status._attr_native_value == ConnectionStatus.OFFLINE.value:
                # Online but waiting for valid state telemetry
                _LOGGER.info("Cala device %s availability=online", device_id)
                connection_status.set_state(ConnectionStatus.PENDING)
                connection_status.async_write_ha_state()
                _set_entities_available(False)
        except Exception:
            _LOGGER.exception("Unhandled error in availability_received for %s", device_id)

    def message_received(msg) -> None:
        """
        State telemetry handler.
        Rules:
          - Must never raise.
          - Must ignore broken JSON / non-dict payloads.
          - Must only refresh timeout after a valid dict payload was processed.
        """
        try:
            raw = _payload_to_str(msg.payload)

            try:
                payload = json.loads(raw)
            except Exception as e:
                _LOGGER.warning("Invalid JSON on %s: %s (%s)", state_topic, raw, e)
                return

            if not isinstance(payload, dict):
                _LOGGER.warning("Unexpected payload type on %s: %s", state_topic, type(payload))
                return

            async def _process_payload() -> None:
                energy = _coerce_float(payload.get("energy_used_kwh"))
                gallons = _coerce_float(payload.get("gallons_used"))
                totalizer.update(energy, gallons)

                _mark_connected_if_needed()
                _refresh_timeout()

                # Update entities with coercion/ignore semantics.
                for s in sensors:
                    try:
                        s.update_from_payload(payload)
                        s.async_write_ha_state()
                    except Exception:
                        _LOGGER.exception("Error updating sensor %s", getattr(s, "_key", "?"))

                for b in binaries:
                    try:
                        b.update_from_payload(payload)
                        b.async_write_ha_state()
                    except Exception:
                        _LOGGER.exception("Error updating binary sensor %s", getattr(b, "_key", "?"))

                for t in totalizer_sensors:
                    try:
                        t.update_value()
                        t.async_write_ha_state()
                    except Exception:
                        _LOGGER.exception("Error updating totalizer sensor %s", getattr(t, "_attr_name", "?"))

            hass.async_create_task(_process_payload())
        except Exception:
            _LOGGER.exception("Unhandled error in message_received for %s", device_id)

    unsub_state = await mqtt.async_subscribe(hass, state_topic, message_received, qos=0)
    unsub_avail = await mqtt.async_subscribe(hass, availability_topic, availability_received, qos=0)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}
    hass.data[DOMAIN][entry.entry_id]["mqtt_unsubscribes"] = [unsub_state, unsub_avail]
    hass.data[DOMAIN][entry.entry_id]["timeout_timer"] = lambda: (
        timeout_timer_handle.cancel() if timeout_timer_handle is not None else None
    )
