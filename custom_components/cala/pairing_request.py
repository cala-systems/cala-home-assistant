import aiohttp
import base64
import hashlib
import logging
import json
import asyncio
import os

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend

from .pairing_errors import (
    ERROR_CANNOT_CONNECT,
    ERROR_DEVICE_ERROR,
    ERROR_PAIRING_REJECTED,
    classify_exception,
    classify_http_error,
)
from .const import (
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


def _encrypt_payload(payload: dict, pairing_code: str) -> str:
    """
    Encrypt payload with AES-128-CBC using pairing_code as key.
    Key derived as SHA256(pairing_code)[:16]. IV (16 bytes) is prepended.
    Output: base64(iv || ciphertext). Compatible with ESP32 mbedTLS.

    ESP32 decryption (Arduino/mbedTLS):
      Parse JSON body, get "encrypted" string.
      base64_decode → raw bytes.
      key = SHA256(pairing_code)[:16]
      iv = raw[0:16], ciphertext = raw[16:]
      AES_decrypt_CBC(key, iv, ciphertext)
      PKCS7 unpad, then JSON parse.
    """
    key = hashlib.sha256(pairing_code.encode("utf-8")).digest()[:16]
    iv = os.urandom(16)
    plaintext = json.dumps(payload).encode("utf-8")

    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), default_backend())
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()

    return base64.b64encode(iv + ciphertext).decode("ascii")


async def _http_pair(
    url: str,
    device_id: str,
    device_name: str,
    pairing_code: str,
    broker_host: str,
    broker_port: int,
    username: str,
    password: str,
) -> tuple[dict | None, str | None, str | None]:
    """
    POST pairing code and broker info to device.

    Returns (entry_data, error_key, error_detail). On success error_key and
    error_detail are None. error_key is a translations/*.json error key and
    error_detail a short human-readable reason for the {error_detail}
    placeholder (device response text or transport failure).
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
    encrypted = _encrypt_payload(payload, pairing_code)
    body = {"encrypted": encrypted}

    try:
        async with aiohttp.ClientSession() as session:
            timeout = aiohttp.ClientTimeout(
                total=PAIRING_TIMEOUT_S,
                sock_connect=PAIRING_SOCK_READ_S,
                sock_read=PAIRING_SOCK_READ_S,
            )
            async with session.post(url, json=body, timeout=timeout) as response:
                body_text = await response.text()
                if response.status != 200:
                    # Error bodies are the firmware's short reason strings
                    # ("Invalid or expired device id", "Decryption failed");
                    # they never contain credentials.
                    err, detail = classify_http_error(response.status, body_text)
                    _LOGGER.warning(
                        "Cala pairing rejected by device: url=%s status=%s body=%r -> %s",
                        url,
                        response.status,
                        body_text[:200],
                        err,
                    )
                    return (None, err, detail)
                resp = _safe_json_loads(body_text)
                if not isinstance(resp, dict):
                    _LOGGER.warning(
                        "Cala pairing: HTTP 200 but body is not a JSON object (%s)",
                        type(resp).__name__ if resp is not None else "unparseable",
                    )
                    return (None, ERROR_DEVICE_ERROR, "HTTP 200 with a non-JSON body")
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
                        "Cala pairing response not accepted (no accepted/status and no mqtt credentials). "
                        "Response keys: %s", list(resp.keys())
                    )
                    return (
                        None,
                        ERROR_PAIRING_REJECTED,
                        f"response keys: {', '.join(resp.keys()) or 'none'}",
                    )
                data = _extract_pairing_fields(device_id, device_name, resp)
                _LOGGER.debug(
                    "Cala pairing succeeded: device_id=%s, mqtt_username=%s, password=%s, state_topic=%s, command_topic=%s",
                    device_id,
                    data.get(CONF_MQTT_USERNAME),
                    _mask_password(data.get(CONF_MQTT_PASSWORD)),
                    data.get(CONF_STATE_TOPIC),
                    data.get(CONF_COMMAND_TOPIC),
                )
                return (data, None, None)
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        err, detail = classify_exception(e)
        _LOGGER.warning(
            "Cala pairing HTTP request to %s failed: %s: %s",
            url,
            type(e).__name__,
            e,
        )
        return (None, err, detail)
    except Exception as e:  # noqa: BLE001
        _LOGGER.exception("Unexpected error during Cala HTTP pairing")
        return (None, ERROR_CANNOT_CONNECT, f"{type(e).__name__}: {e}")

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
    resp_device_id = resp.get("device_id") or resp.get("id")
    if isinstance(resp_device_id, str) and resp_device_id.strip():
        device_id = resp_device_id.strip()

    resp_device_name = resp.get("device_name") or resp.get("name")
    if isinstance(resp_device_name, str) and resp_device_name.strip():
        device_name = resp_device_name.strip()
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


    data: dict = {
        CONF_DEVICE_NAME: device_name,
        CONF_DEVICE_ID: device_id,
        CONF_STATE_TOPIC: state_topic,
        CONF_COMMAND_TOPIC: command_topic,
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