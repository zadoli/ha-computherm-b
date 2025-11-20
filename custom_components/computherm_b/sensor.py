"""Sensor platform for Computherm integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (BinarySensorDeviceClass,
                                                    BinarySensorEntity)
from homeassistant.components.sensor import (SensorDeviceClass, SensorEntity,
                                             SensorStateClass)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import COORDINATOR, DOMAIN
from .const import DeviceAttributes as DA
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
    # Add temperature sensors - support for multiple sensors
    sensor_readings = device_data.get(DA.SENSOR_READINGS, {})

    for sensor_key, sensor_info in sensor_readings.items():
        # Only create temperature sensors
        if sensor_info.get("type") != "TEMPERATURE":
            continue

        # Create unique identifier for tracking
        entity_tracking_key = f"{device_id}_{sensor_key}"

        if entity_tracking_key not in existing_entities["temperature"]:
            _LOGGER.info(
                "Creating temperature sensor entity for device %s, sensor %s",
                device_id,
                sensor_key)
            entities_to_add.append(
                ComputhermTemperatureSensor(
                    coordinator, device_id, sensor_key))
            existing_entities["temperature"].add(entity_tracking_key)

    # Fallback: if no sensor_readings, create default temperature sensor for backward compatibility
    if not sensor_readings and device_id not in existing_entities["temperature"]:
        _LOGGER.info(
            "Creating default temperature sensor entity for device %s (backward compatibility)",
            device_id)
        entities_to_add.append(
            ComputhermTemperatureSensor(
                coordinator, device_id, None))
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
    # Add sensor-specific diagnostic sensors
    sensor_readings = device_data.get(DA.SENSOR_READINGS, {})

    for sensor_key, sensor_info in sensor_readings.items():
        # Only create diagnostic sensors for temperature sensors
        if sensor_info.get("type") != "TEMPERATURE":
            continue

        sensor_name = sensor_info.get("name", sensor_key)

        # Create battery sensor if available
        if "battery" in sensor_info:
            entity_tracking_key = f"{device_id}_{sensor_key}_battery"
            if entity_tracking_key not in existing_entities["battery"]:
                _LOGGER.info("Creating battery sensor for device %s, sensor %s", device_id, sensor_key)
                entities_to_add.append(
                    ComputhermBatterySensor(coordinator, device_id, sensor_key, sensor_name))
                existing_entities["battery"].add(entity_tracking_key)

        # Create RSSI sensor if available
        if "rssi" in sensor_info:
            entity_tracking_key = f"{device_id}_{sensor_key}_rssi"
            if entity_tracking_key not in existing_entities["rssi"]:
                _LOGGER.info("Creating rssi sensor for device %s, sensor %s", device_id, sensor_key)
                entities_to_add.append(
                    ComputhermRSSISensor(coordinator, device_id, sensor_key, sensor_name))
                existing_entities["rssi"].add(entity_tracking_key)

        # Create RSSI Level sensor if available
        if "rssi_level" in sensor_info:
            entity_tracking_key = f"{device_id}_{sensor_key}_rssi_level"
            if entity_tracking_key not in existing_entities["rssi_level"]:
                _LOGGER.info("Creating rssi_level sensor for device %s, sensor %s", device_id, sensor_key)
                entities_to_add.append(
                    ComputhermRSSILevelSensor(coordinator, device_id, sensor_key, sensor_name))
                existing_entities["rssi_level"].add(entity_tracking_key)

    # Add device-level diagnostic sensors (from base_info, without sensor name)
    # Device-level RSSI sensor if available
    if DA.RSSI in device_data and device_id not in existing_entities["rssi"]:
        _LOGGER.info("Creating device-level rssi sensor for device %s", device_id)
        entities_to_add.append(ComputhermRSSISensor(coordinator, device_id))
        existing_entities["rssi"].add(device_id)

    # Device-level RSSI Level sensor if available
    if DA.RSSI_LEVEL in device_data and device_id not in existing_entities["rssi_level"]:
        _LOGGER.info("Creating device-level rssi_level sensor for device %s", device_id)
        entities_to_add.append(ComputhermRSSILevelSensor(coordinator, device_id))
        existing_entities["rssi_level"].add(device_id)

    # Add device-level source sensor if available
    if DA.SOURCE in device_data and device_id not in existing_entities["source"]:
        _LOGGER.info("Creating source sensor for device %s", device_id)
        entities_to_add.append(ComputhermSourceSensor(coordinator, device_id))
        existing_entities["source"].add(device_id)


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
        # Safety check for available_sensor_ids
        if 'available_sensor_ids' not in device_data or not device_data['available_sensor_ids']:
            return self._get_default_name()

        sensor_id = str(device_data['available_sensor_ids'][0])

        # Safety check for sensors dictionary
        if 'sensors' not in device_data or sensor_id not in device_data['sensors']:
            return self._get_default_name()

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

    def __init__(
        self,
        coordinator: ComputhermDataUpdateCoordinator,
        serial: str,
        sensor_key: str | None = None,
    ) -> None:
        """Initialize the temperature sensor."""
        self.sensor_key = sensor_key
        super().__init__(coordinator, serial)

    def _setup_entity_info(self) -> None:
        """Set up entity information for temperature sensor."""
        device_data = self.coordinator.device_data.get(self.device_id, {})

        # Multi-sensor case
        if self.sensor_key and DA.SENSOR_READINGS in device_data:
            sensor_readings = device_data[DA.SENSOR_READINGS]
            if self.sensor_key in sensor_readings:
                sensor_info = sensor_readings[self.sensor_key]
                sensor_name = sensor_info.get("name", self.sensor_key)

                # Set unique_id with sensor_key to differentiate multiple sensors
                self._attr_unique_id = f"{DOMAIN}_{self.device_id}_temperature_{self.sensor_key}"
                # Use translation_placeholders for multi-sensor support
                self._attr_translation_placeholders = {"sensor_name": sensor_name}

                _LOGGER.info(
                    "Temperature entity initialized - ID: %s, Sensor Name: %s, Sensor Key: %s",
                    self._attr_unique_id,
                    sensor_name,
                    self.sensor_key
                )
                return

        # Fallback to old behavior for backward compatibility
        if not device_data or 'available_sensor_ids' not in device_data:
            _LOGGER.error(
                "Device %s has no sensor data available",
                self.device_id)
            entity_name = self._get_default_name()
            # Set placeholder with default name
            self._attr_translation_placeholders = {"sensor_name": "Temperature"}
        else:
            entity_name = self._get_entity_name(device_data)
            # Try to get sensor name from device data for placeholder
            sensor_name = "Temperature"  # Default fallback
            if 'available_sensor_ids' in device_data and device_data['available_sensor_ids']:
                sensor_id = str(device_data['available_sensor_ids'][0])
                if 'sensors' in device_data and sensor_id in device_data['sensors']:
                    sensor_name = device_data["sensors"][sensor_id].get("name", "Temperature")
            # Always set the placeholder
            self._attr_translation_placeholders = {"sensor_name": sensor_name}

        self._attr_unique_id = f"{DOMAIN}_{self.device_id}_{entity_name}"

        _LOGGER.info(
            "Entity initialized - ID: %s, Name: %s",
            self._attr_unique_id,
            entity_name
        )

    def _process_entity_name(self, base_name: str) -> str:
        """Process the temperature entity name."""
        # Temperature name comes from translation
        return base_name

    @property
    def native_value(self) -> float | None:
        """Return the current temperature."""
        # Multi-sensor case
        if self.sensor_key:
            sensor_readings = self.device_data.get(DA.SENSOR_READINGS, {})
            if self.sensor_key in sensor_readings:
                reading = sensor_readings[self.sensor_key].get("reading")
                if reading is not None:
                    return float(reading)
                return None

        # Fallback to old behavior for backward compatibility
        if self.device_data.get(DA.TEMPERATURE) is not None:
            return float(self.device_data[DA.TEMPERATURE])
        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Multi-sensor case - check if the specific sensor has a reading
        if self.sensor_key:
            sensor_readings = self.device_data.get(DA.SENSOR_READINGS, {})
            if self.sensor_key in sensor_readings:
                # Sensor is available if device is online and it has data
                return self.device_data.get(DA.ONLINE, False) and sensor_readings[self.sensor_key].get("reading") is not None

        # Fallback to device online status
        return self.device_data.get(DA.ONLINE, False)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes for multi-sensor support."""
        if not self.sensor_key:
            return None

        sensor_readings = self.device_data.get(DA.SENSOR_READINGS, {})
        if self.sensor_key not in sensor_readings:
            return None

        sensor_info = sensor_readings[self.sensor_key]
        attributes = {}

        # Add sensor source
        if "src" in sensor_info:
            attributes["source"] = sensor_info["src"]

        # Add diagnostic info if available
        for attr in ["battery", "rssi", "rssi_level"]:
            if attr in sensor_info:
                attributes[attr] = sensor_info[attr]

        return attributes if attributes else None


