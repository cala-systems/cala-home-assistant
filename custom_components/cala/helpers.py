"""Shared helpers for the Cala integration."""

import asyncio
import json

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import async_get as async_get_device_registry
from homeassistant.helpers.entity_registry import (
    async_entries_for_device,
    async_get as async_get_entity_registry,
)

from .const import DOMAIN

BOOST_UNIQUE_ID_SUFFIX = "_boost_mode_on"


def _normalize_mqtt_payload(payload) -> str:
    """Convert MQTT payload (bytes/str/memoryview) to string."""
    if payload is None:
        return ""
    if isinstance(payload, (bytes, bytearray)):
        return payload.decode("utf-8", errors="replace")
    if isinstance(payload, memoryview):
        return payload.tobytes().decode("utf-8", errors="replace")
    return str(payload) if payload else ""


def parse_mqtt_json_payload(payload) -> dict | None:
    """Parse MQTT message payload as JSON dict. Returns None on parse failure."""
    try:
        raw = _normalize_mqtt_payload(payload)
        data = json.loads(raw) if raw else {}
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def parse_mqtt_response_payload(payload) -> dict[str, str | None]:
    """Parse MQTT response into status and reason. Handles bytes/str."""
    result: dict[str, str | None] = {"status": None, "reason": None}
    data = parse_mqtt_json_payload(payload)
    if data:
        result["status"] = data.get("status")
        result["reason"] = data.get("reason") or "unknown"
    return result


async def publish_command_and_wait_response(
    hass: HomeAssistant,
    command_topic: str,
    payload: dict,
    timeout: float,
) -> dict[str, str | None]:
    """
    Publish command to MQTT, subscribe to response topic, wait for reply.
    Returns dict with status and reason. Raises HomeAssistantError on timeout or rejection.
    """
    response_topic = f"{command_topic.rstrip('/')}/response"
    response_received = asyncio.Event()
    result: dict[str, str | None] = {"status": None, "reason": None}

    @callback
    def _on_response(msg) -> None:
        parsed = parse_mqtt_response_payload(msg.payload)
        result["status"] = parsed["status"]
        result["reason"] = parsed["reason"]
        response_received.set()

    unsub = await mqtt.async_subscribe(hass, response_topic, _on_response, qos=1)
    try:
        await mqtt.async_publish(
            hass,
            topic=command_topic,
            payload=json.dumps(payload),
            qos=1,
            retain=False,
        )
        try:
            await asyncio.wait_for(response_received.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise HomeAssistantError(
                f"No response from device within {timeout:.0f} seconds"
            )
    finally:
        unsub()

    if result["status"] == "rejected":
        raise HomeAssistantError(
            f"Device rejected command: {result.get('reason', 'unknown')}"
        )
    if result["status"] != "accepted":
        raise HomeAssistantError(
            f"Unexpected response from device: {result.get('status', 'unknown')}"
        )
    return result


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
