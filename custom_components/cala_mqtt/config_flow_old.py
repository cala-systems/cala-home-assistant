from __future__ import annotations

import asyncio
import json
import logging
from urllib.parse import urlparse

import aiohttp
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
    CONF_MQTT_USERNAME,
    CONF_MQTT_PASSWORD,
    CONF_BROKER_HOST,
    CONF_BROKER_PORT,
)

_LOGGER = logging.getLogger(__name__)

PAIRING_TIMEOUT_S = 30


async def _mqtt_available(hass) -> bool:
    """Return True if an MQTT client is available."""
    if hasattr(mqtt, "async_wait_for_mqtt_client"):
        client = await mqtt.async_wait_for_mqtt_client(hass)
        return client is not None
    if hasattr(mqtt, "async_get_client"):
        return mqtt.async_get_client(hass) is not None
    return False


def _broker_host_port_from_hass(hass) -> tuple[str, int]:
    """Infer MQTT broker host and port from HA config (e.g. same host as HA, port 1883)."""
    url = hass.config.internal_url or hass.config.external_url or ""
    if url:
        parsed = urlparse(url)
        if parsed.hostname:
            return (parsed.hostname, 1883)
    return ("homeassistant.local", 1883)


def _mask_password(pw: str | None) -> str:
    """Return a safe string for logging (e.g. *** or ab***xy)."""
    if pw is None or not isinstance(pw, str):
        return "<none>"
    if len(pw) <= 4:
        return "***"
    return f"{pw[:2]}***{pw[-2:]}"


def _safe_json_loads(payload: bytes | str) -> dict | None:
    try:
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8", errors="replace")
        return json.loads(payload)
    except Exception:
        return None


async def _http_pair(
    hass,
    url: str,
    device_id: str,
    device_name: str,
    pairing_code: str,
) -> tuple[dict | None, str | None]:
    """
    POST pairing code and broker info to device; return (entry_data, error_key).
    Uses same payload shape for discovery and manual (ESP URL) flows.
    """
    ha_url = hass.config.internal_url or hass.config.external_url
    broker_host, broker_port = _broker_host_port_from_hass(hass)
    payload = {
        "pairing_code": pairing_code,
        "device_id": device_id,
        "ha": {
            "name": hass.config.location_name or "Home Assistant",
        },
        "mqtt_broker": {
            "host": broker_host,
            "port": broker_port,
        },
    }
    if ha_url:
        payload["ha"]["url"] = ha_url

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=PAIRING_TIMEOUT_S),
            ) as response:
                body = await response.text()
                resp = _safe_json_loads(body)
                if response.status != 200 or not isinstance(resp, dict):
                    _LOGGER.warning(
                        "Cala pairing HTTP response: status=%s, body_type=%s",
                        response.status,
                        type(resp).__name__ if resp is not None else "None",
                    )
                    return (None, "cannot_connect")
                # Accepted if device says so, or if it returned MQTT credentials (e.g. mqtt.username/password)
                mqtt = resp.get("mqtt") if isinstance(resp.get("mqtt"), dict) else {}
                has_creds = bool((mqtt.get("username") or resp.get("username")) and (mqtt.get("password") is not None or resp.get("password") is not None))
                accepted = (
                    resp.get("accepted") is True
                    or (isinstance(resp.get("status"), str) and resp.get("status", "").lower() == "accepted")
                    or has_creds
                )
                if not accepted:
                    _LOGGER.warning(
                        "Cala pairing response not accepted (no accepted/status and no mqtt credentials)"
                    )
                    return (None, "cannot_connect")
                data = _extract_pairing_fields(device_id, device_name, resp)
                _LOGGER.warning(
                    "Cala pairing succeeded: device_id=%s, mqtt_username=%s, password=%s, state_topic=%s, command_topic=%s",
                    device_id,
                    data.get(CONF_MQTT_USERNAME),
                    _mask_password(data.get(CONF_MQTT_PASSWORD)),
                    data.get(CONF_STATE_TOPIC),
                    data.get(CONF_COMMAND_TOPIC),
                )
                return (data, None)
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        _LOGGER.warning(
            "Cala pairing HTTP request failed: %s",
            type(e).__name__,
        )
        return (None, "cannot_connect")
    except Exception:
        _LOGGER.exception("Unexpected error during Cala HTTP pairing")
        return (None, "cannot_connect")


DEFAULT_TOPIC_PREFIX = "cala"


