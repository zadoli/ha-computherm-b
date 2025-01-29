"""Sensor platform for Computherm integration."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    COORDINATOR,
    ATTR_TEMPERATURE,
    ATTR_DEVICE_TYPE,
    ATTR_FW_VERSION,
)
from .coordinator import ComputhermDataUpdateCoordinator

_LOGGER = logging.getLogger(__package__)
    
async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Computherm temperature sensors."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id][COORDINATOR]
    
    _LOGGER.info("Setting up Computherm sensor platform")
    
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
            
        _LOGGER.info("Creating sensor entity for device %s", device_id)
        entity = ComputhermTemperatureSensor(hass, coordinator, device_id)
        async_add_entities([entity], True)
        existing_entities.add(device_id)
        _LOGGER.info("Sensor entity created for device %s", device_id)
    
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
    _LOGGER.info("Sensor platform setup completed")

class ComputhermTemperatureSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Computherm Temperature Sensor."""

    _attr_has_entity_name = True
    _attr_translation_key = DOMAIN
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: ComputhermDataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.device_id = serial
        
        # Set unique ID and device info
        self._attr_unique_id = f"{DOMAIN}_{serial}_temperature"
        self._attr_name = "temperature"

        # Log entity ID and attributes
        _LOGGER.info(
            "Initializing temperature sensor - ID: %s, Device ID: %s",
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
            "Temperature sensor device info - Device: %s, Info: %s",
            serial,
            device_info
        )
        
        self._attr_device_info = device_info

    @property
    def device_data(self) -> dict:
        """Get the current device data."""
        return self.coordinator.device_data.get(self.device_id, {})

    @property
    def native_value(self) -> float | None:
        """Return the current temperature."""
        if self.device_data.get(ATTR_TEMPERATURE) is not None:
            return float(self.device_data[ATTR_TEMPERATURE])
        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.device_data.get("online", False)
