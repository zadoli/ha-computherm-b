"""Sensor platform for Computherm integration."""
from __future__ import annotations

import asyncio
import logging

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
    ATTR_TEMPERATURE,
    ATTR_HUMIDITY,
    ATTR_DEVICE_TYPE,
    ATTR_FW_VERSION,
    ATTR_RELAY_STATE,
    ATTR_BATTERY,
    ATTR_RSSI,
    ATTR_RSSI_LEVEL,
    ATTR_SOURCE,
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
    
    existing_temperature_entities = set()  # Track temperature entities we've already added
    existing_humidity_entities = set()  # Track humidity entities we've already added
    existing_relay_entities = set()  # Track relay entities we've already added
    # Track each type of diagnostic entity separately
    existing_battery_entities = set()
    existing_rssi_entities = set()
    existing_rssi_level_entities = set()
    existing_source_entities = set()
    
    @callback
    def _async_add_entities_for_device(device_id: str) -> None:
        """Create and add entities for a device that has received base_info."""
        if device_id not in coordinator.devices_with_base_info:
            _LOGGER.debug("Device %s has no base_info yet", device_id)
            return
            
        if not coordinator.devices_with_base_info[device_id]:
            _LOGGER.debug("Device %s has empty base_info", device_id)
            return

        entities_to_add = []
            
        device_data = coordinator.device_data.get(device_id, {})
        if not device_data or 'available_sensor_ids' not in device_data:
            _LOGGER.debug("Device %s has no sensor data yet", device_id)
            return

        # Add temperature sensor if not already added
        if device_id not in existing_temperature_entities:
            _LOGGER.info("Creating temperature sensor entity for device %s", device_id)
            temp_entity = ComputhermTemperatureSensor(hass, coordinator, device_id)
            entities_to_add.append(temp_entity)
            existing_temperature_entities.add(device_id)
            
        # Add humidity sensor if not already added and device has humidity readings
        if device_id not in existing_humidity_entities and ATTR_HUMIDITY in device_data:
            _LOGGER.info("Creating humidity sensor entity for device %s", device_id)
            humidity_entity = ComputhermHumiditySensor(hass, coordinator, device_id)
            entities_to_add.append(humidity_entity)
            existing_humidity_entities.add(device_id)

        # Add relay binary sensor if not already added
        if device_id not in existing_relay_entities:
            _LOGGER.info("Creating relay binary sensor entity for device %s", device_id)
            relay_entity = ComputhermRelaySensor(hass, coordinator, device_id)
            entities_to_add.append(relay_entity)
            existing_relay_entities.add(device_id)

        # Add diagnostic sensors only if their attributes are present and not already added
        diagnostic_entities = []
        
        # Only create battery sensor if battery attribute exists and not already added
        if ATTR_BATTERY in device_data and device_id not in existing_battery_entities:
            _LOGGER.info("Creating battery sensor for device %s", device_id)
            diagnostic_entities.append(ComputhermBatterySensor(hass, coordinator, device_id))
            existing_battery_entities.add(device_id)
            
        # Only create RSSI sensor if RSSI attribute exists and not already added
        if ATTR_RSSI in device_data and device_id not in existing_rssi_entities:
            _LOGGER.info("Creating RSSI sensor for device %s", device_id)
            diagnostic_entities.append(ComputhermRSSISensor(hass, coordinator, device_id))
            existing_rssi_entities.add(device_id)
            
        # Only create RSSI level sensor if RSSI level attribute exists and not already added
        if ATTR_RSSI_LEVEL in device_data and device_id not in existing_rssi_level_entities:
            _LOGGER.info("Creating RSSI level sensor for device %s", device_id)
            diagnostic_entities.append(ComputhermRSSILevelSensor(hass, coordinator, device_id))
            existing_rssi_level_entities.add(device_id)
            
        # Only create source sensor if source attribute exists and not already added
        if ATTR_SOURCE in device_data and device_id not in existing_source_entities:
            _LOGGER.info("Creating source sensor for device %s", device_id)
            diagnostic_entities.append(ComputhermSourceSensor(hass, coordinator, device_id))
            existing_source_entities.add(device_id)
        
        if diagnostic_entities:
            entities_to_add.extend(diagnostic_entities)
            _LOGGER.info("Created diagnostic entities for device %s", device_id)
            
        if entities_to_add:
            async_add_entities(entities_to_add, True)
            _LOGGER.info("Sensor entities created for device %s", device_id)
    
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

