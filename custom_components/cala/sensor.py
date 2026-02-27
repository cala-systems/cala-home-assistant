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
    UnitOfPower,
    UnitOfTime,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.helpers import issue_registry as ir
from .helpers import parse_mqtt_json_payload
from .const import (
    CONF_COMMAND_TOPIC,
    CONF_DEVICE_ID,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
    LITERS_TO_GALLONS,
    ConnectionStatus,
)

_LOGGER = logging.getLogger(__name__)

CONNECTION_TIMEOUT_S = 300  # 5 minutes without data → offline
REPAIR_OFFLINE_AFTER_S = 900  # 15 minutes offline → raise a Repair Issue
REPAIR_ISSUE_ID_TPL = "offline_prolonged_{device_id}"

TELEMETRY_FIELDS = {
    "top_c": {
        "name": "Top Temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "upper_c": {
        "name": "Upper Temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "lower_c": {
        "name": "Lower Temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "liters_available": {
        "name": "Water Available",
        "unit": UnitOfVolume.LITERS,
        "device_class": SensorDeviceClass.WATER,
        "state_class": None,  # tank level, not cumulative; WATER allows only total/total_increasing/None
    },
    "compressor_hz": {
        "name": "Compressor Frequency",
        "unit": "Hz",
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "energy_used_kwh": {
        "name": "Power",
        "unit": UnitOfPower.KILO_WATT,
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
        "scale": 60,  # device sends kWh used in last min -> kW (kWh/min * 60 = kW)
    },
    "liters_used": {
        "name": "Flow Rate",
        "unit": UnitOfVolumeFlowRate.GALLONS_PER_MINUTE,
        "device_class": None,  # flow rate (vol/time), not volume; WATER expects total/total_increasing
        "state_class": SensorStateClass.MEASUREMENT,
        "scale": 0.264172,  # L/min -> US gal/min
    },
    "delivery_c": {
        "name": "Delivery Temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "ambient_c": {
        "name": "Ambient Temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
    },

    "uptime_sec": {
        "name": "Uptime",
        "unit": UnitOfTime.SECONDS,
        "device_class": SensorDeviceClass.DURATION,
        "entity_category": EntityCategory.DIAGNOSTIC,
        "state_class": SensorStateClass.TOTAL,
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
        "state_class": SensorStateClass.MEASUREMENT,
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
            "serial_number": self._device_id,
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
        # Most telemetry values are numeric measurements but string fields (fw_version, wifi_ip, wifi_ssid) should not declare a state_class,
        # because HA assumes they are numeric and will throw on async_write_ha_state error.
        if key in ("fw_version", "wifi_ip", "wifi_ssid"):
            self._attr_state_class = None
        elif key in ("energy_used_kwh", "gallons_used"):
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        else:
            self._attr_state_class = meta.get("state_class")
        
        self._attr_native_value = None
        self._scale = meta.get("scale", 1)

    def update_from_payload(self, payload: dict[str, Any]) -> None:
        raw = payload.get(self._key)
        coerced = _coerce_telemetry_value(self._key, raw)
        if coerced is None:
            return
        if self._scale != 1:
            try:
                val = float(coerced) * self._scale
                self._attr_native_value = round(val, 3)
            except (TypeError, ValueError):
                return
        else:
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
    """Accumulates energy and liters (both per-min rates, summed). Rolls over at midnight."""
    def __init__(self, hass: HomeAssistant, device_id: str) -> None:
        self._hass = hass
        self._device_id = device_id
        self._store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{device_id}")
        self._today_energy = 0.0
        self._today_liters = 0.0
        self._total_energy = 0.0
        self._total_liters = 0.0
        self._last_energy: float | None = None
        self._last_liters: float | None = None
        self._last_date: str | None = None

    async def _load(self) -> None:
        data = await self._store.async_load()
        if data:
            self._today_energy = _coerce_float(data.get("today_energy", 0))
            self._today_liters = _coerce_float(data.get("today_liters", 0))
            self._total_energy = _coerce_float(data.get("total_energy", 0))
            self._total_liters = _coerce_float(data.get("total_liters", 0))
            self._last_energy = _coerce_float(data.get("last_energy", 0))
            self._last_liters = _coerce_float(data.get("last_liters", 0))
            self._last_date = data.get("last_date")

    def _persist(self) -> None:
        self._store.async_delay_save(
            lambda: {
                "today_energy": self._today_energy,
                "today_liters": self._today_liters,
                "total_energy": self._total_energy,
                "total_liters": self._total_liters,
                "last_energy": self._last_energy,
                "last_liters": self._last_liters,
                "last_date": self._last_date,
            }
        )

    def _rollover_if_needed(self) -> None:
        today = date.today().isoformat()
        if self._last_date != today:
            self._today_energy = 0.0
            self._today_liters = 0.0
            self._last_date = today

    def update(self, energy_kwh: float | None, liters: float | None) -> None:
        """Process new values from device. Both energy and liters are per-minute rates;
        sum each reading directly (device sends every minute)."""
        today_str = date.today().isoformat()
        if self._last_date != today_str:
            self._today_energy = 0.0
            self._today_liters = 0.0
            self._last_date = today_str

        if energy_kwh is not None:
            if energy_kwh < 0:
                _LOGGER.warning(
                    "Cala totalizer: negative energy_used_kwh rejected: %s (device: %s)",
                    energy_kwh,
                    self._device_id,
                )
            else:
                self._today_energy += energy_kwh
                self._total_energy += energy_kwh
                self._last_energy = energy_kwh

        if liters is not None:
            if liters < 0:
                _LOGGER.warning(
                    "Cala totalizer: negative liters_used rejected: %s (device: %s)",
                    liters,
                    self._device_id,
                )
            else:
                self._today_liters += liters
                self._total_liters += liters
                self._last_liters = liters

        self._persist()

    @callback
    def _on_midnight(self, now: datetime) -> None:
        """Rollover at midnight: reset today's accumulator."""
        self._today_energy = 0.0
        self._today_liters = 0.0
        self._last_date = date.today().isoformat()
        self._persist()

    def energy_today(self) -> float | None:
        return self._today_energy if self._last_energy is not None else None

    def today_last_reset(self) -> datetime | None:
        if self._last_date is None:
            return None
        return datetime.combine(date.fromisoformat(self._last_date), datetime.min.time())

    def energy_cumulative(self) -> float | None:
        if self._last_energy is None:
            return None
        return round(self._total_energy, 6)

    def water_today(self) -> float | None:
        return self._today_liters if self._last_liters is not None else None

    def water_cumulative(self) -> float | None:
        if self._last_liters is None:
            return None
        return round(self._total_liters, 4)

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
        raw = self._totalizer.energy_cumulative()
        if raw is None:
            return
        if raw < 0:
            _LOGGER.warning(
                "Cala Energy Total: negative value rejected: %s (entity: %s)",
                raw,
                self._attr_unique_id,
            )
            return
        self._attr_native_value = raw


class CalaWaterTodaySensor(CalaBase, SensorEntity):
    def __init__(self, device_id: str, device_name: str, totalizer: CalaTotalizer):
        super().__init__(device_id, device_name)
        self._totalizer = totalizer
        self._attr_name = f"Water Used (Today)"
        self._attr_unique_id = f"cala_{device_id}_water_today"
        self._attr_native_unit_of_measurement = UnitOfVolume.GALLONS
        self._attr_device_class = SensorDeviceClass.WATER
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_native_value = None
        self._attr_last_reset = None

    def update_value(self) -> None:
        raw = self._totalizer.water_today()
        self._attr_native_value = (
            round(raw * LITERS_TO_GALLONS, 2) if raw is not None else None
        )
        self._attr_last_reset = self._totalizer.today_last_reset()


class CalaWaterCumulativeSensor(CalaBase, SensorEntity):
    def __init__(self, device_id: str, device_name: str, totalizer: CalaTotalizer):
        super().__init__(device_id, device_name)
        self._totalizer = totalizer
        self._attr_name = f"Water Used (Total)"
        self._attr_unique_id = f"cala_{device_id}_water_cumulative"
        self._attr_native_unit_of_measurement = UnitOfVolume.GALLONS
        self._attr_device_class = SensorDeviceClass.WATER
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_native_value = None

    def update_value(self) -> None:
        raw = self._totalizer.water_cumulative()
        if raw is None:
            return
        if raw < 0:
            _LOGGER.warning(
                "Cala Water Total: negative value rejected: %s (entity: %s)",
                raw,
                self._attr_unique_id,
            )
            return
        self._attr_native_value = round(raw * LITERS_TO_GALLONS, 2)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    def _set_entities_available(available: bool) -> None:
        for e in all_data_entities:
            e._attr_available = available
            e.async_write_ha_state()

    device_id = entry.data[CONF_DEVICE_ID]
    device_name = entry.data.get("device_name") or "Cala Water Heater"
    state_topic = entry.data["state_topic"]
    command_topic = entry.data.get(CONF_COMMAND_TOPIC) or f"cala/{device_id}/command"
    response_topic = f"{command_topic.rstrip('/')}/response"

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

    # Store boost binary sensor for boost_services to update on success
    boost_binary = next((b for b in binaries if b._key == "boost_mode_on"), None)
    if boost_binary:
        hass.data.setdefault(DOMAIN, {}).setdefault("boost_entities", {})[
            device_id
        ] = boost_binary

    async_add_entities([connection_status] + sensors + binaries + totalizer_sensors)

    timeout_timer_handle = None
    repair_timer_handle = None

    def _call_on_loop(func, *args) -> None:
        hass.loop.call_soon_threadsafe(func, *args)

    def _repair_issue_id() -> str:
        return REPAIR_ISSUE_ID_TPL.format(device_id=device_id)

    def _create_repair_issue() -> None:
        # Called only after prolonged offline (15 min)
        try:
            ir.async_create_issue(
                hass,
                DOMAIN,
                _repair_issue_id(),
                is_fixable=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key=None,
                title=f"Cala device {device_id} appears offline",
                description=(
                    "Your Cala device has been offline for an extended period.\n\n"
                    "If the device was reset or re-paired, you likely need to re-provision it.\n\n"
                    "Go to: Settings → Devices & services → Cala → Configure → "
                    "Re-provision device (pairing code, broker, credentials)."
                ),
            )
        except Exception:
            _LOGGER.exception("Failed to create repair issue for %s", device_id)

    def _delete_repair_issue() -> None:
        try:
            ir.async_delete_issue(hass, DOMAIN, _repair_issue_id())
        except Exception:
            # delete should be best-effort and silent-ish
            _LOGGER.debug("No repair issue to delete for %s", device_id)

    def _schedule_repair_issue() -> None:
        nonlocal repair_timer_handle
        if repair_timer_handle is not None:
            repair_timer_handle.cancel()
        repair_timer_handle = hass.loop.call_later(REPAIR_OFFLINE_AFTER_S, _create_repair_issue)

    def _clear_repair_issue_and_timer() -> None:
        nonlocal repair_timer_handle
        if repair_timer_handle is not None:
            repair_timer_handle.cancel()
            repair_timer_handle = None
        _delete_repair_issue()

    def _set_entities_available(available: bool) -> None:
        def _do() -> None:
            for e in all_data_entities:
                e._attr_available = available
                e.async_write_ha_state()
        _call_on_loop(_do)
    
    _set_entities_available(connection_status._attr_native_value == ConnectionStatus.CONNECTED.value)

    @callback
    def _on_timeout() -> None:
        nonlocal timeout_timer_handle
        timeout_timer_handle = None
        connection_status.set_state(ConnectionStatus.OFFLINE)
        connection_status.async_write_ha_state()
        _set_entities_available(False)
        _schedule_repair_issue()
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
            connection_status.set_state(ConnectionStatus.CONNECTED)
            connection_status.async_write_ha_state()
            _clear_repair_issue_and_timer()
            _set_entities_available(True)

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
                liters = _coerce_float(payload.get("liters_used"))
                totalizer.update(energy, liters)

                _mark_connected_if_needed()
                _refresh_timeout()

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

            def _schedule() -> None:
                hass.async_create_task(_process_payload())
            hass.loop.call_soon_threadsafe(_schedule)
        except Exception:
            _LOGGER.exception("Unhandled error in message_received for %s", device_id)

    @callback
    def _on_command_response(msg) -> None:
        """Handle device responses to commands (accepted/rejected)."""
        try:
            payload = parse_mqtt_json_payload(msg.payload)
            if not payload:
                _LOGGER.debug("Invalid or non-dict JSON on %s", response_topic)
                return
            status = payload.get("status")
            if status == "accepted":
                _LOGGER.info(
                    "Cala device %s: command accepted, id=%s",
                    device_id,
                    payload.get("id"),
                )
            elif status == "rejected":
                _LOGGER.warning(
                    "Cala device %s: command rejected, reason=%s",
                    device_id,
                    payload.get("reason", "unknown"),
                )
            else:
                _LOGGER.debug("Cala device %s: command response: %s", device_id, payload)
        except Exception:
            _LOGGER.exception("Unhandled error in _on_command_response for %s", device_id)

    unsub_state = await mqtt.async_subscribe(hass, state_topic, message_received, qos=1)
    unsub_response = await mqtt.async_subscribe(
        hass, response_topic, _on_command_response, qos=1
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}
    hass.data[DOMAIN][entry.entry_id]["mqtt_unsubscribes"] = [unsub_state, unsub_response]
    hass.data[DOMAIN][entry.entry_id]["timeout_timer"] = lambda: (
        timeout_timer_handle.cancel() if timeout_timer_handle is not None else None
    )
    hass.data[DOMAIN][entry.entry_id]["repair_timer"] = lambda: (
        repair_timer_handle.cancel() if repair_timer_handle is not None else None
    )
    hass.data[DOMAIN][entry.entry_id]["repair_issue_clear"] = _delete_repair_issue

