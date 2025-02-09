"""Sensor platform for Computherm integration."""
from __future__ import annotations

import logging
from typing import Any, Final, Optional

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory

from .const import (
    DOMAIN,
    COORDINATOR,
    DeviceAttributes as DA,
)
from .coordinator import ComputhermDataUpdateCoordinator

_LOGGER = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Computherm temperature sensors."""
    coordinator: ComputhermDataUpdateCoordinator = hass.data[
        DOMAIN][config_entry.entry_id][COORDINATOR]

    _LOGGER.info("Setting up Computherm sensor platform")

    # Wait for devices to be fetched
    await coordinator.async_config_entry_first_refresh()

    # Track entities we've already added
    existing_entities = {
        "temperature": set(),
        "humidity": set(),
        "relay": set(),
        "battery": set(),
        "rssi": set(),
        "rssi_level": set(),
        "source": set(),
    }

    @callback
    def _async_add_entities_for_device(device_id: str) -> None:
        """Create and add entities for a device that has received base_info."""
        if not _is_device_ready(coordinator, device_id):
            return

        device_data = coordinator.device_data.get(device_id, {})
        if not device_data or 'available_sensor_ids' not in device_data:
            _LOGGER.debug("Device %s has no sensor data yet", device_id)
            return

        entities_to_add = []

        # Add core sensors
        _add_core_sensors(
            coordinator,
            device_id,
            device_data,
            entities_to_add,
            existing_entities)

        # Add diagnostic sensors
        _add_diagnostic_sensors(
            coordinator,
            device_id,
            device_data,
            entities_to_add,
            existing_entities)

        if entities_to_add:
            async_add_entities(entities_to_add, True)
            _LOGGER.info("Sensor entities created for device %s", device_id)

    # Add entities for devices that already have base_info
    for serial in coordinator.devices:
        if _is_device_ready(coordinator, serial):
            _LOGGER.info("Found existing base_info for device %s", serial)
            _async_add_entities_for_device(serial)

    # Register listener for coordinator updates
    config_entry.async_on_unload(
        coordinator.async_add_listener(
            lambda: async_handle_coordinator_update(
                coordinator,
                _async_add_entities_for_device)))
    _LOGGER.info("Sensor platform setup completed")


def _is_device_ready(
        coordinator: ComputhermDataUpdateCoordinator,
        device_id: str) -> bool:
    """Check if device is ready for entity creation."""
    if device_id not in coordinator.devices_with_base_info:
        _LOGGER.debug("Device %s has no base_info yet", device_id)
        return False

    if not coordinator.devices_with_base_info[device_id]:
        _LOGGER.debug("Device %s has empty base_info", device_id)
        return False

    return True


def _add_core_sensors(
    coordinator: ComputhermDataUpdateCoordinator,
    device_id: str,
    device_data: dict,
    entities_to_add: list,
    existing_entities: dict,
) -> None:
    """Add core sensor entities."""
    # Add temperature sensor
    if device_id not in existing_entities["temperature"]:
        _LOGGER.info(
            "Creating temperature sensor entity for device %s",
            device_id)
        entities_to_add.append(
            ComputhermTemperatureSensor(
                coordinator, device_id))
        existing_entities["temperature"].add(device_id)

    # Add humidity sensor if device has humidity readings
    if device_id not in existing_entities["humidity"] and DA.HUMIDITY in device_data:
        _LOGGER.info(
            "Creating humidity sensor entity for device %s",
            device_id)
        entities_to_add.append(
            ComputhermHumiditySensor(
                coordinator, device_id))
        existing_entities["humidity"].add(device_id)

    # Add relay binary sensor
    if device_id not in existing_entities["relay"]:
        _LOGGER.info(
            "Creating relay binary sensor entity for device %s",
            device_id)
        entities_to_add.append(ComputhermRelaySensor(coordinator, device_id))
        existing_entities["relay"].add(device_id)


def _add_diagnostic_sensors(
    coordinator: ComputhermDataUpdateCoordinator,
    device_id: str,
    device_data: dict,
    entities_to_add: list,
    existing_entities: dict,
) -> None:
    """Add diagnostic sensor entities."""
    diagnostic_sensors = [
        (DA.BATTERY, "battery", ComputhermBatterySensor),
        (DA.RSSI, "rssi", ComputhermRSSISensor),
        (DA.RSSI_LEVEL, "rssi_level", ComputhermRSSILevelSensor),
        (DA.SOURCE, "source", ComputhermSourceSensor),
    ]

    for attr, key, sensor_class in diagnostic_sensors:
        if attr in device_data and device_id not in existing_entities[key]:
            _LOGGER.info("Creating %s sensor for device %s", key, device_id)
            entities_to_add.append(sensor_class(coordinator, device_id))
            existing_entities[key].add(device_id)


@callback
def async_handle_coordinator_update(
    coordinator: ComputhermDataUpdateCoordinator,
    add_entities_callback: callable,
) -> None:
    """Handle updated data from the coordinator."""
    for device_id in coordinator.devices:
        if device_id in coordinator.devices_with_base_info and coordinator.devices_with_base_info[
                device_id]:
            add_entities_callback(device_id)


class ComputhermSensorBase(CoordinatorEntity):
    """Base class for Computherm sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ComputhermDataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.device_id = serial
        self._setup_device()

    def _setup_device(self) -> None:
        """Set up device information."""
        self._setup_device_info()
        self._setup_entity_info()

    def _setup_device_info(self) -> None:
        """Set up device info dictionary."""
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self.device_id)},
            "serial_number": self.device_id,
            "name": f"Computherm {self.device_id}",
            "manufacturer": "Computherm",
            "model": self.coordinator.devices[self.device_id].get(DA.DEVICE_TYPE, "") or "B Series Thermostat",
            "sw_version": self.coordinator.devices[self.device_id].get(DA.FW_VERSION),
            "hw_version": self.coordinator.devices[self.device_id].get("type"),
        }

    def _setup_entity_info(self) -> None:
        """Set up entity information."""
        device_data = self.coordinator.device_data.get(self.device_id, {})
        if not device_data or 'available_sensor_ids' not in device_data:
            _LOGGER.error(
                "Device %s has no sensor data available",
                self.device_id)
            entity_name = self._get_default_name()
        else:
            entity_name = self._get_entity_name(device_data)

        self._attr_unique_id = f"{DOMAIN}_{self.device_id}_{entity_name}"

        _LOGGER.info(
            "Entity initialized - ID: %s, Name: %s",
            self._attr_unique_id,
            entity_name
        )

    def _get_default_name(self) -> str:
        """Get default entity name."""
        return self._attr_translation_key or "sensor"

    def _get_entity_name(self, device_data: dict) -> str:
        """Get entity name from device data."""
        sensor_id = str(device_data['available_sensor_ids'][0])
        base_name = device_data["sensors"][sensor_id].get(
            "name", self._get_default_name())
        return self._process_entity_name(base_name)

    def _process_entity_name(self, base_name: str) -> str:
        """Process the entity name."""
        return base_name

    @property
    def device_data(self) -> dict[str, Any]:
        """Get the current device data."""
        return self.coordinator.device_data.get(self.device_id, {})

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.device_data.get(DA.ONLINE, False)


