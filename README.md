# Cala (MQTT)

Home Assistant custom integration for Cala water heaters.

> **Beta:** This integration requires a beta firmware build on the Cala water heater. To join the beta program, email [beta@calasystems.com](mailto:beta@calasystems.com).

## Prerequisites

Before starting:

- Cala device powered and connected to WiFi
- Home Assistant running and accessible
- MQTT broker installed and running (Mosquitto recommended)

If you do not have MQTT installed:

1. Go to **Settings** → **Add-ons**
2. Install **Mosquitto broker**
3. Start it

## Installation

Install the Cala **integration** (the Home Assistant component that connects to your Cala water heater). The physical device is set up separately in the Setup section below.

### Option A: HACS

1. Install HACS
2. HACS → Integrations → ⋮ → Custom repositories
3. Add this repository URL
4. Category: Integration
5. Install "Cala"
6. Restart Home Assistant

### Option B: Manual copy

1. Copy the `cala` folder into `/config/custom_components/`
2. Restart Home Assistant

**Via SSH:**

```bash
# SSH into Home Assistant
ssh root@homeassistant.local
# or: ssh root@<HA_IP_ADDRESS>

# Create custom_components folder if needed
cd /config
mkdir -p custom_components
exit

# From your local machine, copy the integration
scp -r cala root@homeassistant.local:/config/custom_components/
```

## Setup

1. **Get the pairing code from your Cala water heater:** On the device display, go to **Settings** → **Advanced** → **Home Assistant**. Note the pairing code shown there.
2. After Home Assistant restarts, Cala should automatically announce itself via local discovery
3. Go to **Settings** → **Devices & Services** in Home Assistant
4. Click **Add** and complete the setup, entering the pairing code when prompted

**Preferred:** Discovery via mDNS/Zeroconf (device advertises itself)

**Fallback:** Manual setup (enter device host/port), then enter the pairing code and MQTT credentials.

## MQTT Username and Password

During setup, you will be prompted for:

- MQTT username
- MQTT password

These must match your MQTT broker credentials.

**If using Mosquitto Add-on:**

1. Go to **Settings** → **Add-ons** → **Mosquitto broker**
2. Open the **Configuration** tab
3. Create a new login and store the username and password for Cala setup

**Custom MQTT setup:** Use the credentials configured in your broker. Confirm the broker host and port are correct.

## Verifying MQTT Connection

After setup:

- Cala should appear under **Devices**
- Sensor entities should populate automatically
- No additional configuration is required

If Cala does not appear:

- Confirm MQTT broker is running
- Confirm credentials are correct
- Check logs under **Settings** → **System** → **Logs**

## Boost Mode

Boost mode heats water on demand. Each Cala device includes a boost button and exposes services for automations.

### Boost Button

On the device page, a button shows:

- **Start 24h Boost** when boost is off — starts a 24-hour boost
- **Stop Boost** when boost is on — stops the current boost

### Services

Use these in automations or scripts:

| Service            | Description                                                                             |
| ------------------ | --------------------------------------------------------------------------------------- |
| `cala.start_boost` | Start boost mode. Requires `device_id`. Optional `duration` (hours, 1–168, default 24). |
| `cala.stop_boost`  | Stop boost mode. Requires `device_id`.                                                  |

**Example (Start 24h boost):**

```yaml
service: cala.start_boost
data:
  device_id: your_device_id # e.g. phil_wil_desk or 2507xxa006
  duration: 24
```

**Example (Stop boost):**

```yaml
service: cala.stop_boost
data:
  device_id: your_device_id
```

### Boost Status

The `binary_sensor.xxx_boost_mode_on` entity reports whether boost is active. Use it in automations or to show boost status on dashboards.

## Time-of-Use Rates

The `cala.set_tou_schedule` service pushes a period-based electricity rate schedule to the device. Rates are absolute **$/kWh**. Any time not covered by a period falls back to the mandatory `defaultRate`.

**Schema rules:**

- `version` must be `1`
- `defaultRate` must be a positive float ($/kWh)
- At most **4 seasons**, **4 daySchedules** per season, **8 periods** per daySchedule
- Season `startDate`/`endDate` are inclusive `MM-DD` strings; a season may wrap the year end (e.g. `11-01` → `02-28`); season ranges must not overlap
- `days` are lowercase `sun`/`mon`/`tue`/`wed`/`thu`/`fri`/`sat`; a day may not appear in two daySchedules of the same season
- Periods use minutes since local midnight: `startMin` inclusive, `endMin` exclusive, max `1440`; periods must not overlap and must not cross midnight (split into two periods instead)

**Example:**

```yaml
service: cala.set_tou_schedule
data:
  device_id: your_device_id
  schedule:
    version: 1
    defaultRate: 0.12
    seasons:
      - startDate: "06-01"
        endDate: "09-30"
        daySchedules:
          - days: [mon, tue, wed, thu, fri]
            periods:
              - startMin: 600 # 10:00
                endMin: 840 # 14:00
                rate: 0.32
```

### Automatic publishing from a rates entity

Instead of calling the service directly, you can point the integration at an entity that exposes an hourly rate forecast (e.g. from [openadr3-ven-hass](https://github.com/cala-systems/openadr3-ven-hass)) via the **TOU rates entity** option in the integration's Configure dialog. The entity must expose a `forecast` attribute: a list of at least 24 `{datetime, value, hour}` entries.

On every state change of that entity (and once at startup), the integration:

1. Rotates the rolling forecast into a midnight-anchored 24-hour rate array
2. Compresses it into a schedule: the most common rate becomes `defaultRate`, consecutive hours with equal non-default rates merge into periods, wrapped in a single all-year (`01-01` → `12-31`), all-days season
3. If more than 8 periods result, the 8 rates deviating most from `defaultRate` are kept and the rest are absorbed into `defaultRate` (a warning logs the maximum rate error introduced)
4. Publishes the schedule to the device, skipping the publish when the schedule is unchanged since the last successful one

## Solar & Battery Data (Optional)

Solar and battery entity mappings are optional. Cala receives advisory data only and remains in full control of operation. No direct control commands are accepted from Home Assistant for these inputs.

## Removing the Integration

To uninstall:

1. Remove Cala from **Devices & Services**
2. Delete `/config/custom_components/cala`
3. Restart Home Assistant
