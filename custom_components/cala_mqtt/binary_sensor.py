from homeassistant.components.binary_sensor import BinarySensorEntity

class CalaConnectedBinarySensor(BinarySensorEntity):
    _attr_name = "Cala Connected"
    _attr_is_on = True
