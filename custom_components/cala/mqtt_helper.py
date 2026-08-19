from homeassistant.components import mqtt


async def _mqtt_available(hass) -> bool:
    """Return True if an MQTT client is available."""
    if hasattr(mqtt, "async_wait_for_mqtt_client"):
        # Returns a bool, not a client. Comparing it with `is not None` made
        # False read as available, so this guard never actually blocked.
        return bool(await mqtt.async_wait_for_mqtt_client(hass))
    if hasattr(mqtt, "async_get_client"):
        return mqtt.async_get_client(hass) is not None
    return False