class ComputhermSensorBase(CoordinatorEntity, SensorEntity):
    """Base class for Computherm sensors."""

    _attr_has_entity_name = True
    _attr_translation_key = DOMAIN

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: ComputhermDataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.device_id = serial
        
        device_info = {
            "identifiers": {(DOMAIN, serial)},
            "serial_number": serial,
            "name": f"Computherm {serial}",
            "manufacturer": "Computherm",
            "model": self.coordinator.devices[self.device_id].get(ATTR_DEVICE_TYPE, "") or "B Series Thermostat",
            "sw_version": self.coordinator.devices[self.device_id].get(ATTR_FW_VERSION),
            "hw_version": self.coordinator.devices[self.device_id].get("type"),
        }
        
        self._attr_device_info = device_info

    @property
    def device_data(self) -> dict:
        """Get the current device data."""
        return self.coordinator.device_data.get(self.device_id, {})

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.device_data.get("online", False)


class ComputhermNumericSensorBase(ComputhermSensorBase):
    """Base class for numeric Computherm sensors."""

    _attr_state_class = SensorStateClass.MEASUREMENT


class ComputhermTemperatureSensor(ComputhermNumericSensorBase):
    """Representation of a Computherm Temperature Sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermometer"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: ComputhermDataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the temperature sensor."""
        super().__init__(hass, coordinator, serial)

        device_data = coordinator.device_data.get(serial, {})

        _LOGGER.info(
            "Initializing temperature sensor with device data: %s",
            device_data
        )
        
        # Set unique ID and device info        
        if not device_data or 'available_sensor_ids' not in device_data:
            _LOGGER.error("Device %s has no sensor data available", serial)
            entity_name = "temperature"
        else:
            sensor_id = str(device_data['available_sensor_ids'][0])
            entity_name = device_data["sensors"][sensor_id].get("name", "temperature")
            if "temperature" not in entity_name:
                entity_name += " temperature"
                
        self._attr_unique_id = f"{DOMAIN}_{serial}_{entity_name}"
        self._attr_name = entity_name
        
        _LOGGER.info(
            "Temperature entity initialized - ID: %s, Name: %s",
            self._attr_unique_id,
            self._attr_name
        )

    @property
    def native_value(self) -> float | None:
        """Return the current temperature."""
        if self.device_data.get(ATTR_TEMPERATURE) is not None:
            return float(self.device_data[ATTR_TEMPERATURE])
        return None


class ComputhermBatterySensor(ComputhermNumericSensorBase):
    """Representation of a Computherm Battery Sensor."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:battery"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: ComputhermDataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the battery sensor."""
        super().__init__(hass, coordinator, serial)
        self._attr_unique_id = f"{DOMAIN}_{serial}_battery"
        self._attr_name = "Battery"

    @property
    def native_value(self) -> float | None:
        """Return the battery level."""
        battery = self.device_data.get(ATTR_BATTERY)
        if battery is not None:
            # Convert "100%" to 100
            try:
                return float(battery.rstrip("%"))
            except (ValueError, AttributeError):
                return None
        return None


class ComputhermRSSISensor(ComputhermNumericSensorBase):
    """Representation of a Computherm RSSI Sensor."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = "dB"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:signal"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: ComputhermDataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the RSSI sensor."""
        super().__init__(hass, coordinator, serial)
        self._attr_unique_id = f"{DOMAIN}_{serial}_rssi"
        self._attr_name = "RSSI"

    @property
    def native_value(self) -> float | None:
        """Return the RSSI value."""
        rssi = self.device_data.get(ATTR_RSSI)
        if rssi is not None:
            # Convert "-85 dB" to -85
            try:
                return float(rssi.split()[0])
            except (ValueError, IndexError):
                return None
        return None


