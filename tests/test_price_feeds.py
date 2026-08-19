from datetime import datetime, timedelta, timezone

import pytest

from cala.price_feeds import (
    clamp_rates_to_floor,
    normalize_price_attributes,
)

TZ = timezone(timedelta(hours=2))


def hourly(hour):
    return datetime(2026, 7, 17, hour, 0, tzinfo=TZ)


def nordpool_raw_today(values, minutes_step=60):
    entries = []
    for hour in range(24):
        for offset in range(0, 60, minutes_step):
            start = datetime(2026, 7, 17, hour, offset, tzinfo=TZ)
            entries.append(
                {
                    "start": start,
                    "end": start + timedelta(minutes=minutes_step),
                    "value": values[hour] if minutes_step == 60 else values[hour][offset // minutes_step],
                }
            )
    return entries


class TestOpenadr3:
    def test_forecast_rotation(self):
        forecast = [
            {"hour": (7 + i) % 24, "value": 0.10 + ((7 + i) % 24) * 0.01}
            for i in range(24)
        ]
        rates, source = normalize_price_attributes({"forecast": forecast})
        assert source == "openadr3"
        assert rates == [pytest.approx(0.10 + h * 0.01) for h in range(24)]

    def test_short_forecast_rejected(self):
        forecast = [{"hour": h, "value": 0.1} for h in range(23)]
        rates, source = normalize_price_attributes({"forecast": forecast})
        assert source == "openadr3"
        assert rates is None


class TestNordpool:
    def test_hourly_raw_today(self):
        values = [0.10 + h * 0.005 for h in range(24)]
        rates, source = normalize_price_attributes(
            {"raw_today": nordpool_raw_today(values), "today": values}
        )
        assert source == "nordpool"
        assert rates == pytest.approx(values)

    def test_iso_string_timestamps(self):
        values = [0.2] * 24
        entries = [
            {
                "start": hourly(h).isoformat(),
                "end": (hourly(h) + timedelta(hours=1)).isoformat(),
                "value": values[h],
            }
            for h in range(24)
        ]
        rates, source = normalize_price_attributes({"raw_today": entries})
        assert source == "nordpool"
        assert rates == pytest.approx(values)

    def test_quarter_hourly_averaged(self):
        values = [[0.1, 0.2, 0.3, 0.4] for _ in range(24)]
        rates, source = normalize_price_attributes(
            {"raw_today": nordpool_raw_today(values, minutes_step=15)}
        )
        assert source == "nordpool"
        assert rates == pytest.approx([0.25] * 24)

    def test_missing_hour_rejected(self):
        values = [0.2] * 24
        entries = nordpool_raw_today(values)[:23]
        rates, _source = normalize_price_attributes({"raw_today": entries})
        assert rates is None

    def test_null_value_rejected(self):
        entries = nordpool_raw_today([0.2] * 24)
        entries[5]["value"] = None
        rates, _source = normalize_price_attributes({"raw_today": entries})
        assert rates is None


class TestEntsoe:
    def test_prices_today(self):
        entries = [
            {"time": f"2026-07-17 {h:02d}:00:00+02:00", "price": 0.05 + h * 0.01}
            for h in range(24)
        ]
        rates, source = normalize_price_attributes({"prices_today": entries})
        assert source == "entsoe"
        assert rates == pytest.approx([0.05 + h * 0.01 for h in range(24)])

    def test_combined_prices_uses_first_day(self):
        today = [
            {"time": f"2026-07-17 {h:02d}:00:00+02:00", "price": 0.10}
            for h in range(24)
        ]
        tomorrow = [
            {"time": f"2026-07-18 {h:02d}:00:00+02:00", "price": 0.99}
            for h in range(24)
        ]
        rates, source = normalize_price_attributes({"prices": today + tomorrow})
        assert source == "entsoe"
        assert rates == pytest.approx([0.10] * 24)


class TestTibber:
    def test_today_number_list(self):
        values = [0.15 + h * 0.002 for h in range(24)]
        rates, source = normalize_price_attributes({"today": values})
        assert source == "tibber"
        assert rates == pytest.approx(values)

    def test_today_dict_entries(self):
        entries = [
            {"startsAt": hourly(h).isoformat(), "total": 0.3}
            for h in range(24)
        ]
        rates, source = normalize_price_attributes({"today": entries})
        assert source == "tibber"
        assert rates == pytest.approx([0.3] * 24)

    def test_wrong_length_number_list_rejected(self):
        rates, source = normalize_price_attributes({"today": [0.1] * 23})
        assert source == "tibber"
        assert rates is None


class TestDetection:
    def test_forecast_takes_precedence(self):
        forecast = [{"hour": h, "value": 0.5} for h in range(24)]
        rates, source = normalize_price_attributes(
            {"forecast": forecast, "today": [0.1] * 24}
        )
        assert source == "openadr3"
        assert rates == pytest.approx([0.5] * 24)

    def test_unknown_attributes(self):
        rates, source = normalize_price_attributes({"friendly_name": "x"})
        assert rates is None
        assert source is None


class TestClamp:
    def test_no_clamp_needed(self):
        rates, changed = clamp_rates_to_floor([0.1, 0.2], 0.001)
        assert rates == [0.1, 0.2]
        assert changed == 0

    def test_clamps_zero_and_negative(self):
        rates, changed = clamp_rates_to_floor([0.1, 0.0, -0.05, 0.2], 0.001)
        assert rates == [0.1, 0.001, 0.001, 0.2]
        assert changed == 2
