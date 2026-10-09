"""Context sources read from HA's Energy dashboard settings instead of asked for."""

import asyncio
import json
import sys
import types
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from cala import energy_sources, publish
from cala.const import DOMAIN

DEVICE_ID = "260121B006"
T0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)

# Phil's home box as of 2026-10-02: solar only, plus the heater as a device.
HOME_PREFS = {
    "energy_sources": [
        {
            "type": "solar",
            "stat_energy_from": "sensor.envoy_202325045900_energy_production_today",
            "config_entry_solar_forecast": ["01JN1N6VY16TEMMF9REBFDRVKD"],
            "stat_rate": "sensor.envoy_202325045900_current_power_production",
        }
    ],
    "device_consumption": [
        {
            "stat_consumption": "sensor.cala_water_heater_energy_total",
            "name": "Cala HPWH",
            "stat_rate": "sensor.cala_water_heater_energy_used",
        }
    ],
}

FULL_PREFS = {
    "energy_sources": [
        {"type": "solar", "stat_energy_from": "sensor.pv_kwh", "stat_rate": "sensor.pv_w"},
        {
            "type": "grid",
            "stat_energy_from": "sensor.grid_in_kwh",
            "stat_energy_to": "sensor.grid_out_kwh",
            "stat_rate": "sensor.grid_w",
            "cost_adjustment_day": 0,
        },
        {
            "type": "battery",
            "stat_energy_from": "sensor.batt_out_kwh",
            "stat_energy_to": "sensor.batt_in_kwh",
            "stat_rate": "sensor.batt_w",
            "stat_soc": "sensor.batt_soc",
        },
    ],
    "device_consumption": [],
}


@dataclass
class FakeState:
    state: str
    attributes: dict = field(default_factory=dict)
    last_updated: datetime = T0
    last_reported: datetime = T0


class FakeStates:
    def __init__(self, states):
        self._states = states

    def get(self, entity_id):
        return self._states.get(entity_id)


class FakeEntry:
    def __init__(self, options, entry_id="e1", state="loaded"):
        self.options = options
        self.data = {"device_id": DEVICE_ID}
        self.entry_id = entry_id
        self.title = entry_id
        self.state = state


class FakeConfigEntries:
    def __init__(self, entries):
        self._entries = entries
        self.reloaded = []

    def async_entries(self, domain):
        return list(self._entries)

    def async_schedule_reload(self, entry_id):
        self.reloaded.append(entry_id)


class FakeHass:
    def __init__(self, states=None, entries=()):
        self.states = FakeStates(states or {})
        self.data = {}
        self.config_entries = FakeConfigEntries(entries)


def w(value, unit="W"):
    return FakeState(str(value), {"unit_of_measurement": unit})


# ---- Mapping ----

def test_home_prefs_map_solar_to_live_production_sensor():
    assert energy_sources.mapping_from_energy_prefs(HOME_PREFS) == {
        "solar_production_entity": "sensor.envoy_202325045900_current_power_production",
    }


def test_full_prefs_use_energy_sign_conventions():
    assert energy_sources.mapping_from_energy_prefs(FULL_PREFS) == {
        "solar_production_entity": "sensor.pv_w",
        "grid_power_entity": "sensor.grid_w",
        "grid_power_sign": "positive_is_import",
        "battery_power_entity": "sensor.batt_w",
        "battery_power_sign": "positive_is_discharging",
        "battery_soc_entity": "sensor.batt_soc",
    }


@pytest.mark.parametrize("prefs", [None, {}, {"energy_sources": []}])
def test_no_energy_settings_maps_nothing(prefs):
    assert energy_sources.mapping_from_energy_prefs(prefs) == {}


def test_sources_without_power_sensors_are_skipped():
    prefs = {"energy_sources": [
        {"type": "solar", "stat_energy_from": "sensor.pv_kwh"},
        {"type": "grid", "stat_energy_from": "sensor.grid_kwh", "stat_energy_to": None},
    ]}
    assert energy_sources.mapping_from_energy_prefs(prefs) == {}


def test_external_statistics_are_skipped():
    prefs = {"energy_sources": [
        {"type": "solar", "stat_energy_from": "x:pv", "stat_rate": "enphase:pv_power"},
    ]}
    assert energy_sources.mapping_from_energy_prefs(prefs) == {}


def test_first_of_several_solar_sources_is_used():
    prefs = {"energy_sources": [
        {"type": "solar", "stat_energy_from": "sensor.a_kwh", "stat_rate": "sensor.a_w"},
        {"type": "solar", "stat_energy_from": "sensor.b_kwh", "stat_rate": "sensor.b_w"},
    ]}
    assert energy_sources.mapping_from_energy_prefs(prefs)["solar_production_entity"] == "sensor.a_w"


# ---- Automatic vs hand-mapped ----

def test_automatic_mode_ignores_stale_hand_mapping_but_keeps_grid_status():
    opts = {
        "solar_production_entity": "sensor.power_production_now",
        "grid_power_entity": "sensor.old_grid",
        "grid_status_entity": "binary_sensor.x",
        "grid_status_invert": True,
        "context_publish_interval_s": 30.0,
        "tou_rates_entity": "sensor.nordpool",
    }
    mapping = energy_sources.mapping_from_energy_prefs(HOME_PREFS)
    assert energy_sources.effective_context_options(opts, mapping) == {
        "context_publish_interval_s": 30.0,
        "tou_rates_entity": "sensor.nordpool",
        "grid_status_entity": "binary_sensor.x",
        "grid_status_invert": True,
        "solar_production_entity": "sensor.envoy_202325045900_current_power_production",
    }


