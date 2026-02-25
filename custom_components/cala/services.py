"""Cala MQTT command services: create_boost, create_vacation."""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
import voluptuous as vol

from .const import ATTR_DEVICE_ID, CONF_DEVICE_ID, DOMAIN
from .helpers import get_command_topic

_LOGGER = logging.getLogger(__name__)

SERVICE_CREATE_BOOST = "create_boost"
SERVICE_CREATE_VACATION = "create_vacation"
SERVICE_OPEN_BOOST_DIALOG = "open_boost_dialog"
SERVICE_OPEN_VACATION_DIALOG = "open_vacation_dialog"

ATTR_HOURS = "hours"
ATTR_VACATION_ID = "id"
ATTR_START_DATE = "start_date"
ATTR_END_DATE = "end_date"

CREATE_BOOST_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): str,
        vol.Required(ATTR_HOURS): vol.In([6, 12, 24, 48]),
    }
)

CREATE_VACATION_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): str,
        vol.Required(ATTR_VACATION_ID): str,
        vol.Required(ATTR_START_DATE): vol.Coerce(int),
        vol.Required(ATTR_END_DATE): vol.Coerce(int),
    }
)


async def _publish_command(
    hass: HomeAssistant, device_id: str, payload: dict[str, Any]
) -> bool:
    """Publish command to device. Returns True on success."""
    topic = get_command_topic(hass, device_id)
    if not topic:
        _LOGGER.error("Cala: no config entry for device_id=%s", device_id)
        return False
    try:
        await mqtt.async_publish(
            hass,
            topic=topic,
            payload=json.dumps(payload),
            qos=1,
            retain=False,
        )
        _LOGGER.info("Cala: published command to %s: %s", topic, payload)
        return True
    except Exception as exc:
        _LOGGER.error("Cala: failed to publish command to %s: %s", topic, exc)
        return False


async def create_boost(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle cala.create_boost service call."""
    device_id = call.data[ATTR_DEVICE_ID]
    hours = call.data[ATTR_HOURS]
    payload = {"type": "create_boost", "hours": hours}
    await _publish_command(hass, device_id, payload)


async def create_vacation(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle cala.create_vacation service call."""
    device_id = call.data[ATTR_DEVICE_ID]
    vacation_id = call.data[ATTR_VACATION_ID]
    start_date = call.data[ATTR_START_DATE]
    end_date = call.data[ATTR_END_DATE]
    payload = {
        "type": "create_vacation",
        "id": vacation_id,
        "startDate": start_date,
        "endDate": end_date,
    }
    await _publish_command(hass, device_id, payload)


def _get_entry_id_for_device(hass: HomeAssistant, device_id: str) -> str | None:
    """Get config entry ID for a device_id."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_DEVICE_ID) == device_id:
            return entry.entry_id
    return None


def async_setup_services(hass: HomeAssistant) -> None:
    """Register Cala services."""
    if hass.services.has_service(DOMAIN, SERVICE_CREATE_BOOST):
        return

    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_BOOST,
        lambda call: create_boost(hass, call),
        schema=CREATE_BOOST_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_VACATION,
        lambda call: create_vacation(hass, call),
        schema=CREATE_VACATION_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_OPEN_BOOST_DIALOG,
        lambda call: open_boost_dialog(hass, call),
        schema=vol.Schema({vol.Required(ATTR_DEVICE_ID): str}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_OPEN_VACATION_DIALOG,
        lambda call: open_vacation_dialog(hass, call),
        schema=vol.Schema({vol.Required(ATTR_DEVICE_ID): str}),
    )
    _LOGGER.debug(
        "Cala services registered: %s, %s, %s, %s",
        SERVICE_CREATE_BOOST,
        SERVICE_CREATE_VACATION,
        SERVICE_OPEN_BOOST_DIALOG,
        SERVICE_OPEN_VACATION_DIALOG,
    )
