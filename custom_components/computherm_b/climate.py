"""Climate platform for Computherm integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    HVACAction,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
)

from .const import (
    DOMAIN,
    COORDINATOR,
    API_BASE_URL,
    API_DEVICE_CONTROL_ENDPOINT,
    ATTR_DEVICE_TYPE,
    ATTR_FW_VERSION,
    ATTR_RELAY_STATE,
    ATTR_TEMPERATURE,
    ATTR_TARGET_TEMPERATURE,
    ATTR_FUNCTION,
    ATTR_ONLINE,
    ATTR_HUMIDITY,
    ATTR_DEVICE_ID,
    ATTR_MODE,
)
from .coordinator import ComputhermDataUpdateCoordinator

_LOGGER = logging.getLogger(__package__)

SUPPORT_FLAGS = (
    ClimateEntityFeature.TARGET_TEMPERATURE |
    ClimateEntityFeature.TURN_OFF |
    ClimateEntityFeature.TURN_ON
)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Computherm climate platform."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][COORDINATOR]
    
    _LOGGER.info("Setting up Computherm climate platform")
    
    # Wait for devices to be fetched
    await coordinator.async_config_entry_first_refresh()

    existing_entities = set()  # Track entities we've already added
    
    @callback
    def _async_add_entities_for_device(device_id: str) -> None:
        """Create and add entities for a device that has received base_info."""
        if device_id in existing_entities:            
            return
            
        if device_id not in coordinator.devices_with_base_info:
            _LOGGER.debug("Device %s has no base_info yet", device_id)
            return
            
        if not coordinator.devices_with_base_info[device_id]:
            _LOGGER.debug("Device %s has empty base_info", device_id)
            return
            
        _LOGGER.info("Creating climate entity for device %s", device_id)
        entity = ComputhermThermostat(hass, coordinator, device_id)
        async_add_entities([entity], True)
        existing_entities.add(device_id)
        _LOGGER.info("Climate entity created for device %s", device_id)
    
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
    _LOGGER.info("Climate platform setup completed")

class ComputhermThermostat(CoordinatorEntity, ClimateEntity):
    """Representation of a Computherm Thermostat."""

    _attr_has_entity_name = True
    _attr_translation_key = DOMAIN
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermostat"
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF]
    _attr_supported_features = SUPPORT_FLAGS
    _attr_target_temperature_step = 0.1

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: ComputhermDataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the thermostat."""
        super().__init__(coordinator)
        self.serial_number = serial
        # Get the API ID from devices dictionary
        self.api_device_id = coordinator.devices[serial].get(ATTR_DEVICE_ID)
        if not self.api_device_id:
            _LOGGER.error("No API device ID found for serial number %s", serial)
        
        # Get min/max temperature from relays config if available
        relays = coordinator.device_data[self.serial_number].get("relays", {})
        first_relay = next(iter(relays.values()), {})
        configs = first_relay.get("configs", {})
        self._attr_min_temp = configs.get("setpoint_min", 5)
        self._attr_max_temp = configs.get("setpoint_max", 30)

        
        # Set unique ID and device info
        entity_name = coordinator.device_data[self.serial_number].get("base_info", {}).get("name", "thermostat")
        self._attr_unique_id = f"{DOMAIN}_{self.serial_number}_{entity_name}"
        self._attr_name = entity_name

        # Log entity ID and attributes
        _LOGGER.info(
            "Initializing climate entity - ID: %s, Device ID: %s",
            self._attr_unique_id,
            self.serial_number
        )
        
        device_info = {
            "identifiers": {(DOMAIN, serial)},
            "serial_number": serial,
            "name": f"Computherm {serial}",
            "manufacturer": "Computherm",
            "model": self.coordinator.devices[self.serial_number].get(ATTR_DEVICE_TYPE, "") or "B Series Thermostat",
            "sw_version": self.coordinator.devices[self.serial_number].get(ATTR_FW_VERSION),
            "hw_version": self.coordinator.devices[self.serial_number].get("type"),            
        }
        
        # Log device info
        _LOGGER.info(
            "Climate entity - Device serial: %s, name: %s, Info: %s",
            serial,
            self._attr_name,
            device_info
        )
        
        self._attr_device_info = device_info

    @property
    def device_data(self) -> dict:
        """Get the current device data."""
        return self.coordinator.device_data.get(self.serial_number, {})

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        if self.device_data.get(ATTR_TEMPERATURE) is not None:
            return float(self.device_data[ATTR_TEMPERATURE])
        return None

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        if self.device_data.get(ATTR_TARGET_TEMPERATURE) is not None:
            return float(self.device_data[ATTR_TARGET_TEMPERATURE])
        return None

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the current operation mode."""
        if not self.device_data.get(ATTR_ONLINE, False) or "off" == self.device_data.get(ATTR_MODE):
            return HVACMode.OFF        
        function = self.device_data.get(ATTR_FUNCTION)
        if function == "cooling":
            return HVACMode.COOL
        return HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current running hvac operation."""
        if not self.device_data.get(ATTR_ONLINE, False):
            _LOGGER.debug("Device %s is offline, setting action to OFF", self.serial_number)
            return HVACAction.OFF
        if self.hvac_mode == HVACMode.OFF:
            _LOGGER.debug("Device %s mode is OFF, setting action to OFF", self.serial_number)
            return HVACAction.OFF
        function = self.device_data.get(ATTR_FUNCTION)
        relay_state = self.device_data.get(ATTR_RELAY_STATE, False)
        
        _LOGGER.debug(
            "Device %s - Function: %s, Relay State: %s, HVAC Mode: %s",
            self.serial_number,
            function,
            relay_state,
            self.hvac_mode
        )
        
        if function == "cooling":
            action = HVACAction.COOLING if relay_state else HVACAction.IDLE
            _LOGGER.debug("Device %s - Cooling Action: %s", self.serial_number, action)
            return action
        else:
            action = HVACAction.HEATING if relay_state else HVACAction.IDLE
            _LOGGER.debug("Device %s - Heating Action: %s", self.serial_number, action)
            return action

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.device_data.get(ATTR_ONLINE, False)

    @property
    def current_humidity(self) -> int | None:
        """Return the current humidity."""
        if self.device_data.get(ATTR_HUMIDITY) is not None:
            return round(float(self.device_data[ATTR_HUMIDITY]))
        return None

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        try:
            _LOGGER.info(
                "Setting temperature to %.1f°C for device %s (API ID: %s)",
                temperature,
                self.serial_number,
                self.api_device_id
            )
            request_data = {
                "relay": 1,
                "manual_set_point": round(float(temperature), 1),
            }
            _LOGGER.info(
                "Sending temperature change request for device %s (API ID: %s): %s",
                self.serial_number,
                self.api_device_id,
                request_data
            )
            async with self.coordinator.session.post(
                f"{API_BASE_URL}{API_DEVICE_CONTROL_ENDPOINT.format(device_id=self.api_device_id)}",
                headers={"Authorization": f"Bearer {self.coordinator.auth_token}"},
                json=request_data,
            ) as response:
                response_data = await response.json()
                _LOGGER.info(
                    "Temperature change response for device %s (API ID: %s): %s",
                    self.serial_number,
                    self.api_device_id,
                    response_data
                )
                response.raise_for_status()
                _LOGGER.info(
                    "Successfully set temperature to %.1f°C for device %s (API ID: %s)",
                    temperature,
                    self.serial_number,
                    self.api_device_id
                )
                await self.coordinator.async_request_refresh()

        except Exception as error:
            _LOGGER.error(
                "Failed to set temperature for device %s (API ID: %s): %s",
                self.serial_number,
                self.api_device_id,
                error
            )
            raise

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new operation mode."""

        operation = None
        mode = None
        if hvac_mode == HVACMode.OFF:
            operation = "mode"
            mode = "OFF"
        
        if hvac_mode == HVACMode.HEAT:
            operation = "function"
            mode = "HEATING"

        if hvac_mode == HVACMode.COOL:
            operation = "function"
            mode = "COOLING"      
        
        try:
            _LOGGER.info(
                "Setting operation mode to %s for device %s (API ID: %s)",
                mode,
                self.serial_number,
                self.api_device_id
            )
            request_data = {
                "relay": 1,
                operation: mode
            }

            if "off" == self.device_data.get(ATTR_MODE):
                request_data["mode"] = "MANUAL"

            _LOGGER.info(
                "Sending HVAC mode change request for device %s (API ID: %s): %s",
                self.serial_number,
                self.api_device_id,
                request_data
            )
            async with self.coordinator.session.post(
                f"{API_BASE_URL}{API_DEVICE_CONTROL_ENDPOINT.format(device_id=self.api_device_id)}",
                headers={"Authorization": f"Bearer {self.coordinator.auth_token}"},
                json=request_data,
            ) as response:
                response_data = await response.json()
                _LOGGER.info(
                    "HVAC mode change response for device %s (API ID: %s): %s",
                    self.serial_number,
                    self.api_device_id,
                    response_data
                )
                response.raise_for_status()
                _LOGGER.info(
                    "Successfully set operation mode to %s for device %s (API ID: %s)",
                    mode,
                    self.serial_number,
                    self.api_device_id
                )
                await self.coordinator.async_request_refresh()

        except Exception as error:
            _LOGGER.error(
                "Failed to set operation mode for device %s (API ID: %s): %s",
                self.serial_number,
                self.api_device_id,
                error
            )
            raise
