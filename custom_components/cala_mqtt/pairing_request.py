import aiohttp
import logging
import json
import asyncio

from .const import (
    CONF_AVAILABILITY_TOPIC,
    CONF_BROKER_HOST,
    CONF_BROKER_PORT,
    CONF_COMMAND_TOPIC,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_USERNAME,
    CONF_PAIRING_TOKEN,
    CONF_STATE_TOPIC,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_TOPIC_PREFIX = "cala"
PAIRING_TIMEOUT_S = 30
# Bounded read so we don't hang if ESP32 sends response but doesn't close the connection
PAIRING_SOCK_READ_S = 10

async def _http_pair(
    url: str,
    device_id: str,
    device_name: str,
    pairing_code: str,
    broker_host: str,
    broker_port: int,
    username: str,
    password: str,
) -> tuple[dict | None, str | None]:
    """
    POST pairing code and broker info to device; return (entry_data, error_key).
    Uses same payload shape for discovery and manual (ESP URL) flows.
    """
    payload = {
        "pairing_code": pairing_code,
        "device_id": device_id,
        "mqtt_broker": {
            "host": broker_host,
            "port": broker_port,
            "username": username,
            "password": password,
        },
    }

    try:
        async with aiohttp.ClientSession() as session:
            timeout = aiohttp.ClientTimeout(
                total=PAIRING_TIMEOUT_S,
                sock_connect=PAIRING_SOCK_READ_S,
                sock_read=PAIRING_SOCK_READ_S,
            )
            async with session.post(url, json=payload, timeout=timeout) as response:
                body = await response.text()
                resp = _safe_json_loads(body)
                if response.status != 200 or not isinstance(resp, dict):
                    _LOGGER.warning(
                        "Cala pairing HTTP response: status=%s, body_type=%s",
                        response.status,
                        type(resp).__name__ if resp is not None else "None",
                    )
                    return (None, "cannot_connect")
                # Accepted if device says so, or if it returned MQTT/topic data we can use
                mqtt_creds = resp.get("mqtt") if isinstance(resp.get("mqtt"), dict) else {}
                has_creds = bool(
                    mqtt_creds.get("username") or mqtt_creds.get("password")
                    or resp.get("state_topic") or resp.get("topics")
                )
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
                _LOGGER.debug(
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