class ComputhermNumericSensorBase(ComputhermSensorBase, SensorEntity):
    """Base class for numeric Computherm sensors."""

    _attr_state_class = SensorStateClass.MEASUREMENT


class ComputhermTemperatureSensor(ComputhermNumericSensorBase):
    """Representation of a Computherm Temperature Sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_translation_key = "temperature"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermometer"

    def _process_entity_name(self, base_name: str) -> str:
        """Process the temperature entity name."""
        if "temperature" not in base_name.lower():
            self._attr_translation_placeholders = {"custom_name": base_name}
            return f"{base_name} temperature"
        self._attr_name = base_name
        return base_name

    @property
    def native_value(self) -> float | None:
        """Return the current temperature."""
        if self.device_data.get(DA.TEMPERATURE) is not None:
            return float(self.device_data[DA.TEMPERATURE])
        return None


class ComputhermHumiditySensor(ComputhermNumericSensorBase):
    """Representation of a Computherm Humidity Sensor."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_translation_key = "humidity"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:water-percent"

    def _process_entity_name(self, base_name: str) -> str:
        """Process the humidity entity name."""
        if "humidity" not in base_name.lower():
            self._attr_translation_placeholders = {"custom_name": base_name}
            return f"{base_name} humidity"
        self._attr_name = base_name
        return base_name

    @property
    def native_value(self) -> float | None:
        """Return the current humidity."""
        if self.device_data.get(DA.HUMIDITY) is not None:
            return float(self.device_data[DA.HUMIDITY])
        return None


