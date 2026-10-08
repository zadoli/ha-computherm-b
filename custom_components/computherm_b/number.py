"""Number platform for Computherm integration (boost and hysteresis settings)."""
from __future__ import annotations

import logging

from homeassistant.components.number import (NumberDeviceClass, NumberEntity,
                                             NumberMode, RestoreNumber)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import COORDINATOR, DOMAIN
from .const import DeviceAttributes as DA
from .coordinator import ComputhermDataUpdateCoordinator
from .sensor import ComputhermSensorBase, _is_device_ready

_LOGGER = logging.getLogger(__package__)

# Limits from the API (DevicesCommandsBody)
HYSTERESIS_MAX = 20
BOOST_DURATION_MAX_MIN = 90  # boost_time max 5400 s
DEFAULT_BOOST_DURATION_MIN = 30


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Computherm number entities."""
    coordinator: ComputhermDataUpdateCoordinator = hass.data[
        DOMAIN][config_entry.entry_id][COORDINATOR]

    await coordinator.async_config_entry_first_refresh()

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
            if f"{device_id}_{key}" not in existing_entities:
                existing_entities.add(f"{device_id}_{key}")
                entities_to_add.append(factory())

        if DA.BOOST_ACTIVE in device_data:
            _add(DA.BOOST_SET_POINT, lambda: ComputhermBoostSetPointNumber(coordinator, device_id))
            _add("boost_duration", lambda: ComputhermBoostDurationNumber(coordinator, device_id))

        for key in (DA.HYSTERESIS_LOW, DA.HYSTERESIS_HIGH):
            if key in device_data:
                _add(key, lambda key=key: ComputhermHysteresisNumber(coordinator, device_id, key))

        if entities_to_add:
            async_add_entities(entities_to_add)
            _LOGGER.info("[%s] Number entities created", device_id)

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


class ComputhermBoostSetPointNumber(ComputhermSensorBase, NumberEntity):
    """Boost target temperature, stored on the device."""

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_step = 0.1
    _attr_mode = NumberMode.BOX
    _attr_translation_key = "boost_set_point"
    _attr_icon = "mdi:rocket-launch"

    def _setup_entity_info(self) -> None:
        """Set up entity information."""
        self._attr_unique_id = f"{DOMAIN}_{self.device_id}_boost_set_point"
        relays = self.device_data.get("relays", {})
        configs = next(iter(relays.values()), {}).get("configs", {})
        self._attr_native_min_value = configs.get("setpoint_min", 5)
        self._attr_native_max_value = configs.get("setpoint_max", 40)

    @property
    def native_value(self) -> float | None:
        """Return the boost set point."""
        return self.device_data.get(DA.BOOST_SET_POINT)

    async def async_set_native_value(self, value: float) -> None:
        """Set the boost set point."""
        await self.coordinator.async_send_command(
            self.device_id, {"relay": 1, "boost_set_point": round(value, 1)})


class ComputhermBoostDurationNumber(ComputhermSensorBase, RestoreNumber):
    """Duration used when boost is turned on. Kept in Home Assistant, sent with the boost command."""

    _attr_device_class = NumberDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_native_min_value = 1
    _attr_native_max_value = BOOST_DURATION_MAX_MIN
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "boost_duration"
    _attr_icon = "mdi:timer-cog-outline"

    def _setup_entity_info(self) -> None:
        """Set up entity information."""
        self._attr_unique_id = f"{DOMAIN}_{self.device_id}_boost_duration"
        self._attr_native_value = DEFAULT_BOOST_DURATION_MIN

    async def async_added_to_hass(self) -> None:
        """Restore the last duration."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_number_data()) and last.native_value is not None:
            self._attr_native_value = last.native_value
        self.coordinator.boost_durations[self.device_id] = int(self._attr_native_value * 60)

    @property
    def available(self) -> bool:
        """Always available: the value is local."""
        return True

    async def async_set_native_value(self, value: float) -> None:
        """Set the duration."""
        self._attr_native_value = value
        self.coordinator.boost_durations[self.device_id] = int(value * 60)
        self.async_write_ha_state()


class ComputhermHysteresisNumber(ComputhermSensorBase, NumberEntity):
    """Lower or upper switching hysteresis, stored on the device."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = 0
    _attr_native_max_value = HYSTERESIS_MAX
    _attr_native_step = 0.1
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: ComputhermDataUpdateCoordinator,
        serial: str,
        key: str,
    ) -> None:
        """Initialize the hysteresis number."""
        self.key = key
        self._attr_translation_key = key
        self._attr_icon = "mdi:arrow-collapse-down" if key == DA.HYSTERESIS_LOW else "mdi:arrow-collapse-up"
        super().__init__(coordinator, serial)

    def _setup_entity_info(self) -> None:
        """Set up entity information."""
        self._attr_unique_id = f"{DOMAIN}_{self.device_id}_{self.key}"

    @property
    def native_value(self) -> float | None:
        """Return the hysteresis."""
        return self.device_data.get(self.key)

    async def async_set_native_value(self, value: float) -> None:
        """Set the hysteresis."""
        await self.coordinator.async_send_command(
            self.device_id, {"relay": 1, self.key: round(value, 1)})
