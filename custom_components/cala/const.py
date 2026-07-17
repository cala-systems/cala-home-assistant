from enum import StrEnum


class ConnectionStatus(StrEnum):
    PENDING = "Pending"
    CONNECTED = "Connected"
    OFFLINE = "Offline"


DOMAIN = "cala"

CONF_DEVICE_ID = "device_id"
ATTR_DEVICE_ID = "device_id"
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

DEVICE_MANUFACTURER = "Cala Systems"
DEVICE_MODEL = "Cala Water Heater"

LITERS_TO_GALLONS = 0.264172  # US gallons per liter

SERVICE_START_BOOST = "start_boost"
SERVICE_STOP_BOOST = "stop_boost"
SERVICE_SET_TOU_SCHEDULE = "set_tou_schedule"

CONF_TOU_RATES_ENTITY = "tou_rates_entity"
ATTR_SCHEDULE = "schedule"

TOU_RATES_HOURS = 24
TOU_MAX_SEASONS = 4
TOU_MAX_DAY_SCHEDULES = 4
TOU_MAX_PERIODS = 8
MINUTES_PER_DAY = 1440
TOU_RATE_FLOOR = 0.001

CONF_DEVICE_HOST = "device_host"
CONF_DEVICE_PORT = "device_port"
