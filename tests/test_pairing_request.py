"""End-to-end tests for _http_pair against a fake device.

Skipped when aiohttp/cryptography are not installed (the rest of the suite
runs against stubbed Home Assistant only).
"""

import asyncio
import base64
import hashlib
import json
import socket

import pytest

aiohttp = pytest.importorskip("aiohttp")
pytest.importorskip("cryptography")
from aiohttp import web  # noqa: E402

from cala.pairing_request import _http_pair  # noqa: E402

DEVICE_ID = "260121B006"
CODE = "385145"


def _decrypt(encrypted: str, code: str) -> dict:
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    raw = base64.b64decode(encrypted)
    key = hashlib.sha256(code.encode()).digest()[:16]
    dec = Cipher(algorithms.AES(key), modes.CBC(raw[:16])).decryptor()
    padded = dec.update(raw[16:]) + dec.finalize()
    unpad = padding.PKCS7(128).unpadder()
    return json.loads(unpad.update(padded) + unpad.finalize())


async def _pair_against(handler):
    app = web.Application()
    app.router.add_post("/pair", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        return await _http_pair(
            f"http://127.0.0.1:{port}/pair",
            DEVICE_ID,
            "Cala Water Heater",
            CODE,
            "192.168.3.32",
            1883,
            "cala",
            "secret",
        )
    finally:
        await runner.cleanup()


def test_success_returns_credentials_and_topics():
    seen = {}

    async def handler(request):
        body = await request.json()
        seen.update(_decrypt(body["encrypted"], CODE))
        return web.json_response(
            {"mqtt": {"username": "cala", "password": "pw", "topic_prefix": f"cala/{DEVICE_ID}"}}
        )

    data, err, detail = asyncio.run(_pair_against(handler))
    assert (err, detail) == (None, None)
    assert seen["device_id"] == DEVICE_ID
    assert seen["mqtt_broker"] == {
        "host": "192.168.3.32", "port": 1883, "username": "cala", "password": "secret",
    }
    assert data["mqtt_username"] == "cala"
    assert data["state_topic"] == f"cala/{DEVICE_ID}/state"


def test_403_device_id_is_surfaced():
    async def handler(request):
        return web.Response(status=403, text="Invalid or expired device id")

    data, err, detail = asyncio.run(_pair_against(handler))
    assert data is None
    assert err == "invalid_device_id"
    assert detail == "Invalid or expired device id"


def test_400_decryption_failed_is_invalid_code():
    async def handler(request):
        return web.Response(status=400, text="Decryption failed")

    _, err, detail = asyncio.run(_pair_against(handler))
    assert err == "invalid_code"
    assert detail == "Decryption failed"


def test_200_without_credentials_is_pairing_rejected():
    async def handler(request):
        return web.json_response({"status": "nope"})

    _, err, detail = asyncio.run(_pair_against(handler))
    assert err == "pairing_rejected"
    assert "status" in detail


def test_connection_refused_is_cannot_connect_with_detail():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    data, err, detail = asyncio.run(
        _http_pair(f"http://127.0.0.1:{port}/pair", DEVICE_ID, "n", CODE, "h", 1883, "u", "p")
    )
    assert data is None
    assert err == "cannot_connect"
    assert f"127.0.0.1:{port}" in detail
