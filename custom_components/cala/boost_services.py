"""Boost service handlers: start_boost, stop_boost."""

import logging

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import async_get as async_get_device_registry
from homeassistant.helpers.entity_registry import (
    async_entries_for_device,
    async_get as async_get_entity_registry,
)
from .const import ATTR_DEVICE_ID, DOMAIN
from .helpers import get_command_topic, publish_command_and_wait_response

BOOST_UNIQUE_ID_SUFFIX = "_boost_mode_on"

_LOGGER = logging.getLogger(__name__)

RESPONSE_TIMEOUT_S = 10


async def _execute_boost_command(
    hass: HomeAssistant,
    device_id: str,
    payload: dict,
    boost_state: str,
    message: str,
) -> None:
    """Publish command, wait for response, update sensor, show notification."""
    command_topic = get_command_topic(hass, device_id)
    if not command_topic:
        raise HomeAssistantError(f"Unknown device_id: {device_id}")

    await publish_command_and_wait_response(
        hass, command_topic, payload, RESPONSE_TIMEOUT_S
    )

    # Update the boost binary sensor's internal state so it persists (not overwritten by next MQTT)
    boost_entity = (hass.data.get(DOMAIN) or {}).get("boost_entities", {}).get(device_id)
    if boost_entity:
        boost_entity._attr_is_on = boost_state == "on"
        boost_entity.async_write_ha_state()
    else:
        boost_entity_id = get_boost_entity_id(hass, device_id)
        if boost_entity_id:
            hass.states.async_set(boost_entity_id, boost_state)

    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "message": message,
            "title": "Cala Boost",
            "notification_id": f"cala_boost_{device_id}",
        },
        blocking=True,
    )


async def handle_start_boost(call: ServiceCall) -> None:
    """Service: cala.start_boost -> publish boost config over MQTT, wait for device response."""
    hass = call.hass
    device_id = call.data.get(ATTR_DEVICE_ID)
    duration_hours = int(call.data.get("duration", 24))

    if not device_id:
        raise HomeAssistantError("device_id is required")

    _LOGGER.debug("Cala handle_start_boost: device_id=%s duration=%sh", device_id, duration_hours)

    payload = {"type": "create_boost", "hours": duration_hours}
    await _execute_boost_command(
        hass,
        device_id,
        payload,
        boost_state="on",
        message=f"Boost started for {duration_hours} hours",
    )
    _LOGGER.debug("Cala start_boost: device accepted device_id=%s payload=%s", device_id, payload)


async def handle_stop_boost(call: ServiceCall) -> None:
    """Service: cala.stop_boost -> publish boost disable over MQTT, wait for device response."""
    hass = call.hass
    device_id = call.data.get(ATTR_DEVICE_ID)

    if not device_id:
        raise HomeAssistantError("device_id is required")

    _LOGGER.debug("Cala handle_stop_boost: device_id=%s", device_id)

    payload = {"type": "cancel_boost"}
    await _execute_boost_command(
        hass,
        device_id,
        payload,
        boost_state="off",
        message="Boost stopped",
    )
    _LOGGER.debug("Cala stop_boost: device accepted device_id=%s", device_id)

def get_boost_entity_id(hass, device_id: str) -> str | None:
    """Find the boost_mode_on binary sensor entity_id for a device."""
    ent_reg = async_get_entity_registry(hass)
    unique_id = f"cala_{device_id}_boost_mode_on"
    for platform in ("sensor", "cala"):
        entity_id = ent_reg.async_get_entity_id("binary_sensor", platform, unique_id)
        if entity_id:
            return entity_id
    dev_reg = async_get_device_registry(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, device_id)})
    if device:
        for entry in async_entries_for_device(ent_reg, device.id):
            if entry.unique_id and entry.unique_id.endswith(BOOST_UNIQUE_ID_SUFFIX):
                return entry.entity_id
    device_id_norm = device_id.lower().replace("-", "_")
    for entry in ent_reg.entities.values():
        if (
            entry.domain == "binary_sensor"
            and entry.unique_id
            and entry.unique_id.lower().endswith(BOOST_UNIQUE_ID_SUFFIX)
            and (
                device_id.lower() in entry.unique_id.lower()
                or device_id_norm in entry.unique_id.lower()
            )
        ):
            return entry.entity_id
    return None