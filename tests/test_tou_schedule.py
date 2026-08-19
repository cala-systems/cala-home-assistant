import copy
import logging

import pytest
import voluptuous as vol

from cala.tou_services import (
    DAY_NAMES,
    SET_TOU_SCHEDULE_SCHEMA,
    TOU_SCHEDULE_SCHEMA,
    _compress_rates_to_schedule,
)

CANONICAL = {
    "version": 1,
    "defaultRate": 0.12,
    "seasons": [
        {
            "startDate": "06-01",
            "endDate": "09-30",
            "daySchedules": [
                {
                    "days": ["mon", "tue", "wed", "thu", "fri"],
                    "periods": [{"startMin": 600, "endMin": 840, "rate": 0.32}],
                }
            ],
        }
    ],
}


def schedule_with(**overrides):
    schedule = copy.deepcopy(CANONICAL)
    schedule.update(overrides)
    return schedule


def season(start, end, days=("sat", "sun"), periods=None):
    return {
        "startDate": start,
        "endDate": end,
        "daySchedules": [
            {
                "days": list(days),
                "periods": periods
                or [{"startMin": 0, "endMin": 60, "rate": 0.05}],
            }
        ],
    }


class TestScheduleSchemaAccepts:
    def test_canonical(self):
        assert TOU_SCHEDULE_SCHEMA(copy.deepcopy(CANONICAL)) == CANONICAL

    def test_service_schema(self):
        data = SET_TOU_SCHEDULE_SCHEMA(
            {"device_id": "2507xxa006", "schedule": copy.deepcopy(CANONICAL)}
        )
        assert data["device_id"] == "2507xxa006"
        assert data["schedule"] == CANONICAL

    def test_empty_seasons(self):
        TOU_SCHEDULE_SCHEMA(schedule_with(seasons=[]))

    def test_wraparound_season(self):
        TOU_SCHEDULE_SCHEMA(schedule_with(seasons=[season("11-01", "03-31")]))

    def test_two_seasons_one_wrapping(self):
        TOU_SCHEDULE_SCHEMA(
            schedule_with(
                seasons=[season("06-01", "09-30"), season("10-01", "05-31")]
            )
        )

    def test_full_day_period_and_all_days(self):
        TOU_SCHEDULE_SCHEMA(
            schedule_with(
                seasons=[
                    season(
                        "01-01",
                        "12-31",
                        days=DAY_NAMES,
                        periods=[
                            {"startMin": 0, "endMin": 1440, "rate": 0.5}
                        ],
                    )
                ]
            )
        )

    def test_adjacent_periods(self):
        TOU_SCHEDULE_SCHEMA(
            schedule_with(
                seasons=[
                    season(
                        "01-01",
                        "12-31",
                        periods=[
                            {"startMin": 600, "endMin": 840, "rate": 0.3},
                            {"startMin": 840, "endMin": 900, "rate": 0.4},
                        ],
                    )
                ]
            )
        )

    def test_max_bounds(self):
        starts = ["01-01", "04-01", "07-01", "10-01"]
        ends = ["03-31", "06-30", "09-30", "12-31"]
        day_groups = [["sun"], ["mon", "tue"], ["wed", "thu"], ["fri", "sat"]]
        periods = [
            {"startMin": h * 60, "endMin": (h + 1) * 60, "rate": 0.2 + h * 0.01}
            for h in range(8)
        ]
        seasons = [
            {
                "startDate": start,
                "endDate": end,
                "daySchedules": [
                    {"days": days, "periods": copy.deepcopy(periods)}
                    for days in day_groups
                ],
            }
            for start, end in zip(starts, ends)
        ]
        TOU_SCHEDULE_SCHEMA(schedule_with(seasons=seasons))


