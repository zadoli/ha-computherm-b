"""The Computherm Integration."""
from __future__ import annotations

import logging

from custom_components.computherm_b.const import COORDINATOR, DOMAIN
from custom_components.computherm_b.coordinator import \
    ComputhermDataUpdateCoordinator
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

# ANSI color codes
BLUE = '\033[94m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
BOLD_RED = '\033[1;91m'
RESET = '\033[0m'


class ColoredFormatter(logging.Formatter):
    """Custom formatter that adds colors based on log level."""

    COLORS = {
        'DEBUG': BLUE,
        'INFO': GREEN,
        'WARNING': YELLOW,
        'ERROR': RED,
        'CRITICAL': BOLD_RED
    }

    def format(self, record):
        """Format log record with colors."""
        color = self.COLORS.get(record.levelname, RESET)
        record.levelname = f"{color}{record.levelname}{RESET}"
        record.msg = f"{color}{record.msg}{RESET}"
        return super().format(record)


# Set up custom logging format to include package name and filename with colors
_formatter = ColoredFormatter(
    '%(asctime)s %(levelname)s [%(name)s.%(filename)s] %(message)s')
_handler = logging.StreamHandler()
_handler.setFormatter(_formatter)
_LOGGER = logging.getLogger(__package__)
_LOGGER.addHandler(_handler)
_LOGGER.propagate = False  # Prevent duplicate logging


PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.SELECT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Computherm from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    try:
        _LOGGER.debug("Setting up Computherm integration")
        coordinator = ComputhermDataUpdateCoordinator(
            hass,
            config_entry=entry,
        )

        try:
            await coordinator.async_config_entry_first_refresh()
        except ConfigEntryAuthFailed as err:
            _LOGGER.error("Authentication failed: %s", err)
            raise
        except Exception as err:
            _LOGGER.error("Failed to refresh coordinator: %s", err)
            raise ConfigEntryNotReady from err

        hass.data[DOMAIN][entry.entry_id] = {
            COORDINATOR: coordinator,
        }

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        _LOGGER.debug("Computherm integration setup completed successfully")

        return True

    except ConfigEntryAuthFailed:
        _LOGGER.error("Invalid authentication")
        raise
    except Exception as error:
        _LOGGER.exception("Unexpected error setting up integration: %s", error)
        raise ConfigEntryNotReady from error


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    try:
        coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]

        if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
            # Stop the coordinator's WebSocket connection and clear data
            await coordinator.async_stop()
            hass.data[DOMAIN].pop(entry.entry_id)
            _LOGGER.debug("Computherm integration unloaded successfully")

        return unload_ok
    except Exception as error:
        _LOGGER.exception("Error unloading Computherm integration: %s", error)
        return False
