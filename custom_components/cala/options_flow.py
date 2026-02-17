import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import section
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
)

from .const import (
    DOMAIN,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_DEVICE_HOST,
    CONF_DEVICE_PORT,
)
from .pairing_request import _http_pair

_LOGGER = logging.getLogger(__name__)

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional("solar_production_entity"): EntitySelector(
            EntitySelectorConfig(domain=["sensor", "input_number"])
        ),
        vol.Optional("battery_soc_entity"): EntitySelector(
            EntitySelectorConfig(domain=["sensor", "input_number"])
        ),
    }
)

INIT_SCHEMA = vol.Schema(
    {
        vol.Required("next_step", default="entities"): SelectSelector(
            SelectSelectorConfig(
                options=[
                    {"value": "entities", "label": "Entity mappings (solar, battery)"},
                    {"value": "reprovision", "label": "Re-provision device (pairing code, broker, credentials)"},
                ]
            )
        ),
    }
)


def _reprovision_schema(entry) -> vol.Schema:
    data = entry.data
    return vol.Schema(
        {
            vol.Required(
                CONF_DEVICE_HOST,
                default=data.get(CONF_DEVICE_HOST) or "",
            ): str,
            vol.Required(
                CONF_DEVICE_PORT,
                default=data.get(CONF_DEVICE_PORT, 80),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
            vol.Required("provisioning_code"): str,
            vol.Required("mqtt_username", default=data.get("mqtt_username") or ""): str,
            vol.Required("mqtt_password"): str,
            vol.Required("advanced"): section(
                vol.Schema(
                    {
                        vol.Required(
                            "mqtt_broker",
                            default=data.get("broker_host") or "homeassistant.local",
                        ): str,
                        vol.Required(
                            "mqtt_port",
                            default=data.get("broker_port", 1883),
                        ): vol.Coerce(int),
                    }
                ),
                {"collapsed": True},
            ),
        }
    )


class CalaOptionsFlowHandler(config_entries.OptionsFlowWithReload):
    """Options flow with reload so context publishing picks up new entities."""

    async def async_step_init(self, user_input=None):
        if user_input is None:
            return self.async_show_form(
                step_id="init",
                data_schema=INIT_SCHEMA,
            )
        next_step = user_input.get("next_step", "entities")
        if next_step == "reprovision":
            return await self.async_step_reprovision(None)
        return await self.async_step_entities(None)

    async def async_step_entities(self, user_input=None):
        """Entity mapping options."""
        if user_input is not None:
            _LOGGER.info(
                "Cala options saved for %s: %s",
                self.config_entry.data.get(CONF_DEVICE_ID, "?"),
                {k: v for k, v in user_input.items() if v},
            )
            return self.async_create_entry(data=user_input)

        data_schema = self.add_suggested_values_to_schema(
            OPTIONS_SCHEMA, self.config_entry.options
        )
        return self.async_show_form(
            step_id="entities",
            data_schema=data_schema,
        )

    async def async_step_reprovision(self, user_input=None):
        """Re-provision device with new pairing code, broker, or credentials."""
        if user_input is None:
            return self.async_show_form(
                step_id="reprovision",
                data_schema=_reprovision_schema(self.config_entry),
                description_placeholders={
                    "device_id": self.config_entry.data.get(CONF_DEVICE_ID, "?"),
                },
            )

        host = (user_input.get(CONF_DEVICE_HOST) or "").strip()
        port = int(user_input.get(CONF_DEVICE_PORT) or 80)
        adv = user_input.get("advanced") or {}
        mqtt_broker = (adv.get("mqtt_broker") or "homeassistant.local").strip()
        mqtt_port = int(adv.get("mqtt_port") or 1883)
        provisioning_code = (user_input.get("provisioning_code") or "").strip()
        mqtt_username = (user_input.get("mqtt_username") or "").strip()
        mqtt_password = user_input.get("mqtt_password") or ""

        errors = {}
        if not host:
            errors["base"] = "invalid_host"
        elif not provisioning_code:
            errors["base"] = "invalid_provisioning_code"
        elif not mqtt_username:
            errors["base"] = "invalid_mqtt_username"

        if errors:
            return self.async_show_form(
                step_id="reprovision",
                data_schema=_reprovision_schema(self.config_entry),
                errors=errors,
            )

        device_id = self.config_entry.data.get(CONF_DEVICE_ID, "unknown")
        device_name = self.config_entry.data.get(CONF_DEVICE_NAME) or "Cala Water Heater"
        url = f"http://{host}:{port}/pair"

        data, err = await _http_pair(
            url,
            device_id,
            device_name,
            provisioning_code,
            mqtt_broker,
            mqtt_port,
            mqtt_username,
            mqtt_password,
        )

        if err or not data:
            return self.async_show_form(
                step_id="reprovision",
                data_schema=_reprovision_schema(self.config_entry),
                errors={"base": "cannot_connect"},
            )

        new_data = {
            **self.config_entry.data,
            **data,
            CONF_DEVICE_HOST: host,
            CONF_DEVICE_PORT: port,
        }
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
        _LOGGER.info(
            "Cala device %s re-provisioned successfully",
            device_id,
        )
        return self.async_create_entry(data=self.config_entry.options or {})