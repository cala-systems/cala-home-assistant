# Cala test control panel

Hand-set solar, grid and battery values in Home Assistant and have the Cala
integration publish them to a water heater, with no solar, battery or grid
hardware. Every value is a slider or toggle you set by hand: no simulation, no derived
values.

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

3. **Map the test entities in the Cala options.** Settings → Devices & services →
   Cala → Configure → Entity mappings:

   <!-- options -->
   ```yaml
   solar_production_entity: sensor.cala_test_solar_production
   grid_power_entity: sensor.cala_test_grid_power
   grid_power_sign: positive_is_import
   grid_status_entity: binary_sensor.cala_test_grid_status
   battery_soc_entity: sensor.cala_test_battery_soc
   battery_power_entity: sensor.cala_test_battery_power
   battery_power_sign: positive_is_charging
   ```

   Leave grid import / grid export empty and grid status invert off. Saving
   reloads the integration.

4. **Set a solar policy on the heater in the Cala app.** Without one the
   firmware ignores the context and nothing will change on the heater.

## What the package creates

| Entity | What it is |
|---|---|
| `input_number.cala_test_pv_w` | PV production slider, 0 to 15000 W |
| `input_select.cala_test_grid_direction` | Grid direction, `Import` or `Export` |
| `input_number.cala_test_grid_magnitude_w` | Grid power slider, 0 to 15000 W, in the direction above |
| `input_number.cala_test_battery_soc` | Battery SOC slider, 0 to 100 % |
| `input_select.cala_test_battery_direction` | Battery direction, `Charge` or `Discharge` |
| `input_number.cala_test_battery_magnitude_w` | Battery power slider, 0 to 10000 W, in the direction above |
| `input_boolean.cala_test_grid_connected` | Grid connected (on) or off-grid (off) |
| `input_boolean.cala_test_pv_available` | Off makes the PV sensor `unavailable` |
| `input_boolean.cala_test_grid_power_available` | Off makes the grid power sensor `unavailable` |
| `input_boolean.cala_test_grid_status_available` | Off makes the grid status sensor `unavailable` |
| `input_boolean.cala_test_battery_soc_available` | Off makes the SOC sensor `unavailable` |
| `input_boolean.cala_test_battery_power_available` | Off makes the battery power sensor `unavailable` |
| `sensor.cala_test_solar_production` | power, W |
| `sensor.cala_test_grid_power` | power, W, signed: + importing, − exporting |
| `sensor.cala_test_battery_soc` | battery, % |
| `sensor.cala_test_battery_power` | power, W, signed: + charging, − discharging |
| `binary_sensor.cala_test_grid_status` | connectivity, `on` = connected |
| `sensor.cala_test_last_context` | the last message seen on `cala/+/context` (`ts` as state, payload as attributes) |

Sliders and toggles reset to their initial values (0 W, 50 %, grid direction
Import, battery direction Charge, everything on) when Home Assistant restarts.

Grid and battery power are each a direction plus a slider. To test export, set
**Grid direction** to Export and the grid power slider to the size of the
export; to test discharge, set **Battery direction** to Discharge the same way.
The sliders never go negative; the direction alone decides the sign of
`sensor.cala_test_grid_power` and `sensor.cala_test_battery_power`.

The template sensors are rewritten every 10 s even when nothing moves. That
advances their `last_reported`, which the integration sends as `ts`, so the
heater keeps treating the data as live. 10 s rather than 30 s keeps `ts`
moving on every publish down to the shortest publish interval the options
allow (10 s).

## Worked example

With PV 6000, grid Export 2500, SOC 95, battery Charge 800 and grid connected on, the
integration publishes (`ts` is the sensors' `last_reported` in Unix seconds):

<!-- example-payload -->
```json
{
  "v": 2,
  "ts": 1790856000.0,
  "context": {
    "solar": {"production_w": 6000.0, "producing": true},
    "grid": {"import_w": 0.0, "export_w": 2500.0, "power_w": -2500.0, "exporting": true, "importing": false, "grid_disconnected": false},
    "battery": {"soc_percent": 95.0, "power_w": 800.0, "charging": true, "discharging": false}
  }
}
```

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
| Grid power sensor available | `grid` carries only `grid_disconnected` |
| Grid status sensor available | `grid_disconnected` is left out |
| Battery SOC sensor available | `battery.soc_percent` is left out |
| Battery power sensor available | `battery.power_w`, `charging`, `discharging` are left out |
| All five | nothing is published |
| Grid connected | `grid.grid_disconnected` is `true` |

PV at 0 W sends `"producing": false`.
