"""Unit tests for the /pair failure classifier."""

import asyncio

from cala.pairing_errors import (
    ERROR_CANNOT_CONNECT,
    ERROR_DEVICE_ERROR,
    ERROR_INVALID_CODE,
    ERROR_INVALID_DEVICE_ID,
    classify_exception,
    classify_http_error,
    error_placeholders,
)


def test_403_device_id_mismatch():
    err, detail = classify_http_error(403, "Invalid or expired device id")
    assert err == ERROR_INVALID_DEVICE_ID
    assert detail == "Invalid or expired device id"


def test_403_code_rejected():
    err, detail = classify_http_error(403, "Invalid or expired code")
    assert err == ERROR_INVALID_CODE
    assert detail == "Invalid or expired code"


def test_400_decryption_failed_means_wrong_code():
    assert classify_http_error(400, "Decryption failed")[0] == ERROR_INVALID_CODE
    assert classify_http_error(400, "Invalid JSON")[0] == ERROR_INVALID_CODE
    assert classify_http_error(400, b"Missing encrypted payload")[0] == ERROR_INVALID_CODE


def test_400_other_is_device_error_with_status():
    err, detail = classify_http_error(400, "Missing host")
    assert err == ERROR_DEVICE_ERROR
    assert detail == "HTTP 400: Missing host"


def test_other_status_includes_status_and_empty_body_marker():
    err, detail = classify_http_error(500, "")
    assert err == ERROR_DEVICE_ERROR
    assert detail == "HTTP 500: no response body"


def test_detail_is_whitespace_collapsed_and_bounded():
    _, detail = classify_http_error(404, "  lots \n of   " + "x" * 500)
    assert "\n" not in detail
    assert len(detail) <= len("HTTP 404: ") + 200


class ConnectionTimeoutError(asyncio.TimeoutError):  # mirrors aiohttp's hierarchy
    pass


class ClientConnectorError(Exception):
    pass


def test_connect_timeout_is_distinguished_from_read_timeout():
    err, detail = classify_exception(ConnectionTimeoutError())
    assert err == ERROR_CANNOT_CONNECT
    assert "TCP connection timed out" in detail

    err, detail = classify_exception(asyncio.TimeoutError())
    assert err == ERROR_CANNOT_CONNECT
    assert "did not answer in time" in detail


def test_connector_error_keeps_aiohttp_message():
    exc = ClientConnectorError("Cannot connect to host 192.168.1.192:80 [Connect call failed]")
    err, detail = classify_exception(exc)
    assert err == ERROR_CANNOT_CONNECT
    assert "192.168.1.192:80" in detail


def test_unknown_exception_reports_class_name():
    err, detail = classify_exception(ValueError("boom"))
    assert err == ERROR_CANNOT_CONNECT
    assert detail == "ValueError: boom"


def test_error_placeholders_never_none():
    assert error_placeholders("http://h/pair", None, None) == {
        "url": "http://h/pair",
        "device_id": "",
        "error_detail": "",
    }
