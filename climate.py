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
from homeassistant.core import HomeAssistant
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
    
    # Wait for devices to be fetched
    await coordinator.async_config_entry_first_refresh()
    
    entities = []
    
    # Create a function to add entities when base_info is received
    async def add_entities_for_device(device_id: str) -> None:
        """Create and add entities for a device that has received base_info."""
        if device_id not in coordinator.devices_with_base_info or not coordinator.devices_with_base_info[device_id]:
            return
        entity = ComputhermThermostat(hass, coordinator, device_id)
        async_add_entities([entity], True)
    
    # Add entities for devices that already have base_info
    for serial in coordinator.devices:
        if serial in coordinator.devices_with_base_info and coordinator.devices_with_base_info[serial]:
            entities.append(ComputhermThermostat(hass, coordinator, serial))
    
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
        self._attr_unique_id = f"{DOMAIN}_{serial}"
        self._attr_name = "thermostat"

        # Log entity ID and attributes
        _LOGGER.debug(
            "Initializing climate entity - ID: %s, Device ID: %s, Device Data: %s",
            self._attr_unique_id,
            self.device_id,
            self.device_data
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
        _LOGGER.debug(
            "Climate entity device info - Device: %s, Info: %s",
            serial,
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
        if self.device_data.get(ATTR_TARGET_TEMPERATURE) is not None:
            return float(self.device_data[ATTR_TARGET_TEMPERATURE])
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
            return HVACAction.OFF
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        if self.device_data.get("is_heating", False):
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.device_data.get(ATTR_ONLINE, False)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        try:
            async with self.coordinator.session.post(
                f"{API_BASE_URL}{API_DEVICE_CONTROL_ENDPOINT.format(serial_number=self.device_id)}",
                headers={"Authorization": f"Bearer {self.coordinator.auth_token}"},
                json={"target_temperature": temperature},
            ) as response:
                response.raise_for_status()
                _LOGGER.debug(
                    "Set temperature to %.1f°C for device %s",
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
            async with self.coordinator.session.post(
                f"{API_BASE_URL}{API_DEVICE_CONTROL_ENDPOINT.format(serial_number=self.device_id)}",
                headers={"Authorization": f"Bearer {self.coordinator.auth_token}"},
                json={"operation_mode": operation_mode},
            ) as response:
                response.raise_for_status()
                _LOGGER.debug(
                    "Set operation mode to %s for device %s",
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
