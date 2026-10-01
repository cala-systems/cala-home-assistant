import json
import logging
from datetime import datetime, timezone

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import (
    BATTERY_POWER_SIGNS,
    BATTERY_SIGN_POSITIVE_IS_DISCHARGING,
    CONF_BATTERY_POWER_ENTITY,
    CONF_BATTERY_POWER_SIGN,
    CONF_BATTERY_SOC_ENTITY,
    CONF_DEVICE_ID,
    CONF_GRID_EXPORT_ENTITY,
    CONF_GRID_IMPORT_ENTITY,
    CONF_GRID_POWER_ENTITY,
    CONF_GRID_POWER_SIGN,
    CONF_GRID_STATUS_ENTITY,
    CONF_GRID_STATUS_INVERT,
    GRID_POWER_SIGNS,
    GRID_SIGN_POSITIVE_IS_EXPORT,
)
from .helpers import entity_id_from_option

_LOGGER = logging.getLogger(__name__)

# ---- Constants ----

SUPPORTED_POWER_UNITS = {"W", "kW"}
MAX_REASONABLE_POWER_W = 100_000  # sanity limit
# Grid-status states, lower-cased with spaces and dashes as underscores.
# binary_sensor "on" means on-grid (e.g. Powerwall grid_status); invert if not.
ON_GRID_STATES = {
    "on", "true", "1", "on_grid", "ongrid", "connected", "grid_connected",
    "systemgridconnected",
}
OFF_GRID_STATES = {
    "off", "false", "0", "off_grid", "offgrid", "disconnected", "grid_disconnected",
    "islanded", "island", "grid_down", "outage", "systemislandedactive",
}
_warned_fraction_soc: set[str] = set()
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


def _read_power_w(hass: HomeAssistant, entity_id: str):
    """Return the entity's power in W (any sign), or None if missing/bad unit."""
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

    return value


def _normalize_power_w(hass: HomeAssistant, entity_id: str):
    """Non-negative power in W (PV production, import/export magnitudes)."""
    value = _read_power_w(hass, entity_id)
    if value is None:
        return None

    if value < 0 or value > MAX_REASONABLE_POWER_W:
        _LOGGER.warning(
            "Entity %s power value out of range: %s W",
            entity_id,
            value,
        )
        return None

    return round(value, 2) + 0.0


def _normalize_signed_power_w(hass: HomeAssistant, entity_id: str):
    """Signed power in W, as the entity reports it, bounded to +/-100 kW."""
    value = _read_power_w(hass, entity_id)
    if value is None:
        return None

    if abs(value) > MAX_REASONABLE_POWER_W:
        _LOGGER.warning(
            "Entity %s power value out of range: %s W",
            entity_id,
            value,
        )
        return None

    return round(value, 2) + 0.0


def _sign_option(opts: dict, key: str, allowed: tuple[str, ...]) -> str:
    value = opts.get(key) or allowed[0]
    if value not in allowed:
        _LOGGER.warning("Option %s has unknown value %s; using %s", key, value, allowed[0])
        return allowed[0]
    return value


def _grid_context(hass: HomeAssistant, opts: dict):
    """Grid power on the wire convention: power_w > 0 importing, < 0 exporting."""
    grid_entity = entity_id_from_option(opts.get(CONF_GRID_POWER_ENTITY))
    import_entity = entity_id_from_option(opts.get(CONF_GRID_IMPORT_ENTITY))
    export_entity = entity_id_from_option(opts.get(CONF_GRID_EXPORT_ENTITY))

    if grid_entity:
        power_w = _normalize_signed_power_w(hass, grid_entity)
        if power_w is None:
            return None
        sign = _sign_option(opts, CONF_GRID_POWER_SIGN, GRID_POWER_SIGNS)
        if sign == GRID_SIGN_POSITIVE_IS_EXPORT:
            power_w = -power_w + 0.0
        import_w = power_w if power_w > 0 else 0.0
        export_w = -power_w if power_w < 0 else 0.0
    elif import_entity and export_entity:
        import_w = _normalize_power_w(hass, import_entity)
        export_w = _normalize_power_w(hass, export_entity)
        if import_w is None or export_w is None:
            return None
        power_w = round(import_w - export_w, 2) + 0.0
    else:
        return None

    return {
        "import_w": import_w,
        "export_w": export_w,
        "power_w": power_w,
        "exporting": export_w > 0,
        "importing": import_w > 0,
    }


