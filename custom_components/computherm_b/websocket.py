"""WebSocket client for Computherm integration."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import ssl
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Final, List, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from .const import (
    WebSocketConfig as WSC,
    DeviceAttributes as DA,
)

_LOGGER = logging.getLogger(__package__)

# Create SSL context at module level, outside of any async context
SSL_CONTEXT: Final = ssl.create_default_context()
SSL_CONTEXT.load_default_certs()

class WebSocketMessageHandler:
    """Handle WebSocket message parsing and processing."""

    @staticmethod
    def _process_readings(readings: List[Dict[str, Any]], serial: str, device_update: Dict[str, Any]) -> None:
        """Process temperature and humidity readings and update device state."""
        for reading in readings:
            if "reading" not in reading:
                continue
                
            # Add common sensor attributes if present
            for attr in ["battery", "rssi", "rssi_level", "src"]:
                if attr in reading:
                    # Convert rssi_level and src to lowercase
                    if attr in ["rssi_level", "src"]:
                        device_update[attr] = str(reading[attr]).lower() if reading[attr] is not None else None
                    else:
                        device_update[attr] = reading[attr]
                    _LOGGER.debug(
                        "Device %s %s update: %s",
                        serial,
                        attr,
                        device_update[attr]
                    )
                
            if reading["type"] == WSC.Events.TEMPERATURE:
                device_update[DA.TEMPERATURE] = reading["reading"]
                _LOGGER.debug(
                    "Device %s temperature update: %.1f°C",
                    serial,
                    reading["reading"]
                )
            elif reading["type"] == WSC.Events.HUMIDITY:
                device_update[DA.HUMIDITY] = reading["reading"]
                _LOGGER.debug(
                    "Device %s humidity update: %.1f%%",
                    serial,
                    reading["reading"]
                )
            elif reading["type"] == WSC.Events.TARGET_TEMPERATURE:
                device_update[DA.TARGET_TEMPERATURE] = reading["reading"]
                _LOGGER.debug(
                    "Device %s target temperature update: %.1f°C",
                    serial,
                    reading["reading"]
                )

    @staticmethod
    def _process_relays(relays: List[Dict[str, Any]], serial: str, device_update: Dict[str, Any]) -> None:
        """Process relay states and update device state."""
        _LOGGER.debug("Processing relays for device %s: %s", serial, relays)
        for relay in relays:
            _LOGGER.debug("Processing relay update for device %s: %s", serial, relay)
            if "relay_state" in relay:
                relay_state = relay[DA.RELAY_STATE] == WSC.Events.RELAY_STATES["ON"]
                device_update[DA.RELAY_STATE] = relay_state
                device_update["is_heating"] = relay_state  # Keep is_heating for backward compatibility
                _LOGGER.debug(
                    "Device %s relay state update: %s (relay_state: %s, is_heating: %s)",
                    serial,
                    "ON" if relay_state else "OFF",
                    relay_state,
                    relay_state
                )
            if "function" in relay:
                function_value = str(relay[DA.FUNCTION]).lower() if relay[DA.FUNCTION] is not None else None
                device_update[DA.FUNCTION] = function_value
                _LOGGER.debug(
                    "Device %s function update: %s",
                    serial,
                    function_value)
                    
            if "mode" in relay:
                mode_value = str(relay["mode"]).lower() if relay["mode"] is not None else None
                device_update[DA.MODE] = mode_value
                _LOGGER.debug(
                    "Device %s mode update: %s",
                    serial,
                    mode_value)

            if "manual_set_point" in relay:
                device_update[DA.TARGET_TEMPERATURE] = relay["manual_set_point"]
                _LOGGER.debug(
                    "Device %s target temperature point update: %.1f°C",
                    serial,
                    relay["manual_set_point"]
                )

    @staticmethod
    def process_base_info(event_data: Dict[str, Any], serial: str) -> Dict[str, Any]:
        """Process base_info event data."""
        relay_array = event_data.get("relays", [])
        reading_array = event_data.get("readings", [])
        
        sensors = {
            str(reading["sensor"]): {
                "id": reading["id"],
                "src": str(reading["src"]).lower() if reading["src"] is not None else None,
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
            DA.ONLINE: event_data.get(DA.ONLINE, False),
            "base_info": event_data["base_info"],
            "available_sensor_ids": sensor_ids,
            "available_relay_ids": relay_ids,
            "sensors": sensors,
            "relays": relays,
        }
        _LOGGER.info("Updated device %s with device_update: %s", serial, device_update)
        return device_update

class WebSocketClient:
    """WebSocket client for handling real-time device updates."""

    def __init__(
        self,
        auth_token: str,
        device_serials: List[str],
        data_callback: Callable[[Dict[str, Any]], None],
    ) -> None:
        """Initialize the WebSocket client."""
        self.auth_token = auth_token
        self.device_serials = device_serials
        self.data_callback = data_callback
        self.websocket = None
        self._ws_task: Optional[asyncio.Task] = None
        self._ping_task: Optional[asyncio.Task] = None
        self._sid: Optional[str] = None
        self._ping_interval: Optional[float] = None
        self._reconnect_interval: float = 5  # Start with 5 seconds
        self._max_reconnect_interval: Final[float] = 300  # Max 5 minutes
        self._last_ping_time: Optional[datetime] = None
        self._stopping: bool = False
        self._connecting: bool = False  # Flag to prevent multiple simultaneous connection attempts
        self._message_handler = WebSocketMessageHandler()

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
        await self._cleanup_tasks()

    async def _cleanup_tasks(self) -> None:
        """Clean up WebSocket and ping tasks."""
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
            try:
                await self._handle_connection()
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

    async def _handle_connection(self) -> None:
        """Handle a single WebSocket connection lifecycle."""
        if self.websocket:
            # Ensure old connection is properly closed
            try:
                await self.websocket.close()
            except Exception:
                pass
            self.websocket = None

        _LOGGER.info("Attempting to establish WebSocket connection...")
        async with websockets.connect(WSC.BASE_URL, ssl=SSL_CONTEXT) as websocket:
            self.websocket = websocket
            self._reconnect_interval = 5  # Reset on successful connection
            _LOGGER.info("WebSocket connected successfully")

            await self._handle_initial_connection()
            await self._setup_connection()
            await self._process_messages()

    async def _handle_initial_connection(self) -> None:
        """Handle initial connection message and setup."""
        message = await self.websocket.recv()
        if not message.startswith("0"):
            raise ValueError(f"Unexpected initial message: {message}")

        connect_data = json.loads(message[1:])
        self._sid = connect_data.get("sid")
        self._ping_interval = connect_data.get("pingInterval", 25000) / 1000
        _LOGGER.info("WebSocket initialized with SID: %s", self._sid)

    async def _setup_connection(self) -> None:
        """Set up the connection with login and subscriptions."""
        # Send login message
        login_message = WSC.MESSAGE_TEMPLATES["LOGIN"].format(access_token=self.auth_token)
        await self.websocket.send(login_message)
        response = await self.websocket.recv()
        _LOGGER.info("Login response received: %s", response)

        # Start ping task
        if self._ping_task is None or self._ping_task.done():
            self._ping_task = asyncio.create_task(self._ping_handler())

        # Subscribe to all devices in a single message
        device_serials_json = json.dumps(self.device_serials)
        subscribe_msg = WSC.MESSAGE_TEMPLATES["SUBSCRIBE"].format(device_ids=device_serials_json)
        await self.websocket.send(subscribe_msg)
        _LOGGER.info("Subscribed to devices: %s", self.device_serials)
        
        # Request properties for each device
        for serial in self.device_serials:
            scan_msg = WSC.MESSAGE_TEMPLATES["SCAN"].format(device_id=serial)
            await self.websocket.send(scan_msg)
            _LOGGER.info("Sent scan request for device %s", serial)

    async def _process_messages(self) -> None:
        """Process incoming WebSocket messages."""
        while True:
            if self._stopping:
                return
            message = await self.websocket.recv()
            await self._handle_message(message)

    async def _ping_handler(self) -> None:
        """Send periodic ping messages with health check."""
        while not self._stopping and self.websocket:
            try:
                self._last_ping_time = datetime.now()
                await self.websocket.send(WSC.PING_MESSAGE)
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
                _LOGGER.error("WebSocket error response: %s (Code: %s, Full data: %s)", 
                             error_data.get("message"), error_data.get("code"), error_data)
                return
                
            if data[0] != "event":
                _LOGGER.debug("Received non-event message - Type: %s, Data: %s", data[0], data[1])
                return

            event_data = data[1]
            serial = None
            device_update: Dict[str, Any] = {}

            # Handle base_info case
            if "base_info" in event_data:
                _LOGGER.info("Received base_info event: %s", event_data)
                serial = event_data["base_info"].get(DA.SERIAL_NUMBER)
                if not serial:
                    _LOGGER.warning("base_info missing serial_number: %s", event_data)
                    return
                if serial not in self.device_serials:
                    _LOGGER.warning("Received base_info for unknown device: %s", serial)
                    return
                
                device_update = self._message_handler.process_base_info(event_data, serial)
            else:
                # Handle regular updates
                serial = event_data.get(DA.SERIAL_NUMBER)
                if not serial or serial not in self.device_serials:
                    _LOGGER.warning("Invalid or unknown device serial in update: %s", serial)
                    return
                device_update = {
                    DA.ONLINE: event_data.get(DA.ONLINE, False)
                }

            # Process readings and relays
            if "readings" in event_data:
                self._message_handler._process_readings(event_data["readings"], serial, device_update)

            if "relays" in event_data:
                _LOGGER.debug(
                    "Device %s received relay update: %s",
                    serial,
                    event_data["relays"]
                )
                self._message_handler._process_relays(event_data["relays"], serial, device_update)

            _LOGGER.debug(
                "Device %s %s: %s",
                serial,
                "base_info and state update" if "base_info" in event_data else "update",
                device_update
            )

            # Notify callback with the update
            self.data_callback({serial: device_update})

        except Exception as error:
            _LOGGER.error("Error processing WebSocket message: %s", error)
