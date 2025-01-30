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
    ATTR_DEVICE_IP,
    ATTR_TEMPERATURE,
    ATTR_TARGET_TEMPERATURE,
    ATTR_OPERATION_MODE,
    ATTR_ONLINE,
    ATTR_HUMIDITY,
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
    
    entities = []
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
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = SUPPORT_FLAGS
    _attr_min_temp = 5
    _attr_max_temp = 30
    _attr_target_temperature_step = 0.5

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: ComputhermDataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the thermostat."""
        super().__init__(coordinator)
        self.device_id = serial
        
        # Set unique ID and device info
        device_name = coordinator.devices_with_base_info[serial].get("name", "thermostat")
        self._attr_unique_id = f"{DOMAIN}_{serial}_{device_name}"
        self._attr_name = device_name

        # Log entity ID and attributes
        _LOGGER.info(
            "Initializing climate entity - ID: %s, Device ID: %s",
            self._attr_unique_id,
            self.device_id
        )
        
        device_info = {
            "identifiers": {(DOMAIN, serial)},
            "serial_number": serial,
            "name": f"Computherm {serial}",
            "manufacturer": "Computherm",
            "model": self.coordinator.devices[self.device_id].get(ATTR_DEVICE_TYPE, "") or "B Series Thermostat",
            "sw_version": self.coordinator.devices[self.device_id].get(ATTR_FW_VERSION),
            "hw_version": self.coordinator.devices[self.device_id].get("type"),            
        }
        
        # Log device info
        _LOGGER.info(
            "Climate entity device info - Device serial: %s, name: %s, Info: %s",
            serial,
            self._attr_name,
            device_info
        )
        
        self._attr_device_info = device_info

    @property
    def device_data(self) -> dict:
        """Get the current device data."""
        return self.coordinator.device_data.get(self.device_id, {})

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        if self.device_data.get(ATTR_TEMPERATURE) is not None:
            return float(self.device_data[ATTR_TEMPERATURE])
        return None

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        temp = self.device_data.get(ATTR_TARGET_TEMPERATURE)
        if temp is not None:
            _LOGGER.debug("Device %s target temperature: %.1f°C", self.device_id, temp)
            return float(temp)
        return None

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the current operation mode."""
        if not self.device_data.get(ATTR_ONLINE, False):
            return HVACMode.OFF
        operation_mode = self.device_data.get(ATTR_OPERATION_MODE)
        if operation_mode == "off":
            return HVACMode.OFF
        return HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current running hvac operation."""
        if not self.device_data.get(ATTR_ONLINE, False):
            _LOGGER.debug("Device %s is offline, setting action to OFF", self.device_id)
            return HVACAction.OFF
        if self.hvac_mode == HVACMode.OFF:
            _LOGGER.debug("Device %s mode is OFF, setting action to OFF", self.device_id)
            return HVACAction.OFF
        is_heating = self.device_data.get("is_heating", False)
        action = HVACAction.HEATING if is_heating else HVACAction.IDLE
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
                "Setting temperature to %.1f°C for device %s",
                temperature,
                self.device_id
            )
            async with self.coordinator.session.post(
                f"{API_BASE_URL}{API_DEVICE_CONTROL_ENDPOINT.format(serial_number=self.device_id)}",
                headers={"Authorization": f"Bearer {self.coordinator.auth_token}"},
                json={"target_temperature": temperature},
            ) as response:
                response.raise_for_status()
                _LOGGER.info(
                    "Successfully set temperature to %.1f°C for device %s",
                    temperature,
                    self.device_id
                )
                await self.coordinator.async_request_refresh()

        except Exception as error:
            _LOGGER.error(
                "Failed to set temperature for device %s: %s",
                self.device_id,
                error
            )
            raise

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new operation mode."""
        operation_mode = "heat" if hvac_mode == HVACMode.HEAT else "off"
        
        try:
            _LOGGER.info(
                "Setting operation mode to %s for device %s",
                operation_mode,
                self.device_id
            )
            async with self.coordinator.session.post(
                f"{API_BASE_URL}{API_DEVICE_CONTROL_ENDPOINT.format(serial_number=self.device_id)}",
                headers={"Authorization": f"Bearer {self.coordinator.auth_token}"},
                json={"operation_mode": operation_mode},
            ) as response:
                response.raise_for_status()
                _LOGGER.info(
                    "Successfully set operation mode to %s for device %s",
                    operation_mode,
                    self.device_id
                )
                await self.coordinator.async_request_refresh()

        except Exception as error:
            _LOGGER.error(
                "Failed to set operation mode for device %s: %s",
                self.device_id,
                error
            )
            raise
