"""Constants for the Computherm integration."""
from typing import Final, Dict, List

# Integration domain and coordinator
DOMAIN: Final[str] = "computherm_b"
COORDINATOR: Final[str] = "coordinator"

# API Configuration
API_BASE_URL: Final[str] = "https://api.computhermbseries.com"
API_LOGIN_ENDPOINT: Final[str] = "/api/auth/login"
API_DEVICES_ENDPOINT: Final[str] = "/api/devices"
API_DEVICE_CONTROL_ENDPOINT: Final[str] = "/api/devices/{device_id}/cmd"

# Device Types and Models
DEVICE_TYPES: Final[Dict[str, str]] = {
    "BBOIL": "bboil-classic",
    "BSERIES": "b-series",
}

DEVICE_TYPE_BBOIL: Final[str] = DEVICE_TYPES["BBOIL"]
DEVICE_TYPE_BSERIES: Final[str] = DEVICE_TYPES["BSERIES"]


# Device Attributes
class DeviceAttributes:
    """Device attribute constants."""

    # Identification
    SERIAL_NUMBER: Final[str] = "serial_number"
    DEVICE_ID: Final[str] = "id"  # API ID used for commands
    DEVICE_TYPE: Final[str] = "device_type"
    FW_VERSION: Final[str] = "fw_ver"
    DEVICE_IP: Final[str] = "device_ip"
    ACCESS_STATUS: Final[str] = "access_status"

    # State
    TEMPERATURE: Final[str] = "temperature"
    HUMIDITY: Final[str] = "humidity"
    TARGET_TEMPERATURE: Final[str] = "target_temperature"
    FUNCTION: Final[str] = "function"
    MODE: Final[str] = "mode"
    RELAY_STATE: Final[str] = "relay_state"
    ONLINE: Final[str] = "online"

    # Diagnostic
    BATTERY: Final[str] = "battery"
    RSSI: Final[str] = "rssi"
    RSSI_LEVEL: Final[str] = "rssi_level"
    SOURCE: Final[str] = "src"


# For backward compatibility
ATTR_SERIAL_NUMBER = DeviceAttributes.SERIAL_NUMBER
ATTR_DEVICE_ID = DeviceAttributes.DEVICE_ID
ATTR_DEVICE_TYPE = DeviceAttributes.DEVICE_TYPE
ATTR_FW_VERSION = DeviceAttributes.FW_VERSION
ATTR_DEVICE_IP = DeviceAttributes.DEVICE_IP
ATTR_ACCESS_STATUS = DeviceAttributes.ACCESS_STATUS
ATTR_TEMPERATURE = DeviceAttributes.TEMPERATURE
ATTR_HUMIDITY = DeviceAttributes.HUMIDITY
ATTR_TARGET_TEMPERATURE = DeviceAttributes.TARGET_TEMPERATURE
ATTR_FUNCTION = DeviceAttributes.FUNCTION
ATTR_MODE = DeviceAttributes.MODE
ATTR_RELAY_STATE = DeviceAttributes.RELAY_STATE
ATTR_ONLINE = DeviceAttributes.ONLINE
ATTR_BATTERY = DeviceAttributes.BATTERY
ATTR_RSSI = DeviceAttributes.RSSI
ATTR_RSSI_LEVEL = DeviceAttributes.RSSI_LEVEL
ATTR_SOURCE = DeviceAttributes.SOURCE


# WebSocket Configuration
class WebSocketConfig:
    """WebSocket configuration constants."""

    BASE_URL: Final[str] = "wss://api.computhermbseries.com/socket.io/?EIO=4&transport=websocket"
    PING_MESSAGE: Final[str] = "3"  # Socket.IO ping message
    MESSAGE_TEMPLATES: Final[Dict[str, str]] = {
        "LOGIN": '40/devices,{{"accessToken":"{access_token}"}}',
        "SUBSCRIBE": '42/devices,["subscribe",{device_ids}]',
        "SCAN": '42/devices,["cmd","{{\\"serial_number\\":\\"{device_id}\\",\\"cmd\\":\\"scan\\"}}"]',
    }
    
    # Event Types
    class Events:
        """WebSocket event type constants."""
        TEMPERATURE: Final[str] = "TEMPERATURE"
        HUMIDITY: Final[str] = "HUMIDITY"
        TARGET_TEMPERATURE: Final[str] = "TARGET_TEMPERATURE"
        RELAY: Final[str] = "RELAY"
        RELAY_STATES: Final[Dict[str, str]] = {
            "ON": "ON",
            "OFF": "OFF",
        }


# Operation Modes and Functions
MODE_SCHEDULE: Final[str] = "schedule"
MODE_MANUAL: Final[str] = "manual"
MODE_OFF: Final[str] = "off"
AVAILABLE_MODES: Final[List[str]] = [MODE_SCHEDULE, MODE_MANUAL, MODE_OFF]

FUNCTION_HEATING: Final[str] = "heating"
FUNCTION_COOLING: Final[str] = "cooling"
AVAILABLE_FUNCTIONS: Final[List[str]] = [FUNCTION_HEATING, FUNCTION_COOLING]
