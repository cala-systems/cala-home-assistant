"""TOU schedule service and auto-publish driven by an upstream entity.

Service `cala.set_tou_schedule` accepts a period-based schedule (seasons →
daySchedules → periods, falling back to `defaultRate`) for manual /
automation use.

`publish_tou_schedule_from_entity` reads an upstream price entity's
attributes (openadr3-ven-hass, Nord Pool, ENTSO-E, or Tibber shapes; see
`price_feeds`), normalizes them to a midnight-anchored 24-element array,
compresses that into a single all-year schedule, and publishes it.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
import voluptuous as vol

from .const import (
    ATTR_DEVICE_ID,
    ATTR_SCHEDULE,
    CONF_DEVICE_ID,
    CONF_TOU_RATES_ENTITY,
    DOMAIN,
    MINUTES_PER_DAY,
    TOU_MAX_DAY_SCHEDULES,
    TOU_MAX_PERIODS,
    TOU_MAX_SEASONS,
    TOU_RATE_FLOOR,
    TOU_RATES_HOURS,
)
from .helpers import get_command_topic, publish_command_and_wait_response
from .price_feeds import clamp_rates_to_floor, normalize_price_attributes

_LOGGER = logging.getLogger(__name__)

RESPONSE_TIMEOUT_S = 10

DAY_NAMES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")

# Cumulative day-of-year offsets for a leap year, so 02-29 is accepted.
_MONTH_OFFSETS = (0, 31, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335)
_DAYS_IN_MONTH = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def validate_season_date(value: str) -> str:
    """Check a MM-DD string is a real calendar date (leap 02-29 allowed)."""
    month = int(value[:2])
    day = int(value[3:])
    if not 1 <= month <= 12:
        raise vol.Invalid(f"invalid month in season date: {value}")
    if not 1 <= day <= _DAYS_IN_MONTH[month - 1]:
        raise vol.Invalid(f"invalid day in season date: {value}")
    return value


def validate_period_bounds(period: dict[str, Any]) -> dict[str, Any]:
    """Check startMin < endMin within a single period."""
    if period["startMin"] >= period["endMin"]:
        raise vol.Invalid(
            f"period startMin ({period['startMin']}) must be less than "
            f"endMin ({period['endMin']})"
        )
    return period


def validate_no_period_overlap(day_schedule: dict[str, Any]) -> dict[str, Any]:
    """Check periods within one daySchedule don't overlap."""
    periods = sorted(day_schedule["periods"], key=lambda p: p["startMin"])
    for prev, cur in zip(periods, periods[1:]):
        if cur["startMin"] < prev["endMin"]:
            raise vol.Invalid(
                f"periods overlap: [{prev['startMin']}, {prev['endMin']}) and "
                f"[{cur['startMin']}, {cur['endMin']})"
            )
    return day_schedule


def validate_unique_days(season: dict[str, Any]) -> dict[str, Any]:
    """Check no day appears in more than one daySchedule of a season."""
    seen: set[str] = set()
    for day_schedule in season["daySchedules"]:
        for day in day_schedule["days"]:
            if day in seen:
                raise vol.Invalid(
                    f"day '{day}' appears in multiple daySchedules of one season"
                )
            seen.add(day)
    return season


def _date_ordinal(value: str) -> int:
    return _MONTH_OFFSETS[int(value[:2]) - 1] + int(value[3:]) - 1


def _season_day_set(season: dict[str, Any]) -> set[int]:
    start = _date_ordinal(season["startDate"])
    end = _date_ordinal(season["endDate"])
    if start <= end:
        return set(range(start, end + 1))
    # Wrap-around season (e.g. 11-01 → 02-28).
    return set(range(start, 366)) | set(range(0, end + 1))


def validate_no_season_overlap(schedule: dict[str, Any]) -> dict[str, Any]:
    """Check season date ranges don't overlap (wrap-around aware)."""
    covered: set[int] = set()
    for season in schedule["seasons"]:
        days = _season_day_set(season)
        if covered & days:
            raise vol.Invalid(
                f"season {season['startDate']}→{season['endDate']} overlaps "
                "an earlier season"
            )
        covered |= days
    return schedule


PERIOD_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required("startMin"): vol.All(
                int, vol.Range(min=0, max=MINUTES_PER_DAY - 1)
            ),
            vol.Required("endMin"): vol.All(
                int, vol.Range(min=1, max=MINUTES_PER_DAY)
            ),
            vol.Required("rate"): vol.All(vol.Coerce(float), vol.Range(min=0)),
        }
    ),
    validate_period_bounds,
)

DAY_SCHEDULE_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required("days"): vol.All(
                [vol.In(DAY_NAMES)], vol.Length(min=1, max=len(DAY_NAMES))
            ),
            vol.Required("periods"): vol.All(
                [PERIOD_SCHEMA], vol.Length(min=1, max=TOU_MAX_PERIODS)
            ),
        }
    ),
    validate_no_period_overlap,
)

SEASON_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required("startDate"): vol.All(
                str, vol.Match(r"^\d{2}-\d{2}$"), validate_season_date
            ),
            vol.Required("endDate"): vol.All(
                str, vol.Match(r"^\d{2}-\d{2}$"), validate_season_date
            ),
            vol.Required("daySchedules"): vol.All(
                [DAY_SCHEDULE_SCHEMA],
                vol.Length(min=1, max=TOU_MAX_DAY_SCHEDULES),
            ),
        }
    ),
    validate_unique_days,
)

