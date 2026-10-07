"""examples/test_panel: the package, dashboard and README agree with each other and the code."""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from cala import const, publish
from cala.sensor import TELEMETRY_FIELDS

PANEL_DIR = Path(__file__).resolve().parents[1] / "examples" / "test_panel"
PACKAGE = yaml.safe_load((PANEL_DIR / "cala_test_panel.yaml").read_text())
DASHBOARD_TEXT = (PANEL_DIR / "dashboard.yaml").read_text()
DASHBOARD = yaml.safe_load(DASHBOARD_TEXT)
README = (PANEL_DIR / "README.md").read_text()

TEST_ID_RE = re.compile(r"\b(?:sensor|binary_sensor|input_number|input_select|input_boolean)\.cala_test_\w+")
MIN_PUBLISH_INTERVAL_S = 10  # options_flow NumberSelector min


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _template_entities() -> dict[str, dict]:
    out = {}
    for block in PACKAGE["template"]:
        for domain in ("sensor", "binary_sensor"):
            for ent in block.get(domain, []):
                out[f"{domain}.{_slug(ent['name'])}"] = ent
    return out


TEMPLATES = _template_entities()
PACKAGE_IDS = (
    {f"input_number.{k}" for k in PACKAGE["input_number"]}
    | {f"input_select.{k}" for k in PACKAGE["input_select"]}
    | {f"input_boolean.{k}" for k in PACKAGE["input_boolean"]}
    | set(TEMPLATES)
    | {f"sensor.{_slug(s['name'])}" for s in PACKAGE["mqtt"]["sensor"]}
)


def _dashboard_entities(node) -> list[str]:
    if isinstance(node, dict):
        found = [node["entity"]] if isinstance(node.get("entity"), str) else []
        return found + [e for v in node.values() for e in _dashboard_entities(v)]
    if isinstance(node, list):
        return [e for v in node for e in _dashboard_entities(v)]
    return []


def _fenced_after(marker: str) -> str:
    m = re.search(rf"<!-- {marker} -->\s*```\w*\n(.*?)```", README, re.S)
    assert m, f"README block {marker} not found"
    return m.group(1)


README_OPTIONS = yaml.safe_load(_fenced_after("options"))
README_PAYLOAD = json.loads(_fenced_after("example-payload"))


def test_readme_and_dashboard_only_reference_entities_the_package_creates():
    referenced = set(TEST_ID_RE.findall(README)) | set(TEST_ID_RE.findall(DASHBOARD_TEXT))
    assert referenced - PACKAGE_IDS == set()
    assert set(TEMPLATES) <= referenced


def test_dashboard_cala_ids_match_the_integrations_naming():
    names = [m["name"] for m in TELEMETRY_FIELDS.values()]
    names += list(const.BINARY_FIELDS.values()) + ["Connection", "Energy Today", "Energy Total"]
    known = {_slug(f"Cala Water Heater {n}") for n in names}
    cala_ids = [e for e in _dashboard_entities(DASHBOARD) if ".cala_water_heater_" in e]
    assert cala_ids
    for entity_id in cala_ids:
        assert entity_id.split(".", 1)[1] in known, entity_id


@pytest.mark.parametrize(
    "entity_id, device_class, unit",
    [
        ("sensor.cala_test_solar_production", "power", "W"),
        ("sensor.cala_test_grid_power", "power", "W"),
        ("sensor.cala_test_battery_power", "power", "W"),
        ("sensor.cala_test_battery_soc", "battery", "%"),
        ("binary_sensor.cala_test_grid_status", "connectivity", None),
    ],
)
def test_template_entity_classes_and_units(entity_id, device_class, unit):
    ent = TEMPLATES[entity_id]
    assert ent["device_class"] == device_class
    assert ent.get("unit_of_measurement") == unit
    assert unit is None or unit in publish.SUPPORTED_POWER_UNITS | {"%"}


def test_every_template_has_an_availability_toggle_the_package_defines():
    for entity_id, ent in TEMPLATES.items():
        toggles = re.findall(r"input_boolean\.\w+", ent["availability"])
        assert toggles and set(toggles) <= PACKAGE_IDS, entity_id


def test_triggers_rewrite_on_every_input_and_faster_than_any_publish_interval():
    (block,) = PACKAGE["template"]
    triggers = block["triggers"]
    watched = {e for t in triggers if t["trigger"] == "state" for e in t["entity_id"]}
    inputs = {i for i in PACKAGE_IDS if i.startswith(("input_number.", "input_select.", "input_boolean."))}
    assert watched == inputs
    (pattern,) = [t for t in triggers if t["trigger"] == "time_pattern"]
    assert int(pattern["seconds"].lstrip("/")) <= MIN_PUBLISH_INTERVAL_S


