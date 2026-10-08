"""Switch platform for Computherm integration (boost)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import COORDINATOR, DOMAIN
from .const import DeviceAttributes as DA
from .coordinator import ComputhermDataUpdateCoordinator
from .number import DEFAULT_BOOST_DURATION_MIN
from .sensor import ComputhermSensorBase, _is_device_ready

_LOGGER = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Computherm boost switch."""
    coordinator: ComputhermDataUpdateCoordinator = hass.data[
        DOMAIN][config_entry.entry_id][COORDINATOR]

    await coordinator.async_config_entry_first_refresh()

    existing_entities: set[str] = set()

    @callback
    def _async_add_entities_for_device(device_id: str) -> None:
        """Create the boost switch once the device reports boost data."""
        if not _is_device_ready(coordinator, device_id) or device_id in existing_entities:
            return
        if DA.BOOST_ACTIVE not in coordinator.device_data.get(device_id, {}):
            return
        # Mark before adding: async_add_entities can re-enter this callback
        existing_entities.add(device_id)
        async_add_entities([ComputhermBoostSwitch(coordinator, device_id)])

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


class ComputhermBoostSwitch(ComputhermSensorBase, SwitchEntity):
    """Boost on/off. Turning on uses the boost set point and duration entities."""

    _attr_translation_key = "boost"
    _attr_icon = "mdi:rocket-launch"

    def _setup_entity_info(self) -> None:
        """Set up entity information."""
        self._attr_unique_id = f"{DOMAIN}_{self.device_id}_boost"

    @property
    def is_on(self) -> bool | None:
        """Return true if boost is active."""
        return self.device_data.get(DA.BOOST_ACTIVE)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start boost for the configured duration."""
        duration = self.coordinator.boost_durations.get(self.device_id, DEFAULT_BOOST_DURATION_MIN * 60)
        await self.coordinator.async_send_command(self.device_id, {"relay": 1, "boost_time": duration})

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop boost."""
        await self.coordinator.async_send_command(self.device_id, {"relay": 1, "boost_time": 0})
