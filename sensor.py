"""Sensor platform for Computherm integration."""
from __future__ import annotations

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
        entities.append(ComputhermTemperatureSensor(coordinator, serial))
    
    async_add_entities(entities, True)

class ComputhermTemperatureSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Computherm Temperature Sensor."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: ComputhermDataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.device_id = serial
        
        # Set unique ID and device info
        self._attr_unique_id = f"{DOMAIN}_{serial}_temperature"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, serial)},
        }

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
