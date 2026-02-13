import json
import logging
from datetime import datetime, timezone

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

# ---- Constants ----

SUPPORTED_POWER_UNITS = {"W", "kW"}
MAX_REASONABLE_POWER_W = 100_000  # sanity limit
SOC_MIN = 0.0
SOC_MAX = 100.0


# ---- Helpers ----

def _get_state(hass: HomeAssistant, entity_id: str):
    if not entity_id:
        return None
    return hass.states.get(entity_id)


def _get_float_state(hass: HomeAssistant, entity_id: str):
    state = _get_state(hass, entity_id)
    if not state:
        return None

    if state.state in ("unknown", "unavailable", ""):
        return None

    try:
        return float(state.state)
    except ValueError:
        _LOGGER.warning(
            "Entity %s has non-numeric state: %s",
            entity_id,
            state.state,
        )
        return None


def _normalize_power_w(hass: HomeAssistant, entity_id: str):
    state = _get_state(hass, entity_id)
    if not state:
        return None

    value = _get_float_state(hass, entity_id)
    if value is None:
        return None

    unit = state.attributes.get("unit_of_measurement")

    if unit not in SUPPORTED_POWER_UNITS:
        _LOGGER.warning(
            "Entity %s has unsupported power unit: %s",
            entity_id,
            unit,
        )
        return None

    if unit == "kW":
        value = value * 1000.0

    if value < 0 or value > MAX_REASONABLE_POWER_W:
        _LOGGER.warning(
            "Entity %s power value out of range: %s W",
            entity_id,
            value,
        )
        return None

    return round(value, 2)


def _normalize_soc(entity_id: str, value: float):
    if value < SOC_MIN or value > SOC_MAX:
        _LOGGER.warning(
            "Battery SOC entity %s out of range: %s",
            entity_id,
            value,
        )
        return None

    # Cala expects 0.0–1.0
    return round(value / 100.0, 4)


# ---- Main publisher ----

async def publish_context(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """
    Build and publish Cala energy context over MQTT.

    This function is:
    - idempotent
    - safe on partial data
    - strict on validation
    """

    device_id = entry.data.get("device_id")
    if not device_id:
        _LOGGER.error("Missing device_id in config entry")
        return

    opts = entry.options or {}

    ctx: dict = {}

    # ---- Solar ----
    solar_entity = opts.get("solar_production_entity")
    if solar_entity:
        solar_w = _normalize_power_w(hass, solar_entity)
        if solar_w is not None:
            ctx.setdefault("solar", {})["production_w"] = solar_w

    # ---- Grid ----
    grid_import_entity = opts.get("grid_import_entity")
    if grid_import_entity:
        import_w = _normalize_power_w(hass, grid_import_entity)
        if import_w is not None:
            ctx.setdefault("grid", {})["import_w"] = import_w

    grid_export_entity = opts.get("grid_export_entity")
    if grid_export_entity:
        export_w = _normalize_power_w(hass, grid_export_entity)
        if export_w is not None:
            ctx.setdefault("grid", {})["export_w"] = export_w

    # ---- Battery ----
    battery_soc_entity = opts.get("battery_soc_entity")
    if battery_soc_entity:
        soc_raw = _get_float_state(hass, battery_soc_entity)
        if soc_raw is not None:
            soc_norm = _normalize_soc(battery_soc_entity, soc_raw)
            if soc_norm is not None:
                ctx.setdefault("battery", {})["soc"] = soc_norm

    # ---- Nothing valid? Do not publish ----
    if not ctx:
        _LOGGER.debug(
            "No valid context data to publish for device %s",
            device_id,
        )
        return

    
    payload = {
        "v": 1,
        "ts": datetime.now(tz=timezone.utc).timestamp(),
        "context": ctx,
    }

    topic = f"cala/{device_id}/context"

    _LOGGER.info("Cala publish_context: publishing payload=%s", ctx)
    _LOGGER.info("Cala publish_context: publishing topic=%s", topic)

    try:
        await mqtt.async_publish(
            hass,
            topic=topic,
            payload=json.dumps(payload),
            qos=0,
            retain=False,
        )
        _LOGGER.info(
            "Published Cala context for %s: %s",
            device_id,
            payload,
        )
    except Exception as exc:
        _LOGGER.error(
            "Failed to publish Cala context for %s: %s",
            device_id,
            exc,
        )