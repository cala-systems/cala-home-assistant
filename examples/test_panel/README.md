# Cala test control panel

Hand-set solar, grid and battery values in Home Assistant and have the Cala
integration publish them to a water heater, with no solar, battery or grid
hardware. Every value is a slider or toggle you set by hand: no simulation, no derived
values.

The test sensors behave like a stock Home Assistant install's (power in W with
HA's sign conventions, plus kWh meters) and go into the Energy settings the
way a homeowner's would. That exercises Cala's default path: it reads the
Energy settings, with nothing configured in the Cala options.

## Setup

1. **Add the package.** Copy `cala_test_panel.yaml` to `/config/packages/` and
   enable packages in `configuration.yaml`:

   ```yaml
   homeassistant:
     packages:
       cala_test_panel: !include packages/cala_test_panel.yaml
   ```

   Restart Home Assistant. The MQTT integration must already be set up, which it
   is if the Cala integration is working.

2. **Add the dashboard.** Settings → Dashboards → Add dashboard → open it →
   ⋮ → Edit → ⋮ → Raw configuration editor, and paste `dashboard.yaml` under
   `views:`. If your heater's entities are not `*.cala_water_heater_*`, see
   the comment at the top of `dashboard.yaml`.

3. **Add the test sensors to the Energy settings.** Settings → Dashboards →
   Energy. Use a Home Assistant whose Energy history you don't mind filling
   with test numbers.

   | Energy setting | Field | Sensor |
   |---|---|---|
   | Solar panels | Solar production energy | `sensor.cala_test_solar_energy` |
   | | Solar production power | `sensor.cala_test_solar_production` |
   | Electricity grid | Grid consumption | `sensor.cala_test_grid_import_energy` |
   | | Return to grid | `sensor.cala_test_grid_export_energy` |
   | | Grid power (standard, not inverted) | `sensor.cala_test_grid_power` |
   | Home battery storage | Energy going in to the battery | `sensor.cala_test_battery_charge_energy` |
   | | Energy coming out of the battery | `sensor.cala_test_battery_discharge_energy` |
   | | Battery power (standard, not inverted) | `sensor.cala_test_battery_power` |
   | | State of charge (newer HA versions only) | `sensor.cala_test_battery_soc` |

   Leave the Cala options alone: **Choose solar, grid and battery sensors by
   hand** stays off. Saving the Energy settings reloads Cala, and its log
   shows `Cala context sources (from Energy settings): [...]`.

   The same settings as Home Assistant stores them (`.storage/energy`):

   <!-- energy -->
   ```yaml
   energy_sources:
     - type: solar
       stat_energy_from: sensor.cala_test_solar_energy
       stat_rate: sensor.cala_test_solar_production
     - type: grid
       stat_energy_from: sensor.cala_test_grid_import_energy
       stat_energy_to: sensor.cala_test_grid_export_energy
       stat_rate: sensor.cala_test_grid_power
     - type: battery
       stat_energy_from: sensor.cala_test_battery_discharge_energy
       stat_energy_to: sensor.cala_test_battery_charge_energy
       stat_rate: sensor.cala_test_battery_power
       stat_soc: sensor.cala_test_battery_soc
   ```

4. **Set a solar policy on the heater in the Cala app.** Without one the
   firmware ignores the context and nothing will change on the heater.

### Testing grid status (hand-mapped)

The Energy settings have no grid-status (outage) sensor, so testing
`grid_disconnected` still needs the hand-mapped override: Settings → Devices &
services → Cala → Configure → Settings, turn on **Choose solar, grid and
battery sensors by hand**, submit, then on the next page:

<!-- options -->
```yaml
manual_context_entities: true
solar_production_entity: sensor.cala_test_solar_production
grid_power_entity: sensor.cala_test_grid_power
grid_power_sign: positive_is_import
grid_status_entity: binary_sensor.cala_test_grid_status
battery_soc_entity: sensor.cala_test_battery_soc
battery_power_entity: sensor.cala_test_battery_power
battery_power_sign: positive_is_discharging
```

Leave grid import / grid export empty and grid status invert off. While the
toggle is on, the Energy settings are ignored; turn it off again when you're
done.

## What the package creates