class TestScheduleSchemaRejects:
    @pytest.mark.parametrize("version", [0, 2, "1", None])
    def test_bad_version(self, version):
        with pytest.raises(vol.Invalid):
            TOU_SCHEDULE_SCHEMA(schedule_with(version=version))

    @pytest.mark.parametrize("rate", [0, -0.1, "cheap", None])
    def test_bad_default_rate(self, rate):
        with pytest.raises(vol.Invalid):
            TOU_SCHEDULE_SCHEMA(schedule_with(defaultRate=rate))

    def test_missing_default_rate(self):
        schedule = schedule_with()
        del schedule["defaultRate"]
        with pytest.raises(vol.Invalid):
            TOU_SCHEDULE_SCHEMA(schedule)

    @pytest.mark.parametrize(
        "date", ["6-1", "2026-06-01", "13-01", "00-10", "01-00", "02-30", "04-31"]
    )
    def test_bad_season_date(self, date):
        with pytest.raises(vol.Invalid):
            TOU_SCHEDULE_SCHEMA(schedule_with(seasons=[season(date, "09-30")]))
        with pytest.raises(vol.Invalid):
            TOU_SCHEDULE_SCHEMA(schedule_with(seasons=[season("06-01", date)]))

    @pytest.mark.parametrize("day", ["monday", "Mon", "MON", "m", 1])
    def test_bad_day_name(self, day):
        with pytest.raises(vol.Invalid):
            TOU_SCHEDULE_SCHEMA(
                schedule_with(seasons=[season("01-01", "12-31", days=[day])])
            )

    def test_empty_days(self):
        with pytest.raises(vol.Invalid):
            TOU_SCHEDULE_SCHEMA(
                schedule_with(seasons=[season("01-01", "12-31", days=[])])
            )

    def test_empty_periods(self):
        schedule = schedule_with()
        schedule["seasons"][0]["daySchedules"][0]["periods"] = []
        with pytest.raises(vol.Invalid):
            TOU_SCHEDULE_SCHEMA(schedule)

    @pytest.mark.parametrize(
        "period",
        [
            {"startMin": 600, "endMin": 600, "rate": 0.3},
            {"startMin": 840, "endMin": 600, "rate": 0.3},
            {"startMin": -60, "endMin": 60, "rate": 0.3},
            {"startMin": 1440, "endMin": 1440, "rate": 0.3},
            {"startMin": 600, "endMin": 1441, "rate": 0.3},
            {"startMin": 600.5, "endMin": 840, "rate": 0.3},
            {"startMin": "600", "endMin": 840, "rate": 0.3},
            {"startMin": 600, "endMin": 840, "rate": -0.1},
            {"startMin": 600, "endMin": 840},
        ],
    )
    def test_bad_period(self, period):
        with pytest.raises(vol.Invalid):
            TOU_SCHEDULE_SCHEMA(
                schedule_with(seasons=[season("01-01", "12-31", periods=[period])])
            )

    def test_overlapping_periods(self):
        with pytest.raises(vol.Invalid):
            TOU_SCHEDULE_SCHEMA(
                schedule_with(
                    seasons=[
                        season(
                            "01-01",
                            "12-31",
                            periods=[
                                {"startMin": 600, "endMin": 900, "rate": 0.3},
                                {"startMin": 840, "endMin": 960, "rate": 0.4},
                            ],
                        )
                    ]
                )
            )

    def test_duplicate_day_in_one_day_schedule(self):
        with pytest.raises(vol.Invalid):
            TOU_SCHEDULE_SCHEMA(
                schedule_with(
                    seasons=[season("01-01", "12-31", days=["mon", "mon"])]
                )
            )

    def test_day_in_two_day_schedules(self):
        schedule = schedule_with(seasons=[season("01-01", "12-31", days=["mon"])])
        schedule["seasons"][0]["daySchedules"].append(
            {
                "days": ["mon", "tue"],
                "periods": [{"startMin": 60, "endMin": 120, "rate": 0.2}],
            }
        )
        with pytest.raises(vol.Invalid):
            TOU_SCHEDULE_SCHEMA(schedule)

    def test_overlapping_seasons(self):
        with pytest.raises(vol.Invalid):
            TOU_SCHEDULE_SCHEMA(
                schedule_with(
                    seasons=[season("06-01", "09-30"), season("09-30", "12-31")]
                )
            )

    def test_overlapping_seasons_wraparound(self):
        with pytest.raises(vol.Invalid):
            TOU_SCHEDULE_SCHEMA(
                schedule_with(
                    seasons=[season("11-01", "02-28"), season("01-15", "03-10")]
                )
            )

    def test_too_many_seasons(self):
        seasons = [
            season(f"{m:02d}-01", f"{m:02d}-15") for m in range(1, 6)
        ]
        with pytest.raises(vol.Invalid):
            TOU_SCHEDULE_SCHEMA(schedule_with(seasons=seasons))

    def test_too_many_day_schedules(self):
        schedule = schedule_with(seasons=[season("01-01", "12-31", days=["sun"])])
        for i, day in enumerate(["mon", "tue", "wed", "thu"]):
            schedule["seasons"][0]["daySchedules"].append(
                {
                    "days": [day],
                    "periods": [
                        {"startMin": i * 60, "endMin": (i + 1) * 60, "rate": 0.2}
                    ],
                }
            )
        with pytest.raises(vol.Invalid):
            TOU_SCHEDULE_SCHEMA(schedule)

    def test_too_many_periods(self):
        periods = [
            {"startMin": h * 120, "endMin": h * 120 + 60, "rate": 0.2}
            for h in range(9)
        ]
        with pytest.raises(vol.Invalid):
            TOU_SCHEDULE_SCHEMA(
                schedule_with(seasons=[season("01-01", "12-31", periods=periods)])
            )


