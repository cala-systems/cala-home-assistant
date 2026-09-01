"""Map /pair failures to config-flow error keys.

Kept free of aiohttp and Home Assistant imports so it can be unit-tested
standalone (see tests/conftest.py).

Firmware semantics (embESP32 HomeAssistantWebServer.hpp):

* 400 "Decryption failed" / "Invalid JSON" / "Missing encrypted payload"
  -> the device could not decrypt the payload: wrong pairing code.
* 400 anything else -> malformed request (an integration bug, not user error).
* 403 "Invalid or expired code" -> pairing code rejected.
* 403 "Invalid or expired device id" -> code accepted, device_id mismatch.
* 408 -> the device timed out reading the request body.
* Connect timeout / refused -> the pairing server is not reachable. It only
  runs while the heater shows Settings -> Advanced -> Home Assistant.
"""

from __future__ import annotations

import asyncio

ERROR_CANNOT_CONNECT = "cannot_connect"
ERROR_INVALID_CODE = "invalid_code"
ERROR_INVALID_DEVICE_ID = "invalid_device_id"
ERROR_DEVICE_ERROR = "device_error"
ERROR_PAIRING_REJECTED = "pairing_rejected"

DETAIL_MAX_LEN = 200


def _trim(body: str | bytes | None) -> str:
    if body is None:
        return ""
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", errors="replace")
    text = " ".join(body.split())
    if len(text) > DETAIL_MAX_LEN:
        text = text[: DETAIL_MAX_LEN - 1] + "\u2026"
    return text


def classify_http_error(status: int, body: str | bytes | None) -> tuple[str, str]:
    """Return (error_key, detail) for a non-200 /pair response."""
    text = _trim(body)
    lower = text.lower()
    if status == 403:
        if "device id" in lower or "device_id" in lower:
            return ERROR_INVALID_DEVICE_ID, text
        return ERROR_INVALID_CODE, text
    if status == 400 and (
        "decrypt" in lower or "invalid json" in lower or "encrypted" in lower
    ):
        return ERROR_INVALID_CODE, text
    return ERROR_DEVICE_ERROR, f"HTTP {status}: {text or 'no response body'}"


def classify_exception(exc: BaseException) -> tuple[str, str]:
    """Return (error_key, detail) for a transport-level failure.

    Matches aiohttp exceptions by class name so this module does not import
    aiohttp. ConnectionTimeoutError must be checked before the generic
    timeout case because it subclasses asyncio.TimeoutError.
    """
    name = type(exc).__name__
    msg = str(exc).strip()
    if name == "ConnectionTimeoutError":
        return (
            ERROR_CANNOT_CONNECT,
            "the TCP connection timed out (no answer from the device on that port)",
        )
    if name in ("ServerTimeoutError", "SocketTimeoutError") or isinstance(
        exc, asyncio.TimeoutError
    ):
        return ERROR_CANNOT_CONNECT, "connected, but the device did not answer in time"
    if name == "ServerDisconnectedError":
        return ERROR_CANNOT_CONNECT, "the device closed the connection before responding"
    if name == "ClientConnectorError":
        return ERROR_CANNOT_CONNECT, msg or "connection failed"
    return ERROR_CANNOT_CONNECT, f"{name}: {msg}" if msg else name


def error_placeholders(url: str, device_id: str | None, detail: str | None) -> dict[str, str]:
    """Placeholders referenced by the error strings in translations/*.json."""
    return {
        "url": url,
        "device_id": device_id or "",
        "error_detail": detail or "",
    }