def test_readme_options_are_real_option_names_and_values():
    allowed_signs = {
        const.CONF_GRID_POWER_SIGN: const.GRID_POWER_SIGNS,
        const.CONF_BATTERY_POWER_SIGN: const.BATTERY_POWER_SIGNS,
    }
    for key, value in README_OPTIONS.items():
        if key in allowed_signs:
            assert value in allowed_signs[key]
        else:
            assert key in publish.CONTEXT_ENTITY_KEYS
            assert value in TEMPLATES


# ---- The worked example, through the real publisher ----

T0 = datetime.fromtimestamp(README_PAYLOAD["ts"], tz=timezone.utc)
EXAMPLE_INPUTS = {
    "input_number.cala_test_pv_w": "6000.0",
    "input_number.cala_test_grid_magnitude_w": "2500.0",
    "input_select.cala_test_grid_direction": "Export",
    "input_number.cala_test_battery_soc": "95.0",
    "input_number.cala_test_battery_w": "800.0",
    "input_boolean.cala_test_grid_connected": "on",
}


@dataclass
class FakeState:
    state: str
    attributes: dict = field(default_factory=dict)
    last_updated: datetime = T0
    last_reported: datetime = T0


class FakeHass:
    def __init__(self, states: dict):
        self.states = self
        self._states = states

    def get(self, entity_id):
        return self._states.get(entity_id)


def _render(inputs: dict, unavailable: set[str] = frozenset()) -> FakeHass:
    """Evaluate the package's templates for the subset of Jinja they use."""
    states = {}
    for entity_id, ent in TEMPLATES.items():
        if entity_id in unavailable:
            states[entity_id] = FakeState("unavailable")
            continue
        sources = re.findall(r"input_\w+\.\w+", ent["state"])
        (source,) = [s for s in sources if not s.startswith("input_select.")]
        raw = inputs[source]
        if entity_id.startswith("binary_sensor."):
            value = "on" if raw == "on" else "off"
        else:
            value = float(raw)
            for direction in (s for s in sources if s.startswith("input_select.")):
                if inputs[direction] == "Export":
                    value = 0 - value
            value = str(value)
        unit = ent.get("unit_of_measurement")
        states[entity_id] = FakeState(value, {"unit_of_measurement": unit} if unit else {})
    return FakeHass(states)


def _payload(hass) -> dict | None:
    ctx = publish.build_context(hass, README_OPTIONS)
    ts = publish._source_ts(hass, README_OPTIONS)
    if not ctx or ts is None:
        return None
    return {"v": publish.PAYLOAD_VERSION, "ts": ts, "context": ctx}


def test_grid_direction_is_a_selector_and_the_power_slider_is_never_negative():
    (direction,) = PACKAGE["input_select"].values()
    assert direction["options"] == ["Import", "Export"]
    assert direction["initial"] == "Import"
    assert PACKAGE["input_number"]["cala_test_grid_magnitude_w"]["min"] == 0
    grid_state = TEMPLATES["sensor.cala_test_grid_power"]["state"]
    assert "is_state('input_select.cala_test_grid_direction', 'Export')" in grid_state


@pytest.mark.parametrize(
    "direction, magnitude, power_w, importing, exporting",
    [("Import", "1400.0", 1400.0, True, False), ("Export", "1400.0", -1400.0, False, True)],
)
def test_grid_direction_reaches_the_payload(direction, magnitude, power_w, importing, exporting):
    inputs = dict(
        EXAMPLE_INPUTS,
        **{
            "input_select.cala_test_grid_direction": direction,
            "input_number.cala_test_grid_magnitude_w": magnitude,
        },
    )
    grid = _payload(_render(inputs))["context"]["grid"]
    assert grid["power_w"] == power_w
    assert grid["importing"] is importing
    assert grid["exporting"] is exporting


def test_readme_worked_example_is_what_the_publisher_sends():
    assert _payload(_render(EXAMPLE_INPUTS)) == README_PAYLOAD


@pytest.mark.parametrize(
    "unavailable, gone",
    [
        ({"sensor.cala_test_solar_production"}, ["solar"]),
        ({"sensor.cala_test_grid_power"}, ["grid.power_w", "grid.import_w"]),
        ({"binary_sensor.cala_test_grid_status"}, ["grid.grid_disconnected"]),
        ({"sensor.cala_test_battery_soc"}, ["battery.soc_percent"]),
        ({"sensor.cala_test_battery_power"}, ["battery.power_w", "battery.charging"]),
    ],
)
def test_missing_data_table(unavailable, gone):
    ctx = _payload(_render(EXAMPLE_INPUTS, unavailable))["context"]
    for path in gone:
        section, _, key = path.partition(".")
        assert section not in ctx or (key and key not in ctx[section])


def test_all_sensors_unavailable_publishes_nothing():
    assert _payload(_render(EXAMPLE_INPUTS, set(TEMPLATES))) is None


def test_grid_connected_off_sends_grid_disconnected():
    inputs = dict(EXAMPLE_INPUTS, **{"input_boolean.cala_test_grid_connected": "off"})
    assert _payload(_render(inputs))["context"]["grid"]["grid_disconnected"] is True