def _extract_pairing_fields(device_id: str, device_name: str, resp: dict) -> dict:
    """Normalize the device pairing response into entry.data"""
    topics = resp.get("topics") if isinstance(resp.get("topics"), dict) else {}
    mqtt_creds = resp.get("mqtt") if isinstance(resp.get("mqtt"), dict) else {}
    # topic_prefix can be at top level, under topics, or under mqtt (e.g. mqtt.topic_prefix)
    prefix_raw = (
        topics.get("prefix")
        or resp.get("topic_prefix")
        or mqtt_creds.get("topic_prefix")
        or ""
    )
    prefix = (prefix_raw or "").strip() or DEFAULT_TOPIC_PREFIX
    # If prefix looks like a full path (e.g. "cala/phil_wil_desk"), use as base: {prefix}/state
    # Otherwise use as segment: {prefix}/{device_id}/state
    if "/" in prefix:
        base = prefix.rstrip("/")
        default_state = f"{base}/state"
        default_command = f"{base}/command"
        default_availability = f"{base}/availability"
    else:
        default_state = f"{prefix}/{device_id}/state"
        default_command = f"{prefix}/{device_id}/command"
        default_availability = f"{prefix}/{device_id}/availability"

    state_topic = (
        topics.get("telemetry")
        or topics.get("state")
        or resp.get(CONF_STATE_TOPIC)
        or resp.get("telemetry_topic")
        or resp.get("state_topic")
        or default_state
    )

    command_topic = (
        topics.get("command")
        or resp.get(CONF_COMMAND_TOPIC)
        or resp.get("command_topic")
        or default_command
    )

    availability_topic = (
        topics.get("availability")
        or resp.get(CONF_AVAILABILITY_TOPIC)
        or resp.get("availability_topic")
        or default_availability
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

    # MQTT credentials returned by device for broker login (saved as config entry data)
    mqtt_creds = resp.get("mqtt") if isinstance(resp.get("mqtt"), dict) else {}
    username = (
        mqtt_creds.get("username")
        or resp.get(CONF_MQTT_USERNAME)
        or resp.get("username")
    )
    password = (
        mqtt_creds.get("password")
        or resp.get(CONF_MQTT_PASSWORD)
        or resp.get("password")
    )
    if isinstance(username, str) and username.strip():
        data[CONF_MQTT_USERNAME] = username.strip()
    if isinstance(password, str):
        data[CONF_MQTT_PASSWORD] = password

    _LOGGER.debug(
        "Cala pairing fields extracted: device_id=%s, has_username=%s, has_password=%s, state_topic=%s",
        device_id,
        bool(data.get(CONF_MQTT_USERNAME)),
        bool(data.get(CONF_MQTT_PASSWORD)),
        data.get(CONF_STATE_TOPIC),
    )
    return data


class CalaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_zeroconf(self, discovery_info):
        """Handle Zeroconf discovery: Cala device advertised itself; show pairing code form."""
        _LOGGER.debug("Cala discovered via Zeroconf: %s", discovery_info)

        # Get host, port, device_id from discovery (support both object and dict-style)
        host = getattr(discovery_info, "host", None) or (discovery_info or {}).get("host", "")
        port = getattr(discovery_info, "port", None) or (discovery_info or {}).get("port", 80)
        props = getattr(discovery_info, "properties", None) or (discovery_info or {}).get("properties", {}) or {}
        device_id = (props.get("device_id") or props.get("id") or "").strip() or None

        if not host:
            return self.async_abort(reason="invalid_discovery")

        self._discovery_info = discovery_info
        self._discovery_host = host
        self._discovery_port = int(port) if port else 80
        self._discovery_device_id = device_id

        if device_id:
            await self.async_set_unique_id(device_id)
            self._abort_if_unique_id_configured()

        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema(
                {vol.Required(CONF_PAIRING_CODE): str}
            ),
            description_placeholders={
                "device_id": device_id or "unknown",
            },
        )

    async def async_step_pair(self, user_input=None):
        """User entered pairing code (after discovery); POST to device and save MQTT credentials."""
        placeholders = {"device_id": getattr(self, "_discovery_device_id", None) or "unknown"}
        pair_schema = vol.Schema({vol.Required(CONF_PAIRING_CODE): str})

        if user_input is None:
            return self.async_show_form(
                step_id="pair",
                data_schema=pair_schema,
                description_placeholders=placeholders,
            )

        if not await _mqtt_available(self.hass):
            return self.async_abort(reason="mqtt_not_configured")

        pairing_code = (user_input.get(CONF_PAIRING_CODE) or "").strip()
        if not pairing_code:
            return self.async_show_form(
                step_id="pair",
                data_schema=pair_schema,
                description_placeholders=placeholders,
                errors={CONF_PAIRING_CODE: "required"},
            )

        host = getattr(self, "_discovery_host", None)
        port = getattr(self, "_discovery_port", 80)
        device_id = getattr(self, "_discovery_device_id", None) or "cala_device"
        device_name = device_id or "Cala Water Heater"
        url = f"http://{host}:{port}/pair"

        _LOGGER.warning("Cala pairing: sending POST to %s for device_id=%s", url, device_id)
        data, err = await _http_pair(
            self.hass, url, device_id, device_name, pairing_code
        )
        if err:
            _LOGGER.warning("Cala pairing failed: err=%s (device_id=%s, url=%s)", err, device_id, url)
            return self.async_show_form(
                step_id="pair",
                data_schema=vol.Schema({vol.Required(CONF_PAIRING_CODE, default=pairing_code): str}),
                description_placeholders={"device_id": device_id},
                errors={"base": err},
            )
        if not data.get(CONF_MQTT_USERNAME) or not data.get(CONF_MQTT_PASSWORD):
            _LOGGER.warning(
                "Cala device did not return mqtt_username/mqtt_password; storing anyway"
            )
        _LOGGER.warning(
            "Cala config entry created: title=%s, device_id=%s, mqtt_username=%s, state_topic=%s, command_topic=%s",
            device_name,
            data.get(CONF_DEVICE_ID),
            data.get(CONF_MQTT_USERNAME),
            data.get(CONF_STATE_TOPIC),
            data.get(CONF_COMMAND_TOPIC),
        )
        return self.async_create_entry(title=device_name, data=data)

    async def async_step_user(self, user_input=None):
        """Cala devices advertise via Zeroconf; no manual add. Abort with instructions."""
        return self.async_abort(reason="cala_advertises")