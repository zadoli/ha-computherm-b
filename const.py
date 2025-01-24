"""Constants for the Computherm integration."""

DOMAIN = "computherm"
COORDINATOR = "coordinator"

DEFAULT_SCAN_INTERVAL = 30

# API endpoints
API_BASE_URL = "https://api.computhermbseries.com"
API_LOGIN_ENDPOINT = "/api/v1/auth/login"
API_DEVICES_ENDPOINT = "/api/v1/devices"
API_DEVICE_CONTROL_ENDPOINT = "/api/v1/devices/{device_id}/control"

# WebSocket configuration
WEBSOCKET_URL = "wss://api.computhermbseries.com/socket.io/?EIO=4&transport=websocket"
WEBSOCKET_PING_INTERVAL = 25  # seconds
WEBSOCKET_PING_TIMEOUT = 20  # seconds

# WebSocket message types
WS_SUBSCRIBE_MESSAGE = '42/devices,["subscribe",["{device_id}"]]'
WS_PING_MESSAGE = "2"  # Socket.IO ping message

# WebSocket event types
WS_TEMPERATURE_EVENT = "TEMPERATURE"
WS_RELAY_EVENT = "RELAY"
WS_RELAY_STATE_ON = "ON"
WS_RELAY_STATE_OFF = "OFF"

# Device attributes
ATTR_TEMPERATURE = "temperature"
ATTR_TARGET_TEMPERATURE = "target_temperature"
ATTR_OPERATION_MODE = "operation_mode"
ATTR_RELAY_STATE = "relay_state"
ATTR_ONLINE = "online"

# Supported features
SUPPORT_FLAGS = 0