def _grid_disconnected(hass: HomeAssistant, opts: dict):
    """True when the house is off-grid (utility power lost), False on-grid, None if unknown."""
    entity_id = entity_id_from_option(opts.get(CONF_GRID_STATUS_ENTITY))
    state = _get_state(hass, entity_id)
    if not state or state.state in ("unknown", "unavailable", ""):
        return None

    key = state.state.strip().lower().replace("-", "_").replace(" ", "_")
    if key in ON_GRID_STATES:
        disconnected = False
    elif key in OFF_GRID_STATES:
        disconnected = True
    else:
        _LOGGER.warning(
            "Grid status entity %s has unrecognised state: %s",
            entity_id,
            state.state,
        )
        return None

    if opts.get(CONF_GRID_STATUS_INVERT):
        disconnected = not disconnected
    return disconnected


def _soc_percent(hass: HomeAssistant, entity_id: str):
    """Battery state of charge as 0-100 %, or None."""
    state = _get_state(hass, entity_id)
    value = _get_float_state(hass, entity_id)
    if state is None or value is None:
        return None

    unit = state.attributes.get("unit_of_measurement")
    if unit not in (None, "%"):
        _LOGGER.warning(
            "Battery SOC entity %s has unsupported unit: %s",
            entity_id,
            unit,
        )
        return None

    if value < SOC_MIN or value > SOC_MAX:
        _LOGGER.warning(
            "Battery SOC entity %s out of range: %s",
            entity_id,
            value,
        )
        return None

    if unit is None and 0 < value <= 1.0 and entity_id not in _warned_fraction_soc:
        _warned_fraction_soc.add(entity_id)
        _LOGGER.warning(
            "Battery SOC entity %s has no unit and reads %s; Cala expects 0-100 %%, "
            "so if this is a 0-1 fraction the battery will look nearly empty",
            entity_id,
            value,
        )

    return round(value, 2) + 0.0


def _battery_context(hass: HomeAssistant, opts: dict):
    battery: dict = {}

    soc_entity = entity_id_from_option(opts.get(CONF_BATTERY_SOC_ENTITY))
    if soc_entity:
        soc = _soc_percent(hass, soc_entity)
        if soc is not None:
            battery["soc_percent"] = soc

    power_entity = entity_id_from_option(opts.get(CONF_BATTERY_POWER_ENTITY))
    if power_entity:
        power_w = _normalize_signed_power_w(hass, power_entity)
        if power_w is not None:
            sign = _sign_option(opts, CONF_BATTERY_POWER_SIGN, BATTERY_POWER_SIGNS)
            if sign == BATTERY_SIGN_POSITIVE_IS_DISCHARGING:
                power_w = -power_w + 0.0
            battery["power_w"] = power_w
            battery["charging"] = power_w > 0
            battery["discharging"] = power_w < 0

    return battery or None


# ---- Main publisher ----

async def publish_context(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """
    Build and publish Cala energy context over MQTT.

    This function is:
    - idempotent
    - safe on partial data
    - strict on validation
    """

    device_id = entry.data.get(CONF_DEVICE_ID)
    if not device_id:
        _LOGGER.error("Missing device_id in config entry")
        return

    opts = entry.options or {}

    ctx: dict = {}

    # ---- Solar ----
    solar_entity = entity_id_from_option(opts.get("solar_production_entity"))
    if solar_entity:
        solar_w = _normalize_power_w(hass, solar_entity)
        if solar_w is not None:
            ctx["solar"] = {"production_w": solar_w, "producing": solar_w > 0}

    # ---- Grid ----
    grid = _grid_context(hass, opts)
    if grid is not None:
        ctx["grid"] = grid
    disconnected = _grid_disconnected(hass, opts)
    if disconnected is not None:
        ctx.setdefault("grid", {})["grid_disconnected"] = disconnected

    # ---- Battery ----
    battery = _battery_context(hass, opts)
    if battery is not None:
        ctx["battery"] = battery

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