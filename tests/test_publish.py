"""Context publisher: what reaches cala/<device_id>/context for given HA states."""

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from cala import publish

DEVICE_ID = "260121B006"
TOPIC = f"cala/{DEVICE_ID}/context"
T0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)


@dataclass
class FakeState:
    state: str
    attributes: dict = field(default_factory=dict)
    last_updated: datetime = T0
    last_reported: datetime = T0


class FakeStates:
    def __init__(self, states: dict):
        self._states = states

    def get(self, entity_id):
        return self._states.get(entity_id)


class FakeHass:
    def __init__(self, states: dict):
        self.states = FakeStates(states)


class FakeEntry:
    def __init__(self, options: dict, data: dict | None = None):
        self.options = options
        self.data = {"device_id": DEVICE_ID} if data is None else data


def power(value, unit="W", **kw):
    return FakeState(str(value), {"unit_of_measurement": unit}, **kw)


@pytest.fixture
def published(monkeypatch):
    calls = []

    async def async_publish(hass, topic, payload, qos=0, retain=False):
        calls.append({"topic": topic, "payload": json.loads(payload), "qos": qos, "retain": retain})

    monkeypatch.setattr(publish.mqtt, "async_publish", async_publish, raising=False)
    return calls


def run(states: dict, options: dict, published, data=None):
    asyncio.run(publish.publish_context(FakeHass(states), FakeEntry(options, data)))
    return published[-1] if published else None


SOLAR = "sensor.pv_power"
SOC = "sensor.battery_soc"


class TestV1Payload:
    def test_solar_and_battery(self, published):
        before = time.time()
        msg = run(
            {SOLAR: power(5230), SOC: FakeState("87", {"unit_of_measurement": "%"})},
            {"solar_production_entity": SOLAR, "battery_soc_entity": SOC},
            published,
        )
        assert msg["topic"] == TOPIC
        assert msg["qos"] == 0 and msg["retain"] is False
        payload = msg["payload"]
        assert payload["v"] == 1
        assert before - 1 <= payload["ts"] <= time.time() + 1
        assert payload["context"] == {
            "solar": {"production_w": 5230.0},
            "battery": {"soc": 0.87},
        }

    def test_kw_is_converted(self, published):
        msg = run({SOLAR: power("5.23", "kW")}, {"solar_production_entity": SOLAR}, published)
        assert msg["payload"]["context"] == {"solar": {"production_w": 5230.0}}

    @pytest.mark.parametrize(
        "state",
        [
            power("unknown"),
            power("unavailable"),
            power(""),
            power("abc"),
            power(500, "VA"),
            power(500, None),
            power(-1),
            power(100_001),
        ],
    )
    def test_bad_solar_is_dropped(self, published, state):
        msg = run(
            {SOLAR: state, SOC: FakeState("50", {"unit_of_measurement": "%"})},
            {"solar_production_entity": SOLAR, "battery_soc_entity": SOC},
            published,
        )
        assert msg["payload"]["context"] == {"battery": {"soc": 0.5}}

    @pytest.mark.parametrize("value", ["-1", "100.1", "unavailable"])
    def test_bad_soc_is_dropped(self, published, value):
        msg = run(
            {SOLAR: power(100), SOC: FakeState(value)},
            {"solar_production_entity": SOLAR, "battery_soc_entity": SOC},
            published,
        )
        assert msg["payload"]["context"] == {"solar": {"production_w": 100.0}}

    def test_battery_omitted_when_unmapped(self, published):
        msg = run({SOLAR: power(0)}, {"solar_production_entity": SOLAR}, published)
        assert msg["payload"]["context"] == {"solar": {"production_w": 0.0}}

    def test_nothing_valid_publishes_nothing(self, published):
        assert run({SOLAR: power("unavailable")}, {"solar_production_entity": SOLAR}, published) is None
        assert run({}, {}, published) is None

    def test_missing_entity_publishes_nothing(self, published):
        assert run({}, {"solar_production_entity": SOLAR}, published) is None

    def test_missing_device_id_publishes_nothing(self, published):
        assert run({SOLAR: power(100)}, {"solar_production_entity": SOLAR}, published, data={}) is None


class TestOptionShapes:
    """EntitySelector options can be stored as a dict; __init__ already handles that."""

    def test_dict_valued_options(self, published):
        msg = run(
            {SOLAR: power(1200), SOC: FakeState("40", {"unit_of_measurement": "%"})},
            {
                "solar_production_entity": {"entity_id": SOLAR},
                "battery_soc_entity": {"id": SOC},
            },
            published,
        )
        assert msg["payload"]["context"] == {
            "solar": {"production_w": 1200.0},
            "battery": {"soc": 0.4},
        }

    def test_whitespace_and_empty_options(self, published):
        msg = run({SOLAR: power(10)}, {"solar_production_entity": f"  {SOLAR} ", "battery_soc_entity": ""}, published)
        assert msg["payload"]["context"] == {"solar": {"production_w": 10.0}}
