Cala HA integration v0.2.0 enforcing MQTT presence.

## Copying code

From terminal dir `home-assistant/cala_mqtt_ha_integration_v0_2/custom_components` run

```bash
scp -r cala_mqtt root@homeassistant.local:/config/custom_components/cala_mqtt
```

Then from a terminal window that is ssh'd into HA run

```bash
ha core restart
```
