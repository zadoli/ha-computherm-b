"""DataUpdateCoordinator for Computherm integration."""
import asyncio
import json
import logging
import re
from datetime import timedelta
import websockets

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    DEFAULT_SCAN_INTERVAL,
    API_BASE_URL,
    API_LOGIN_ENDPOINT,
    API_DEVICES_ENDPOINT,
    WEBSOCKET_URL,
    WEBSOCKET_PING_INTERVAL,
    WS_SUBSCRIBE_MESSAGE,
    WS_PING_MESSAGE,
    WS_TEMPERATURE_EVENT,
    WS_RELAY_EVENT,
    WS_RELAY_STATE_ON,
)

_LOGGER = logging.getLogger(__name__)

class ComputhermDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Computherm data."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        config_entry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            # No update interval needed as we use WebSocket push updates
            update_interval=None,
        )
        self.config_entry = config_entry
        self.session = async_get_clientsession(hass)
        self.auth_token = None
        self.devices = {}
        self.device_data = {}
        self.websocket = None
        self._ws_task = None
        self._ping_task = None
        self._sid = None

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        try:
            if not self.auth_token:
                await self._authenticate()
                await self._fetch_devices()
                await self._setup_websocket()

            return self.device_data

        except asyncio.TimeoutError as error:
            raise UpdateFailed(f"Timeout communicating with API: {error}")
        except Exception as error:
            raise UpdateFailed(f"Error communicating with API: {error}")

    async def _authenticate(self):
        """Authenticate with the API."""
        try:
            async with self.session.post(
                f"{API_BASE_URL}{API_LOGIN_ENDPOINT}",
                json={
                    "username": self.config_entry.data["username"],
                    "password": self.config_entry.data["password"],
                },
            ) as resp:
                if resp.status == 401:
                    raise ConfigEntryAuthFailed("Invalid credentials")
                resp.raise_for_status()
                result = await resp.json()
                self.auth_token = result.get("token") or result.get("access_token")
        except Exception as error:
            raise ConfigEntryAuthFailed(f"Authentication failed: {error}")

    async def _fetch_devices(self):
        """Fetch list of devices for the user."""
        try:
            async with self.session.get(
                f"{API_BASE_URL}{API_DEVICES_ENDPOINT}",
                headers={"Authorization": f"Bearer {self.auth_token}"},
            ) as resp:
                if resp.status == 401:
                    raise ConfigEntryAuthFailed("Invalid authentication")
                resp.raise_for_status()
                devices = await resp.json()
                
                # Store device information
                self.devices = {
                    device["id"]: device
                    for device in devices
                }
                
                if not self.devices:
                    _LOGGER.error("No devices found for user")
                    
        except Exception as error:
            raise UpdateFailed(f"Failed to fetch devices: {error}")

    async def _setup_websocket(self):
        """Set up WebSocket connection."""
        if self._ws_task and not self._ws_task.done():
            return

        self._ws_task = asyncio.create_task(self._websocket_listener())

    async def _websocket_listener(self):
        """Listen to WebSocket messages."""
        while True:
            try:
                async with websockets.connect(WEBSOCKET_URL) as websocket:
                    self.websocket = websocket
                    _LOGGER.debug("WebSocket connected")

                    # Handle initial connection message
                    message = await websocket.recv()
                    if message.startswith("0"):
                        data = json.loads(message[1:])
                        self._sid = data.get("sid")
                        
                        # Start ping task
                        if self._ping_task is None or self._ping_task.done():
                            self._ping_task = asyncio.create_task(
                                self._ping_websocket(websocket)
                            )

                        # Subscribe to all devices
                        for device_id in self.devices:
                            subscribe_msg = WS_SUBSCRIBE_MESSAGE.format(device_id=device_id)
                            await websocket.send(subscribe_msg)
                            _LOGGER.debug("Subscribed to device %s", device_id)

                        # Process incoming messages
                        while True:
                            message = await websocket.recv()
                            await self._handle_ws_message(message)

            except websockets.exceptions.ConnectionClosed:
                _LOGGER.warning("WebSocket connection closed, reconnecting...")
            except Exception as error:
                _LOGGER.error("WebSocket error: %s", error)

            await asyncio.sleep(5)  # Wait before reconnecting

    async def _ping_websocket(self, websocket):
        """Send periodic ping messages to keep the connection alive."""
        while True:
            try:
                await asyncio.sleep(WEBSOCKET_PING_INTERVAL)
                if websocket.open:
                    await websocket.send(WS_PING_MESSAGE)
                    _LOGGER.debug("Ping sent")
                else:
                    break
            except Exception as error:
                _LOGGER.error("Error sending ping: %s", error)
                break

    async def _handle_ws_message(self, message: str):
        """Handle incoming WebSocket message."""
        if not message.startswith("42/devices"):
            return

        try:
            # Extract the JSON part of the message
            match = re.match(r'42/devices,(.+)', message)
            if not match:
                return

            data = json.loads(match.group(1))
            if not isinstance(data, list) or len(data) != 2 or data[0] != "event":
                return

            event_data = data[1]
            device_id = event_data.get("serial_number")
            if not device_id or device_id not in self.device_data:
                self.device_data[device_id] = {}

            # Handle temperature readings
            if "readings" in event_data:
                for reading in event_data["readings"]:
                    if reading["type"] == WS_TEMPERATURE_EVENT:
                        self.device_data[device_id]["temperature"] = reading["reading"]
                        self.device_data[device_id]["online"] = event_data.get("online", False)

            # Handle relay state
            if "relays" in event_data:
                for relay in event_data["relays"]:
                    self.device_data[device_id]["is_heating"] = relay["relay_state"] == WS_RELAY_STATE_ON
                    self.device_data[device_id]["online"] = event_data.get("online", False)

            # Notify listeners
            self.async_set_updated_data(self.device_data)

        except Exception as error:
            _LOGGER.error("Error processing WebSocket message: %s", error)

    async def async_stop(self):
        """Stop the WebSocket connection."""
        if self._ping_task:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass
            self._ping_task = None

        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            self._ws_task = None

        if self.websocket:
            await self.websocket.close()
            self.websocket = None
