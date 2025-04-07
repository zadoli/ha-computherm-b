"""Select platform for Computherm integration."""
from __future__ import annotations

import logging
from typing import Any, Final

import aiohttp
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (API_BASE_URL, API_DEVICE_CONTROL_ENDPOINT,
                    AVAILABLE_FUNCTIONS, AVAILABLE_MODES, COORDINATOR, DOMAIN)
from .const import DeviceAttributes as DA
from .coordinator import ComputhermDataUpdateCoordinator

_LOGGER = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Computherm mode select."""
    coordinator: ComputhermDataUpdateCoordinator = hass.data[
        DOMAIN][config_entry.entry_id][COORDINATOR]

    _LOGGER.info("Setting up Computherm select platform")

    # Wait for devices to be fetched
    await coordinator.async_config_entry_first_refresh()

    existing_mode_entities = set()
    existing_function_entities = set()

    @callback
    def _async_add_entities_for_device(device_id: str) -> None:
        """Create and add entities for a device that has received base_info."""
        if not _is_device_ready(coordinator, device_id):
            return

        entities_to_add = []

        # Add mode select if not already added
        if device_id not in existing_mode_entities:
            _LOGGER.info(
                "Creating mode select entity for device %s",
                device_id)
            mode_entity = ComputhermModeSelect(coordinator, device_id)
            entities_to_add.append(mode_entity)
            existing_mode_entities.add(device_id)

        # Add function select if not already added
        if device_id not in existing_function_entities:
            _LOGGER.info(
                "Creating function select entity for device %s",
                device_id)
            function_entity = ComputhermFunctionSelect(coordinator, device_id)
            entities_to_add.append(function_entity)
            existing_function_entities.add(device_id)

        if entities_to_add:
            async_add_entities(entities_to_add, True)
            _LOGGER.info("Select entities created for device %s", device_id)

    # Add entities for devices that already have base_info
    for serial in coordinator.devices:
        if _is_device_ready(coordinator, serial):
            _LOGGER.info("Found existing base_info for device %s", serial)
            _async_add_entities_for_device(serial)

    # Register listener for coordinator updates
    config_entry.async_on_unload(
        coordinator.async_add_listener(
            lambda: async_handle_coordinator_update(
                coordinator,
                _async_add_entities_for_device)))
    _LOGGER.info("Select platform setup completed")


def _is_device_ready(
        coordinator: ComputhermDataUpdateCoordinator,
        device_id: str) -> bool:
    """Check if device is ready for entity creation."""
    if device_id not in coordinator.devices_with_base_info:
        _LOGGER.debug("Device %s has no base_info yet", device_id)
        return False

    if not coordinator.devices_with_base_info[device_id]:
        _LOGGER.debug("Device %s has empty base_info", device_id)
        return False

    return True


@callback
def async_handle_coordinator_update(
    coordinator: ComputhermDataUpdateCoordinator,
    add_entities_callback: callable,
) -> None:
    """Handle updated data from the coordinator."""
    for device_id in coordinator.devices:
        if device_id in coordinator.devices_with_base_info and coordinator.devices_with_base_info[
                device_id]:
            add_entities_callback(device_id)


class ComputhermSelectBase(CoordinatorEntity, SelectEntity):
    """Base class for Computherm select entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ComputhermDataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self.serial_number = serial
        self._setup_device()

    def _setup_device(self) -> None:
        """Set up device information."""
        # Get the API ID from devices dictionary
        self.api_device_id = self.coordinator.devices[self.serial_number].get(
            DA.DEVICE_ID)
        if not self.api_device_id:
            raise HomeAssistantError(
                f"No API device ID found for serial number {self.serial_number}")

        self._setup_device_info()

    def _setup_device_info(self) -> None:
        """Set up device info dictionary."""
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self.serial_number)},
            "serial_number": self.serial_number,
            "name": f"Computherm {self.serial_number}",
            "manufacturer": "Computherm",
            "model": self.coordinator.devices[self.serial_number].get(DA.DEVICE_TYPE, "") or "B Series Thermostat",
            "sw_version": self.coordinator.devices[self.serial_number].get(DA.FW_VERSION),
            "hw_version": self.coordinator.devices[self.serial_number].get("type"),
        }

    @property
    def device_data(self) -> dict[str, Any]:
        """Get the current device data."""
        return self.coordinator.device_data.get(self.serial_number, {})

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.device_data.get(DA.ONLINE, False)

    async def _send_command(self, command_data: dict[str, Any]) -> None:
        """Send command to device."""
        if not self.api_device_id:
            raise HomeAssistantError(
                f"Cannot send command: No API device ID available for serial number {self.serial_number}")

        url = f"{API_BASE_URL}{API_DEVICE_CONTROL_ENDPOINT.format(device_id=self.api_device_id)}"
        headers = {"Authorization": f"Bearer {self.coordinator.auth_token}"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=command_data, headers=headers) as response:
                    response_text = await response.text()

                    if 200 <= response.status < 300:
                        _LOGGER.info(
                            "Successfully sent command %s for device %s",
                            command_data,
                            self.serial_number
                        )
                        await self.coordinator.async_request_refresh()
                    else:
                        raise HomeAssistantError(
                            f"Failed to send command. Status: {response.status}, Response: {response_text}"
                        )
        except Exception as error:
            raise HomeAssistantError(
                f"Error sending command: {error}") from error


class ComputhermModeSelect(ComputhermSelectBase):
    """Representation of a Computherm Mode Select."""

    _attr_translation_key = "mode"
    _attr_options: Final = AVAILABLE_MODES

    def __init__(
        self,
        coordinator: ComputhermDataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the mode select."""
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{DOMAIN}_{serial}_mode"

    @property
    def current_option(self) -> str | None:
        """Return the current mode."""
        return self.device_data.get(DA.MODE)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        await self._send_command({
            "relay": 1,
            "mode": option.upper()
        })


class ComputhermFunctionSelect(ComputhermSelectBase):
    """Representation of a Computherm Function Select."""

    _attr_translation_key = "function"
    _attr_options: Final = AVAILABLE_FUNCTIONS

    def __init__(
        self,
        coordinator: ComputhermDataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the function select."""
        super().__init__(coordinator, serial)
        self._attr_unique_id = f"{DOMAIN}_{serial}_function"

    @property
    def current_option(self) -> str | None:
        """Return the current function."""
        return self.device_data.get(DA.FUNCTION)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        await self._send_command({
            "relay": 1,
            "function": option.upper()
        })
