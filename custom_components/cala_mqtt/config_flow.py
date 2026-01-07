from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import mqtt

from .const import (
    DOMAIN,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_STATE_TOPIC,
    CONF_COMMAND_TOPIC,
)


async def _mqtt_available(hass) -> bool:
    """Return True if an MQTT client is available."""
    if hasattr(mqtt, "async_wait_for_mqtt_client"):
        client = await mqtt.async_wait_for_mqtt_client(hass)
        return client is not None

    if hasattr(mqtt, "async_get_client"):
        return mqtt.async_get_client(hass) is not None

    return False


class CalaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        # HARD REQUIRE MQTT
        if not await _mqtt_available(self.hass):
            return self.async_abort(reason="mqtt_not_configured")

        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID].strip()
            # Default the device name to the device_id when none is provided,
            # so the device shows up in HA with the same identifier you publish to.
            device_name = user_input.get(CONF_DEVICE_NAME, "").strip() or device_id

            await self.async_set_unique_id(device_id)
            self._abort_if_unique_id_configured()

            # Derive topics from device_id (NOT user-editable)
            data = {
                CONF_DEVICE_NAME: device_name,
                CONF_DEVICE_ID: device_id,
                CONF_STATE_TOPIC: f"cala/{device_id}/telemetry",
                CONF_COMMAND_TOPIC: f"cala/{device_id}/command",
            }

            return self.async_create_entry(
                title=device_name,
                data=data,
            )

        schema = vol.Schema(
            {
                vol.Optional(CONF_DEVICE_NAME, default=""): str,
                vol.Required(CONF_DEVICE_ID, default="wh_01"): str,
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema)