"""The Computherm Integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import aiohttp
import async_timeout
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.exceptions import ConfigEntryNotReady, ConfigEntryAuthFailed

from .const import DOMAIN, COORDINATOR
from .coordinator import ComputhermDataUpdateCoordinator

_LOGGER = logging.getLogger(__package__)

PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.SENSOR]

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
