"""State writes must skip entities HA never added, e.g. user-disabled ones."""

import pytest

from cala.helpers import write_state_if_added
from cala.sensor import TELEMETRY_FIELDS, CalaTelemetrySensor


@pytest.fixture
def sensor(monkeypatch):
    s = CalaTelemetrySensor("dev1", "Cala", "inlet_c", TELEMETRY_FIELDS["inlet_c"])
    s.writes = 0

    def _write():
        # Mirrors HA's _async_verify_state_writable.
        if s.hass is None:
            raise RuntimeError(f"Attribute hass is None for {s}")
        s.writes += 1

    monkeypatch.setattr(s, "async_write_ha_state", _write)
    return s


def test_skips_entity_not_added_to_hass(sensor):
    write_state_if_added(sensor)
    assert sensor.writes == 0


def test_writes_entity_added_to_hass(sensor):
    sensor.hass = object()
    write_state_if_added(sensor)
    assert sensor.writes == 1
