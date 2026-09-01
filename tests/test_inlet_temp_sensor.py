"""Inlet temperature telemetry: entity shape and payload handling."""

import pytest

from cala.sensor import TELEMETRY_FIELDS, CalaTelemetrySensor

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfTemperature


@pytest.fixture
def inlet_sensor():
    return CalaTelemetrySensor(
        "dev1", "Cala", "inlet_c", TELEMETRY_FIELDS["inlet_c"]
    )


def test_inlet_temp_is_a_declared_telemetry_field():
    assert "inlet_c" in TELEMETRY_FIELDS


def test_inlet_sensor_declares_temperature_metadata(inlet_sensor):
    assert inlet_sensor._attr_unique_id == "cala_dev1_inlet_c"
    assert inlet_sensor._attr_name == "Cala Inlet Temperature"
    assert inlet_sensor._attr_native_unit_of_measurement is UnitOfTemperature.CELSIUS
    assert inlet_sensor._attr_device_class is SensorDeviceClass.TEMPERATURE
    assert inlet_sensor._attr_state_class is SensorStateClass.MEASUREMENT
    # Celsius on the wire, Celsius natively — HA converts for imperial users.
    assert inlet_sensor._scale == 1


def test_inlet_sensor_reads_value_from_payload(inlet_sensor):
    inlet_sensor.update_from_payload({"inlet_c": 13.75, "ambient_c": 21.0})
    assert inlet_sensor._attr_native_value == pytest.approx(13.75)


# The device omits inlet_c until InletTempHelper has banked a daily sample.
# A missing key must leave the last known value alone rather than reset it.
def test_missing_inlet_key_leaves_value_untouched(inlet_sensor):
    inlet_sensor.update_from_payload({"inlet_c": 13.75})
    inlet_sensor.update_from_payload({"ambient_c": 21.0})
    assert inlet_sensor._attr_native_value == pytest.approx(13.75)


def test_non_numeric_inlet_value_is_ignored(inlet_sensor):
    inlet_sensor.update_from_payload({"inlet_c": 13.75})
    inlet_sensor.update_from_payload({"inlet_c": "not-a-number"})
    assert inlet_sensor._attr_native_value == pytest.approx(13.75)
