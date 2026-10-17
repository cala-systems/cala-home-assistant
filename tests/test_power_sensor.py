"""Power telemetry: a kW rate, so it must not declare a cumulative state class."""

from cala.sensor import TELEMETRY_FIELDS, CalaTelemetrySensor

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass


def test_power_sensor_is_a_measurement():
    sensor = CalaTelemetrySensor(
        "dev1", "Cala", "energy_used_kwh", TELEMETRY_FIELDS["energy_used_kwh"]
    )
    assert sensor._attr_device_class is SensorDeviceClass.POWER
    assert sensor._attr_state_class is SensorStateClass.MEASUREMENT
