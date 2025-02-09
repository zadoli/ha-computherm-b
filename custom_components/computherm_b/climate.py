"""Climate platform for Computherm integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Final, Optional

from homeassistant.components.climate import (ClimateEntity,
                                              ClimateEntityFeature, HVACAction,
                                              HVACMode)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (API_BASE_URL, API_DEVICE_CONTROL_ENDPOINT, COORDINATOR,
                    DOMAIN)
from .const import DeviceAttributes as DA
from .coordinator import ComputhermDataUpdateCoordinator

_LOGGER = logging.getLogger(__package__)

SUPPORT_FLAGS: Final = (
    ClimateEntityFeature.TARGET_TEMPERATURE
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Computherm climate platform."""
    coordinator: ComputhermDataUpdateCoordinator = hass.data[
        DOMAIN][config_entry.entry_id][COORDINATOR]

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
        entity = ComputhermThermostat(coordinator, device_id)
        async_add_entities([entity], True)
        existing_entities.add(device_id)
        _LOGGER.info("Climate entity created for device %s", device_id)

    # Add entities for devices that already have base_info
    for serial in coordinator.devices:
        _LOGGER.debug("Checking device %s for base_info", serial)
        if serial in coordinator.devices_with_base_info and coordinator.devices_with_base_info[
                serial]:
            _LOGGER.info("Found existing base_info for device %s", serial)
            _async_add_entities_for_device(serial)

    @callback
    def async_handle_coordinator_update() -> None:
        """Handle updated data from the coordinator."""
        for device_id in coordinator.devices:
            if device_id in coordinator.devices_with_base_info and coordinator.devices_with_base_info[
                    device_id]:
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
        coordinator: ComputhermDataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the thermostat."""
        super().__init__(coordinator)
        self.serial_number = serial
        self._setup_device_info()

    def _setup_device_info(self) -> None:
        """Set up device information and entity attributes."""
        # Get the API ID from devices dictionary
        self.api_device_id = self.coordinator.devices[self.serial_number].get(
            DA.DEVICE_ID)
        if not self.api_device_id:
            raise HomeAssistantError(
                f"No API device ID found for serial number {self.serial_number}")

        # Get min/max temperature from relays config
        self._setup_temperature_limits()

        # Set unique ID and device info
        self._setup_entity_info()

        # Set up device info dictionary
        self._setup_device_info_dict()

    def _setup_temperature_limits(self) -> None:
        """Set up min and max temperature limits from relay configs."""
        relays = self.coordinator.device_data[self.serial_number].get(
            "relays", {})
        first_relay = next(iter(relays.values()), {})
        configs = first_relay.get("configs", {})
        self._attr_min_temp = configs.get("setpoint_min", 5)
        self._attr_max_temp = configs.get("setpoint_max", 30)

    def _setup_entity_info(self) -> None:
        """Set up entity ID and name."""
        entity_name = self.coordinator.device_data[self.serial_number].get(
            "base_info", {}).get("name", "thermostat")
        self._attr_unique_id = f"{DOMAIN}_{self.serial_number}_{entity_name}"
        self._attr_name = entity_name
        _LOGGER.info(
            "Initializing climate entity - ID: %s, Device ID: %s",
            self._attr_unique_id,
            self.serial_number
        )

    def _setup_device_info_dict(self) -> None:
        """Set up the device info dictionary."""
        device_info = {
            "identifiers": {(DOMAIN, self.serial_number)},
            "serial_number": self.serial_number,
            "name": f"Computherm {self.serial_number}",
            "manufacturer": "Computherm",
            "model": self.coordinator.devices[self.serial_number].get(DA.DEVICE_TYPE, "") or "B Series Thermostat",
            "sw_version": self.coordinator.devices[self.serial_number].get(DA.FW_VERSION),
            "hw_version": self.coordinator.devices[self.serial_number].get("type"),
        }
        _LOGGER.info(
            "Climate entity - Device serial: %s, name: %s, Info: %s",
            self.serial_number,
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
        if self.device_data.get(DA.TEMPERATURE) is not None:
            return float(self.device_data[DA.TEMPERATURE])
        return None

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        if self.device_data.get(DA.TARGET_TEMPERATURE) is not None:
            return float(self.device_data[DA.TARGET_TEMPERATURE])
        return None

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the current operation mode."""
        if not self.device_data.get(
                DA.ONLINE,
                False) or "off" == self.device_data.get(
                DA.MODE):
            return HVACMode.OFF
        function = self.device_data.get(DA.FUNCTION)
        return HVACMode.COOL if function == "cooling" else HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current running hvac operation."""
        if not self._is_device_active():
            return HVACAction.OFF

        function = self.device_data.get(DA.FUNCTION)
        relay_state = self.device_data.get(DA.RELAY_STATE, False)

        _LOGGER.debug(
            "Device %s - Function: %s, Relay State: %s, HVAC Mode: %s",
            self.serial_number,
            function,
            relay_state,
            self.hvac_mode
        )

        return self._determine_hvac_action(function, relay_state)

    def _is_device_active(self) -> bool:
        """Check if the device is active and operational."""
        if not self.device_data.get(DA.ONLINE, False):
            _LOGGER.debug(
                "Device %s is offline, setting action to OFF",
                self.serial_number)
            return False
        if self.hvac_mode == HVACMode.OFF:
            _LOGGER.debug(
                "Device %s mode is OFF, setting action to OFF",
                self.serial_number)
            return False
        return True

    def _determine_hvac_action(
            self,
            function: str,
            relay_state: bool) -> HVACAction:
        """Determine the current HVAC action based on function and relay state."""
        if function == "cooling":
            action = HVACAction.COOLING if relay_state else HVACAction.IDLE
            _LOGGER.debug(
                "Device %s - Cooling Action: %s",
                self.serial_number,
                action)
            return action

        action = HVACAction.HEATING if relay_state else HVACAction.IDLE
        _LOGGER.debug(
            "Device %s - Heating Action: %s",
            self.serial_number,
            action)
        return action

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.device_data.get(DA.ONLINE, False)

    @property
    def current_humidity(self) -> int | None:
        """Return the current humidity."""
        if self.device_data.get(DA.HUMIDITY) is not None:
            return round(float(self.device_data[DA.HUMIDITY]))
        return None

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        try:
            await self._send_temperature_command(temperature)
        except Exception as error:
            _LOGGER.error(
                "Failed to set temperature for device %s (API ID: %s): %s",
                self.serial_number,
                self.api_device_id,
                error
            )
            raise HomeAssistantError(
                f"Failed to set temperature: {error}") from error

    async def _send_temperature_command(self, temperature: float) -> None:
        """Send temperature change command to the device."""
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

        _LOGGER.debug(
            "Sending target temperature change request for device %s: %s",
            self.serial_number,
            request_data
        )

        async with self.coordinator.session.post(
            f"{API_BASE_URL}{API_DEVICE_CONTROL_ENDPOINT.format(device_id=self.api_device_id)}",
            headers={"Authorization": f"Bearer {self.coordinator.auth_token}"},
            json=request_data,
        ) as response:
            response_data = await response.json()
            response.raise_for_status()

            _LOGGER.info(
                "Successfully set target temperature to %.1f°C for device %s",
                temperature,
                self.serial_number
            )
            await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new operation mode."""
        try:
            operation_mode = self._get_operation_mode(hvac_mode)
            if operation_mode is None:
                _LOGGER.error("Invalid HVAC mode: %s", hvac_mode)
                return

            await self._send_hvac_mode_command(operation_mode)
        except Exception as error:
            _LOGGER.error(
                "Failed to set operation mode for device %s (API ID: %s): %s",
                self.serial_number,
                self.api_device_id,
                error
            )
            raise HomeAssistantError(
                f"Failed to set HVAC mode: {error}") from error

    def _get_operation_mode(
            self, hvac_mode: HVACMode) -> Optional[tuple[str, str]]:
        """Get operation mode parameters based on HVAC mode."""
        mode_map = {
            HVACMode.OFF: ("mode", "OFF"),
            HVACMode.HEAT: ("function", "HEATING"),
            HVACMode.COOL: ("function", "COOLING"),
        }
        return mode_map.get(hvac_mode)

    async def _send_hvac_mode_command(
            self, operation_mode: tuple[str, str]) -> None:
        """Send HVAC mode change command to the device."""
        operation, mode = operation_mode
        _LOGGER.info(
            "Setting operation mode to %s for device %s",
            mode,
            self.serial_number
        )

        request_data = {
            "relay": 1,
            operation: mode
        }

        if "off" == self.device_data.get(DA.MODE):
            request_data["mode"] = "MANUAL"

        _LOGGER.debug(
            "Sending HVAC mode change request for device %s: %s",
            self.serial_number,
            request_data
        )

        async with self.coordinator.session.post(
            f"{API_BASE_URL}{API_DEVICE_CONTROL_ENDPOINT.format(device_id=self.api_device_id)}",
            headers={"Authorization": f"Bearer {self.coordinator.auth_token}"},
            json=request_data,
        ) as response:
            response_data = await response.json()
            response.raise_for_status()

            _LOGGER.info(
                "Successfully set operation mode to %s for device %s",
                mode,
                self.serial_number
            )
            await self.coordinator.async_request_refresh()
