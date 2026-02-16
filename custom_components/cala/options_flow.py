import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional("solar_production_entity"): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["sensor", "input_number"])
        ),
        vol.Optional("grid_import_entity"): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["sensor", "input_number"])
        ),
        vol.Optional("grid_export_entity"): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["sensor", "input_number"])
        ),
        vol.Optional("battery_soc_entity"): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["sensor", "input_number"])
        ),
    }
)


class CalaOptionsFlowHandler(config_entries.OptionsFlowWithReload):
    """Options flow with reload so context publishing picks up new entities."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            _LOGGER.info(
                "Cala options saved for %s: %s",
                self.config_entry.data.get("device_id", "?"),
                {k: v for k, v in user_input.items() if v},
            )
            return self.async_create_entry(data=user_input)

        data_schema = self.add_suggested_values_to_schema(
            OPTIONS_SCHEMA, self.config_entry.options
        )
        return self.async_show_form(step_id="init", data_schema=data_schema)