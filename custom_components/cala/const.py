from enum import StrEnum


class ConnectionStatus(StrEnum):
    PENDING = "Pending"
    CONNECTED = "Connected"
    OFFLINE = "Offline"


DOMAIN = "cala"

CONF_DEVICE_ID = "device_id"
CONF_DEVICE_NAME = "device_name"
CONF_STATE_TOPIC = "state_topic"
CONF_COMMAND_TOPIC = "command_topic"

CONF_PAIRING_CODE = "pairing_code"
CONF_PAIRING_TOKEN = "pairing_token"
CONF_MQTT_USERNAME = "mqtt_username"
CONF_MQTT_PASSWORD = "mqtt_password"
CONF_BROKER_HOST = "broker_host"
CONF_BROKER_PORT = "broker_port"

DEFAULT_STATE_TOPIC_TPL = "cala/{device_id}/state"
DEFAULT_COMMAND_TOPIC_TPL = "cala/{device_id}/command"
DEFAULT_RESPONSE_TOPIC_SUFFIX = "/response"  # cala/{device_id}/command/response

DEVICE_MANUFACTURER = "Cala Systems"
DEVICE_MODEL = "Cala Water Heater"

CONF_DEVICE_HOST = "device_host"
CONF_DEVICE_PORT = "device_port"
