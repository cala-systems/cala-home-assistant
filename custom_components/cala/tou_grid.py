"""Derive a TOU schedule from Schedule-helper weekly grids.

Up to three tiers, each a `schedule` helper entity plus a rate; tier order
is priority, so later tiers' blocks are clipped against earlier ones at
minute precision. Weekdays with identical resulting patterns group into
one daySchedule inside a single all-year season; defaultRate fills gaps.

Reading the weekly grid: the schedule integration does NOT expose its
block config as state attributes, so `read_schedule_config` reaches into
HA internals — `hass.data["entity_components"]["schedule"]`
(EntityComponent registers itself there) → `get_entity(entity_id)` →
the entity's `_config` dict ({monday: [{from, to}], ...}). This is
private API and may break across HA versions; every access is wrapped
and fails soft with a debug log.
"""

from __future__ import annotations

import logging
from datetime import time as dt_time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir

from .const import (
    CONF_DEVICE_ID,
    CONF_TOU_DEFAULT_RATE,
    DOMAIN,
    MINUTES_PER_DAY,
    TOU_MAX_DAY_SCHEDULES,
    TOU_MAX_PERIODS,
    TOU_TIER_OPTIONS,
)
from .tou_services import DAY_NAMES, _publish_schedule, schedule_from_price_feed

_LOGGER = logging.getLogger(__name__)

SCHEDULE_DAY_TO_TOU = {
    "monday": "mon",
    "tuesday": "tue",
    "wednesday": "wed",
    "thursday": "thu",
    "friday": "fri",
    "saturday": "sat",
    "sunday": "sun",
}


def time_to_minutes(value: Any) -> int | None:
    """Convert a schedule block boundary to minutes since midnight.

    Accepts datetime.time (the schedule integration stores 24:00 as
    time.max) or "HH:MM[:SS]" strings including "24:00".
    """
    if isinstance(value, dt_time):
        if value.hour == 23 and value.minute == 59 and value.second >= 59:
            return MINUTES_PER_DAY
        return value.hour * 60 + value.minute
    if isinstance(value, str):
        parts = value.split(":")
        try:
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
        except (ValueError, IndexError):
            return None
        if hour == 24 and minute == 0:
            return MINUTES_PER_DAY
        if 0 <= hour < 24 and 0 <= minute < 60:
            return hour * 60 + minute
    return None


def week_blocks_from_config(
    config: dict[str, Any],
) -> dict[str, list[tuple[int, int]]] | None:
    """Extract {tou_day: [(startMin, endMin), ...]} from a schedule config.

    Returns None if any block has an unrecognized shape.
    """
    if not isinstance(config, dict):
        return None
    blocks: dict[str, list[tuple[int, int]]] = {}
    for schedule_day, tou_day in SCHEDULE_DAY_TO_TOU.items():
        day_blocks = config.get(schedule_day) or []
        if not isinstance(day_blocks, list):
            return None
        for block in day_blocks:
            if not isinstance(block, dict):
                return None
            start = time_to_minutes(block.get("from"))
            end = time_to_minutes(block.get("to"))
            if start is None or end is None or start >= end:
                return None
            blocks.setdefault(tou_day, []).append((start, end))
    return blocks


def derive_grid_schedule(
    default_rate: float,
    tiers: list[tuple[float, dict[str, list[tuple[int, int]]], str]],
) -> tuple[dict[str, Any] | None, str | None]:
    """Build a schedule dict from prioritized (rate, week_blocks, entity_id)
    tiers. Returns (schedule, None) or (None, error) on a bounds violation.
    """
    day_periods: dict[str, list[dict[str, Any]]] = {}
    for day in DAY_NAMES:
        slots: list[int | None] = [None] * MINUTES_PER_DAY
        for tier_index, (_rate, blocks, _entity_id) in enumerate(tiers):
            for start, end in blocks.get(day, ()):
                for minute in range(start, min(end, MINUTES_PER_DAY)):
                    if slots[minute] is None:
                        slots[minute] = tier_index

        periods: list[dict[str, Any]] = []
        for minute in range(MINUTES_PER_DAY):
            tier_index = slots[minute]
            if tier_index is None:
                continue
            rate = tiers[tier_index][0]
            if rate == default_rate:
                continue
            if (
                periods
                and periods[-1]["endMin"] == minute
                and periods[-1]["rate"] == rate
            ):
                periods[-1]["endMin"] = minute + 1
            else:
                periods.append(
                    {"startMin": minute, "endMin": minute + 1, "rate": rate}
                )

        if len(periods) > TOU_MAX_PERIODS:
            involved = sorted(
                {
                    tiers[i][2]
                    for i in {s for s in slots if s is not None}
                }
            )
            return None, (
                f"{day}: {len(periods)} rate periods exceed the "
                f"{TOU_MAX_PERIODS}-period limit (helpers: {', '.join(involved)})"
            )
        if periods:
            day_periods[day] = periods

    groups: dict[tuple, dict[str, Any]] = {}
    for day, periods in day_periods.items():
        key = tuple((p["startMin"], p["endMin"], p["rate"]) for p in periods)
        group = groups.setdefault(key, {"days": [], "periods": periods})
        group["days"].append(day)

    if len(groups) > TOU_MAX_DAY_SCHEDULES:
        entities = sorted({entity_id for _r, _b, entity_id in tiers})
        return None, (
            f"{len(groups)} distinct weekday patterns exceed the "
            f"{TOU_MAX_DAY_SCHEDULES}-daySchedule limit "
            f"(helpers: {', '.join(entities)})"
        )

    if not groups:
        return {"version": 1, "defaultRate": default_rate, "seasons": []}, None

    return {
        "version": 1,
        "defaultRate": default_rate,
        "seasons": [
            {
                "startDate": "01-01",
                "endDate": "12-31",
                "daySchedules": [
                    {"days": group["days"], "periods": group["periods"]}
                    for group in groups.values()
                ],
            }
        ],
    }, None


