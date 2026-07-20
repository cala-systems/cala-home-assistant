"""Per-device memory of the last successfully published TOU schedule.

Every publish path (the set_tou_schedule service and the price-feed
auto-publish) records here; the diagnostic TOU schedule sensor exposes the
stored schedule as attributes so the Lovelace card can prefill its editor.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import DOMAIN

STORE_KEY = "last_tou_published"
SIGNAL_TOU_SCHEDULE_RECORDED = "cala_tou_schedule_recorded_{device_id}"


def _store(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    return hass.data.setdefault(DOMAIN, {}).setdefault(STORE_KEY, {})


def record_published_schedule(
    hass: HomeAssistant, device_id: str, schedule: dict[str, Any]
) -> None:
    """Remember a successfully published schedule and notify listeners."""
    _store(hass)[device_id] = {
        "schedule": schedule,
        "published_at": dt_util.utcnow().isoformat(),
    }
    async_dispatcher_send(
        hass, SIGNAL_TOU_SCHEDULE_RECORDED.format(device_id=device_id)
    )


def seed_published_schedule(
    hass: HomeAssistant,
    device_id: str,
    schedule: dict[str, Any],
    published_at: str | None,
) -> None:
    """Restore a schedule (e.g. from a restored entity state) without
    overwriting anything recorded since startup."""
    store = _store(hass)
    if device_id not in store:
        store[device_id] = {"schedule": schedule, "published_at": published_at}


def get_published_schedule(
    hass: HomeAssistant, device_id: str
) -> dict[str, Any] | None:
    """Return {"schedule": ..., "published_at": ...} or None."""
    return _store(hass).get(device_id)
