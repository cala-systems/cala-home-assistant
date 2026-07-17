import asyncio

import pytest

from cala import tou_schedule_sensor, tou_services, tou_store
from cala.tou_store import (
    get_published_schedule,
    record_published_schedule,
    seed_published_schedule,
)

SCHEDULE = {"version": 1, "defaultRate": 0.12, "seasons": []}
OTHER = {"version": 1, "defaultRate": 0.3, "seasons": []}


class FakeHass:
    def __init__(self):
        self.data = {}


class TestStore:
    def test_get_empty(self):
        assert get_published_schedule(FakeHass(), "dev1") is None

    def test_record_and_get(self):
        hass = FakeHass()
        record_published_schedule(hass, "dev1", SCHEDULE)
        record = get_published_schedule(hass, "dev1")
        assert record["schedule"] == SCHEDULE
        assert record["published_at"]

    def test_record_fires_signal(self, monkeypatch):
        sent = []
        monkeypatch.setattr(
            tou_store, "async_dispatcher_send", lambda hass, signal: sent.append(signal)
        )
        record_published_schedule(FakeHass(), "dev1", SCHEDULE)
        assert sent == ["cala_tou_schedule_recorded_dev1"]

    def test_per_device_isolation(self):
        hass = FakeHass()
        record_published_schedule(hass, "dev1", SCHEDULE)
        record_published_schedule(hass, "dev2", OTHER)
        assert get_published_schedule(hass, "dev1")["schedule"] == SCHEDULE
        assert get_published_schedule(hass, "dev2")["schedule"] == OTHER

    def test_seed_only_when_empty(self):
        hass = FakeHass()
        seed_published_schedule(hass, "dev1", SCHEDULE, "2026-07-17T00:00:00+00:00")
        assert get_published_schedule(hass, "dev1")["schedule"] == SCHEDULE
        seed_published_schedule(hass, "dev1", OTHER, None)
        assert get_published_schedule(hass, "dev1")["schedule"] == SCHEDULE

    def test_seed_does_not_overwrite_recorded(self):
        hass = FakeHass()
        record_published_schedule(hass, "dev1", SCHEDULE)
        seed_published_schedule(hass, "dev1", OTHER, None)
        assert get_published_schedule(hass, "dev1")["schedule"] == SCHEDULE


class TestPublishRecords:
    def _hass(self):
        return FakeHass()

    def test_successful_publish_records(self, monkeypatch):
        hass = self._hass()

        async def ok(hass_, topic, payload, timeout):
            return {"status": "accepted", "reason": None}

        monkeypatch.setattr(tou_services, "publish_command_and_wait_response", ok)
        monkeypatch.setattr(
            tou_services, "get_command_topic", lambda hass_, device_id: "cala/dev1/command"
        )
        asyncio.run(tou_services._publish_schedule(hass, "dev1", SCHEDULE))
        assert get_published_schedule(hass, "dev1")["schedule"] == SCHEDULE

    def test_failed_publish_does_not_record(self, monkeypatch):
        from homeassistant.exceptions import HomeAssistantError

        hass = self._hass()

        async def rejected(hass_, topic, payload, timeout):
            raise HomeAssistantError("Device rejected command: bad_schedule")

        monkeypatch.setattr(
            tou_services, "publish_command_and_wait_response", rejected
        )
        monkeypatch.setattr(
            tou_services, "get_command_topic", lambda hass_, device_id: "cala/dev1/command"
        )
        with pytest.raises(HomeAssistantError):
            asyncio.run(tou_services._publish_schedule(hass, "dev1", SCHEDULE))
        assert get_published_schedule(hass, "dev1") is None


class FakeRestoredState:
    def __init__(self, state, attributes):
        self.state = state
        self.attributes = attributes


class TestScheduleSensor:
    def _sensor(self, hass):
        sensor = tou_schedule_sensor.CalaTouScheduleSensor("dev1", "Heater")
        sensor.hass = hass
        return sensor

    def test_empty_store(self):
        sensor = self._sensor(FakeHass())
        assert sensor.native_value is None
        assert sensor.extra_state_attributes == {
            "cala_tou_device": "dev1",
            "schedule": None,
        }

    def test_reflects_store(self):
        hass = FakeHass()
        record_published_schedule(hass, "dev1", SCHEDULE)
        sensor = self._sensor(hass)
        assert sensor.native_value == get_published_schedule(hass, "dev1")["published_at"]
        assert sensor.extra_state_attributes["schedule"] == SCHEDULE

    def test_restores_seed_store(self, monkeypatch):
        hass = FakeHass()
        sensor = self._sensor(hass)

        async def last_state():
            return FakeRestoredState(
                "2026-07-16T02:00:00+00:00", {"schedule": SCHEDULE}
            )

        monkeypatch.setattr(sensor, "async_get_last_state", last_state)
        asyncio.run(sensor.async_added_to_hass())
        record = get_published_schedule(hass, "dev1")
        assert record["schedule"] == SCHEDULE
        assert record["published_at"] == "2026-07-16T02:00:00+00:00"
        assert sensor.native_value == "2026-07-16T02:00:00+00:00"

    def test_restore_does_not_clobber_newer_record(self, monkeypatch):
        hass = FakeHass()
        record_published_schedule(hass, "dev1", OTHER)
        sensor = self._sensor(hass)

        async def last_state():
            return FakeRestoredState("2026-07-16T02:00:00+00:00", {"schedule": SCHEDULE})

        monkeypatch.setattr(sensor, "async_get_last_state", last_state)
        asyncio.run(sensor.async_added_to_hass())
        assert get_published_schedule(hass, "dev1")["schedule"] == OTHER

    def test_unique_id_and_category(self):
        sensor = self._sensor(FakeHass())
        assert sensor._attr_unique_id == "cala_dev1_tou_schedule"
        assert sensor._attr_entity_category == "diagnostic"
