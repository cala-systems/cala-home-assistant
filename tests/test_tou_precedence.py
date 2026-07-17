import asyncio
from datetime import time

import pytest

from cala import tou_grid, tou_services


class FakeState:
    def __init__(self, state, attributes):
        self.state = state
        self.attributes = attributes


class FakeStates:
    def __init__(self):
        self.by_id = {}

    def get(self, entity_id):
        return self.by_id.get(entity_id)


class FakeHass:
    def __init__(self):
        self.data = {}
        self.states = FakeStates()


class FakeEntry:
    def __init__(self, options):
        self.data = {"device_id": "dev1"}
        self.options = options
        self.entry_id = "entry1"


PEAK_CONFIG = {"monday": [{"from": time(16, 0), "to": time(21, 0)}]}

GRID_OPTIONS = {
    "tou_default_rate": 0.12,
    "tou_tier1_entity": "schedule.peak",
    "tou_tier1_rate": 0.32,
}

FEED_FORECAST = [
    {"hour": h, "value": 0.40 if 16 <= h < 21 else 0.10} for h in range(24)
]


@pytest.fixture
def published(monkeypatch):
    calls = []

    async def _record(hass, device_id, schedule):
        calls.append(schedule)

    monkeypatch.setattr(tou_services, "_publish_schedule", _record)
    monkeypatch.setattr(tou_grid, "_publish_schedule", _record)
    monkeypatch.setattr(
        tou_grid, "read_schedule_config", lambda hass, entity_id: PEAK_CONFIG
    )
    return calls


def make_hass_and_entry(feed_state=None, extra_options=None):
    hass = FakeHass()
    options = dict(GRID_OPTIONS)
    if extra_options:
        options.update(extra_options)
    if feed_state is not None:
        options["tou_rates_entity"] = "sensor.prices"
        hass.states.by_id["sensor.prices"] = feed_state
    return hass, FakeEntry(options)


class TestFeedWinsPrecedence:
    def test_valid_feed_suppresses_grid(self, published):
        hass, entry = make_hass_and_entry(
            FakeState("12", {"forecast": FEED_FORECAST})
        )
        asyncio.run(tou_grid.publish_tou_schedule_from_grid(hass, entry))
        assert published == []

    def test_no_feed_configured_grid_publishes(self, published):
        hass, entry = make_hass_and_entry()
        asyncio.run(tou_grid.publish_tou_schedule_from_grid(hass, entry))
        assert len(published) == 1
        assert published[0]["defaultRate"] == 0.12

    def test_unavailable_feed_grid_publishes(self, published):
        hass, entry = make_hass_and_entry(
            FakeState("unavailable", {"forecast": FEED_FORECAST})
        )
        asyncio.run(tou_grid.publish_tou_schedule_from_grid(hass, entry))
        assert len(published) == 1

    def test_invalid_feed_data_grid_publishes(self, published):
        hass, entry = make_hass_and_entry(
            FakeState("12", {"friendly_name": "junk"})
        )
        asyncio.run(tou_grid.publish_tou_schedule_from_grid(hass, entry))
        assert len(published) == 1

    def test_feed_recovery_reasserts_feed(self, published):
        hass, entry = make_hass_and_entry(
            FakeState("unavailable", {"forecast": FEED_FORECAST})
        )
        asyncio.run(tou_grid.publish_tou_schedule_from_grid(hass, entry))
        assert len(published) == 1
        grid_schedule = published[0]

        hass.states.by_id["sensor.prices"] = FakeState(
            "12", {"forecast": FEED_FORECAST}
        )
        asyncio.run(tou_services.publish_tou_schedule_from_entity(hass, entry))
        assert len(published) == 2
        feed_schedule = published[1]
        assert feed_schedule != grid_schedule
        assert feed_schedule["defaultRate"] == 0.10

        asyncio.run(tou_grid.publish_tou_schedule_from_grid(hass, entry))
        assert len(published) == 2
