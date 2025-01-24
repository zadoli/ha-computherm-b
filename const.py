"""Constants for the Computherm integration."""

# Integration domain and coordinator
DOMAIN = "computherm_b"
COORDINATOR = "coordinator"

# API Configuration
API_BASE_URL = "https://api.computhermbseries.com"
API_LOGIN_ENDPOINT = "/api/auth/login"
API_DEVICES_ENDPOINT = "/api/devices"
API_DEVICE_CONTROL_ENDPOINT = "/api/devices/{serial_number}/control"

# Device Types and Models
DEVICE_TYPES = {
    "BBOIL": "bboil-classic",
    "BSERIES": "b-series",
}

DEVICE_TYPE_BBOIL = DEVICE_TYPES["BBOIL"]
DEVICE_TYPE_BSERIES = DEVICE_TYPES["BSERIES"]

# Device Identification Attributes
ATTR_SERIAL_NUMBER = "serial_number"
ATTR_DEVICE_TYPE = "device_type"
ATTR_FW_VERSION = "fw_ver"
ATTR_DEVICE_IP = "device_ip"
ATTR_ACCESS_STATUS = "access_status"

# Device State Attributes
ATTR_TEMPERATURE = "temperature"
ATTR_TARGET_TEMPERATURE = "target_temperature"
ATTR_OPERATION_MODE = "operation_mode"
ATTR_RELAY_STATE = "relay_state"
ATTR_ONLINE = "online"

# WebSocket Configuration
WEBSOCKET_CONFIG = {
    "URL": "wss://api.computhermbseries.com/socket.io/?EIO=4&transport=websocket",
    "PING_MESSAGE": "3",  # Socket.IO ping message
    "MESSAGE_TEMPLATES": {
        "LOGIN": '40/devices,{{"accessToken":"{access_token}"}}',
        "SUBSCRIBE": '42/devices,["subscribe",["{device_id}"]]',
    },
}

WEBSOCKET_URL = WEBSOCKET_CONFIG["URL"]
WS_LOGIN_MESSAGE = WEBSOCKET_CONFIG["MESSAGE_TEMPLATES"]["LOGIN"]
WS_SUBSCRIBE_MESSAGE = WEBSOCKET_CONFIG["MESSAGE_TEMPLATES"]["SUBSCRIBE"]
WS_PING_MESSAGE = WEBSOCKET_CONFIG["PING_MESSAGE"]

# WebSocket Event Types
WS_EVENTS = {
    "TEMPERATURE": "TEMPERATURE",
    "TARGET_TEMPERATURE": "TARGET_TEMPERATURE",
    "RELAY": "RELAY",
    "RELAY_STATES": {
        "ON": "ON",
        "OFF": "OFF",
    },
}

WS_TEMPERATURE_EVENT = WS_EVENTS["TEMPERATURE"]
WS_TARGET_TEMPERATURE_EVENT = WS_EVENTS["TARGET_TEMPERATURE"]
WS_RELAY_EVENT = WS_EVENTS["RELAY"]
WS_RELAY_STATE_ON = WS_EVENTS["RELAY_STATES"]["ON"]
WS_RELAY_STATE_OFF = WS_EVENTS["RELAY_STATES"]["OFF"]

# Default Values
DEFAULT_SCAN_INTERVAL = 30  # seconds

# Feature Support
SUPPORT_FLAGS = 0  # Base support flags, extended in climate.py
