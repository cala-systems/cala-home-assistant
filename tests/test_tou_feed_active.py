"""feed-wins for the card path: active_feed_entity drives the card's
read-only banner. A configured feed that yields a valid schedule owns the
device; the card is the fallback otherwise."""

from cala import tou_schedule_sensor
from cala.tou_services import active_feed_entity, configured_feed_entity

FORECAST = [
    {"hour": h, "value": 0.40 if 16 <= h < 21 else 0.10} for h in range(24)
]


class FakeState:
    def __init__(self, state, attributes):
        self.state = state
        self.attributes = attributes


class FakeStates:
    def __init__(self, by_id=None):
        self.by_id = by_id or {}

    def get(self, entity_id):
        return self.by_id.get(entity_id)


class FakeHass:
    def __init__(self, by_id=None):
        self.data = {}
        self.states = FakeStates(by_id)


class FakeEntry:
    entry_id = "entry1"

    def __init__(self, options):
        self.options = options


def _entry(feed="sensor.prices"):
    return FakeEntry({"tou_rates_entity": feed} if feed else {})


class TestActiveFeedEntity:
    def test_no_feed_configured(self):
        assert active_feed_entity(FakeHass(), _entry(feed=None)) is None

    def test_valid_feed_is_active(self):
        hass = FakeHass({"sensor.prices": FakeState("12", {"forecast": FORECAST})})
        assert active_feed_entity(hass, _entry()) == "sensor.prices"

    def test_unavailable_feed_not_active(self):
        hass = FakeHass(
            {"sensor.prices": FakeState("unavailable", {"forecast": FORECAST})}
        )
        assert active_feed_entity(hass, _entry()) is None

    def test_missing_feed_entity_not_active(self):
        assert active_feed_entity(FakeHass(), _entry()) is None

    def test_feed_without_valid_data_not_active(self):
        hass = FakeHass(
            {"sensor.prices": FakeState("12", {"friendly_name": "junk"})}
        )
        assert active_feed_entity(hass, _entry()) is None

    def test_feed_recovery_flips_active(self):
        entry = _entry()
        down = FakeHass(
            {"sensor.prices": FakeState("unavailable", {"forecast": FORECAST})}
        )
        assert active_feed_entity(down, entry) is None
        up = FakeHass({"sensor.prices": FakeState("12", {"forecast": FORECAST})})
        assert active_feed_entity(up, entry) == "sensor.prices"

    def test_configured_feed_entity_normalizes_dict(self):
        entry = FakeEntry({"tou_rates_entity": {"entity_id": "sensor.x"}})
        assert configured_feed_entity(entry) == "sensor.x"


class TestSensorExposesFeedActive:
    def _sensor(self, hass, entry):
        sensor = tou_schedule_sensor.CalaTouScheduleSensor(entry, "dev1", "Heater")
        sensor.hass = hass
        return sensor

    def test_attribute_reports_active_feed(self):
        hass = FakeHass({"sensor.prices": FakeState("12", {"forecast": FORECAST})})
        sensor = self._sensor(hass, _entry())
        assert sensor.extra_state_attributes["feed_active_entity"] == "sensor.prices"

    def test_attribute_none_when_feed_down(self):
        hass = FakeHass(
            {"sensor.prices": FakeState("unavailable", {"forecast": FORECAST})}
        )
        sensor = self._sensor(hass, _entry())
        assert sensor.extra_state_attributes["feed_active_entity"] is None
