from __future__ import annotations

import logging
from .pairing_request import _http_pair
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import section
from .mqtt_helper import _mqtt_available
from .options_flow import CalaOptionsFlowHandler

from .const import (
    DOMAIN,
    CONF_DEVICE_NAME,
    CONF_DEVICE_ID,
    CONF_DEVICE_HOST,
    CONF_DEVICE_PORT,
    ConnectionStatus,
)

_LOGGER = logging.getLogger(__name__)


class CalaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Entry point: prefer discovery, allow manual fallback."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["discovery", "manual"],
        )

    async def async_step_discovery(self, user_input=None):
        """Discovery path (keeps existing behavior)."""
        return self.async_abort(reason="use_zeroconf")
    
    async def async_step_reauth(self, user_input=None):
        """Handle reauth (credentials/device reprovision needed)."""
        entry_id = self.context.get("entry_id")
        entry = self.hass.config_entries.async_get_entry(entry_id) if entry_id else None
        if entry is None:
            return self.async_abort(reason="invalid_discovery")

        self._reauth_entry = entry

        self._discovery_host = (entry.data.get("device_host") or "").strip()
        self._discovery_port = entry.data.get("device_port") or 80
        self._discovery_device_id = entry.data.get("device_id")

        # Reuse the existing provision step UX
        return await self.async_step_provision(user_input)
    
    def _manual_device_schema(self):
        return vol.Schema(
            {
                vol.Required(CONF_DEVICE_HOST): str,
                vol.Required(
                    CONF_DEVICE_PORT,
                    default=80
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=1, max=65535),
                ),
                vol.Required(CONF_DEVICE_ID): str,
            }
        )
    
    async def async_step_manual(self, user_input=None):
        """Manual setup when discovery isn't working."""
        if not await _mqtt_available(self.hass):
            return self.async_abort(reason="mqtt_not_configured")

        if user_input is not None:
            host = user_input[CONF_DEVICE_HOST].strip()
            port = user_input[CONF_DEVICE_PORT]
            device_id = user_input[CONF_DEVICE_ID].strip()

            errors = {}
            if not host:
                errors["base"] = "invalid_host"
            elif not device_id:
                errors["base"] = "invalid_device_id"

            if errors:
                return self.async_show_form(
                    step_id="manual",
                    data_schema=self._manual_device_schema(),
                    errors=errors,
                )

            self._discovery_host = host
            self._discovery_port = port
            self._discovery_device_id = device_id

            return await self.async_step_provision()

        return self.async_show_form(
            step_id="manual",
            data_schema=self._manual_device_schema(),
        )

    async def async_step_zeroconf(self, discovery_info):
        """Handle Zeroconf discovery: Cala device advertised itself; show pairing code form."""
        _LOGGER.debug("Cala discovered via Zeroconf: %s", discovery_info)

        # Get host, port, device_id from discovery (support both object and dict-style)
        host = getattr(discovery_info, "host", None) or (discovery_info or {}).get("host", "")
        port = getattr(discovery_info, "port", None) or (discovery_info or {}).get("port", 80)
        props = getattr(discovery_info, "properties", None) or (discovery_info or {}).get("properties", {}) or {}
        device_id = (props.get("device_id") or props.get("id") or "").strip() or None

        if device_id:
            await self.async_set_unique_id(device_id)
            self._abort_if_unique_id_configured()

        if not host:
            return self.async_abort(reason="invalid_discovery")

        #TODO: What do we need to pass in here?
        if not await _mqtt_available(self.hass):
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
        if user_input is None:
            return self.async_show_form(
                step_id="provision",
                data_schema=self._provision_schema(),
            )

        host = (getattr(self, "_discovery_host", None) or "").strip()
        port = getattr(self, "_discovery_port", 80) or 80
        device_id = getattr(self, "_discovery_device_id", None) or host or "unknown"
        device_name = "Cala Water Heater"

        adv = user_input.get("advanced") or {}
        mqtt_broker = (adv.get("mqtt_broker") or "homeassistant.local").strip()
        mqtt_port = adv.get("mqtt_port", 1883)

        url = f"http://{host}:{port}/pair"

        provisioning_code = user_input["provisioning_code"].strip()
        mqtt_username = user_input["mqtt_username"].strip()
        mqtt_password = user_input["mqtt_password"]

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

        _LOGGER.debug("Provision result err=%s data_type=%s data=%s", err, type(data), data)

        if err is None and isinstance(data, dict) and data:
            actual_id = (data.get(CONF_DEVICE_ID) or "").strip()
            if actual_id:
                await self.async_set_unique_id(actual_id)
                self._abort_if_unique_id_configured()

            entry_data = {
                **data,
                CONF_DEVICE_HOST: host,
                CONF_DEVICE_PORT: port,
                "_connection_initial_state": ConnectionStatus.PENDING,
            }

            # If this provision is happening as part of reauthentication, update existing entry instead of creating a new one
            reauth_entry = getattr(self, "_reauth_entry", None)
            if reauth_entry is not None:
                self.hass.config_entries.async_update_entry(reauth_entry, data=data)
                await self.hass.config_entries.async_reload(reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

            return self.async_create_entry(
                title=f"Cala Device ({data.get(CONF_DEVICE_NAME, device_id)})",
                data=entry_data,
            )

        return self.async_show_form(
            step_id="provision",
            data_schema=self._provision_schema(),
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return CalaOptionsFlowHandler()