class ComputhermDiagnosticSensorBase(ComputhermNumericSensorBase):
    """Base class for diagnostic sensors."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC


class ComputhermBatterySensor(ComputhermDiagnosticSensorBase):
    """Representation of a Computherm Battery Sensor."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_translation_key = "battery"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:battery"

    def _setup_entity_info(self) -> None:
        """Set up entity information."""
        self._attr_unique_id = f"{DOMAIN}_{self.device_id}_battery"

    @property
    def native_value(self) -> float | None:
        """Return the battery level."""
        battery = self.device_data.get(DA.BATTERY)
        if battery is not None:
            try:
                return float(battery.rstrip("%"))
            except (ValueError, AttributeError):
                return None
        return None


class ComputhermRSSISensor(ComputhermDiagnosticSensorBase):
    """Representation of a Computherm RSSI Sensor."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_translation_key = "rssi"
    _attr_native_unit_of_measurement = "dB"
    _attr_icon = "mdi:signal"

    def _setup_entity_info(self) -> None:
        """Set up entity information."""
        self._attr_unique_id = f"{DOMAIN}_{self.device_id}_rssi"

    @property
    def native_value(self) -> float | None:
        """Return the RSSI value."""
        rssi = self.device_data.get(DA.RSSI)
        if rssi is not None:
            try:
                return float(rssi.split()[0])
            except (ValueError, IndexError):
                return None
        return None


class ComputhermRSSILevelSensor(ComputhermSensorBase, SensorEntity):
    """Representation of a Computherm RSSI Level Sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "rssi_level"
    _attr_icon = "mdi:signal"

    def _setup_entity_info(self) -> None:
        """Set up entity information."""
        self._attr_unique_id = f"{DOMAIN}_{self.device_id}_rssi_level"

    @property
    def native_value(self) -> str | None:
        """Return the RSSI level."""
        return self.device_data.get(DA.RSSI_LEVEL)


class ComputhermSourceSensor(ComputhermSensorBase, SensorEntity):
    """Representation of a Computherm Source Sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "source"
    _attr_icon = "mdi:connection"

    def _setup_entity_info(self) -> None:
        """Set up entity information."""
        self._attr_unique_id = f"{DOMAIN}_{self.device_id}_source"

    @property
    def native_value(self) -> str | None:
        """Return the source value."""
        return self.device_data.get(DA.SOURCE)


class ComputhermRelaySensor(ComputhermSensorBase, BinarySensorEntity):
    """Representation of a Computherm Relay Binary Sensor."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_translation_key = "relay"

    def _process_entity_name(self, base_name: str) -> str:
        """Process the relay entity name."""
        return "relay"

    @property
    def is_on(self) -> bool | None:
        """Return true if the relay is on."""
        relay_state = self.device_data.get(DA.RELAY_STATE)
        if relay_state is not None:
            return relay_state
        return None

    @property
    def icon(self) -> str:
        """Return the icon to use for the relay."""
        return "mdi:electric-switch-closed" if self.is_on else "mdi:electric-switch"
