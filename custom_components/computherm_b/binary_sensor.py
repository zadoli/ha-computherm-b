"""Binary sensor platform for Computherm integration."""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (BinarySensorDeviceClass,
                                                    BinarySensorEntity)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import COORDINATOR, DOMAIN
from .const import DeviceAttributes as DA
from .coordinator import ComputhermDataUpdateCoordinator
from .sensor import ComputhermSensorBase, _is_device_ready

_LOGGER = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Computherm binary sensors."""
    coordinator: ComputhermDataUpdateCoordinator = hass.data[
        DOMAIN][config_entry.entry_id][COORDINATOR]

    _LOGGER.info("Setting up Computherm binary sensor platform")

    await coordinator.async_config_entry_first_refresh()

    # Tracking keys of entities already added
    existing_entities: set[str] = set()

    @callback
    def _async_add_entities_for_device(device_id: str) -> None:
        """Create and add entities for a device once its data is available."""
        if not _is_device_ready(coordinator, device_id):
            return

        device_data = coordinator.device_data.get(device_id, {})
        entities_to_add = []

        def _add(key: str, factory) -> None:
            # Mark before adding: async_add_entities can re-enter this callback
            if key not in existing_entities:
                existing_entities.add(key)
                entities_to_add.append(factory())

        if DA.RELAY_ERROR in device_data:
            _add(f"{device_id}_relay_error",
                 lambda: ComputhermRelayErrorBinarySensor(coordinator, device_id))

        for sensor_key, sensor_info in device_data.get(DA.SENSOR_READINGS, {}).items():
            if DA.ERROR in sensor_info:
                _add(f"{device_id}_{sensor_key}_error",
                     lambda sensor_key=sensor_key: ComputhermSensorErrorBinarySensor(
                         coordinator, device_id, sensor_key))

        if entities_to_add:
            async_add_entities(entities_to_add, True)
            _LOGGER.info("[%s] Binary sensor entities created", device_id)

    for serial in coordinator.devices:
        _async_add_entities_for_device(serial)

    @callback
    def async_handle_coordinator_update() -> None:
        """Add entities for devices whose data arrived later."""
        for device_id in coordinator.devices:
            _async_add_entities_for_device(device_id)

    config_entry.async_on_unload(
        coordinator.async_add_listener(async_handle_coordinator_update)
    )


class ComputhermRelayErrorBinarySensor(ComputhermSensorBase, BinarySensorEntity):
    """Error flag reported for the relay output."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "relay_error"

    def _setup_entity_info(self) -> None:
        """Set up entity information."""
        self._attr_unique_id = f"{DOMAIN}_{self.device_id}_relay_error"

    @property
    def is_on(self) -> bool | None:
        """Return true if the relay reports an error."""
        return self.device_data.get(DA.RELAY_ERROR)


class ComputhermSensorErrorBinarySensor(ComputhermSensorBase, BinarySensorEntity):
    """Error flag reported for a single temperature/humidity sensor."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "sensor_error"

    def __init__(
        self,
        coordinator: ComputhermDataUpdateCoordinator,
        serial: str,
        sensor_key: str,
    ) -> None:
        """Initialize the sensor error binary sensor."""
        self.sensor_key = sensor_key
        super().__init__(coordinator, serial)

    def _setup_entity_info(self) -> None:
        """Set up entity information."""
        sensor_info = self.device_data.get(DA.SENSOR_READINGS, {}).get(self.sensor_key, {})
        self._attr_unique_id = f"{DOMAIN}_{self.device_id}_{self.sensor_key}_error"
        self._attr_translation_placeholders = {
            "sensor_name": sensor_info.get("name", self.sensor_key)}

    @property
    def is_on(self) -> bool | None:
        """Return true if the sensor reports an error."""
        return self.device_data.get(DA.SENSOR_READINGS, {}).get(
            self.sensor_key, {}).get(DA.ERROR)