def expand_schedule(schedule):
    """Per-hour rate array implied by a compressed all-year schedule."""
    rates = [schedule["defaultRate"]] * 24
    for szn in schedule["seasons"]:
        for day_schedule in szn["daySchedules"]:
            for period in day_schedule["periods"]:
                for hour in range(period["startMin"] // 60, period["endMin"] // 60):
                    rates[hour] = period["rate"]
    return rates


class TestCompressRatesToSchedule:
    def test_flat_rates_no_periods(self):
        schedule = _compress_rates_to_schedule([0.15] * 24)
        assert schedule == {"version": 1, "defaultRate": 0.15, "seasons": []}
        TOU_SCHEDULE_SCHEMA(schedule)

    def test_banded_rates_round_trip(self):
        rates = (
            [0.10] * 6 + [0.32] * 4 + [0.10] * 4 + [0.45] * 4 + [0.32] * 3 + [0.10] * 3
        )
        schedule = _compress_rates_to_schedule(rates)
        TOU_SCHEDULE_SCHEMA(schedule)
        assert schedule["defaultRate"] == 0.10
        season = schedule["seasons"][0]
        assert season["startDate"] == "01-01"
        assert season["endDate"] == "12-31"
        day_schedule = season["daySchedules"][0]
        assert sorted(day_schedule["days"]) == sorted(DAY_NAMES)
        assert day_schedule["periods"] == [
            {"startMin": 360, "endMin": 600, "rate": 0.32},
            {"startMin": 840, "endMin": 1080, "rate": 0.45},
            {"startMin": 1080, "endMin": 1260, "rate": 0.32},
        ]
        assert expand_schedule(schedule) == rates

    def test_quantizes_to_max_periods_and_reports_error(self, caplog):
        rates = []
        for hour in range(24):
            if hour % 2 == 0:
                rates.append(0.10)
            else:
                rates.append(0.10 + 0.01 * (hour // 2 + 1))
        with caplog.at_level(logging.WARNING):
            schedule = _compress_rates_to_schedule(rates)
        TOU_SCHEDULE_SCHEMA(schedule)
        periods = schedule["seasons"][0]["daySchedules"][0]["periods"]
        assert len(periods) == 8
        expanded = expand_schedule(schedule)
        max_error = max(abs(a - b) for a, b in zip(expanded, rates))
        assert max_error == pytest.approx(0.04)
        assert f"{max_error:.4f} $/kWh" in caplog.text
        # The 8 kept periods are the ones deviating most from defaultRate.
        kept_rates = {p["rate"] for p in periods}
        assert kept_rates == {rates[h] for h in range(9, 24, 2)}

    def test_wrong_length_returns_none(self):
        assert _compress_rates_to_schedule([0.1] * 23) is None
        assert _compress_rates_to_schedule([0.1] * 25) is None

    def test_no_positive_rates_returns_none(self):
        assert _compress_rates_to_schedule([0.0] * 24) is None

    def test_nonpositive_majority_uses_positive_default(self):
        rates = [0.0] * 14 + [0.25] * 10
        schedule = _compress_rates_to_schedule(rates)
        TOU_SCHEDULE_SCHEMA(schedule)
        assert schedule["defaultRate"] == 0.25
        assert expand_schedule(schedule) == rates
