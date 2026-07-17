"""Adapters normalizing price-feed entity attributes to 24 hourly rates.

Auto-detects the source integration by attribute shape and returns a
midnight-anchored 24-element rate list:

- openadr3-ven-hass: `forecast` list of {datetime, value, hour}
- Nord Pool (custom component): `raw_today` list of {start, end, value}
- ENTSO-E (hass-entso-e): `prices_today` (or `prices`) list of {time, price}
- Tibber (custom price sensors): `today` list of 24 numbers, or a list of
  {startsAt/start_time, total/price} dicts

Sub-hourly entries (e.g. 15-minute Nord Pool data) are averaged per hour.
No Home Assistant imports here so the adapters test standalone.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .const import TOU_RATES_HOURS

_TIME_KEYS = ("start", "time", "startsAt", "start_time", "datetime")
_VALUE_KEYS = ("value", "price", "total", "price_total")


def _rates_from_openadr3_forecast(
    forecast: list[dict[str, Any]],
) -> list[float] | None:
    """Rolling-from-now forecast with explicit hour-of-day per entry."""
    if not isinstance(forecast, list) or len(forecast) < TOU_RATES_HOURS:
        return None

    rates: list[float | None] = [None] * TOU_RATES_HOURS
    for entry in forecast[:TOU_RATES_HOURS]:
        if not isinstance(entry, dict):
            return None
        hour = entry.get("hour")
        value = entry.get("value")
        if hour is None or value is None:
            return None
        try:
            hour_i = int(hour) % TOU_RATES_HOURS
            value_f = float(value)
        except (TypeError, ValueError):
            return None
        rates[hour_i] = value_f

    if any(r is None for r in rates):
        # 24 forecast entries should cover 24 distinct hours; if they don't,
        # something is wrong with the source (e.g. half-hour intervals).
        return None
    return [float(r) for r in rates]


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _entry_timestamp_and_value(
    entry: Any,
) -> tuple[datetime, float] | None:
    if not isinstance(entry, dict):
        return None
    timestamp = None
    for key in _TIME_KEYS:
        if key in entry:
            timestamp = _parse_timestamp(entry[key])
            break
    if timestamp is None:
        return None
    value = None
    for key in _VALUE_KEYS:
        if entry.get(key) is not None:
            value = entry[key]
            break
    try:
        return timestamp, float(value)
    except (TypeError, ValueError):
        return None


def _rates_from_timestamped_entries(
    entries: list[Any],
) -> list[float] | None:
    """Bucket {timestamp, value} entries by local hour of the first day seen.

    Averages sub-hourly entries (e.g. 15-minute data) within each hour.
    Returns None unless all 24 hours are covered.
    """
    if not isinstance(entries, list) or not entries:
        return None

    first_date: date | None = None
    sums = [0.0] * TOU_RATES_HOURS
    counts = [0] * TOU_RATES_HOURS
    for entry in entries:
        parsed = _entry_timestamp_and_value(entry)
        if parsed is None:
            return None
        timestamp, value = parsed
        if first_date is None:
            first_date = timestamp.date()
        elif timestamp.date() != first_date:
            continue
        sums[timestamp.hour] += value
        counts[timestamp.hour] += 1

    if any(count == 0 for count in counts):
        return None
    return [sums[h] / counts[h] for h in range(TOU_RATES_HOURS)]


def _rates_from_number_list(values: list[Any]) -> list[float] | None:
    if not isinstance(values, list) or len(values) != TOU_RATES_HOURS:
        return None
    try:
        return [float(v) for v in values]
    except (TypeError, ValueError):
        return None


def normalize_price_attributes(
    attributes: dict[str, Any],
) -> tuple[list[float] | None, str | None]:
    """Detect the feed format and return (24 hourly rates, source name)."""
    if not isinstance(attributes, dict):
        return None, None

    if "forecast" in attributes:
        return (
            _rates_from_openadr3_forecast(attributes["forecast"]),
            "openadr3",
        )
    if "raw_today" in attributes:
        return (
            _rates_from_timestamped_entries(attributes["raw_today"]),
            "nordpool",
        )
    for key in ("prices_today", "prices"):
        if key in attributes:
            return (
                _rates_from_timestamped_entries(attributes[key]),
                "entsoe",
            )
    if "today" in attributes:
        today = attributes["today"]
        rates = _rates_from_number_list(today)
        if rates is None:
            rates = _rates_from_timestamped_entries(today)
        return rates, "tibber"
    return None, None


def clamp_rates_to_floor(
    rates: list[float], floor: float
) -> tuple[list[float], int]:
    """Raise non-positive rates to `floor`; returns (rates, clamped count)."""
    clamped = [rate if rate > 0 else floor for rate in rates]
    changed = sum(1 for old, new in zip(rates, clamped) if old != new)
    return clamped, changed
