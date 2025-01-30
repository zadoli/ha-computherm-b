"""WebSocket client for Computherm integration."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import ssl
from datetime import datetime, timedelta
from typing import Any, Callable

import websockets
from websockets.exceptions import ConnectionClosed

# Create SSL context at module level, outside of any async context
SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.load_default_certs()

# Local imports
from .const import (
    WEBSOCKET_URL,
    WS_LOGIN_MESSAGE,
    WS_SUBSCRIBE_MESSAGE,
    WS_SCAN_MESSAGE,
    WS_PING_MESSAGE,
    WS_TEMPERATURE_EVENT,
    WS_TARGET_TEMPERATURE_EVENT,
    WS_HUMIDITY_EVENT,
    WS_RELAY_STATE_ON,
    ATTR_TEMPERATURE,
    ATTR_HUMIDITY,    
    ATTR_TARGET_TEMPERATURE,
    ATTR_OPERATION_MODE,
    ATTR_ONLINE,
)

_LOGGER = logging.getLogger(__package__)

class WebSocketClient:
    """WebSocket client for handling real-time device updates."""

    def __init__(
        self,
        auth_token: str,
        device_ids: list[str],
        data_callback: Callable[[dict[str, Any]], None],
    ) -> None:
        """Initialize the WebSocket client."""
        self.auth_token = auth_token
        self.device_ids = device_ids
        self.data_callback = data_callback
        self.websocket = None
        self._ws_task = None
        self._ping_task = None
        self._sid = None
        self._ping_interval = None
        self._reconnect_interval = 5  # Start with 5 seconds
        self._max_reconnect_interval = 300  # Max 5 minutes
        self._last_ping_time = None
        self._stopping = False
        self._connecting = False  # Flag to prevent multiple simultaneous connection attempts

    async def start(self) -> None:
        """Start the WebSocket connection."""
        if self._connecting:
            _LOGGER.debug("Connection attempt already in progress")
            return
            
        self._stopping = False
        self._connecting = True
        try:
            if not self._ws_task or self._ws_task.done():
                self._ws_task = asyncio.create_task(self._websocket_handler())
        finally:
            self._connecting = False

    async def stop(self) -> None:
        """Stop the WebSocket connection."""
        self._stopping = True
        
        # Cancel and cleanup ping task
        if self._ping_task and not self._ping_task.done():
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass
            finally:
                self._ping_task = None

        # Close websocket first to trigger clean shutdown
        if self.websocket:
            try:
                await self.websocket.close()
            except Exception as error:
                _LOGGER.debug("Error closing websocket: %s", error)
            finally:
                self.websocket = None

        # Cancel and cleanup websocket task
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            finally:
                self._ws_task = None

    async def _websocket_handler(self) -> None:
        """Handle WebSocket connection with exponential backoff."""
        while not self._stopping:
            if self.websocket:
                # Ensure old connection is properly closed
                try:
                    await self.websocket.close()
                except Exception:
                    pass
                self.websocket = None
            try:
                _LOGGER.info("Attempting to establish WebSocket connection...")
                async with websockets.connect(WEBSOCKET_URL, ssl=SSL_CONTEXT) as websocket:
                    self.websocket = websocket
                    self._reconnect_interval = 5  # Reset on successful connection
                    _LOGGER.info("WebSocket connected successfully")

                    # Handle initial connection message
                    message = await websocket.recv()
                    if not message.startswith("0"):
                        raise ValueError(f"Unexpected initial message: {message}")

                    connect_data = json.loads(message[1:])
                    self._sid = connect_data.get("sid")
                    self._ping_interval = connect_data.get("pingInterval", 25000) / 1000
                    _LOGGER.info("WebSocket initialized with SID: %s", self._sid)
                    
                    # Send login message
                    login_message = WS_LOGIN_MESSAGE.format(access_token=self.auth_token)
                    await websocket.send(login_message)
                    response = await websocket.recv()
                    _LOGGER.info("Login response received: %s", response)

                    # Start ping task
                    if self._ping_task is None or self._ping_task.done():
                        self._ping_task = asyncio.create_task(self._ping_handler())

                    # Subscribe to all devices in a single message
                    device_ids_json = json.dumps(self.device_ids)
                    subscribe_msg = WS_SUBSCRIBE_MESSAGE.format(device_ids=device_ids_json)
                    await websocket.send(subscribe_msg)
                    _LOGGER.info("Subscribed to devices: %s", self.device_ids)
                    
                    # Request properties for each device
                    for device_id in self.device_ids:
                        scan_msg = WS_SCAN_MESSAGE.format(device_id=device_id)
                        await websocket.send(scan_msg)
                        _LOGGER.info("Sent scan request for device %s", device_id)

                    # Process incoming messages
                    while True:
                        if self._stopping:
                            return
                        message = await websocket.recv()
                        await self._handle_message(message)

            except ConnectionClosed as error:
                _LOGGER.warning("WebSocket connection closed: %s", error)
            except Exception as error:
                _LOGGER.error("WebSocket error: %s", error)

            if self._stopping:
                return

            # Implement exponential backoff
            await asyncio.sleep(self._reconnect_interval)
            self._reconnect_interval = min(
                self._reconnect_interval * 2,
                self._max_reconnect_interval
            )

    async def _ping_handler(self) -> None:
        """Send periodic ping messages with health check."""
        while not self._stopping and self.websocket:
            try:
                self._last_ping_time = datetime.now()
                await self.websocket.send(WS_PING_MESSAGE)
                await asyncio.sleep(self._ping_interval)

                # Check if we've missed too many pings
                if (datetime.now() - self._last_ping_time) > timedelta(seconds=self._ping_interval * 3):
                    _LOGGER.warning("Missed too many pings, reconnecting...")
                    if self.websocket:
                        await self.websocket.close()
                    return

            except Exception as error:
                _LOGGER.error("Error in ping handler: %s", error)
                return

    def _process_readings(self, readings: list, device_id: str, device_update: dict) -> None:
        """Process temperature and humidity readings and update device state."""
        for reading in readings:
            if "reading" not in reading:
                continue
                
            if reading["type"] == WS_TEMPERATURE_EVENT:
                device_update[ATTR_TEMPERATURE] = reading["reading"]
                _LOGGER.debug(
                    "Device %s temperature update: %.1f°C",
                    device_id,
                    reading["reading"]
                )
            elif reading["type"] == WS_HUMIDITY_EVENT:
                device_update[ATTR_HUMIDITY] = reading["reading"]
                _LOGGER.debug(
                    "Device %s humidity update: %.1f%%",
                    device_id,
                    reading["reading"]
                )
            elif reading["type"] == WS_TARGET_TEMPERATURE_EVENT:
                device_update[ATTR_TARGET_TEMPERATURE] = reading["reading"]
                _LOGGER.debug(
                    "Device %s target temperature update: %.1f°C",
                    device_id,
                    reading["reading"]
                )

    def _process_relays(self, relays: list, device_id: str, device_update: dict) -> None:
        """Process relay states and update device state."""
        for relay in relays:
            if "relay_state" in relay:
                is_heating = relay["relay_state"] == WS_RELAY_STATE_ON
                device_update["is_heating"] = is_heating
                device_update[ATTR_OPERATION_MODE] = "heat" if is_heating else "off"
                _LOGGER.debug(
                    "Device %s relay state update: %s",
                    device_id,
                    "ON" if is_heating else "OFF"
                )

    async def _handle_message(self, message: str) -> None:
        """Handle incoming WebSocket message."""
        if not message.startswith("42/devices"):
            return

        try:
            # Extract the JSON part of the message
            match = re.match(r'42/devices,(.+)', message)
            if not match:
                _LOGGER.warning("Failed to match message format: %s", message)
                return

            data = json.loads(match.group(1))
            if not isinstance(data, list) or len(data) != 2:
                _LOGGER.warning("Invalid message structure: %s", data)
                return

            # Handle error responses
            if data[0] == "exception":
                error_data = data[1]
                _LOGGER.error("WebSocket error response: %s (Code: %s)", 
                                error_data.get("message"), error_data.get("code"))
                return
                
            if data[0] != "event":
                _LOGGER.debug("Ignoring non-event message: %s", data[0])
                return

            event_data = data[1]
            device_id = None
            device_update = {}

            # Handle base_info case
            if "base_info" in event_data:
                _LOGGER.info("Received base_info event: %s", event_data)
                device_id = event_data["base_info"].get("serial_number")
                if not device_id:
                    _LOGGER.warning("base_info missing serial_number: %s", event_data)
                    return
                if device_id not in self.device_ids:
                    _LOGGER.warning("Received base_info for unknown device: %s", device_id)
                    return
                
                relay_array = event_data.get("relays", [])
                reading_array = event_data.get("readings", [])
                
                sensors = {
                    str(reading["sensor"]): {
                        "id": reading["id"],
                        "src": reading["src"],
                        "sensor": reading["sensor"],
                        "type": reading["type"],
                        "name": reading["name"]
                    } for reading in reading_array
                }
                
                relays = {
                    str(relay["relay"]): relay for relay in relay_array
                }
                
                # Extract available reading and relay identifiers
                sensor_ids = [str(reading["sensor"]) for reading in reading_array]
                relay_ids = [str(relay["relay"]) for relay in relay_array]
                
                device_update = {
                    ATTR_ONLINE: event_data.get(ATTR_ONLINE, False),
                    "base_info": event_data["base_info"],
                    "available_sensor_ids": sensor_ids,
                    "available_relay_ids": relay_ids,
                    "sensors": sensors,
                    "relays": relays,
                }
                _LOGGER.info("Updated device %s with device_update: %s", device_id, device_update)
            else:
                # Handle regular updates
                device_id = event_data.get("serial_number")
                if not device_id or device_id not in self.device_ids:
                    _LOGGER.warning("Invalid or unknown device ID in update: %s", device_id)
                    return
                device_update = {
                    ATTR_ONLINE: event_data.get(ATTR_ONLINE, False)
                }

            # Process readings and relays
            if "readings" in event_data:
                self._process_readings(event_data["readings"], device_id, device_update)

            if "relays" in event_data:
                self._process_relays(event_data["relays"], device_id, device_update)

            # Handle operation mode if explicitly provided
            if "operation_mode" in event_data:
                device_update[ATTR_OPERATION_MODE] = event_data["operation_mode"]
                _LOGGER.debug(
                    "Device %s operation mode update: %s",
                    device_id,
                    event_data["operation_mode"]
                )

            # Notify callback with the update
            self.data_callback({device_id: device_update})
            _LOGGER.debug(
                "Device %s %s: %s",
                device_id,
                "base_info and state update" if "base_info" in event_data else "update",
                device_update
            )

        except Exception as error:
            _LOGGER.error("Error processing WebSocket message: %s", error)
