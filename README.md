Cala MQTT Home Assistant integration (v0.2.0)

- Requires MQTT to be configured in Home Assistant.
- Discovers a single device per config entry; entities attach to that device.
- Telemetry topic format: `cala/<device_id>/telemetry`
- Command topic format: `cala/<device_id>/command`

## Install

From `home-assistant/cala_mqtt_ha_integration_v0_2/custom_components`:

```bash
scp -r cala_mqtt root@homeassistant.local:/config/custom_components/cala_mqtt
```

Then restart Home Assistant:

```bash
ha core restart
```

## Configure in Home Assistant

1. Add Integration → “Cala”.
2. Enter `device_id` (e.g., `phil_gtl_desk_ota23`).
   - If you leave device name blank, it defaults to the `device_id`.
3. Save; the integration will create one device and sensors/binary sensors under it.

If you change the device_id/name, remove the existing Cala entry and add it again.

## Publish telemetry

Publish JSON telemetry to:

```
cala/<device_id>/telemetry
```

Example (device_id `phil_gtl_desk_ota23`):

```bash
mosquitto_pub -t cala/phil_gtl_desk_ota23/telemetry -m '{"top_c":51.2,"upper_element_on":1}'
```

## Entities

Sensors: temperatures, gallons_available, compressor_hz, energy_used_kwh  
Binary sensors: upper_element_on, lower_element_on, boost_mode_on  
Entity names include the device name (e.g., `phil_gtl_desk_ota23 Top Temperature`).

## Viewing logs (debugging pairing / "cannot connect")

The integration logs under `custom_components.cala_mqtt`. To see its messages in **Settings → System → Logging** (or in the main log):

1. **Settings → System → Logging**
2. Under "Loggers", click **Add custom component**
3. Enter: `custom_components.cala_mqtt`
4. Set level to **Debug** (or at least **Info**)
5. Restart Home Assistant if needed, then try pairing again.

You should then see lines such as:

- `Cala pairing: sending POST to http://... for device_id=...`
- `Cala pairing HTTP response: status=...` (when status ≠ 200)
- `Cala pairing HTTP request failed: ...` (when the request errors)
- `Cala pairing failed: err=...` (when the flow returns "cannot connect")
- `Cala pairing succeeded: ...` when the device response is accepted and credentials are extracted.

Full path in the log UI is **Developer tools → Logs** or **Settings → System → Logging**; filter by "Cala" or "cala_mqtt".

## Logo on the Devices page

Home Assistant loads integration/device logos from the [Home Assistant Brands](https://github.com/home-assistant/brands) repository, not from this integration. To show a Cala logo on the Devices page (and on the integration card):

1. Fork [home-assistant/brands](https://github.com/home-assistant/brands).
2. Add a folder `custom_integrations/cala_mqtt/` with:
   - `icon.png` (e.g. 256×256)
   - `icon@2x.png` (2× size for retina)
3. Open a Pull Request. Once merged, the Cala logo will appear for this integration.
