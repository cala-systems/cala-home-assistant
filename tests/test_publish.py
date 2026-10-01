"""Context publisher: what reaches cala/<device_id>/context for given HA states."""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

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


class TestPayload:
    def test_solar_and_battery(self, published):
        msg = run(
            {SOLAR: power(5230), SOC: FakeState("87", {"unit_of_measurement": "%"})},
            {"solar_production_entity": SOLAR, "battery_soc_entity": SOC},
            published,
        )
        assert msg["topic"] == TOPIC
        assert msg["qos"] == 0 and msg["retain"] is False
        payload = msg["payload"]
        assert payload["v"] == 2
        assert payload["ts"] == T0.timestamp()
        assert payload["context"] == {
            "solar": {"production_w": 5230.0, "producing": True},
            "battery": {"soc_percent": 87.0},
        }

    def test_kw_is_converted(self, published):
        msg = run({SOLAR: power("5.23", "kW")}, {"solar_production_entity": SOLAR}, published)
        assert msg["payload"]["context"] == {"solar": {"production_w": 5230.0, "producing": True}}

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
        assert msg["payload"]["context"] == {"battery": {"soc_percent": 50.0}}

    @pytest.mark.parametrize("value", ["-1", "100.1", "unavailable"])
    def test_bad_soc_is_dropped(self, published, value):
        msg = run(
            {SOLAR: power(100), SOC: FakeState(value)},
            {"solar_production_entity": SOLAR, "battery_soc_entity": SOC},
            published,
        )
        assert msg["payload"]["context"] == {"solar": {"production_w": 100.0, "producing": True}}

    def test_battery_omitted_when_unmapped(self, published):
        msg = run({SOLAR: power(0)}, {"solar_production_entity": SOLAR}, published)
        assert msg["payload"]["context"] == {"solar": {"production_w": 0.0, "producing": False}}

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
            "solar": {"production_w": 1200.0, "producing": True},
            "battery": {"soc_percent": 40.0},
        }

    def test_whitespace_and_empty_options(self, published):
        msg = run({SOLAR: power(10)}, {"solar_production_entity": f"  {SOLAR} ", "battery_soc_entity": ""}, published)
        assert msg["payload"]["context"] == {"solar": {"production_w": 10.0, "producing": True}}


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
        assert msg["payload"]["context"] == {"solar": {"production_w": 800.0, "producing": True}}

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


STATUS = "binary_sensor.grid_status"


class TestGridDisconnected:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("on", False),
            ("off", True),
            ("on_grid", False),
            ("off_grid", True),
            ("Off-Grid", True),
            ("Connected", False),
            ("islanded", True),
            ("SystemIslandedActive", True),
        ],
    )
    def test_states(self, published, value, expected):
        g = grid({STATUS: FakeState(value)}, {"grid_status_entity": STATUS}, published)
        assert g == {"grid_disconnected": expected}

    def test_invert(self, published):
        opts = {"grid_status_entity": STATUS, "grid_status_invert": True}
        assert grid({STATUS: FakeState("on")}, opts, published) == {"grid_disconnected": True}
        assert grid({STATUS: FakeState("off")}, opts, published) == {"grid_disconnected": False}

    @pytest.mark.parametrize("value", ["unavailable", "unknown", "", "synchronizing"])
    def test_unknown_omits(self, published, value):
        msg = run(
            {STATUS: FakeState(value), SOLAR: power(1)},
            {"grid_status_entity": STATUS, "solar_production_entity": SOLAR},
            published,
        )
        assert "grid" not in msg["payload"]["context"]

    def test_unmapped_omits(self, published):
        g = grid({GRID: power(-5), STATUS: FakeState("off")}, {"grid_power_entity": GRID}, published)
        assert "grid_disconnected" not in g

    def test_alongside_power(self, published):
        g = grid(
            {GRID: power(-3100), STATUS: FakeState("on")},
            {"grid_power_entity": GRID, "grid_status_entity": STATUS},
            published,
        )
        assert g["grid_disconnected"] is False and g["exporting"] is True

    def test_power_unavailable_keeps_status(self, published):
        g = grid(
            {GRID: power("unavailable"), STATUS: FakeState("off")},
            {"grid_power_entity": GRID, "grid_status_entity": STATUS},
            published,
        )
        assert g == {"grid_disconnected": True}


BATT = "sensor.battery_power"


def battery(states, options, published):
    msg = run(states, options, published)
    return None if msg is None else msg["payload"]["context"].get("battery")


def pct(value, unit="%"):
    return FakeState(str(value), {"unit_of_measurement": unit} if unit else {})


