"""DataUpdateCoordinator for Computherm integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from aiohttp import ClientError, ClientResponseError, ClientSession
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (DataUpdateCoordinator,
                                                      UpdateFailed)

from .const import (API_BASE_URL, API_DEVICES_ENDPOINT, API_LOGIN_ENDPOINT,
                    DOMAIN)
from .const import DeviceAttributes as DA
from .websocket import WebSocketClient

_LOGGER = logging.getLogger(__package__)


class ComputhermError(Exception):
    """Base class for Computherm integration errors."""


class ComputhermConnectionError(ComputhermError):
    """Error occurred while communicating with the API."""


class ComputhermAuthError(ComputhermError):
    """Authentication error occurred."""


class ComputhermDataUpdateCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
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
        self.session: ClientSession = async_get_clientsession(hass)
        self.auth_token: Optional[str] = None
        self.devices: Dict[str, Dict[str, Any]] = {}
        self.device_data: Dict[str, Dict[str, Any]] = {}
        # Track devices that have received base_info
        self.devices_with_base_info: Dict[str, Dict[str, Any]] = {}
        self._ws_client: Optional[WebSocketClient] = None
        _LOGGER.info("Initialized ComputhermDataUpdateCoordinator")

    async def manual_reconnect(self) -> None:
        """Manually trigger a WebSocket reconnection."""
        if self._ws_client:
            await self._ws_client.manual_reconnect()

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from API endpoint."""
        try:
            if not self.auth_token:
                _LOGGER.info("No auth token, starting initial setup...")
                await self._authenticate()
                await self._fetch_devices()
                await self._setup_websocket()
                _LOGGER.info("Initial setup completed successfully")
            elif self._ws_client and not self._ws_client.websocket:
                # Only attempt reconnect if we have a client but lost
                # connection
                _LOGGER.info("WebSocket disconnected, attempting reconnect...")
                await self._ws_client.start()

            return self.device_data

        except asyncio.TimeoutError as error:
            _LOGGER.error("Timeout communicating with API")
            raise ComputhermConnectionError("Connection timed out") from error
        except ClientResponseError as error:
            if error.status == 401:
                _LOGGER.error("Authentication token expired or invalid")
                self.auth_token = None  # Clear token to force re-authentication
                raise ConfigEntryAuthFailed("Authentication failed") from error
            _LOGGER.error("API error: %s", error)
            raise ComputhermConnectionError(
                f"API error: {error.status}") from error
        except ClientError as error:
            _LOGGER.error("Network error: %s", error)
            raise ComputhermConnectionError(
                "Network connection failed") from error
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
                    raise ComputhermAuthError("Invalid credentials")
                resp.raise_for_status()
                result = await resp.json()
                self.auth_token = result.get(
                    "token") or result.get("access_token")
                if not self.auth_token:
                    raise ComputhermAuthError(
                        "No authentication token received")
                _LOGGER.info("Authentication successful")
        except ClientResponseError as error:
            if error.status == 401:
                raise ConfigEntryAuthFailed("Invalid credentials") from error
            raise ComputhermConnectionError(
                f"Authentication failed with status {error.status}") from error
        except ClientError as error:
            raise ComputhermConnectionError(
                f"Network error during authentication: {error}") from error
        except Exception as error:
            raise ComputhermError(
                f"Unexpected error during authentication: {error}") from error

    async def _fetch_devices(self) -> None:
        """Fetch list of devices for the user."""
        try:
            _LOGGER.info("Fetching devices...")
            async with self.session.get(
                f"{API_BASE_URL}{API_DEVICES_ENDPOINT}",
                headers={"Authorization": f"Bearer {self.auth_token}"},
            ) as resp:
                if resp.status == 401:
                    raise ComputhermAuthError("Invalid authentication")
                resp.raise_for_status()
                devices = await resp.json()

                await self._process_devices_response(devices)

        except ClientResponseError as error:
            if error.status == 401:
                raise ConfigEntryAuthFailed(
                    "Invalid authentication") from error
            raise ComputhermConnectionError(
                f"Failed to fetch devices with status {error.status}") from error
        except ClientError as error:
            raise ComputhermConnectionError(
                f"Network error fetching devices: {error}") from error
        except Exception as error:
            raise ComputhermError(
                f"Unexpected error fetching devices: {error}") from error

    async def _process_devices_response(
            self, devices: List[Dict[str, Any]]) -> None:
        """Process the devices response data."""
        self.devices = {}
        for device in devices:
            serial = device.get(DA.SERIAL_NUMBER)
            if serial:
                self.devices[serial] = {
                    DA.DEVICE_ID: device.get("id"),
                    DA.SERIAL_NUMBER: serial,
                    "brand": device.get("brand"),
                    "type": device.get("type"),
                    "user_id": device.get("user_id"),
                    DA.FW_VERSION: device.get(DA.FW_VERSION),
                    DA.DEVICE_IP: device.get(DA.DEVICE_IP),
                    DA.DEVICE_TYPE: device.get(DA.DEVICE_TYPE, ""),
                    DA.ACCESS_STATUS: device.get(DA.ACCESS_STATUS),
                    "access_rules": device.get("access_rules", {})
                }
                _LOGGER.info(
                    "Found device: %s with data: %s",
                    serial,
                    self.devices[serial])
            else:
                _LOGGER.warning(
                    "Device without serial number found: %s", device)

        if not self.devices:
            _LOGGER.warning("No devices found for user")
            await self.async_stop()
            self.device_data = {}  # Clear any existing device data
        else:
            _LOGGER.info(
                "Successfully fetched %d devices: %s", len(
                    self.devices), list(
                    self.devices.keys()))

    async def _setup_websocket(self) -> None:
        """Set up WebSocket connection."""
        try:
            # Only create a new client if we don't have one
            if not self._ws_client:
                if not self.devices:
                    _LOGGER.warning(
                        "No devices available, skipping WebSocket setup")
                    return

                _LOGGER.info(
                    "Setting up WebSocket connection for devices: %s", list(
                        self.devices.keys()))
                self._ws_client = WebSocketClient(
                    auth_token=self.auth_token,
                    device_serials=list(self.devices.keys()),
                    data_callback=self._handle_ws_update,
                )
                await self._ws_client.start()
                _LOGGER.info("WebSocket connection established successfully")
        except Exception as error:
            _LOGGER.error("Failed to setup WebSocket connection: %s", error)
            self._ws_client = None
            raise ComputhermConnectionError(
                f"WebSocket setup failed: {error}") from error

    def _handle_ws_update(self, update: Dict[str, Any]) -> None:
        """Handle device updates from WebSocket."""
        try:
            # Handle token refresh request
            if "token_refresh_needed" in update:
                _LOGGER.info("Token refresh requested by WebSocket client")
                asyncio.create_task(self._handle_token_refresh())
                return

            # Handle device updates
            for serial, device_data in update.items():
                if serial in self.devices:
                    self._process_device_update(serial, device_data)

        except Exception as error:
            _LOGGER.error("Error handling WebSocket update: %s", error)

    async def _handle_token_refresh(self) -> None:
        """Handle token refresh and WebSocket reconnection."""
        try:
            _LOGGER.info("Refreshing auth token...")
            
            # Set token refresh in progress flag
            if self._ws_client:
                self._ws_client.set_token_refresh_in_progress(True)
                await self._ws_client.stop()
                self._ws_client = None

            # Get new token
            await self._authenticate()
            
            # Restart WebSocket with new token
            await self._setup_websocket()
            
            # Reset token refresh flag on the new client
            if self._ws_client:
                self._ws_client.set_token_refresh_in_progress(False)
                
            _LOGGER.info("Token refresh and WebSocket reconnection completed")
        except Exception as error:
            _LOGGER.error("Failed to refresh token: %s", error)
            # Make sure to reset the flag even on error
            if self._ws_client:
                self._ws_client.set_token_refresh_in_progress(False)
            raise

    def _process_device_update(
            self, serial: str, device_data: Dict[str, Any]) -> None:
        """Process update data for a single device."""
        try:
            # Initialize device_data if not exists
            if serial not in self.device_data:
                self._initialize_device_data(serial)

            # Handle base_info updates
            if "base_info" in device_data:
                self._process_base_info_update(serial, device_data)

            # Handle state updates
            self._process_state_update(serial, device_data)

            # _LOGGER.debug(
            #     "Updated device serial %s id: %s - Online: %s, Temp: %s, Target: %s, Function: %s, Heating: %s",
            #     serial,
            #     self.device_data[serial][DA.DEVICE_ID],
            #     device_data.get(DA.ONLINE),
            #     device_data.get(DA.TEMPERATURE),
            #     device_data.get(DA.TARGET_TEMPERATURE),
            #     device_data.get(DA.FUNCTION),
            #     device_data.get("is_heating")
            # )

            # Notify HA of the update
            self.async_set_updated_data(self.device_data)

        except Exception as error:
            _LOGGER.error(
                "Error processing device update for %s: %s",
                serial,
                error)

    def _initialize_device_data(self, serial: str) -> None:
        """Initialize data structure for a device."""
        _LOGGER.info("Initializing data structure for device %s", serial)
        self.device_data[serial] = {
            **self.devices[serial],
            DA.TEMPERATURE: None,
            DA.TARGET_TEMPERATURE: None,
            DA.FUNCTION: None,
            DA.MODE: None,
            DA.RELAY_STATE: None,
            DA.ONLINE: False,
            "is_heating": False,
            "base_info": None,
        }

    def _process_base_info_update(
            self, serial: str, device_data: Dict[str, Any]) -> None:
        """Process base_info update for a device."""
        # _LOGGER.debug(
        #     "Received base_info for device %s",
        #     serial)
        self.devices_with_base_info[serial] = device_data["base_info"]
        self.device_data[serial].update({
            "base_info": device_data["base_info"],
            "available_sensor_ids": device_data["available_sensor_ids"],
            "available_relay_ids": device_data["available_relay_ids"],
            "sensors": device_data["sensors"],
            "relays": device_data["relays"],
        })

    def _process_state_update(
            self, serial: str, device_data: Dict[str, Any]) -> None:
        """Process state update for a device."""
        # Preserve existing function and mode if not provided in update
        if device_data.get(
                DA.FUNCTION) is None and self.device_data[serial].get(
                DA.FUNCTION) is not None:
            existing_function = self.device_data[serial][DA.FUNCTION]
            self.device_data[serial].update(device_data)
            self.device_data[serial][DA.FUNCTION] = existing_function
        elif device_data.get(DA.MODE) is None and self.device_data[serial].get(DA.MODE) is not None:
            existing_mode = self.device_data[serial][DA.MODE]
            self.device_data[serial].update(device_data)
            self.device_data[serial][DA.MODE] = existing_mode
        else:
            self.device_data[serial].update(device_data)

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
