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
                    API_SENSORS_ENDPOINT, API_WIFI_STATE_ENDPOINT, DOMAIN)
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
                    coordinator=self,
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

            # Handle synthetic base_info request
            if "synthesize_base_info_needed" in update:
                device_serial = update.get("device_serial")
                if device_serial:
                    _LOGGER.info(
                        "[%s] Synthesizing base_info from available data",
                        device_serial
                    )
                    self._synthesize_base_info(device_serial)
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

            # Notify HA of the update
            self.async_set_updated_data(self.device_data)

        except Exception as error:
            _LOGGER.error(
                "Error processing device update for %s: %s",
                serial,
                error)

    def _initialize_device_data(self, serial: str) -> None:
        """Initialize data structure for a device."""
        _LOGGER.info("[%s] Initializing data structure", serial)
        self.device_data[serial] = {
            **self.devices[serial],
            DA.TEMPERATURE: None,
            DA.TARGET_TEMPERATURE: None,
            DA.CURRENT_TEMPERATURE: None,
            DA.FUNCTION: None,
            DA.MODE: None,
            DA.RELAY_STATE: None,
            DA.ONLINE: False,
            DA.SENSOR_READINGS: {},
            DA.CONTROLLING_SRC: None,
            DA.CONTROLLING_SENSOR: None,
            "is_heating": False,
            "base_info": None,
        }

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

    def _process_base_info_update(
            self, serial: str, device_data: Dict[str, Any]) -> None:
        """Process base_info update for a device."""
        self.devices_with_base_info[serial] = device_data["base_info"]
        # Update with all data from device_data, including sensor_readings and current_temperature
        self.device_data[serial].update(device_data)

        # Fetch sensor metadata and WiFi state to populate all sensor information
        base_info = device_data.get("base_info", {})
        device_id = base_info.get("id")
        if device_id:
            asyncio.create_task(self._fetch_sensor_metadata(serial, device_id))
            asyncio.create_task(self._fetch_wifi_state(serial, device_id))

    async def _fetch_sensor_metadata(self, serial: str, device_id: int) -> None:
        """Fetch sensor metadata from API for a device."""
        try:
            _LOGGER.debug("[%s] Starting sensor metadata fetch (ID: %s)", serial, device_id)
            endpoint = API_SENSORS_ENDPOINT.format(device_id=device_id)
            url = f"{API_BASE_URL}{endpoint}"
            _LOGGER.debug("[%s] Sensor metadata API URL: %s", serial, url)

            async with self.session.get(
                url,
                headers={"Authorization": f"Bearer {self.auth_token}"},
            ) as resp:
                _LOGGER.debug("[%s] Sensor metadata API response status: %s", serial, resp.status)
                resp.raise_for_status()
                sensors_data = await resp.json()
                _LOGGER.debug("[%s] Sensor metadata API response data: %s", serial, sensors_data)

                # Check if device exists in device_data
                if serial not in self.device_data:
                    _LOGGER.error("[%s] Device not found in device_data! Cannot store sensor metadata.", serial)
                    return

                # Create a new device data dict to ensure change detection works
                updated_device_data = {**self.device_data[serial]}

                # Store the sensor metadata
                updated_device_data["sensor_metadata"] = sensors_data
                _LOGGER.debug("[%s] Sensor metadata stored: %d sensors found", serial, len(sensors_data))

                # Update sensor_readings with names from metadata if they exist
                if DA.SENSOR_READINGS in updated_device_data:
                    for sensor_meta in sensors_data:
                        # Build sensor key to match sensor_readings structure
                        src = sensor_meta.get("src", "").upper()
                        sensor_id = sensor_meta.get("id")
                        sensor_type = sensor_meta.get("type", "").upper()

                        # For ONBOARD sensors, use src_type as key
                        if src == "ONBOARD":
                            sensor_key = f"{src}_{sensor_type}"
                        elif sensor_id is not None:
                            sensor_key = f"{src}_{sensor_id}"
                        else:
                            sensor_num = sensor_meta.get("sensor", 1)
                            sensor_key = f"{src}_{sensor_num}"

                        # Update the name if this sensor exists in sensor_readings
                        if sensor_key in updated_device_data[DA.SENSOR_READINGS]:
                            name = sensor_meta.get("name", "").strip()
                            if name:
                                old_name = updated_device_data[DA.SENSOR_READINGS][sensor_key].get("name", "")
                                updated_device_data[DA.SENSOR_READINGS][sensor_key]["name"] = name
                                _LOGGER.debug("[%s] Updated sensor %s name from '%s' to '%s'",
                                              serial, sensor_key, old_name, name)

                # Update the device_data with the new dict
                self.device_data[serial] = updated_device_data

                # Notify HA of the update
                self.async_set_updated_data({**self.device_data})
                _LOGGER.debug("[%s] Sensor metadata update completed successfully", serial)

        except ClientResponseError as error:
            if error.status == 401:
                _LOGGER.warning(
                    "[%s] Authentication failed while fetching sensor metadata (status: %s)", serial, error.status)
            else:
                _LOGGER.error("[%s] API error fetching sensor metadata: status=%s, error=%s",
                              serial, error.status, error)
        except Exception as error:
            _LOGGER.error("[%s] Failed to fetch sensor metadata: %s", serial, error, exc_info=True)

    async def _fetch_wifi_state(self, serial: str, device_id: int) -> None:
        """Fetch WiFi state from API for a device."""
        try:
            _LOGGER.debug("[%s] Starting WiFi state fetch (ID: %s)", serial, device_id)
            endpoint = API_WIFI_STATE_ENDPOINT.format(device_id=device_id)
            url = f"{API_BASE_URL}{endpoint}"
            _LOGGER.debug("[%s] WiFi state API URL: %s", serial, url)

            async with self.session.get(
                url,
                headers={"Authorization": f"Bearer {self.auth_token}"},
            ) as resp:
                _LOGGER.debug("[%s] WiFi state API response status: %s", serial, resp.status)
                resp.raise_for_status()
                wifi_data = await resp.json()
                _LOGGER.debug("[%s] WiFi state API response data: %s", serial, wifi_data)

                # Check if device exists in device_data
                if serial not in self.device_data:
                    _LOGGER.error("[%s] Device not found in device_data! Cannot store WiFi info.", serial)
                    return

                # Extract system data from response (API returns it wrapped in 'system' key)
                system_data = wifi_data.get("system", {})
                _LOGGER.debug("[%s] Extracted system data: %s", serial, system_data)

                # Create a new device data dict to ensure change detection works
                _LOGGER.debug("[%s] Creating new device data dict", serial)
                updated_device_data = {**self.device_data[serial]}

                # Store the WiFi system info for sensors to access
                _LOGGER.debug("[%s] Storing WiFi info", serial)
                updated_device_data["wifi_info"] = system_data
                _LOGGER.debug("[%s] WiFi info stored: %s", serial, system_data)

                # Always update RSSI values from WiFi API (this is the authoritative source)
                if "rssi" in system_data:
                    _LOGGER.debug("[%s] Updating RSSI from WiFi data: %s (old: %s)", serial,
                                  system_data["rssi"], updated_device_data.get(DA.RSSI))
                    updated_device_data[DA.RSSI] = system_data["rssi"]

                if "rssi_level" in system_data:
                    _LOGGER.debug("[%s] Updating RSSI_LEVEL from WiFi data: %s (old: %s)", serial,
                                  system_data["rssi_level"], updated_device_data.get(DA.RSSI_LEVEL))
                    updated_device_data[DA.RSSI_LEVEL] = system_data["rssi_level"]

                # Update the device_data with the new dict
                self.device_data[serial] = updated_device_data

                # Notify HA of the update with a new top-level dict
                _LOGGER.debug("[%s] Notifying Home Assistant of WiFi data update", serial)
                self.async_set_updated_data({**self.device_data})
                _LOGGER.debug("[%s] WiFi state update completed successfully", serial)

        except ClientResponseError as error:
            if error.status == 401:
                _LOGGER.warning("[%s] Authentication failed while fetching WiFi state (status: %s)",
                                serial, error.status)
            else:
                _LOGGER.error("[%s] API error fetching WiFi state: status=%s, error=%s", serial, error.status, error)
        except Exception as error:
            _LOGGER.error("[%s] Failed to fetch WiFi state: %s", serial, error, exc_info=True)

    def _synthesize_base_info(self, serial: str) -> None:
        """Synthesize base_info from available device data when WebSocket doesn't provide it."""
        try:
            if serial not in self.devices:
                _LOGGER.error("[%s] Cannot synthesize base_info: device not found in devices dict", serial)
                return

            if serial not in self.device_data:
                self._initialize_device_data(serial)

            device_info = self.devices[serial]

            # Create a minimal base_info structure from devices dictionary
            synthetic_base_info = {
                "id": device_info.get(DA.DEVICE_ID),
                "serial_number": serial,
                "brand": device_info.get("brand"),
                "type": device_info.get("type"),
                "user_id": device_info.get("user_id"),
                "fw_ver": device_info.get(DA.FW_VERSION),
                "device_type": device_info.get(DA.DEVICE_TYPE),
                "name": f"{device_info.get(DA.DEVICE_TYPE, 'Thermostat')} {serial}",
                "timezone": "Europe/Budapest",  # Default timezone
                "group_color": None,
                "assigned_partner": None,
            }

            # Check if we already have some data from WebSocket updates
            current_data = self.device_data.get(serial, {})

            # Build synthetic device update with base_info
            device_update = {
                "base_info": synthetic_base_info,
                DA.ONLINE: current_data.get(DA.ONLINE, False),
                "available_sensor_ids": [],
                "available_relay_ids": ["1"],  # Assume at least one relay
                "sensors": {},
                "relays": {
                    "1": {
                        "relay": 1,
                        "type": "THERMOSTAT",
                        "mode": current_data.get(DA.MODE, "MANUAL"),
                        "function": current_data.get(DA.FUNCTION, "HEATING"),
                        "relay_state": current_data.get(DA.RELAY_STATE, False),
                    }
                },
            }

            # Copy over any existing sensor readings
            if DA.SENSOR_READINGS in current_data:
                device_update[DA.SENSOR_READINGS] = current_data[DA.SENSOR_READINGS]

            # Copy over temperature data if available
            if DA.TEMPERATURE in current_data:
                device_update[DA.TEMPERATURE] = current_data[DA.TEMPERATURE]
            if DA.CURRENT_TEMPERATURE in current_data:
                device_update[DA.CURRENT_TEMPERATURE] = current_data[DA.CURRENT_TEMPERATURE]
            if DA.TARGET_TEMPERATURE in current_data:
                device_update[DA.TARGET_TEMPERATURE] = current_data[DA.TARGET_TEMPERATURE]

            _LOGGER.warning(
                "[%s] Created synthetic base_info. Device may have limited functionality until real base_info is received.",
                serial)

            # Process the synthetic base_info as if it came from WebSocket
            self._process_base_info_update(serial, device_update)

            # Notify HA of the update
            self.async_set_updated_data(self.device_data)

        except Exception as error:
            _LOGGER.error(
                "[%s] Failed to synthesize base_info: %s",
                serial,
                error,
                exc_info=True
            )

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