class TestBattery:
    def test_full_block(self, published):
        assert battery(
            {SOC: pct(87), BATT: power(1200)},
            {"battery_soc_entity": SOC, "battery_power_entity": BATT},
            published,
        ) == {"soc_percent": 87.0, "power_w": 1200.0, "charging": True, "discharging": False}

    def test_old_soc_field_is_gone(self, published):
        b = battery({SOC: pct(87)}, {"battery_soc_entity": SOC}, published)
        assert "soc" not in b

    def test_discharging(self, published):
        b = battery({BATT: power("-2.5", "kW")}, {"battery_power_entity": BATT}, published)
        assert b == {"power_w": -2500.0, "charging": False, "discharging": True}

    def test_positive_is_discharging_is_flipped(self, published):
        b = battery(
            {BATT: power(800)},
            {"battery_power_entity": BATT, "battery_power_sign": "positive_is_discharging"},
            published,
        )
        assert b == {"power_w": -800.0, "charging": False, "discharging": True}

    def test_idle(self, published):
        b = battery(
            {BATT: power(0)},
            {"battery_power_entity": BATT, "battery_power_sign": "positive_is_discharging"},
            published,
        )
        assert b == {"power_w": 0.0, "charging": False, "discharging": False}
        assert "-0.0" not in json.dumps(published[-1]["payload"])

    def test_power_out_of_range_dropped(self, published):
        b = battery({SOC: pct(50), BATT: power(-100_001)}, {"battery_soc_entity": SOC, "battery_power_entity": BATT}, published)
        assert b == {"soc_percent": 50.0}

    def test_power_unavailable_keeps_soc(self, published):
        b = battery({SOC: pct(50), BATT: power("unavailable")}, {"battery_soc_entity": SOC, "battery_power_entity": BATT}, published)
        assert b == {"soc_percent": 50.0}

    def test_unmapped_omits_battery(self, published):
        msg = run({SOLAR: power(1), SOC: pct(50), BATT: power(5)}, {"solar_production_entity": SOLAR}, published)
        assert "battery" not in msg["payload"]["context"]

    def test_all_unavailable_omits_battery(self, published):
        msg = run(
            {SOLAR: power(1), SOC: pct("unavailable"), BATT: power("unknown")},
            {"solar_production_entity": SOLAR, "battery_soc_entity": SOC, "battery_power_entity": BATT},
            published,
        )
        assert "battery" not in msg["payload"]["context"]


class TestSoc:
    def test_no_unit_passes_through(self, published):
        assert battery({SOC: pct(64, None)}, {"battery_soc_entity": SOC}, published) == {"soc_percent": 64.0}

    def test_other_unit_dropped(self, published):
        msg = run({SOC: pct(64, "kWh"), SOLAR: power(1)}, {"battery_soc_entity": SOC, "solar_production_entity": SOLAR}, published)
        assert "battery" not in msg["payload"]["context"]

    def test_fraction_without_unit_warns_but_is_not_rescaled(self, published, caplog):
        publish._warned_fraction_soc.clear()
        with caplog.at_level("WARNING"):
            assert battery({SOC: pct("0.87", None)}, {"battery_soc_entity": SOC}, published) == {"soc_percent": 0.87}
            battery({SOC: pct("0.87", None)}, {"battery_soc_entity": SOC}, published)
        assert sum("0-1 fraction" in r.getMessage() for r in caplog.records) == 1

    @pytest.mark.parametrize("state", [pct("0.5"), pct(0, None), pct(5, None)])
    def test_no_fraction_warning(self, published, caplog, state):
        publish._warned_fraction_soc.clear()
        with caplog.at_level("WARNING"):
            battery({SOC: state}, {"battery_soc_entity": SOC}, published)
        assert not any("0-1 fraction" in r.getMessage() for r in caplog.records)


class TestSolarProducing:
    @pytest.mark.parametrize("value, producing", [(0, False), ("0.01", True), (5230, True)])
    def test_producing(self, published, value, producing):
        msg = run({SOLAR: power(value)}, {"solar_production_entity": SOLAR}, published)
        assert msg["payload"]["context"]["solar"]["producing"] is producing


class TestSourceTimestamp:
    def test_latest_last_reported(self, published):
        msg = run(
            {
                SOLAR: power(100, last_updated=T0, last_reported=T0 + timedelta(seconds=40)),
                GRID: power(-5, last_updated=T0 + timedelta(seconds=10), last_reported=T0 + timedelta(seconds=20)),
            },
            {"solar_production_entity": SOLAR, "grid_power_entity": GRID},
            published,
        )
        assert msg["payload"]["ts"] == (T0 + timedelta(seconds=40)).timestamp()

    def test_falls_back_to_last_updated(self, published):
        msg = run(
            {SOLAR: power(100, last_updated=T0 + timedelta(seconds=7), last_reported=None)},
            {"solar_production_entity": SOLAR},
            published,
        )
        assert msg["payload"]["ts"] == (T0 + timedelta(seconds=7)).timestamp()

    def test_unavailable_entity_does_not_advance_ts(self, published):
        msg = run(
            {
                SOLAR: power(100),
                GRID: power("unavailable", last_reported=T0 + timedelta(hours=1)),
            },
            {"solar_production_entity": SOLAR, "grid_power_entity": GRID},
            published,
        )
        assert msg["payload"]["ts"] == T0.timestamp()

    def test_steady_sensor_still_advances(self, published):
        opts = {"solar_production_entity": SOLAR}
        first = run({SOLAR: power(92, last_reported=T0)}, opts, published)["payload"]
        second = run({SOLAR: power(92, last_reported=T0 + timedelta(seconds=30))}, opts, published)["payload"]
        assert first["context"] == second["context"]
        assert second["ts"] - first["ts"] == 30