class ComputhermHumiditySensor(ComputhermNumericSensorBase):
    """Representation of a Computherm Humidity Sensor."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_translation_key = "humidity"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:water-percent"

    def _setup_entity_info(self) -> None:
        """Set up entity information."""
        device_data = self.coordinator.device_data.get(self.device_id, {})
        if not device_data or 'available_sensor_ids' not in device_data:
            _LOGGER.error(
                "Device %s has no sensor data available",
                self.device_id)
            entity_name = self._get_default_name()
            # Set placeholder with default name
            self._attr_translation_placeholders = {"sensor_name": "Humidity"}
        else:
            entity_name = self._get_entity_name(device_data)
            # Try to get sensor name from device data for placeholder
            sensor_name = "Humidity"  # Default fallback
            if 'available_sensor_ids' in device_data and device_data['available_sensor_ids']:
                sensor_id = str(device_data['available_sensor_ids'][0])
                if 'sensors' in device_data and sensor_id in device_data['sensors']:
                    sensor_name = device_data["sensors"][sensor_id].get("name", "Humidity")
            # Always set the placeholder
            self._attr_translation_placeholders = {"sensor_name": sensor_name}

        self._attr_unique_id = f"{DOMAIN}_{self.device_id}_{entity_name}"

        _LOGGER.info(
            "Entity initialized - ID: %s, Name: %s",
            self._attr_unique_id,
            entity_name
        )

    def _process_entity_name(self, base_name: str) -> str:
        """Process the humidity entity name."""
        # Humidity name comes from translation
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

    def __init__(
        self,
        coordinator: ComputhermDataUpdateCoordinator,
        serial: str,
        sensor_key: str | None = None,
        sensor_name: str | None = None,
    ) -> None:
        """Initialize the battery sensor."""
        self.sensor_key = sensor_key
        self.sensor_name = sensor_name
        super().__init__(coordinator, serial)

    def _setup_entity_info(self) -> None:
        """Set up entity information for battery sensor."""
        if self.sensor_key:
            # Sensor-specific battery sensor
            self._attr_unique_id = f"{DOMAIN}_{self.device_id}_battery_{self.sensor_key}"
            # Use translation_placeholders for multi-sensor support
            self._attr_translation_placeholders = {"sensor_name": self.sensor_name}
            _LOGGER.info(
                "Battery entity initialized - ID: %s, Sensor Name: %s, Sensor Key: %s",
                self._attr_unique_id,
                self.sensor_name,
                self.sensor_key
            )
        else:
            # Device-level battery sensor (legacy)
            self._attr_unique_id = f"{DOMAIN}_{self.device_id}_battery"

    @property
    def native_value(self) -> float | None:
        """Return the battery level."""
        # Sensor-specific case
        if self.sensor_key:
            sensor_readings = self.device_data.get(DA.SENSOR_READINGS, {})
            if self.sensor_key in sensor_readings:
                battery = sensor_readings[self.sensor_key].get("battery")
                if battery is not None:
                    try:
                        return float(battery.rstrip("%"))
                    except (ValueError, AttributeError):
                        return None
            return None

        # Device-level case (legacy)
        battery = self.device_data.get(DA.BATTERY)
        if battery is not None:
            try:
                return float(battery.rstrip("%"))
            except (ValueError, AttributeError):
                return None
        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Sensor-specific case - check if the specific sensor has battery data
        if self.sensor_key:
            sensor_readings = self.device_data.get(DA.SENSOR_READINGS, {})
            if self.sensor_key in sensor_readings:
                return self.device_data.get(DA.ONLINE, False) and "battery" in sensor_readings[self.sensor_key]

        # Fallback to device online status
        return self.device_data.get(DA.ONLINE, False)


class ComputhermRSSISensor(ComputhermDiagnosticSensorBase):
    """Representation of a Computherm RSSI Sensor."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_translation_key = "rssi"
    _attr_native_unit_of_measurement = "dB"
    _attr_icon = "mdi:signal"

    def __init__(
        self,
        coordinator: ComputhermDataUpdateCoordinator,
        serial: str,
        sensor_key: str | None = None,
        sensor_name: str | None = None,
    ) -> None:
        """Initialize the RSSI sensor."""
        self.sensor_key = sensor_key
        self.sensor_name = sensor_name
        super().__init__(coordinator, serial)

    def _setup_entity_info(self) -> None:
        """Set up entity information for RSSI sensor."""
        if self.sensor_key:
            # Sensor-specific RSSI sensor
            self._attr_unique_id = f"{DOMAIN}_{self.device_id}_rssi_{self.sensor_key}"
            # Use translation_placeholders for multi-sensor support
            self._attr_translation_placeholders = {"sensor_name": self.sensor_name}
            _LOGGER.info(
                "RSSI entity initialized - ID: %s, Sensor Name: %s, Sensor Key: %s",
                self._attr_unique_id,
                self.sensor_name,
                self.sensor_key
            )
        else:
            # Device-level RSSI sensor (legacy) - no sensor name placeholder needed
            self._attr_unique_id = f"{DOMAIN}_{self.device_id}_rssi"
            self._attr_translation_placeholders = {"sensor_name": "Wi-Fi"}

    @property
    def native_value(self) -> float | None:
        """Return the RSSI value."""
        # Sensor-specific case
        if self.sensor_key:
            sensor_readings = self.device_data.get(DA.SENSOR_READINGS, {})
            if self.sensor_key in sensor_readings:
                rssi = sensor_readings[self.sensor_key].get("rssi")
                if rssi is not None:
                    try:
                        return float(rssi.split()[0])
                    except (ValueError, IndexError, AttributeError):
                        return None
            return None

        # Device-level case (legacy)
        rssi = self.device_data.get(DA.RSSI)
        if rssi is not None:
            try:
                return float(rssi.split()[0])
            except (ValueError, IndexError):
                return None
        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Sensor-specific case - check if the specific sensor has RSSI data
        if self.sensor_key:
            sensor_readings = self.device_data.get(DA.SENSOR_READINGS, {})
            if self.sensor_key in sensor_readings:
                return self.device_data.get(DA.ONLINE, False) and "rssi" in sensor_readings[self.sensor_key]

        # Fallback to device online status
        return self.device_data.get(DA.ONLINE, False)