def read_schedule_config(
    hass: HomeAssistant, entity_id: str
) -> dict[str, Any] | None:
    """Fetch a schedule helper's weekly config via HA internals (fragile)."""
    try:
        component = (hass.data.get("entity_components") or {}).get("schedule")
        if component is None:
            return None
        entity = component.get_entity(entity_id)
        if entity is None:
            return None
        config = getattr(entity, "_config", None)
        return config if isinstance(config, dict) else None
    except Exception:  # noqa: BLE001 — private schedule internals
        _LOGGER.debug(
            "Cala TOU grid: failed reading schedule config for %s",
            entity_id,
            exc_info=True,
        )
        return None


def _entity_id_from_option(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("entity_id") or value.get("id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


async def publish_tou_schedule_from_grid(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Derive a schedule from the configured tier helpers and publish it."""
    device_id = entry.data.get(CONF_DEVICE_ID)
    if not device_id:
        return

    opts = entry.options or {}
    default_rate = opts.get(CONF_TOU_DEFAULT_RATE)
    tier_config: list[tuple[str, float]] = []
    for entity_key, rate_key in TOU_TIER_OPTIONS:
        entity_id = _entity_id_from_option(opts.get(entity_key))
        rate = opts.get(rate_key)
        if entity_id and rate:
            tier_config.append((entity_id, float(rate)))
    if not tier_config or not default_rate:
        return

    # The price feed wins: the grid only publishes while no configured feed
    # entity yields a valid schedule (so a dead feed falls back to the grid).
    if schedule_from_price_feed(hass, entry, log_problems=False) is not None:
        _LOGGER.debug(
            "Cala TOU grid: price feed is active; suppressing grid publish"
        )
        return

    tiers = []
    for entity_id, rate in tier_config:
        config = read_schedule_config(hass, entity_id)
        if config is None:
            _LOGGER.debug(
                "Cala TOU grid: schedule config for %s unavailable; "
                "not publishing",
                entity_id,
            )
            return
        blocks = week_blocks_from_config(config)
        if blocks is None:
            _LOGGER.debug(
                "Cala TOU grid: unrecognized block shape in %s; not publishing",
                entity_id,
            )
            return
        tiers.append((rate, blocks, entity_id))

    schedule, error = derive_grid_schedule(float(default_rate), tiers)
    issue_id = f"tou_grid_bounds_{entry.entry_id}"
    if error:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="tou_grid_bounds",
            translation_placeholders={"detail": error},
        )
        _LOGGER.warning("Cala TOU grid: not publishing: %s", error)
        return
    ir.async_delete_issue(hass, DOMAIN, issue_id)

    entry_data = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    if entry_data.get("last_tou_grid_schedule") == schedule:
        _LOGGER.debug("Cala TOU grid: schedule unchanged, skipping publish")
        return

    try:
        await _publish_schedule(hass, device_id, schedule)
    except HomeAssistantError as exc:
        _LOGGER.warning(
            "Cala TOU grid: device rejected or timed out publishing: %s", exc
        )
        return

    entry_data["last_tou_grid_schedule"] = schedule
    _LOGGER.info(
        "Cala TOU grid: published schedule for %s from %s",
        device_id,
        ", ".join(entity_id for _r, _b, entity_id in tiers),
    )