TOU_SCHEDULE_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required("version"): vol.In([1]),
            vol.Required("defaultRate"): vol.All(
                vol.Coerce(float), vol.Range(min=0, min_included=False)
            ),
            vol.Required("seasons"): vol.All(
                [SEASON_SCHEMA], vol.Length(max=TOU_MAX_SEASONS)
            ),
        }
    ),
    validate_no_season_overlap,
)

SET_TOU_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): str,
        vol.Required(ATTR_SCHEDULE): TOU_SCHEDULE_SCHEMA,
    }
)


async def _publish_schedule(
    hass: HomeAssistant, device_id: str, schedule: dict[str, Any]
) -> None:
    command_topic = get_command_topic(hass, device_id)
    if not command_topic:
        raise HomeAssistantError(f"Unknown device_id: {device_id}")
    payload = {"type": "set_tou_schedule", "touSchedule": schedule}
    await publish_command_and_wait_response(
        hass, command_topic, payload, RESPONSE_TIMEOUT_S
    )


async def handle_set_tou_schedule(call: ServiceCall) -> None:
    """Service: cala.set_tou_schedule — publish a period-based TOU schedule."""
    hass = call.hass
    device_id = call.data[ATTR_DEVICE_ID]
    schedule = call.data[ATTR_SCHEDULE]
    _LOGGER.debug(
        "Cala set_tou_schedule: device_id=%s schedule=%s", device_id, schedule
    )
    await _publish_schedule(hass, device_id, schedule)


def _compress_rates_to_schedule(rates: list[float]) -> dict[str, Any] | None:
    """Compress a midnight-anchored 24-rate array into a schedule dict.

    defaultRate is the most common rate; consecutive equal non-default hours
    merge into periods inside a single all-year, all-days season. If more
    than TOU_MAX_PERIODS periods remain, the ones deviating least from
    defaultRate are absorbed into it (quantization).
    """
    if not isinstance(rates, list) or len(rates) != TOU_RATES_HOURS:
        return None

    counts = Counter(r for r in rates if r > 0)
    if not counts:
        return None
    default_rate = counts.most_common(1)[0][0]

    periods: list[dict[str, Any]] = []
    for hour in range(TOU_RATES_HOURS):
        rate = rates[hour]
        if rate == default_rate:
            continue
        start_min = hour * 60
        if (
            periods
            and periods[-1]["endMin"] == start_min
            and periods[-1]["rate"] == rate
        ):
            periods[-1]["endMin"] = start_min + 60
        else:
            periods.append(
                {"startMin": start_min, "endMin": start_min + 60, "rate": rate}
            )

    if len(periods) > TOU_MAX_PERIODS:
        ranked = sorted(
            periods, key=lambda p: abs(p["rate"] - default_rate), reverse=True
        )
        kept_ids = {id(p) for p in ranked[:TOU_MAX_PERIODS]}
        dropped = ranked[TOU_MAX_PERIODS:]
        max_error = max(abs(p["rate"] - default_rate) for p in dropped)
        periods = [p for p in periods if id(p) in kept_ids]
        _LOGGER.warning(
            "Cala TOU: forecast needs %d periods, quantized to %d; "
            "max rate error introduced: %.4f $/kWh",
            len(periods) + len(dropped),
            len(periods),
            max_error,
        )

    if not periods:
        return {"version": 1, "defaultRate": default_rate, "seasons": []}

    return {
        "version": 1,
        "defaultRate": default_rate,
        "seasons": [
            {
                "startDate": "01-01",
                "endDate": "12-31",
                "daySchedules": [{"days": list(DAY_NAMES), "periods": periods}],
            }
        ],
    }


async def publish_tou_schedule_from_entity(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Read the configured tou_rates_entity, compress, and publish on change."""
    device_id = entry.data.get(CONF_DEVICE_ID)
    if not device_id:
        return

    opts = entry.options or {}
    entity_id = opts.get(CONF_TOU_RATES_ENTITY)
    if isinstance(entity_id, dict):
        entity_id = entity_id.get("entity_id") or entity_id.get("id")
    if not entity_id:
        return

    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable", ""):
        _LOGGER.debug(
            "Cala TOU: source entity %s has no usable state", entity_id
        )
        return

    rates, source = normalize_price_attributes(state.attributes)
    if rates is None:
        _LOGGER.warning(
            "Cala TOU: %s has no recognizable price attributes covering %d "
            "hours (detected source: %s); not publishing",
            entity_id,
            TOU_RATES_HOURS,
            source or "none",
        )
        return

    rates, clamped = clamp_rates_to_floor(rates, TOU_RATE_FLOOR)
    if clamped:
        _LOGGER.warning(
            "Cala TOU: %s: clamped %d non-positive hourly price(s) to the "
            "%.3f floor (firmware rejects rates <= 0)",
            entity_id,
            clamped,
            TOU_RATE_FLOOR,
        )

    schedule = _compress_rates_to_schedule(rates)
    if schedule is None:
        _LOGGER.warning(
            "Cala TOU: %s rates have no positive values; not publishing",
            entity_id,
        )
        return

    entry_data = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    last = entry_data.get("last_tou_schedule")
    if last == schedule:
        _LOGGER.debug("Cala TOU: schedule unchanged, skipping publish")
        return

    try:
        await _publish_schedule(hass, device_id, schedule)
    except HomeAssistantError as exc:
        _LOGGER.warning(
            "Cala TOU: device rejected or timed out publishing schedule: %s",
            exc,
        )
        return

    entry_data["last_tou_schedule"] = schedule
    _LOGGER.info(
        "Cala TOU: published schedule for %s from %s",
        device_id,
        entity_id,
    )