class TaskHass(FakeHass):
    def __init__(self, states):
        super().__init__(states)
        self.tasks = []

    def async_create_task(self, coro):
        self.tasks.append(coro)

    def drain(self):
        while self.tasks:
            asyncio.run(self.tasks.pop(0))


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def timers(monkeypatch):
    t = {"state": [], "interval": [], "later": [], "cancelled": []}

    def track_state(hass, entity_ids, action):
        t["state"].append((list(entity_ids), action))
        return lambda: t["cancelled"].append("state")

    def track_interval(hass, action, interval):
        t["interval"].append((interval, action))
        return lambda: t["cancelled"].append("interval")

    def call_later(hass, delay, action):
        t["later"].append((delay, action))
        return lambda: t["cancelled"].append("later")

    async def mqtt_ready(hass):
        return t.get("mqtt_ready", True)

    monkeypatch.setattr(publish, "async_track_state_change_event", track_state)
    monkeypatch.setattr(publish, "async_track_time_interval", track_interval)
    monkeypatch.setattr(publish, "async_call_later", call_later)
    monkeypatch.setattr(publish, "_mqtt_available", mqtt_ready)
    return t


class TestContextPublisher:
    OPTS = {"solar_production_entity": SOLAR, "grid_power_entity": GRID}

    def make(self, interval_s=30):
        hass = TaskHass({SOLAR: power(100), GRID: power(-50)})
        clock = Clock()
        pub = publish.ContextPublisher(hass, FakeEntry(self.OPTS), interval_s, clock=clock)
        return hass, clock, pub

    def test_context_entity_ids(self):
        assert publish.context_entity_ids(
            {
                "solar_production_entity": {"entity_id": SOLAR},
                "grid_power_entity": GRID,
                "grid_import_entity": "",
                "battery_soc_entity": SOLAR,
                "grid_status_entity": STATUS,
            }
        ) == [SOLAR, GRID, STATUS]

    def test_start_publishes_once_and_schedules(self, published, timers):
        hass, _, pub = self.make()
        pub.async_start([SOLAR, GRID])
        assert timers["state"][0][0] == [SOLAR, GRID]
        assert timers["interval"][0][0] == timedelta(seconds=30)
        hass.drain()
        assert len(published) == 1
        assert published[0]["payload"]["v"] == 2

    def test_start_waits_for_mqtt(self, published, timers):
        timers["mqtt_ready"] = False
        hass, _, pub = self.make()
        pub.async_start([SOLAR])
        hass.drain()
        assert published == []

    def test_interval_publishes(self, published, timers):
        hass, _, pub = self.make(interval_s=45)
        pub.async_start([SOLAR])
        hass.drain()
        interval, action = timers["interval"][0]
        assert interval == timedelta(seconds=45)
        action(None)
        action(None)
        hass.drain()
        assert len(published) == 3

    def test_on_change_is_rate_limited(self, published, timers):
        hass, clock, pub = self.make()
        pub.async_start([SOLAR])
        hass.drain()
        on_change = timers["state"][0][1]

        clock.now += 2
        on_change(None)
        on_change(None)
        hass.drain()
        assert len(published) == 1
        assert len(timers["later"]) == 1
        delay, due = timers["later"][0]
        assert delay == pytest.approx(3)

        clock.now += 3
        due(None)
        hass.drain()
        assert len(published) == 2

        clock.now += 5
        on_change(None)
        hass.drain()
        assert len(published) == 3
        assert len(timers["later"]) == 1

    def test_first_change_publishes_immediately(self, published, timers):
        hass, _, pub = self.make()
        pub._on_state_change(None)
        hass.drain()
        assert len(published) == 1

    def test_stop_cancels_everything(self, published, timers):
        hass, clock, pub = self.make()
        pub.async_start([SOLAR])
        hass.drain()
        clock.now += 1
        timers["state"][0][1](None)
        pub.async_stop()
        assert sorted(timers["cancelled"]) == ["interval", "later", "state"]
        pub.async_stop()
        assert len(timers["cancelled"]) == 3
