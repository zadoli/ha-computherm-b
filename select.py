"""Select platform for Computherm integration."""
from __future__ import annotations

import logging
import aiohttp

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    COORDINATOR,
    ATTR_MODE,
    ATTR_FUNCTION,
    ATTR_DEVICE_TYPE,
    ATTR_FW_VERSION,
    ATTR_DEVICE_ID,
    MODE_SCHEDULE,
    MODE_MANUAL,
    AVAILABLE_MODES,
    FUNCTION_HEATING,
    FUNCTION_COOLING,
    AVAILABLE_FUNCTIONS,
)
from .coordinator import ComputhermDataUpdateCoordinator

_LOGGER = logging.getLogger(__package__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Computherm mode select."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][COORDINATOR]
    
    _LOGGER.info("Setting up Computherm select platform")
    
    # Wait for devices to be fetched
    await coordinator.async_config_entry_first_refresh()
    
    existing_mode_entities = set()
    existing_function_entities = set()
    
    @callback
    def _async_add_entities_for_device(device_id: str) -> None:
        """Create and add entities for a device that has received base_info."""
        if device_id not in coordinator.devices_with_base_info:
            _LOGGER.debug("Device %s has no base_info yet", device_id)
            return
            
        if not coordinator.devices_with_base_info[device_id]:
            _LOGGER.debug("Device %s has empty base_info", device_id)
            return

        entities_to_add = []
            
        # Add mode select if not already added
        if device_id not in existing_mode_entities:
            _LOGGER.info("Creating mode select entity for device %s", device_id)
            mode_entity = ComputhermModeSelect(coordinator, device_id)
            entities_to_add.append(mode_entity)
            existing_mode_entities.add(device_id)

        # Add function select if not already added
        if device_id not in existing_function_entities:
            _LOGGER.info("Creating function select entity for device %s", device_id)
            function_entity = ComputhermFunctionSelect(coordinator, device_id)
            entities_to_add.append(function_entity)
            existing_function_entities.add(device_id)
            
        if entities_to_add:
            async_add_entities(entities_to_add, True)
            _LOGGER.info("Select entities created for device %s", device_id)
    
    # Add entities for devices that already have base_info
    for serial in coordinator.devices:
        _LOGGER.debug("Checking device %s for base_info", serial)
        if serial in coordinator.devices_with_base_info and coordinator.devices_with_base_info[serial]:
            _LOGGER.info("Found existing base_info for device %s", serial)
            _async_add_entities_for_device(serial)
    
    @callback
    def async_handle_coordinator_update() -> None:
        """Handle updated data from the coordinator."""
        for device_id in coordinator.devices:
            if device_id in coordinator.devices_with_base_info and coordinator.devices_with_base_info[device_id]:
                _async_add_entities_for_device(device_id)
    
    # Register listener
    config_entry.async_on_unload(
        coordinator.async_add_listener(async_handle_coordinator_update)
    )
    _LOGGER.info("Select platform setup completed")


class ComputhermModeSelect(CoordinatorEntity, SelectEntity):
    """Representation of a Computherm Mode Select."""

    _attr_has_entity_name = True
    _attr_translation_key = "mode"
    _attr_options = AVAILABLE_MODES

    def __init__(
        self,
        coordinator: ComputhermDataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the mode select."""
        super().__init__(coordinator)
        self.serial_number = serial
        # Get the API ID from devices dictionary
        self.api_device_id = coordinator.devices[serial].get(ATTR_DEVICE_ID)
        if not self.api_device_id:
            _LOGGER.error("No API device ID found for serial number %s", serial)
        
        device_info = {
            "identifiers": {(DOMAIN, serial)},
            "serial_number": serial,
            "name": f"Computherm {serial}",
            "manufacturer": "Computherm",
            "model": coordinator.devices[serial].get(ATTR_DEVICE_TYPE, "") or "B Series Thermostat",
            "sw_version": coordinator.devices[serial].get(ATTR_FW_VERSION),
            "hw_version": coordinator.devices[serial].get("type"),
        }
        self._attr_device_info = device_info
        self._attr_unique_id = f"{DOMAIN}_{serial}_mode"

    @property
    def device_data(self) -> dict:
        """Get the current device data."""
        return self.coordinator.device_data.get(self.serial_number, {})

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.device_data.get("online", False)

    @property
    def current_option(self) -> str | None:
        """Return the current mode."""
        return self.device_data.get(ATTR_MODE)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""        
        if not self.api_device_id:
            _LOGGER.error("Cannot change mode: No API device ID available for serial number %s", self.serial_number)
            return

        url = f"https://api.computhermbseries.com/api/devices/{self.api_device_id}/cmd"
        payload = {
            "relay": 1,
            "mode": f"{option}"
        }

        headers = {
            "Authorization": f"Bearer {self.coordinator.auth_token}"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as response:
                    response_text = await response.text()
                    
                    if 200 <= response.status < 300:  # Any 2xx status code is success
                        _LOGGER.info("Successfully changed mode to %s for device %s (API ID: %s)", 
                                   option, self.serial_number, self.api_device_id)
                        await self.coordinator.async_request_refresh()
                    else:
                        _LOGGER.error(
                            "Failed to change mode for device %s (API ID: %s). Status: %s, Response: %s",
                            self.serial_number,
                            self.api_device_id,
                            response.status,
                            response_text
                        )
        except Exception as e:
            _LOGGER.error("Error changing mode for device %s (API ID: %s): %s", 
                         self.serial_number, self.api_device_id, str(e))


class ComputhermFunctionSelect(CoordinatorEntity, SelectEntity):
    """Representation of a Computherm Function Select."""

    _attr_has_entity_name = True
    _attr_translation_key = "function"
    _attr_options = AVAILABLE_FUNCTIONS

    def __init__(
        self,
        coordinator: ComputhermDataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the function select."""
        super().__init__(coordinator)
        self.serial_number = serial
        # Get the API ID from devices dictionary
        self.api_device_id = coordinator.devices[serial].get(ATTR_DEVICE_ID)
        if not self.api_device_id:
            _LOGGER.error("No API device ID found for serial number %s", serial)
        
        device_info = {
            "identifiers": {(DOMAIN, serial)},
            "serial_number": serial,
            "name": f"Computherm {serial}",
            "manufacturer": "Computherm",
            "model": coordinator.devices[serial].get(ATTR_DEVICE_TYPE, "") or "B Series Thermostat",
            "sw_version": coordinator.devices[serial].get(ATTR_FW_VERSION),
            "hw_version": coordinator.devices[serial].get("type"),
        }
        self._attr_device_info = device_info
        self._attr_unique_id = f"{DOMAIN}_{serial}_function"

    @property
    def device_data(self) -> dict:
        """Get the current device data."""
        return self.coordinator.device_data.get(self.serial_number, {})

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.device_data.get("online", False)

    @property
    def current_option(self) -> str | None:
        """Return the current function."""
        return self.device_data.get(ATTR_FUNCTION)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""        
        if not self.api_device_id:
            _LOGGER.error("Cannot change function: No API device ID available for serial number %s", self.serial_number)
            return

        url = f"https://api.computhermbseries.com/api/devices/{self.api_device_id}/cmd"
        payload = {
            "relay": 1,
            "function": f"{option}"
        }

        headers = {
            "Authorization": f"Bearer {self.coordinator.auth_token}"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as response:
                    response_text = await response.text()
                    
                    if 200 <= response.status < 300:  # Any 2xx status code is success
                        _LOGGER.info("Successfully changed function to %s for device %s (API ID: %s)", 
                                   option, self.serial_number, self.api_device_id)
                        await self.coordinator.async_request_refresh()
                    else:
                        _LOGGER.error(
                            "Failed to change function for device %s (API ID: %s). Status: %s, Response: %s",
                            self.serial_number,
                            self.api_device_id,
                            response.status,
                            response_text
                        )
        except Exception as e:
            _LOGGER.error("Error changing function for device %s (API ID: %s): %s", 
                         self.serial_number, self.api_device_id, str(e))
