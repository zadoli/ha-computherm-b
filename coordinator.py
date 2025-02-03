"""DataUpdateCoordinator for Computherm integration."""
import asyncio
import logging
from typing import Any

from aiohttp import ClientError, ClientResponseError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    API_BASE_URL,
    API_LOGIN_ENDPOINT,
    API_DEVICES_ENDPOINT,
    ATTR_SERIAL_NUMBER,
    ATTR_DEVICE_TYPE,
    ATTR_FW_VERSION,
    ATTR_DEVICE_IP,
    ATTR_ACCESS_STATUS,
    ATTR_TEMPERATURE,
    ATTR_TARGET_TEMPERATURE,
    ATTR_ONLINE,
    ATTR_FUNCTION,
    ATTR_RELAY_STATE,
)
from .websocket import WebSocketClient

_LOGGER = logging.getLogger(__package__)

class ComputhermDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
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
        self.devices_with_base_info = {}  # Track devices that have received base_info
        self._ws_client: WebSocketClient | None = None
        _LOGGER.info("Initialized ComputhermDataUpdateCoordinator")

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from API endpoint."""
        try:
            if not self.auth_token:
                _LOGGER.info("No auth token, starting initial setup...")
                await self._authenticate()
                await self._fetch_devices()
                await self._setup_websocket()
                _LOGGER.info("Initial setup completed successfully")
            elif self._ws_client and not self._ws_client.websocket:
                # Only attempt reconnect if we have a client but lost connection
                _LOGGER.info("WebSocket disconnected, attempting reconnect...")
                await self._ws_client.start()

            return self.device_data

        except asyncio.TimeoutError as error:
            _LOGGER.error("Timeout communicating with API")
            raise UpdateFailed("Connection timed out") from error
        except ClientResponseError as error:
            if error.status == 401:
                _LOGGER.error("Authentication token expired or invalid")
                self.auth_token = None  # Clear token to force re-authentication
                raise ConfigEntryAuthFailed("Authentication failed") from error
            _LOGGER.error("API error: %s", error)
            raise UpdateFailed(f"API error: {error.status}") from error
        except ClientError as error:
            _LOGGER.error("Network error: %s", error)
            raise UpdateFailed("Network connection failed") from error
        except Exception as error:
            _LOGGER.exception("Unexpected error")
            raise UpdateFailed(f"Unexpected error: {str(error)}") from error

    async def _authenticate(self) -> None:
        """Authenticate with the API."""
        try:
            _LOGGER.info("Attempting authentication...")
            async with self.session.post(
                f"{API_BASE_URL}{API_LOGIN_ENDPOINT}",
                json={
                    "email": self.config_entry.data["username"],
                    "password": self.config_entry.data["password"],
                },
            ) as resp:
                if resp.status == 401:
                    raise ConfigEntryAuthFailed("Invalid credentials")
                resp.raise_for_status()
                result = await resp.json()
                self.auth_token = result.get("token") or result.get("access_token")
                if not self.auth_token:
                    raise ConfigEntryAuthFailed("No authentication token received")
                _LOGGER.info("Authentication successful")
        except ClientResponseError as error:
            if error.status == 401:
                raise ConfigEntryAuthFailed("Invalid credentials") from error
            raise UpdateFailed(f"Authentication failed with status {error.status}") from error
        except ClientError as error:
            raise UpdateFailed(f"Network error during authentication: {error}") from error
        except Exception as error:
            raise UpdateFailed(f"Unexpected error during authentication: {error}") from error

    async def _fetch_devices(self) -> None:
        """Fetch list of devices for the user."""
        try:
            _LOGGER.info("Fetching devices...")
            async with self.session.get(
                f"{API_BASE_URL}{API_DEVICES_ENDPOINT}",
                headers={"Authorization": f"Bearer {self.auth_token}"},
            ) as resp:
                if resp.status == 401:
                    raise ConfigEntryAuthFailed("Invalid authentication")
                resp.raise_for_status()
                devices = await resp.json()
                
                # Store device information
                self.devices = {}
                for device in devices:
                    serial = device.get(ATTR_SERIAL_NUMBER)
                    if serial:
                        self.devices[serial] = {
                            "id": device.get("id"),
                            ATTR_SERIAL_NUMBER: serial,
                            "brand": device.get("brand"),
                            "type": device.get("type"),
                            "user_id": device.get("user_id"),
                            ATTR_FW_VERSION: device.get(ATTR_FW_VERSION),
                            ATTR_DEVICE_IP: device.get(ATTR_DEVICE_IP),
                            ATTR_DEVICE_TYPE: device.get(ATTR_DEVICE_TYPE, ""),
                            ATTR_ACCESS_STATUS: device.get(ATTR_ACCESS_STATUS),
                            "access_rules": device.get("access_rules", {})
                        }
                        _LOGGER.info("Found device: %s (Type: %s)", serial, device.get(ATTR_DEVICE_TYPE, "unknown"))
                    else:
                        _LOGGER.warning("Device without serial number found: %s", device)
                
                if not self.devices:
                    _LOGGER.warning("No devices found for user")
                    await self.async_stop()
                    self.device_data = {}  # Clear any existing device data
                else:
                    _LOGGER.info("Successfully fetched %d devices: %s", len(self.devices), list(self.devices.keys()))
                    
        except ClientResponseError as error:
            if error.status == 401:
                raise ConfigEntryAuthFailed("Invalid authentication") from error
            raise UpdateFailed(f"Failed to fetch devices with status {error.status}") from error
        except ClientError as error:
            raise UpdateFailed(f"Network error fetching devices: {error}") from error
        except Exception as error:
            raise UpdateFailed(f"Unexpected error fetching devices: {error}") from error

    async def _setup_websocket(self) -> None:
        """Set up WebSocket connection."""
        try:
            # Only create a new client if we don't have one
            if not self._ws_client:
                if not self.devices:
                    _LOGGER.warning("No devices available, skipping WebSocket setup")
                    return

                _LOGGER.info("Setting up WebSocket connection for devices: %s", list(self.devices.keys()))
                self._ws_client = WebSocketClient(
                    auth_token=self.auth_token,
                    device_ids=list(self.devices.keys()),
                    data_callback=self._handle_ws_update,
                )
                await self._ws_client.start()
                _LOGGER.info("WebSocket connection established successfully")
        except Exception as error:
            _LOGGER.error("Failed to setup WebSocket connection: %s", error)
            self._ws_client = None
            raise

    def _handle_ws_update(self, update: dict[str, Any]) -> None:
        """Handle device updates from WebSocket."""
        try:
            for device_id, device_data in update.items():
                if device_id in self.devices:
                    # Initialize device_data if not exists
                    if device_id not in self.device_data:
                        _LOGGER.info("Initializing data structure for device %s", device_id)
                        self.device_data[device_id] = {
                            **self.devices[device_id],
                            ATTR_TEMPERATURE: None,
                            ATTR_TARGET_TEMPERATURE: None,
                            ATTR_FUNCTION: None,
                            ATTR_RELAY_STATE: None,
                            ATTR_ONLINE: False,
                            "is_heating": False,
                            "base_info": None,  # Initialize base_info as None
                        }
                    
                    # Check if this update contains base_info
                    if "base_info" in device_data:
                        _LOGGER.info("Received base_info for device %s: %s", device_id, device_data["base_info"])
                        self.devices_with_base_info[device_id] = device_data["base_info"]
                        # Update device data with base_info
                        self.device_data[device_id]["base_info"] = device_data["base_info"]
                        self.device_data[device_id]["available_sensor_ids"] = device_data["available_sensor_ids"]
                        self.device_data[device_id]["available_relay_ids"] = device_data["available_relay_ids"]
                        self.device_data[device_id]["sensors"] = device_data["sensors"]
                        self.device_data[device_id]["relays"] = device_data["relays"]
                    
                    # Preserve existing function if not provided in update
                    if device_data.get(ATTR_FUNCTION) is None and self.device_data[device_id].get(ATTR_FUNCTION) is not None:
                        existing_function = self.device_data[device_id][ATTR_FUNCTION]
                        self.device_data[device_id].update(device_data)
                        self.device_data[device_id][ATTR_FUNCTION] = existing_function
                    else:
                        self.device_data[device_id].update(device_data)

                    _LOGGER.info(
                        "Updated device %s - Online: %s, Temp: %s, Target: %s, Function: %s, Heating: %s",
                        device_id,
                        device_data.get(ATTR_ONLINE),
                        device_data.get(ATTR_TEMPERATURE),
                        device_data.get(ATTR_TARGET_TEMPERATURE),
                        device_data.get(ATTR_FUNCTION),
                        device_data.get("is_heating")
                    )
                    
                    # Notify HA of the update
                    self.async_set_updated_data(self.device_data)
            
        except Exception as error:
            _LOGGER.error("Error handling WebSocket update: %s", error)

    async def async_stop(self) -> None:
        """Stop the coordinator."""
        _LOGGER.info("Stopping coordinator...")
        if self._ws_client:
            await self._ws_client.stop()
            self._ws_client = None
        
        self.devices = {}
        self.device_data = {}
        self.auth_token = None
        _LOGGER.info("Coordinator stopped")