| Entity | What it is |
|---|---|
| `input_number.cala_test_pv_w` | PV production slider, 0 to 15000 W |
| `input_number.cala_test_grid_w` | Grid power slider, −15000 to 15000 W, positive = importing |
| `input_number.cala_test_battery_soc` | Battery SOC slider, 0 to 100 % |
| `input_number.cala_test_battery_w` | Battery power slider, −10000 to 10000 W, positive = discharging |
| `input_boolean.cala_test_grid_connected` | Grid connected (on) or off-grid (off) |
| `input_boolean.cala_test_pv_available` | Off makes the PV sensor `unavailable` |
| `input_boolean.cala_test_grid_power_available` | Off makes the grid power sensors `unavailable` |
| `input_boolean.cala_test_grid_status_available` | Off makes the grid status sensor `unavailable` |
| `input_boolean.cala_test_battery_soc_available` | Off makes the SOC sensor `unavailable` |
| `input_boolean.cala_test_battery_power_available` | Off makes the battery power sensors `unavailable` |
| `sensor.cala_test_solar_production` | power, W |
| `sensor.cala_test_grid_power` | power, W, positive = importing |
| `sensor.cala_test_battery_soc` | battery, % |
| `sensor.cala_test_battery_power` | power, W, positive = discharging |
| `binary_sensor.cala_test_grid_status` | connectivity, `on` = connected |
| `sensor.cala_test_grid_import_power`, `sensor.cala_test_grid_export_power` | grid power split by direction, W, always ≥ 0 |
| `sensor.cala_test_battery_discharge_power`, `sensor.cala_test_battery_charge_power` | battery power split by direction, W, always ≥ 0 |
| `sensor.cala_test_solar_energy` | kWh meter (Riemann sum) of the solar power |
| `sensor.cala_test_grid_import_energy`, `sensor.cala_test_grid_export_energy` | kWh meters of the grid import / export power |
| `sensor.cala_test_battery_discharge_energy`, `sensor.cala_test_battery_charge_energy` | kWh meters of the battery discharge / charge power |
| `sensor.cala_test_last_context` | the last message seen on `cala/+/context` (`ts` as state, payload as attributes) |

Sliders and toggles reset to their initial values (0 W, 50 %, everything on)
when Home Assistant restarts. The kWh meters keep counting across restarts.

The template sensors are rewritten every 10 s even when nothing moves. That
advances their `last_reported`, which the integration sends as `ts`, so the
heater keeps treating the data as live. 10 s rather than 30 s keeps `ts`
moving on every publish down to the shortest publish interval the options
allow (10 s).

## Worked example

With PV 6000, grid −2500 (exporting), SOC 95 and battery −800 (charging), the
integration publishes (`ts` is the sensors' `last_reported` in Unix seconds):

<!-- example-payload -->
```json
{
  "v": 2,
  "ts": 1790856000.0,
  "context": {
    "solar": {"production_w": 6000.0, "producing": true},
    "grid": {"import_w": 0.0, "export_w": 2500.0, "power_w": -2500.0, "exporting": true, "importing": false},
    "battery": {"soc_percent": 95.0, "power_w": 800.0, "charging": true, "discharging": false}
  }
}
```

The heater's payload uses its own convention, battery `power_w` positive when
charging; the integration converts from HA's. With the hand-mapped grid status,
`grid` also carries `"grid_disconnected": false`.

Watch it on the broker:

```sh
mosquitto_sub -h <broker> -u <user> -P <password> -t 'cala/+/context' -v
```

It goes out on every change (at most once every 5 s) and on the publish
interval (30 s by default). The dashboard's "Last context published" card
shows the same message.

## Missing-data cases

| Toggle off | Effect on the payload |
|---|---|
| PV sensor available | `solar` is left out |
| Grid power sensor available | `grid` is left out (hand-mapped: carries only `grid_disconnected`) |
| Grid status sensor available | hand-mapped only: `grid_disconnected` is left out |
| Battery SOC sensor available | `battery.soc_percent` is left out |
| Battery power sensor available | `battery.power_w`, `charging`, `discharging` are left out |
| All of them | nothing is published |
| Grid connected | hand-mapped only: `grid.grid_disconnected` is `true` |

PV at 0 W sends `"producing": false`.