class ComputhermRSSILevelSensor(ComputhermSensorBase):
    """Representation of a Computherm RSSI Level Sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:signal"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: ComputhermDataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the RSSI level sensor."""
        super().__init__(hass, coordinator, serial)
        self._attr_unique_id = f"{DOMAIN}_{serial}_rssi_level"
        self._attr_name = "RSSI Level"

    @property
    def native_value(self) -> str | None:
        """Return the RSSI level."""
        return self.device_data.get(ATTR_RSSI_LEVEL)


class ComputhermSourceSensor(ComputhermSensorBase):
    """Representation of a Computherm Source Sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:connection"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: ComputhermDataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the source sensor."""
        super().__init__(hass, coordinator, serial)
        self._attr_unique_id = f"{DOMAIN}_{serial}_source"
        self._attr_name = "Source"

    @property
    def native_value(self) -> str | None:
        """Return the source value."""
        return self.device_data.get(ATTR_SOURCE)


class ComputhermRelaySensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of a Computherm Relay Binary Sensor."""

    _attr_device_class = BinarySensorDeviceClass.HEAT
    _attr_has_entity_name = True
    _attr_translation_key = DOMAIN

    @property
    def icon(self) -> str:
        """Return the icon based on relay state."""
        return "mdi:electric-switch-closed" if self.is_on else "mdi:electric-switch"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: ComputhermDataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the relay sensor."""
        super().__init__(coordinator)
        self.device_id = serial
        
        device_info = {
            "identifiers": {(DOMAIN, serial)},
            "serial_number": serial,
            "name": f"Computherm {serial}",
            "manufacturer": "Computherm",
            "model": coordinator.devices[serial].get(ATTR_DEVICE_TYPE, "") or "B Series Thermostat",
            "sw_version": coordinator.devices[serial].get(ATTR_FW_VERSION),
            "hw_version": coordinator.devices[serial].get("type"),
        }
        self._attr_device_info = device_info

        device_data = coordinator.device_data.get(serial, {})

        _LOGGER.info(
            "Initializing relay sensor with device data: %s",
            device_data
        )

        entity_name = "relay"
        self._attr_unique_id = f"{DOMAIN}_{serial}_{entity_name}"
        self._attr_name = entity_name
        
        _LOGGER.info(
            "Relay entity initialized - ID: %s, Name: %s",
            self._attr_unique_id,
            self._attr_name
        )

    @property
    def device_data(self) -> dict:
        """Get the current device data."""
        return self.coordinator.device_data.get(self.device_id, {})

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.device_data.get("online", False)

    @property
    def is_on(self) -> bool | None:
        """Return true if the relay is on."""
        relay_state = self.device_data.get(ATTR_RELAY_STATE)
        if relay_state is not None:
            return relay_state
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        _LOGGER.debug(
            "Relay state update for %s: %s",
            self.device_id,
            self.device_data.get(ATTR_RELAY_STATE)
        )
        self.async_write_ha_state()


class ComputhermHumiditySensor(ComputhermNumericSensorBase):
    """Representation of a Computherm Humidity Sensor."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:water-percent"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: ComputhermDataUpdateCoordinator,
        serial: str,
    ) -> None:
        """Initialize the humidity sensor."""
        super().__init__(hass, coordinator, serial)

        device_data = coordinator.device_data.get(serial, {})

        _LOGGER.info(
            "Initializing humidity sensor with device data: %s",
            device_data
        )

        # Set unique ID and device info       
        if not device_data or 'available_sensor_ids' not in device_data:
            _LOGGER.error("Device %s has no sensor data available", serial)
            entity_name = "humidity"
        else:
            sensor_id = str(device_data['available_sensor_ids'][0])
            entity_name = device_data["sensors"][sensor_id].get("name", "humidity")
            if "humidity" not in entity_name:
                entity_name += " humidity"
            
        self._attr_unique_id = f"{DOMAIN}_{serial}_{entity_name}"
        self._attr_name = entity_name
        
        _LOGGER.info(
            "Humidity entity initialized - ID: %s, Name: %s",
            self._attr_unique_id,
            self._attr_name
        )

    @property
    def native_value(self) -> float | None:
        """Return the current humidity."""
        if self.device_data.get(ATTR_HUMIDITY) is not None:
            return float(self.device_data[ATTR_HUMIDITY])
        return None
