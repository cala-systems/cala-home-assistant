import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
import logging
from .const import (
    DOMAIN,
    CONF_DEVICE_NAME,    
)

_LOGGER = logging.getLogger(__name__)

class CalaOptionsFlowHandler(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional("solar_production_entity"): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor", "input_number"]
                    )
                ),
                vol.Optional("grid_import_entity"): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor", "input_number"]
                    )
                ),
                vol.Optional("grid_export_entity"): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor", "input_number"]
                    )
                ),
                vol.Optional("battery_soc_entity"): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor", "input_number"]
                    )
                ),
            })
        )