"""Climate platform for Computherm integration."""
from __future__ import annotations

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
)
from .coordinator import ComputhermDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

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
    for device_id, device_info in coordinator.devices.items():
        entities.append(ComputhermThermostat(coordinator, device_id, device_info))
    
    async_add_entities(entities, True)

class ComputhermThermostat(CoordinatorEntity, ClimateEntity):
    """Representation of a Computherm Thermostat."""

    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = SUPPORT_FLAGS
    _attr_min_temp = 5
    _attr_max_temp = 30
    _attr_target_temperature_step = 0.5

    def __init__(
        self, 
        coordinator: ComputhermDataUpdateCoordinator,
        device_id: str,
        device_info: dict,
    ) -> None:
        """Initialize the thermostat."""
        super().__init__(coordinator)
        self.device_id = device_id
        self._device_info = device_info
        
        # Set unique ID and device info
        self._attr_unique_id = f"{DOMAIN}_{device_id}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": device_info.get("name", f"Computherm {device_id}"),
            "manufacturer": "Computherm",
            "model": device_info.get("model", "B Series Thermostat"),
            "sw_version": device_info.get("firmware_version"),
        }

    @property
    def device_data(self) -> dict:
        """Get the current device data."""
        return self.coordinator.device_data.get(self.device_id, {})

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        if self.device_data.get("temperature") is not None:
            return float(self.device_data["temperature"])
        return None

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        if self.device_data.get("target_temperature") is not None:
            return float(self.device_data["target_temperature"])
        return None

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the current operation mode."""
        if not self.device_data.get("online", False):
            return HVACMode.OFF
        return HVACMode.HEAT if self.device_data.get("is_heating") is not None else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current running hvac operation."""
        if not self.device_data.get("online", False):
            return HVACAction.OFF
        if self.device_data.get("is_heating"):
            return HVACAction.HEATING
        if self.hvac_mode == HVACMode.HEAT:
            return HVACAction.IDLE
        return HVACAction.OFF

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.device_data.get("online", False)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        try:
            async with self.coordinator.session.post(
                f"{API_BASE_URL}{API_DEVICE_CONTROL_ENDPOINT.format(device_id=self.device_id)}",
                headers={"Authorization": f"Bearer {self.coordinator.auth_token}"},
                json={"target_temperature": temperature},
            ) as response:
                response.raise_for_status()
                await self.coordinator.async_request_refresh()

        except Exception as error:
            _LOGGER.error("Failed to set temperature for device %s: %s", self.device_id, error)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new operation mode."""
        operation_mode = "heat" if hvac_mode == HVACMode.HEAT else "off"
        
        try:
            async with self.coordinator.session.post(
                f"{API_BASE_URL}{API_DEVICE_CONTROL_ENDPOINT.format(device_id=self.device_id)}",
                headers={"Authorization": f"Bearer {self.coordinator.auth_token}"},
                json={"operation_mode": operation_mode},
            ) as response:
                response.raise_for_status()
                await self.coordinator.async_request_refresh()

        except Exception as error:
            _LOGGER.error("Failed to set operation mode for device %s: %s", self.device_id, error)
