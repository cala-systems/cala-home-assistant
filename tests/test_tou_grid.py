from datetime import time

import pytest

from cala.tou_grid import (
    derive_grid_schedule,
    time_to_minutes,
    week_blocks_from_config,
)
from cala.tou_services import TOU_SCHEDULE_SCHEMA


def blocks(**days):
    return {day: list(ranges) for day, ranges in days.items()}


class TestTimeToMinutes:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (time(0, 0), 0),
            (time(16, 30), 990),
            (time.max, 1440),
            (time(23, 59, 59), 1440),
            ("07:00", 420),
            ("07:00:00", 420),
            ("24:00", 1440),
            ("24:00:00", 1440),
        ],
    )
    def test_valid(self, value, expected):
        assert time_to_minutes(value) == expected

    @pytest.mark.parametrize("value", ["25:00", "07:75", "junk", None, 420])
    def test_invalid(self, value):
        assert time_to_minutes(value) is None


class TestWeekBlocksFromConfig:
    def test_maps_days_and_times(self):
        config = {
            "monday": [{"from": time(16, 0), "to": time(21, 0)}],
            "sunday": [
                {"from": "08:00:00", "to": "11:00:00"},
                {"from": "17:00:00", "to": "24:00"},
            ],
        }
        assert week_blocks_from_config(config) == {
            "mon": [(960, 1260)],
            "sun": [(480, 660), (1020, 1440)],
        }

    def test_empty_config(self):
        assert week_blocks_from_config({"name": "Peak"}) == {}

    @pytest.mark.parametrize(
        "config",
        [
            {"monday": [{"from": "junk", "to": "10:00"}]},
            {"monday": [{"from": "10:00"}]},
            {"monday": [{"from": "12:00", "to": "10:00"}]},
            {"monday": "not-a-list"},
            "not-a-dict",
        ],
    )
    def test_bad_shapes(self, config):
        assert week_blocks_from_config(config) is None


class TestDeriveGridSchedule:
    def test_no_tiers_blocks_gives_empty_seasons(self):
        schedule, error = derive_grid_schedule(
            0.12, [(0.32, {}, "schedule.peak")]
        )
        assert error is None
        assert schedule == {"version": 1, "defaultRate": 0.12, "seasons": []}
        TOU_SCHEDULE_SCHEMA(schedule)

    def test_single_tier_grouping(self):
        weekdays = blocks(
            mon=[(960, 1260)],
            tue=[(960, 1260)],
            wed=[(960, 1260)],
            thu=[(960, 1260)],
            fri=[(960, 1260)],
            sat=[(600, 840)],
        )
        schedule, error = derive_grid_schedule(
            0.12, [(0.32, weekdays, "schedule.peak")]
        )
        assert error is None
        TOU_SCHEDULE_SCHEMA(schedule)
        season = schedule["seasons"][0]
        assert season["startDate"] == "01-01"
        assert season["endDate"] == "12-31"
        day_schedules = {
            tuple(ds["days"]): ds["periods"] for ds in season["daySchedules"]
        }
        assert day_schedules == {
            ("mon", "tue", "wed", "thu", "fri"): [
                {"startMin": 960, "endMin": 1260, "rate": 0.32}
            ],
            ("sat",): [{"startMin": 600, "endMin": 840, "rate": 0.32}],
        }

    def test_lower_tier_clipped_by_higher(self):
        tier1 = blocks(mon=[(960, 1260)])
        tier2 = blocks(mon=[(600, 1080)])
        schedule, error = derive_grid_schedule(
            0.12,
            [
                (0.45, tier1, "schedule.critical"),
                (0.25, tier2, "schedule.peak"),
            ],
        )
        assert error is None
        TOU_SCHEDULE_SCHEMA(schedule)
        periods = schedule["seasons"][0]["daySchedules"][0]["periods"]
        assert periods == [
            {"startMin": 600, "endMin": 960, "rate": 0.25},
            {"startMin": 960, "endMin": 1260, "rate": 0.45},
        ]

    def test_fully_shadowed_tier_disappears(self):
        tier1 = blocks(mon=[(600, 1200)])
        tier2 = blocks(mon=[(700, 800)])
        schedule, error = derive_grid_schedule(
            0.12,
            [
                (0.45, tier1, "schedule.critical"),
                (0.25, tier2, "schedule.peak"),
            ],
        )
        assert error is None
        periods = schedule["seasons"][0]["daySchedules"][0]["periods"]
        assert periods == [{"startMin": 600, "endMin": 1200, "rate": 0.45}]

    def test_tier_at_default_rate_is_omitted(self):
        schedule, error = derive_grid_schedule(
            0.12, [(0.12, blocks(mon=[(0, 600)]), "schedule.peak")]
        )
        assert error is None
        assert schedule["seasons"] == []

    def test_adjacent_same_rate_blocks_merge(self):
        weekdays = blocks(mon=[(600, 720), (720, 840)])
        schedule, error = derive_grid_schedule(
            0.12, [(0.32, weekdays, "schedule.peak")]
        )
        assert error is None
        periods = schedule["seasons"][0]["daySchedules"][0]["periods"]
        assert periods == [{"startMin": 600, "endMin": 840, "rate": 0.32}]

    def test_too_many_day_patterns(self):
        weekdays = blocks(
            mon=[(0, 60)],
            tue=[(60, 120)],
            wed=[(120, 180)],
            thu=[(180, 240)],
            fri=[(240, 300)],
        )
        schedule, error = derive_grid_schedule(
            0.12, [(0.32, weekdays, "schedule.peak")]
        )
        assert schedule is None
        assert "5 distinct weekday patterns" in error
        assert "schedule.peak" in error

    def test_too_many_periods_names_helpers(self):
        weekdays = blocks(mon=[(h * 120, h * 120 + 60) for h in range(9)])
        schedule, error = derive_grid_schedule(
            0.12, [(0.32, weekdays, "schedule.peak")]
        )
        assert schedule is None
        assert "mon: 9 rate periods" in error
        assert "schedule.peak" in error

    def test_full_week_same_pattern_passes_schema(self):
        weekdays = {
            day: [(960, 1260)]
            for day in ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
        }
        schedule, error = derive_grid_schedule(
            0.12, [(0.32, weekdays, "schedule.peak")]
        )
        assert error is None
        TOU_SCHEDULE_SCHEMA(schedule)
        assert len(schedule["seasons"][0]["daySchedules"]) == 1
        assert len(schedule["seasons"][0]["daySchedules"][0]["days"]) == 7
