"""TOU rate services and auto-publish driven by an upstream entity.

Service `cala.set_tou_rates` accepts a midnight-anchored 24-element array
(no rotation) for manual / automation use.

`publish_tou_rates_from_entity` reads an upstream entity's `forecast`
attribute (a list of `{datetime, value, hour}` entries; openadr3-ven-hass
shape) and rotates the next-from-now data into a midnight-anchored array
before publishing. Firmware always expects midnight-anchored — see the
`tou-wire-contract` memory note.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
import voluptuous as vol

from .const import (
    ATTR_DEVICE_ID,
    ATTR_RATES,
    CONF_DEVICE_ID,
    CONF_TOU_RATES_ENTITY,
    DOMAIN,
    TOU_RATES_HOURS,
)
from .helpers import get_command_topic, publish_command_and_wait_response

_LOGGER = logging.getLogger(__name__)

RESPONSE_TIMEOUT_S = 10

SET_TOU_RATES_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): str,
        vol.Required(ATTR_RATES): vol.All(
            [vol.Coerce(float)],
            vol.Length(min=TOU_RATES_HOURS, max=TOU_RATES_HOURS),
        ),
    }
)


async def _publish_rates(
    hass: HomeAssistant, device_id: str, rates: list[float]
) -> None:
    command_topic = get_command_topic(hass, device_id)
    if not command_topic:
        raise HomeAssistantError(f"Unknown device_id: {device_id}")
    payload = {"type": "set_tou_rates", "rates": rates}
    await publish_command_and_wait_response(
        hass, command_topic, payload, RESPONSE_TIMEOUT_S
    )


async def handle_set_tou_rates(call: ServiceCall) -> None:
    """Service: cala.set_tou_rates — publish a midnight-anchored 24-rate array."""
    hass = call.hass
    device_id = call.data[ATTR_DEVICE_ID]
    rates = [float(r) for r in call.data[ATTR_RATES]]
    _LOGGER.debug(
        "Cala set_tou_rates: device_id=%s rates=%s", device_id, rates
    )
    await _publish_rates(hass, device_id, rates)


def _rotate_forecast_to_midnight_anchored(
    forecast: list[dict[str, Any]],
) -> list[float] | None:
    """Take an openadr3-shape forecast (rolling-from-now) and return a
    midnight-anchored 24-element rate array.

    Returns None if the forecast can't cover a full 24 hours.
    """
    if not isinstance(forecast, list) or len(forecast) < TOU_RATES_HOURS:
        return None

    rates: list[float | None] = [None] * TOU_RATES_HOURS
    for entry in forecast[:TOU_RATES_HOURS]:
        if not isinstance(entry, dict):
            return None
        hour = entry.get("hour")
        value = entry.get("value")
        if hour is None or value is None:
            return None
        try:
            hour_i = int(hour) % TOU_RATES_HOURS
            value_f = float(value)
        except (TypeError, ValueError):
            return None
        rates[hour_i] = value_f

    if any(r is None for r in rates):
        # 24 forecast entries should cover 24 distinct hours; if they don't,
        # something is wrong with the source (e.g. half-hour intervals).
        return None
    return [float(r) for r in rates]


async def publish_tou_rates_from_entity(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Read the configured tou_rates_entity, rotate, and publish on change."""
    device_id = entry.data.get(CONF_DEVICE_ID)
    if not device_id:
        return

    opts = entry.options or {}
    entity_id = opts.get(CONF_TOU_RATES_ENTITY)
    if isinstance(entity_id, dict):
        entity_id = entity_id.get("entity_id") or entity_id.get("id")
    if not entity_id:
        return

    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable", ""):
        _LOGGER.debug(
            "Cala TOU: source entity %s has no usable state", entity_id
        )
        return

    forecast = state.attributes.get("forecast")
    rates = _rotate_forecast_to_midnight_anchored(forecast)
    if rates is None:
        _LOGGER.warning(
            "Cala TOU: %s forecast attribute is missing or shorter than %d "
            "entries; not publishing",
            entity_id,
            TOU_RATES_HOURS,
        )
        return

    entry_data = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    last = entry_data.get("last_tou_rates")
    if last == rates:
        _LOGGER.debug("Cala TOU: rates unchanged, skipping publish")
        return

    try:
        await _publish_rates(hass, device_id, rates)
    except HomeAssistantError as exc:
        _LOGGER.warning(
            "Cala TOU: device rejected or timed out publishing rates: %s", exc
        )
        return

    entry_data["last_tou_rates"] = rates
    _LOGGER.info(
        "Cala TOU: published 24 rates for %s from %s",
        device_id,
        entity_id,
    )
