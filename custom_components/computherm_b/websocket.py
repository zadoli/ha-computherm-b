"""WebSocket client for Computherm integration."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
import re
import ssl
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Final, List, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from .const import DeviceAttributes as DA
from .const import WebSocketConfig as WSC

_LOGGER = logging.getLogger(__package__)

# Create SSL context at module level, outside of any async context
SSL_CONTEXT: Final = ssl.create_default_context()
SSL_CONTEXT.load_default_certs()


class WebSocketMessageHandler:
    """Handle WebSocket message parsing and processing."""

    @staticmethod
    def handle_websocket_message(message: str) -> Optional[tuple[bool, Any]]:
        """Handle WebSocket message parsing and error checking.

        Returns:
            Optional[tuple[bool, Any]]: A tuple containing:
                - bool: True if message is an error that requires connection closure
                - Any: Parsed message data if not an error, or error details if is error
            Returns None if message format is invalid or not a devices message
        """
        if not message.startswith("42/devices"):
            return None

        match = re.match(r'42/devices,(.+)', message)
        if not match:
            _LOGGER.warning("Failed to match message format: %s", message)
            return None

        try:
            data = json.loads(match.group(1))
            if not isinstance(data, list) or len(data) != 2:
                _LOGGER.warning("Invalid message structure: %s", data)
                return None

            # Handle error responses
            if data[0] == "exception":
                error_data = data[1]
                error_msg = error_data.get("message", "Unknown error")
                error_status = error_data.get("status")

                if (isinstance(error_data, dict) and error_status == "error"
                        and error_msg == "Forbidden resource"):
                    _LOGGER.error(
                        "WebSocket error: %s (Status: %s)",
                        error_msg,
                        error_status)
                    return True, error_data
                else:
                    error_code = error_data.get("code")
                    if hasattr(
                            error_code,
                            'rcvd') and error_code.rcvd.code in (
                            1000,
                            1005):
                        _LOGGER.debug(
                            "WebSocket error (normal closure): %s (Code: %s, Full data: %s)",
                            error_msg,
                            error_code,
                            error_data)
                    else:
                        _LOGGER.error(
                            "WebSocket error: %s (Full data: %s)",
                            error_msg,
                            error_data)
                    return True, error_data

            return False, data

        except Exception as error:
            _LOGGER.error("Error parsing WebSocket message: %s", error)
            return None

    @staticmethod
    def _process_readings(
            readings: List[Dict[str, Any]],
            serial: str,
            device_update: Dict[str, Any]
    ) -> None:
        """Process temperature and humidity readings and update device state."""
        for reading in readings:
            if "reading" not in reading:
                continue

            # Add common sensor attributes if present
            for attr in ["battery", "rssi", "rssi_level", "src"]:
                if attr in reading:
                    # Convert rssi_level and src to lowercase
                    if attr in ["rssi_level", "src"]:
                        device_update[attr] = str(
                            reading[attr]).lower() if reading[attr] is not None else None
                    else:
                        device_update[attr] = reading[attr]

            if reading["type"] == WSC.Events.TEMPERATURE:
                reading_value = None if reading["reading"] == "N/A" else reading["reading"]
                device_update[DA.TEMPERATURE] = reading_value

            elif reading["type"] == WSC.Events.HUMIDITY:
                reading_value = None if reading["reading"] == "N/A" else reading["reading"]
                device_update[DA.HUMIDITY] = reading_value

            elif reading["type"] == WSC.Events.TARGET_TEMPERATURE:
                reading_value = None if reading["reading"] == "N/A" else reading["reading"]
                device_update[DA.TARGET_TEMPERATURE] = reading_value

    @staticmethod
    def _process_relays(
            relays: List[Dict[str, Any]],
            serial: str,
            device_update: Dict[str, Any]
    ) -> None:
        """Process relay states and update device state."""
        for relay in relays:
            if "relay_state" in relay:
                relay_state = relay[DA.RELAY_STATE] == WSC.Events.RELAY_STATES["ON"]
                device_update[DA.RELAY_STATE] = relay_state
                # Keep is_heating for backward compatibility
                device_update["is_heating"] = relay_state

            if "function" in relay:
                function_value = (str(relay[DA.FUNCTION]).lower()
                                  if relay[DA.FUNCTION] is not None else None)
                device_update[DA.FUNCTION] = function_value

            if "mode" in relay:
                mode_value = (str(relay["mode"]).lower()
                              if relay["mode"] is not None else None)
                device_update[DA.MODE] = mode_value

            if "manual_set_point" in relay:
                set_point = (None if relay["manual_set_point"] == "N/A"
                             else relay["manual_set_point"])
                device_update[DA.TARGET_TEMPERATURE] = set_point

    @staticmethod
    def process_base_info(
            event_data: Dict[str, Any],
            serial: str
    ) -> Dict[str, Any]:
        """Process base_info event data."""
        relay_array = event_data.get("relays", [])
        reading_array = event_data.get("readings", [])

        sensors = {
            str(reading["sensor"]): {
                "id": reading["id"],
                "src": (str(reading["src"]).lower()
                        if reading["src"] is not None else None),
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
        self.token_expiry: Optional[datetime] = self._get_token_expiry(
            auth_token)
        self.websocket = None
        self._ws_task: Optional[asyncio.Task] = None
        self._watchdog_task: Optional[asyncio.Task] = None
        self._sid: Optional[str] = None
        self._ping_interval: Optional[float] = None
        self._last_message_time: Optional[datetime] = None
        self._reconnect_interval: float = 10  # Start with 10 seconds
        self._max_reconnect_interval: Final[float] = 600  # Max 10 minutes
        self._reconnect_attempts: int = 0
        self._stopping: bool = False
        # Flag to prevent multiple simultaneous connection attempts
        self._connecting: bool = False
        # Flag to indicate token refresh is in progress
        self._token_refresh_in_progress: bool = False
        # Flag to track if a namespace disconnect message was received
        self._namespace_disconnect_received: bool = False
        self._message_handler = WebSocketMessageHandler()
        # Event to signal a forced reconnection
        self._force_reconnect = asyncio.Event()

    async def start(self) -> None:
        """Start the WebSocket connection."""
        if self._connecting:
            _LOGGER.debug("Connection attempt already in progress")
            return

        self._stopping = False
        self._connecting = True
        try:
            # Reset the force reconnect event
            self._force_reconnect.clear()

            # Start the watchdog task if it's not running
            if not self._watchdog_task or self._watchdog_task.done():
                self._watchdog_task = asyncio.create_task(self._connection_watchdog())

            # Start the main websocket task
            if not self._ws_task or self._ws_task.done():
                self._ws_task = asyncio.create_task(self._websocket_handler())
        finally:
            self._connecting = False

    async def stop(self) -> None:
        """Stop the WebSocket connection."""
        if not self._stopping:
            self._stopping = True
            await self._cleanup_tasks()

    async def _cleanup_tasks(self) -> None:
        """Clean up WebSocket tasks."""
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

        # Cancel and cleanup watchdog task
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
            finally:
                self._watchdog_task = None

    async def _connection_watchdog(self) -> None:
        """Monitor the connection and force reconnection if it becomes stale."""
        while not self._stopping:
            # Check if we have an active connection and ping interval
            if (self.websocket is not None and
                self._last_message_time is not None and
                    self._ping_interval is not None):

                # Calculate time since last message
                time_since_last_message = (
                    datetime.now() - self._last_message_time).total_seconds()
                ping_timeout = self._ping_interval * 1.2  # Add 20% to the ping interval

                _LOGGER.debug(
                    "Watchdog checking connection status... (last message time: %.1f)",
                    time_since_last_message)

                # If we've exceeded the timeout, force a reconnection
                if time_since_last_message > ping_timeout:
                    _LOGGER.warning(
                        "Watchdog detected stale connection: %.1f sec since last message " +
                        "(timeout: %.1f seconds). Forcing reconnection...",
                        time_since_last_message,
                        ping_timeout)

                    # Close the websocket to force a reconnection
                    if self.websocket:
                        try:
                            # Use create_task to avoid blocking the watchdog
                            asyncio.create_task(self.websocket.close())
                        except Exception as error:
                            _LOGGER.debug("Error closing stale websocket: %s", error)

            # Check every 5 seconds (or half the ping interval if available)
            check_interval = 5.0
            if self._ping_interval is not None:
                check_interval = min(self._ping_interval / 2, 5.0)

            await asyncio.sleep(check_interval)

    async def _websocket_handler(self) -> None:
        """Handle WebSocket connection with improved exponential backoff."""
        while not self._stopping:
            try:
                # Reset namespace disconnect flag before starting a new connection
                self._namespace_disconnect_received = False
                await self._handle_connection()
            except ConnectionClosed as error:
                # Check if error.rcvd is an object with a code attribute or an integer
                if hasattr(error, 'rcvd'):
                    if hasattr(error.rcvd, 'code') and error.rcvd.code in (1000, 1005):
                        _LOGGER.debug("WebSocket connection closed normally")
                    else:
                        _LOGGER.warning("WebSocket connection closed: %s", error)
                else:
                    # This is likely part of normal disconnection after a namespace disconnect
                    if self._namespace_disconnect_received:
                        _LOGGER.debug("WebSocket connection closed after namespace disconnect")
                    else:
                        _LOGGER.warning("WebSocket connection closed with unexpected format: %s", error)
            except Exception as error:
                # For error code -3 ("Try again"), only set error state after
                # backoff time
                is_try_again_error = hasattr(
                    error, 'errno') and error.errno == -3

                # Check if this error is related to the "int is not iterable" issue
                is_int_not_iterable = "argument of type 'int' is not iterable" in str(error)

                if is_try_again_error:
                    _LOGGER.info("DEBUG WebSocket error: %s", error)
                elif is_int_not_iterable and self._namespace_disconnect_received:
                    # This is the specific error we're handling - it's part of normal disconnection
                    _LOGGER.debug("Expected WebSocket closure error after namespace disconnect: %s", error)
                else:
                    _LOGGER.error("WebSocket error: %s", error)

            if self._stopping:
                return

            self._reconnect_attempts += 1

            # Implement exponential backoff with jitter
            jitter = random.uniform(0.8, 1.2)
            backoff_time = min(
                self._reconnect_interval * (2 ** (self._reconnect_attempts - 1)) * jitter,
                self._max_reconnect_interval
            )

            _LOGGER.debug(
                "Reconnection attempt %d in %.1f seconds",
                self._reconnect_attempts,
                backoff_time
            )

            # Wait for backoff time
            await asyncio.sleep(backoff_time)

    def _get_token_expiry(self, token: str) -> Optional[datetime]:
        """Extract expiration time from JWT token."""
        try:
            # JWT token consists of three parts: header.payload.signature
            # We need the payload part which is the second element
            payload = token.split('.')[1]

            # Add padding if needed
            padding = len(payload) % 4
            if padding:
                payload += '=' * (4 - padding)

            # Decode base64
            decoded = base64.b64decode(payload)
            payload_data = json.loads(decoded)

            # Get expiration timestamp
            if 'exp' in payload_data:
                expiry_time = datetime.fromtimestamp(payload_data['exp'])
                _LOGGER.info(
                    "Auth token will expire at: %s",
                    expiry_time.strftime("%Y-%m-%d %H:%M:%S"))
                return expiry_time
            return None
        except Exception as error:
            _LOGGER.warning("Failed to parse token expiration: %s", error)
            return None

    def _token_needs_refresh(self) -> bool:
        """Check if token needs refresh (within 1 hour of expiry)."""
        if self.token_expiry is None:
            return False
        return datetime.now() + timedelta(hours=1) >= self.token_expiry

    def set_token_refresh_in_progress(self, in_progress: bool) -> None:
        """Set the token refresh in progress flag."""
        self._token_refresh_in_progress = in_progress

    async def _handle_connection(self) -> None:
        """Handle a single WebSocket connection lifecycle."""
        # Check if token needs refresh before reconnecting
        if self._token_needs_refresh():
            _LOGGER.info(
                "Auth token near expiry, requesting coordinator to refresh...")
            # Only notify if not already in token refresh
            if not self._token_refresh_in_progress:
                self.data_callback({"token_refresh_needed": True})
            return

        if self.websocket:
            # Ensure old connection is properly closed
            try:
                await self.websocket.close()
            except Exception:
                pass
            self.websocket = None

        _LOGGER.debug("Attempting to establish WebSocket connection...")
        async with websockets.connect(WSC.BASE_URL, ssl=SSL_CONTEXT) as websocket:
            self.websocket = websocket
            # Reset connection parameters on successful connection
            self._reconnect_attempts = 0
            self._reconnect_interval = 5
            _LOGGER.debug("WebSocket connected successfully")

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
        # _LOGGER.debug("WebSocket initialized with SID: %s", self._sid)

    async def _setup_connection(self) -> None:
        """Set up the connection with login and subscriptions."""
        try:
            # Send login message
            login_message = WSC.MESSAGE_TEMPLATES["LOGIN"].format(
                access_token=self.auth_token)
            _LOGGER.debug("Sending login message")
            await self.websocket.send(login_message)
            login_response = await self.websocket.recv()
            _LOGGER.debug("Login response received")

            # Check for authentication errors in the login response
            if "error" in login_response or "exception" in login_response:
                _LOGGER.error("Authentication failed: %s", login_response)
                if self.websocket:
                    await self.websocket.close()
                # Let the backoff mechanism handle the reconnection
                raise ValueError(f"Authentication failed: {login_response}")
        except Exception as error:
            _LOGGER.error("Authentication error: %s", error)
            if self.websocket:
                await self.websocket.close()
            self.websocket = None  # Ensure websocket is set to None to trigger reconnection
            raise  # Re-raise to trigger reconnection with backoff

        try:
            # Subscribe to all devices in a single message
            device_serials_json = json.dumps(self.device_serials)
            subscribe_msg = WSC.MESSAGE_TEMPLATES["SUBSCRIBE"].format(
                device_ids=device_serials_json)
            _LOGGER.debug("Sending subscribe message: %s", subscribe_msg)
            await self.websocket.send(subscribe_msg)
            subscribe_response = await self.websocket.recv()
            _LOGGER.debug(
                "Subscribe response received: %s",
                subscribe_response)

            # Handle subscription response
            result = self._message_handler.handle_websocket_message(
                subscribe_response)
            if result:
                should_close, _ = result
                if should_close and self.websocket:
                    await self.websocket.close()
                    self.websocket = None  # Ensure websocket is set to None
                    return

            # Request properties for each device
            for serial in self.device_serials:
                scan_msg = WSC.MESSAGE_TEMPLATES["SCAN"].format(
                    device_id=serial)
                _LOGGER.debug("Sending scan request for device %s", serial)
                await self.websocket.send(scan_msg)
                await self.websocket.recv()
                _LOGGER.debug("Scan response received for device %s", serial)

            # Initialize last message time
            self._last_message_time = datetime.now()
        except Exception as error:
            _LOGGER.error("Error during setup: %s", error)
            if self.websocket:
                await self.websocket.close()
                self.websocket = None  # Ensure websocket is set to None to trigger reconnection
            raise  # Re-raise to trigger reconnection

    async def _process_messages(self) -> None:
        """Process incoming WebSocket messages."""
        while True:
            if self._stopping:
                return

            # Check if we've exceeded the message timeout (ping_interval + 20%)
            if self._last_message_time is not None and self._ping_interval is not None:
                time_since_last_message = (
                    datetime.now() - self._last_message_time).total_seconds()
                ping_timeout = self._ping_interval * 1.2  # Add 20% to the ping interval

                if time_since_last_message > ping_timeout:
                    _LOGGER.info(
                        "Server ping timeout: %.1f sec since last ping (timeout: %.1f seconds). Reconnecting...",
                        time_since_last_message,
                        ping_timeout)
                    if self.websocket:
                        await self.websocket.close()
                    return  # Exit to trigger reconnection

            # Use wait_for with a timeout to allow checking for forced reconnection
            try:
                # Set a reasonable timeout for the recv operation
                # This allows us to periodically check if we need to force reconnect
                # without blocking indefinitely on recv()
                recv_timeout = 30.0  # 30 seconds timeout
                if self._ping_interval is not None:
                    # Use ping interval as a guide for timeout, but don't go below 5 seconds
                    recv_timeout = max(self._ping_interval, 5.0)

                # Wait for either a message or the timeout
                message = await asyncio.wait_for(self.websocket.recv(), timeout=recv_timeout)
                await self._handle_message(message)

            except asyncio.TimeoutError:
                # No message received within timeout, check if connection is still valid
                if self._last_message_time is not None and self._ping_interval is not None:
                    time_since_last_message = (
                        datetime.now() - self._last_message_time).total_seconds()
                    ping_timeout = self._ping_interval * 1.2

                    if time_since_last_message > ping_timeout:
                        _LOGGER.warning(
                            "No message received for %.1f seconds (timeout: %.1f seconds). Reconnecting...",
                            time_since_last_message,
                            ping_timeout)
                        if self.websocket:
                            await self.websocket.close()
                        return  # Exit to trigger reconnection
                    else:
                        # Connection still valid, continue waiting for messages
                        _LOGGER.debug(
                            "No message received for %.1f seconds, but still within timeout (%.1f seconds). " +
                            "Continuing...",
                            time_since_last_message,
                            ping_timeout)
                        continue
                else:
                    # No last message time or ping interval, continue waiting
                    continue
            except ConnectionClosed as error:
                if error.rcvd.code not in (1000, 1005):
                    _LOGGER.warning("WebSocket connection closed: %s", error)
                return  # Exit to trigger reconnection
            except Exception as error:
                _LOGGER.error("Error receiving message: %s", error)
                if self.websocket:
                    await self.websocket.close()
                return  # Exit to trigger reconnection

    async def _handle_message(self, message: str) -> None:
        """Handle incoming WebSocket message."""

        time_since_last_message = (
            datetime.now() -
            self._last_message_time).total_seconds()

        self._last_message_time = datetime.now()  # Update last ping time

        # Handle Socket.IO protocol messages
        if message == "2":  # Socket.IO v4 ping message from server
            _LOGGER.debug(
                "After %.1f sec, server ping received, sending pong",
                time_since_last_message)
            # Send pong response (3 is pong in Socket.IO v4)
            await self.websocket.send("3")
            return
        elif message == "1":  # Socket.IO v4 disconnect message
            _LOGGER.warning(
                "After %.1f sec, server requested disconnect",
                time_since_last_message)
            if self.websocket:
                await self.websocket.close()
            return

        # Socket.IO v4 connect message (should be handled in
        # _handle_initial_connection)
        elif message.startswith("0"):
            _LOGGER.debug(
                "After %.1f sec, received connect message outside of initial connection",
                time_since_last_message)
            return

        # Socket.IO v4 namespace connect message
        elif message.startswith("40"):
            _LOGGER.debug(
                "After %.1f sec, namespace connect message received: %s",
                time_since_last_message, message)
            return

        # Socket.IO v4 namespace disconnect message
        elif message.startswith("41"):
            _LOGGER.debug(
                "After %.1f sec, namespace disconnect message received: %s",
                time_since_last_message, message)
            # Set the flag to indicate we received a namespace disconnect message
            self._namespace_disconnect_received = True
            return

        result = self._message_handler.handle_websocket_message(message)
        if not result:
            return

        should_close, data = result
        if should_close:
            if self.websocket:
                await self.websocket.close()
            return

        _LOGGER.debug(
            "After %.1f sec, received WebSocket message: %s",
            time_since_last_message, data)

        if data[0] != "event":
            _LOGGER.debug(
                "Received non-event message - Type: %s, Data: %s",
                data[0],
                data[1])
            return

        event_data = data[1]

        # Handle base_info case
        if "base_info" in event_data:
            # _LOGGER.debug("Received base_info event: %s", event_data)
            serial = event_data["base_info"].get(DA.SERIAL_NUMBER)
            if not serial:
                _LOGGER.warning(
                    "base_info missing serial_number: %s", event_data)
                return
            if serial not in self.device_serials:
                _LOGGER.warning(
                    "Received base_info for unknown device: %s", serial)
                return

            device_update = self._message_handler.process_base_info(
                event_data, serial)
        else:
            # Handle regular updates
            serial = event_data.get(DA.SERIAL_NUMBER)
            if not serial or serial not in self.device_serials:
                _LOGGER.warning(
                    "Invalid or unknown device serial in update: %s", serial)
                return
            device_update = {
                DA.ONLINE: event_data.get(DA.ONLINE, False)
            }

        # Process readings and relays
        if "readings" in event_data:
            self._message_handler._process_readings(
                event_data["readings"], serial, device_update)

        if "relays" in event_data:
            self._message_handler._process_relays(
                event_data["relays"], serial, device_update)

        # Notify callback with the update
        self.data_callback({serial: device_update})