def test_grid_status_is_not_an_energy_source_key():
    assert "grid_status_entity" not in energy_sources.CONTEXT_SOURCE_KEYS
    assert "grid_status_invert" not in energy_sources.CONTEXT_SOURCE_KEYS


def test_manual_mode_keeps_hand_mapping_and_ignores_energy():
    opts = {
        "manual_context_entities": True,
        "solar_production_entity": "sensor.cala_test_solar_production",
        "grid_power_entity": "sensor.cala_test_grid_power",
    }
    mapping = energy_sources.mapping_from_energy_prefs(FULL_PREFS)
    assert energy_sources.effective_context_options(opts, mapping) == opts


# ---- End to end: Energy settings -> payload ----

def test_energy_settings_publish_with_normalised_signs(monkeypatch):
    calls = []

    async def async_publish(hass, topic, payload, qos=0, retain=False):
        calls.append(json.loads(payload))

    monkeypatch.setattr(publish.mqtt, "async_publish", async_publish, raising=False)

    # Energy convention: grid -2500 = exporting, battery -800 = charging.
    hass = FakeHass({
        "sensor.pv_w": w(6000),
        "sensor.grid_w": w(-2.5, "kW"),
        "sensor.batt_w": w(-800),
        "sensor.batt_soc": FakeState("95", {"unit_of_measurement": "%"}),
    })
    entry = FakeEntry({})
    opts = energy_sources.effective_context_options(
        entry.options, energy_sources.mapping_from_energy_prefs(FULL_PREFS)
    )
    asyncio.run(publish.publish_context(hass, entry, opts))

    assert calls[0]["context"] == {
        "solar": {"production_w": 6000.0, "producing": True},
        "grid": {"import_w": 0.0, "export_w": 2500.0, "power_w": -2500.0,
                 "exporting": True, "importing": False},
        "battery": {"soc_percent": 95.0, "power_w": 800.0, "charging": True,
                    "discharging": False},
    }


def test_energy_settings_plus_grid_status_option_publish_grid_disconnected(monkeypatch):
    calls = []

    async def async_publish(hass, topic, payload, qos=0, retain=False):
        calls.append(json.loads(payload))

    monkeypatch.setattr(publish.mqtt, "async_publish", async_publish, raising=False)

    hass = FakeHass({
        "sensor.pv_w": w(6000),
        "sensor.grid_w": w(-2.5, "kW"),
        "sensor.batt_w": w(-800),
        "sensor.batt_soc": FakeState("95", {"unit_of_measurement": "%"}),
        "binary_sensor.powerwall_grid_status": FakeState("off"),
    })
    # Grid status is a plain option; solar/grid/battery still come from Energy.
    entry = FakeEntry({"grid_status_entity": "binary_sensor.powerwall_grid_status"})
    opts = energy_sources.effective_context_options(
        entry.options, energy_sources.mapping_from_energy_prefs(FULL_PREFS)
    )
    asyncio.run(publish.publish_context(hass, entry, opts))

    assert calls[0]["context"]["grid"] == {
        "import_w": 0.0, "export_w": 2500.0, "power_w": -2500.0,
        "exporting": True, "importing": False, "grid_disconnected": True,
    }
    assert calls[0]["context"]["solar"]["production_w"] == 6000.0


# ---- Reacting to Energy settings changes ----

class FakeManager:
    def __init__(self, data):
        self.data = data
        self.listeners = []

    def async_listen_updates(self, listener):
        self.listeners.append(listener)


@pytest.fixture
def energy_manager(monkeypatch):
    manager = FakeManager(HOME_PREFS)

    async def async_get_manager(hass):
        return manager

    mod = types.ModuleType("homeassistant.components.energy.data")
    mod.async_get_manager = async_get_manager
    monkeypatch.setitem(sys.modules, "homeassistant.components.energy", types.ModuleType("e"))
    monkeypatch.setitem(sys.modules, "homeassistant.components.energy.data", mod)
    return manager


def test_settings_change_reloads_only_affected_automatic_entries(energy_manager):
    auto = FakeEntry({}, "auto")
    manual = FakeEntry({"manual_context_entities": True}, "manual")
    unloaded = FakeEntry({}, "unloaded", state="not_loaded")
    hass = FakeHass(entries=[auto, manual, unloaded])

    async def scenario():
        hass.data[DOMAIN] = {
            e.entry_id: {energy_sources.MAPPING_KEY: await energy_sources.async_energy_mapping(hass)}
            for e in (auto, manual, unloaded)
        }
        await energy_sources.async_setup_energy_listener(hass)
        await energy_sources.async_setup_energy_listener(hass)  # idempotent
        assert len(energy_manager.listeners) == 1

        # Unrelated Energy edit (same power sensors): nothing reloads.
        await energy_manager.listeners[0]()
        assert hass.config_entries.reloaded == []

        energy_manager.data = FULL_PREFS
        await energy_manager.listeners[0]()

    asyncio.run(scenario())
    assert hass.config_entries.reloaded == ["auto"]


def test_missing_energy_component_maps_nothing(monkeypatch):
    monkeypatch.setitem(sys.modules, "homeassistant.components.energy.data", None)
    assert asyncio.run(energy_sources.async_energy_mapping(FakeHass())) == {}
