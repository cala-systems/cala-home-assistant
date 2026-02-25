"""Boost service handlers: start_boost, stop_boost."""

import logging

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from .helpers import (
    get_boost_entity_id,
    get_command_topic,
    publish_command_and_wait_response,
)

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
    device_id = call.data.get("device_id")
    duration_hours = int(call.data.get("duration", 24))

    if not device_id:
        raise HomeAssistantError("device_id is required")

    _LOGGER.info("Cala handle_start_boost: device_id=%s duration=%sh", device_id, duration_hours)

    payload = {"type": "create_boost", "hours": duration_hours}
    await _execute_boost_command(
        hass,
        device_id,
        payload,
        boost_state="on",
        message=f"Boost started for {duration_hours} hours",
    )
    _LOGGER.info("Cala start_boost: device accepted device_id=%s payload=%s", device_id, payload)


async def handle_stop_boost(call: ServiceCall) -> None:
    """Service: cala.stop_boost -> publish boost disable over MQTT, wait for device response."""
    hass = call.hass
    device_id = call.data.get("device_id")

    if not device_id:
        raise HomeAssistantError("device_id is required")

    _LOGGER.info("Cala handle_stop_boost: device_id=%s", device_id)

    payload = {"type": "cancel_boost"}
    await _execute_boost_command(
        hass,
        device_id,
        payload,
        boost_state="off",
        message="Boost stopped",
    )
    _LOGGER.info("Cala stop_boost: device accepted device_id=%s", device_id)