class ComputhermRSSILevelSensor(ComputhermSensorBase, SensorEntity):
    """Representation of a Computherm RSSI Level Sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "rssi_level"
    _attr_icon = "mdi:signal"

    def __init__(
        self,
        coordinator: ComputhermDataUpdateCoordinator,
        serial: str,
        sensor_key: str | None = None,
        sensor_name: str | None = None,
    ) -> None:
        """Initialize the RSSI level sensor."""
        self.sensor_key = sensor_key
        self.sensor_name = sensor_name
        super().__init__(coordinator, serial)

    def _setup_entity_info(self) -> None:
        """Set up entity information for RSSI level sensor."""
        if self.sensor_key:
            # Sensor-specific RSSI level sensor
            self._attr_unique_id = f"{DOMAIN}_{self.device_id}_rssi_level_{self.sensor_key}"
            # Use translation_placeholders for multi-sensor support
            self._attr_translation_placeholders = {"sensor_name": self.sensor_name}
            _LOGGER.info(
                "RSSI Level entity initialized - ID: %s, Sensor Name: %s, Sensor Key: %s",
                self._attr_unique_id,
                self.sensor_name,
                self.sensor_key
            )
        else:
            # Device-level RSSI level sensor (legacy) - no sensor name placeholder needed
            self._attr_unique_id = f"{DOMAIN}_{self.device_id}_rssi_level"
            self._attr_translation_placeholders = {"sensor_name": "Wi-Fi"}

    @property
    def native_value(self) -> str | None:
        """Return the RSSI level."""
        # Sensor-specific case
        if self.sensor_key:
            sensor_readings = self.device_data.get(DA.SENSOR_READINGS, {})
            if self.sensor_key in sensor_readings:
                return sensor_readings[self.sensor_key].get("rssi_level")
            return None

        # Device-level case (legacy)
        return self.device_data.get(DA.RSSI_LEVEL)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Sensor-specific case - check if the specific sensor has RSSI level data
        if self.sensor_key:
            sensor_readings = self.device_data.get(DA.SENSOR_READINGS, {})
            if self.sensor_key in sensor_readings:
                return self.device_data.get(DA.ONLINE, False) and "rssi_level" in sensor_readings[self.sensor_key]

        # Fallback to device online status
        return self.device_data.get(DA.ONLINE, False)


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
