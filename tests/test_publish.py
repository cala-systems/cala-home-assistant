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


GRID = "sensor.grid_power"
IMPORT = "sensor.grid_import"
EXPORT = "sensor.grid_export"


def grid(states, options, published):
    msg = run(states, options, published)
    return None if msg is None else msg["payload"]["context"].get("grid")


class TestGridSigned:
    def test_export_positive_is_import(self, published):
        assert grid({GRID: power(-3100)}, {"grid_power_entity": GRID}, published) == {
            "import_w": 0.0,
            "export_w": 3100.0,
            "power_w": -3100.0,
            "exporting": True,
            "importing": False,
        }

    def test_import_positive_is_import(self, published):
        assert grid(
            {GRID: power("1.5", "kW")},
            {"grid_power_entity": GRID, "grid_power_sign": "positive_is_import"},
            published,
        ) == {
            "import_w": 1500.0,
            "export_w": 0.0,
            "power_w": 1500.0,
            "exporting": False,
            "importing": True,
        }

    def test_positive_is_export_is_flipped(self, published):
        g = grid(
            {GRID: power(3100)},
            {"grid_power_entity": GRID, "grid_power_sign": "positive_is_export"},
            published,
        )
        assert g["power_w"] == -3100.0
        assert g["export_w"] == 3100.0 and g["import_w"] == 0.0
        assert g["exporting"] is True and g["importing"] is False

    def test_zero_is_neither(self, published):
        g = grid(
            {GRID: power(0)},
            {"grid_power_entity": GRID, "grid_power_sign": "positive_is_export"},
            published,
        )
        assert g == {"import_w": 0.0, "export_w": 0.0, "power_w": 0.0, "exporting": False, "importing": False}
        assert "-0.0" not in json.dumps(published[-1]["payload"])

    def test_no_deadband(self, published):
        g = grid({GRID: power("-0.5")}, {"grid_power_entity": GRID}, published)
        assert g["exporting"] is True and g["export_w"] == 0.5

    def test_bound_is_symmetric(self, published):
        assert grid({GRID: power(-100_000)}, {"grid_power_entity": GRID}, published)["export_w"] == 100_000.0
        assert grid({GRID: power(-100_001), SOLAR: power(1)}, {"grid_power_entity": GRID, "solar_production_entity": SOLAR}, published) is None
        assert grid({GRID: power(100_001), SOLAR: power(1)}, {"grid_power_entity": GRID, "solar_production_entity": SOLAR}, published) is None

    def test_unknown_sign_falls_back_to_import(self, published):
        g = grid({GRID: power(200)}, {"grid_power_entity": GRID, "grid_power_sign": "bogus"}, published)
        assert g["power_w"] == 200.0 and g["importing"] is True

    @pytest.mark.parametrize("state", [power("unavailable"), power("unknown"), power(5, "VA"), None])
    def test_unavailable_omits_grid(self, published, state):
        states = {SOLAR: power(800)}
        if state is not None:
            states[GRID] = state
        msg = run(states, {"grid_power_entity": GRID, "solar_production_entity": SOLAR}, published)
        assert msg["payload"]["context"] == {"solar": {"production_w": 800.0}}

    def test_unavailable_grid_alone_publishes_nothing(self, published):
        assert run({GRID: power("unavailable")}, {"grid_power_entity": GRID}, published) is None

    def test_dict_option(self, published):
        assert grid({GRID: power(-10)}, {"grid_power_entity": {"entity_id": GRID}}, published)["power_w"] == -10.0


class TestGridPair:
    def test_exporting(self, published):
        assert grid(
            {IMPORT: power(0), EXPORT: power("3.1", "kW")},
            {"grid_import_entity": IMPORT, "grid_export_entity": EXPORT},
            published,
        ) == {
            "import_w": 0.0,
            "export_w": 3100.0,
            "power_w": -3100.0,
            "exporting": True,
            "importing": False,
        }

    def test_importing(self, published):
        g = grid(
            {IMPORT: power(450), EXPORT: power(0)},
            {"grid_import_entity": IMPORT, "grid_export_entity": EXPORT},
            published,
        )
        assert g["power_w"] == 450.0 and g["importing"] is True and g["exporting"] is False

    @pytest.mark.parametrize("bad", [IMPORT, EXPORT])
    def test_either_unavailable_omits_grid(self, published, bad):
        states = {IMPORT: power(0), EXPORT: power(100), SOLAR: power(1)}
        states[bad] = power("unavailable")
        msg = run(
            states,
            {"grid_import_entity": IMPORT, "grid_export_entity": EXPORT, "solar_production_entity": SOLAR},
            published,
        )
        assert "grid" not in msg["payload"]["context"]

    def test_negative_magnitude_rejected(self, published):
        msg = run(
            {IMPORT: power(0), EXPORT: power(-100), SOLAR: power(1)},
            {"grid_import_entity": IMPORT, "grid_export_entity": EXPORT, "solar_production_entity": SOLAR},
            published,
        )
        assert "grid" not in msg["payload"]["context"]

    def test_only_one_of_pair_mapped_omits_grid(self, published):
        msg = run({IMPORT: power(10), SOLAR: power(1)}, {"grid_import_entity": IMPORT, "solar_production_entity": SOLAR}, published)
        assert "grid" not in msg["payload"]["context"]

    def test_signed_entity_wins_over_pair(self, published):
        g = grid(
            {GRID: power(-50), IMPORT: power(999), EXPORT: power(0)},
            {"grid_power_entity": GRID, "grid_import_entity": IMPORT, "grid_export_entity": EXPORT},
            published,
        )
        assert g["power_w"] == -50.0
