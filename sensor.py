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
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    COORDINATOR,
    ATTR_TEMPERATURE,
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
    
    # Wait for devices to be fetched
    await coordinator.async_config_entry_first_refresh()
    
    entities = []
    
    # Create a function to add entities when base_info is received
    async def add_entities_for_device(device_id: str) -> None:
        """Create and add entities for a device that has received base_info."""
        if device_id not in coordinator.devices_with_base_info or not coordinator.devices_with_base_info[device_id]:
            return
        entity = ComputhermTemperatureSensor(hass, coordinator, device_id)
        async_add_entities([entity], True)
    
    # Add entities for devices that already have base_info
    for serial in coordinator.devices:
        if serial in coordinator.devices_with_base_info and coordinator.devices_with_base_info[serial]:
            entities.append(ComputhermTemperatureSensor(hass, coordinator, serial))
    
    if entities:
        async_add_entities(entities, True)
    
    # Set up listener for future base_info updates
    async def handle_coordinator_update() -> None:
        """Handle updated data from the coordinator."""
        tasks = []
        for device_id in coordinator.devices:
            if (device_id in coordinator.devices_with_base_info and 
                coordinator.devices_with_base_info[device_id] and
                not any(device_id == entity.device_id for entity in entities)):
                tasks.append(add_entities_for_device(device_id))
        if tasks:
            await asyncio.gather(*tasks)
    
    # Register listener
    config_entry.async_on_unload(
        coordinator.async_add_listener(handle_coordinator_update)
    )

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
        _LOGGER.debug(
            "Initializing temperature sensor - ID: %s, Device ID: %s, Device Data: %s",
            self._attr_unique_id,
            self.device_id,
            self.device_data
        )
        device_info = {
            "identifiers": {(DOMAIN, serial)},
            "name": f"Computherm {serial}",
            "manufacturer": "Computherm",
            "model": coordinator.devices[self.device_id].get("type", "B Series Thermostat"),
        }
        
        # Log device info
        _LOGGER.debug(
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
