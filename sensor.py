"""Sensor platform for Computherm integration."""
from __future__ import annotations

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
    for serial, device_info in coordinator.devices.items():
        entities.append(ComputhermTemperatureSensor(hass, coordinator, serial))
    
    async_add_entities(entities, True)

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
