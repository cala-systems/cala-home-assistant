from __future__ import annotations

import asyncio
import json
import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import mqtt

from .const import (
    DOMAIN,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_STATE_TOPIC,
    CONF_COMMAND_TOPIC,
    CONF_AVAILABILITY_TOPIC,
    CONF_PAIRING_CODE,
    CONF_PAIRING_TOKEN,
    CONF_BROKER_HOST,
    CONF_BROKER_PORT,
    DEFAULT_STATE_TOPIC_TPL,
    DEFAULT_COMMAND_TOPIC_TPL,
    DEFAULT_AVAILABILITY_TOPIC_TPL,
)

_LOGGER = logging.getLogger(__name__)

PAIR_REQUEST_TOPIC_TPL = "cala/{device_id}/pair/request"
PAIR_ACCEPTED_TOPIC_TPL = "cala/{device_id}/pair/accepted"
PAIRING_TIMEOUT_S = 30


async def _mqtt_available(hass) -> bool:
    """Return True if an MQTT client is available."""
    if hasattr(mqtt, "async_wait_for_mqtt_client"):
        client = await mqtt.async_wait_for_mqtt_client(hass)
        return client is not None
    if hasattr(mqtt, "async_get_client"):
        return mqtt.async_get_client(hass) is not None
    return False


def _safe_json_loads(payload: bytes | str) -> dict | None:
    try:
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8", errors="replace")
        return json.loads(payload)
    except Exception:
        return None


def _extract_pairing_fields(device_id: str, device_name: str, resp: dict) -> dict:
    """Normalize the device pairing response into entry.data"""
    topics = resp.get("topics") if isinstance(resp.get("topics"), dict) else {}

    state_topic = (
        topics.get("telemetry")
        or topics.get("state")
        or resp.get(CONF_STATE_TOPIC)
        or resp.get("telemetry_topic")
        or resp.get("state_topic")
        or DEFAULT_STATE_TOPIC_TPL.format(device_id=device_id)
    )

    command_topic = (
        topics.get("command")
        or resp.get(CONF_COMMAND_TOPIC)
        or resp.get("command_topic")
        or DEFAULT_COMMAND_TOPIC_TPL.format(device_id=device_id)
    )

    availability_topic = (
        topics.get("availability")
        or resp.get(CONF_AVAILABILITY_TOPIC)
        or resp.get("availability_topic")
        or DEFAULT_AVAILABILITY_TOPIC_TPL.format(device_id=device_id)
    )

    data: dict = {
        CONF_DEVICE_NAME: device_name,
        CONF_DEVICE_ID: device_id,
        CONF_STATE_TOPIC: state_topic,
        CONF_COMMAND_TOPIC: command_topic,
        CONF_AVAILABILITY_TOPIC: availability_topic,
    }

    token = resp.get("token") or resp.get("auth_token") or resp.get(CONF_PAIRING_TOKEN)
    if isinstance(token, str) and token.strip():
        data[CONF_PAIRING_TOKEN] = token.strip()

    broker = resp.get("broker") if isinstance(resp.get("broker"), dict) else {}
    broker_host = (
        broker.get("host")
        or broker.get("hostname")
        or resp.get(CONF_BROKER_HOST)
        or resp.get("broker_host")
    )
    if isinstance(broker_host, str) and broker_host.strip():
        data[CONF_BROKER_HOST] = broker_host.strip()

    broker_port = broker.get("port") or resp.get(CONF_BROKER_PORT) or resp.get("broker_port")
    if isinstance(broker_port, int):
        data[CONF_BROKER_PORT] = broker_port
    elif isinstance(broker_port, str) and broker_port.isdigit():
        data[CONF_BROKER_PORT] = int(broker_port)

    return data


class CalaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if not await _mqtt_available(self.hass):
            return self.async_abort(reason="mqtt_not_configured")

        errors: dict[str, str] = {}

        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID].strip()
            pairing_code = user_input[CONF_PAIRING_CODE].strip()
            device_name = user_input.get(CONF_DEVICE_NAME, "").strip() or device_id

            if not device_id:
                errors[CONF_DEVICE_ID] = "required"
            if not pairing_code:
                errors[CONF_PAIRING_CODE] = "required"

            if not errors:
                await self.async_set_unique_id(device_id)
                self._abort_if_unique_id_configured()

                pair_request_topic = PAIR_REQUEST_TOPIC_TPL.format(device_id=device_id)
                pair_accepted_topic = PAIR_ACCEPTED_TOPIC_TPL.format(device_id=device_id)

                loop = asyncio.get_running_loop()
                fut: asyncio.Future[dict] = loop.create_future()

                def _on_msg(msg):
                    resp = _safe_json_loads(msg.payload)
                    if not isinstance(resp, dict):
                        return

                    accepted = resp.get("accepted")
                    status = resp.get("status")
                    if accepted is True or (isinstance(status, str) and status.lower() == "accepted"):
                        resp_device_id = resp.get("device_id")
                        if resp_device_id and str(resp_device_id) != device_id:
                            return
                        if not fut.done():
                            fut.set_result(resp)

                unsubscribe = await mqtt.async_subscribe(
                    self.hass, pair_accepted_topic, _on_msg, qos=1
                )

                try:
                    # HA URL only if configured
                    ha_url = self.hass.config.internal_url or self.hass.config.external_url

                    request_payload = {
                        "device_id": device_id,
                        "pairing_code": pairing_code,
                        "ha": {
                            "name": self.hass.config.location_name or "Home Assistant",
                        },
                    }
                    if ha_url:
                        request_payload["ha"]["url"] = ha_url

                    await mqtt.async_publish(
                        self.hass,
                        pair_request_topic,
                        json.dumps(request_payload),
                        qos=1,
                        retain=False,
                    )

                    resp = await asyncio.wait_for(fut, timeout=PAIRING_TIMEOUT_S)

                except asyncio.TimeoutError:
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("Unexpected error during Cala pairing flow")
                    errors["base"] = "cannot_connect"
                finally:
                    try:
                        unsubscribe()
                    except Exception:
                        pass

                if not errors:
                    data = _extract_pairing_fields(device_id, device_name, resp)
                    return self.async_create_entry(title=device_name, data=data)

        schema = vol.Schema(
            {
                vol.Optional(CONF_DEVICE_NAME, default=""): str,
                vol.Required(CONF_DEVICE_ID, default=""): str,
                vol.Required(CONF_PAIRING_CODE, default=""): str,
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)