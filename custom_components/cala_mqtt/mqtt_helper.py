async def _mqtt_available(hass) -> bool:
    """Return True if an MQTT client is available."""
    if hasattr(mqtt, "async_wait_for_mqtt_client"):
        client = await mqtt.async_wait_for_mqtt_client(hass)
        return client is not None
    if hasattr(mqtt, "async_get_client"):
        return mqtt.async_get_client(hass) is not None
    return False