from __future__ import annotations

import logging
from .pairing_request import _http_pair
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import section
from .mqtt_helper import _mqtt_available

from .const import (
    DOMAIN,
    CONF_DEVICE_NAME,    
)

_LOGGER = logging.getLogger(__name__)


class CalaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        # This integration relies on zeroconf discovery
        return self.async_abort(reason="use_zeroconf")

    async def async_step_zeroconf(self, discovery_info):
        """Handle Zeroconf discovery: Cala device advertised itself; show pairing code form."""
        _LOGGER.debug("Cala discovered via Zeroconf: %s", discovery_info)

        # Get host, port, device_id from discovery (support both object and dict-style)
        host = getattr(discovery_info, "host", None) or (discovery_info or {}).get("host", "")
        port = getattr(discovery_info, "port", None) or (discovery_info or {}).get("port", 80)
        props = getattr(discovery_info, "properties", None) or (discovery_info or {}).get("properties", {}) or {}
        device_id = (props.get("device_id") or props.get("id") or "").strip() or None

        if not host:
            return self.async_abort(reason="invalid_discovery")

        #TODO: What do we need to pass in here?
        if not _mqtt_available(self.hass):
            return self.async_abort(reason="mqtt_not_configured")

        self._discovery_info = discovery_info
        self._discovery_host = host
        self._discovery_port = int(port) if port else 80
        self._discovery_device_id = device_id

        if device_id:
            await self.async_set_unique_id(device_id)
            self._abort_if_unique_id_configured()

        return await self.async_step_provision()
    
    def _provision_schema(self):
        """Single-step schema with broker/port in a collapsible Advanced section."""
        return vol.Schema(
            {
                vol.Required("provisioning_code"): str,
                vol.Required("mqtt_username"): str,
                vol.Required("mqtt_password"): str,
                vol.Required("advanced"): section(
                    vol.Schema(
                        {
                            vol.Required("mqtt_broker", default="homeassistant.local"): str,
                            vol.Required("mqtt_port", default=1883): vol.Coerce(int),
                        }
                    ),
                    {"collapsed": True},
                ),
            }
        )

    async def async_step_provision(self, user_input=None):
        if user_input is not None:
            host = getattr(self, "_discovery_host", None) or ""
            port = getattr(self, "_discovery_port", 80) or 80
            device_id = getattr(self, "_discovery_device_id", None) or "unknown"
            device_name = "Cala Water Heater"

            # Section fields come nested under the section key
            adv = user_input.get("advanced") or {}
            mqtt_broker = adv.get("mqtt_broker", "homeassistant.local")
            mqtt_port = adv.get("mqtt_port", 1883)

            url = f"http://{host}:{port}/pair"
            data, err = await _http_pair(
                url,
                device_id,
                device_name,
                user_input["provisioning_code"],
                mqtt_broker,
                mqtt_port,
                user_input["mqtt_username"],
                user_input["mqtt_password"],
            )
            if err is None and data:
                return self.async_create_entry(
                    title=f"Cala Device ({data.get(CONF_DEVICE_NAME, device_id)})",
                    data=data,
                )
            return self.async_show_form(
                step_id="provision",
                data_schema=self._provision_schema(),
                errors={"base": err or "provisioning_failed"},
            )

        return self.async_show_form(
            step_id="provision",
            data_schema=self._provision_schema(),
        )