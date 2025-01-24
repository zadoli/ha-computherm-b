"""Config flow for Computherm integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
import aiohttp

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, API_BASE_URL, API_LOGIN_ENDPOINT

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("username"): str,
        vol.Required("password"): str,
    }
)

async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    session = async_get_clientsession(hass)

    try:
        async with session.post(
            f"{API_BASE_URL}{API_LOGIN_ENDPOINT}",
            json={
                "username": data["username"],
                "password": data["password"],
            },
        ) as response:
            if response.status == 401:
                raise InvalidAuth
            response.raise_for_status()
            result = await response.json()

        # Return info to be stored in the config entry.
        return {"title": f"Computherm ({data['username']})"}

    except aiohttp.ClientConnectionError as error:
        raise CannotConnect from error
    except aiohttp.ClientResponseError as error:
        if error.status == 401:
            raise InvalidAuth from error
        raise CannotConnect from error
    except Exception as error:
        _LOGGER.exception("Unexpected exception")
        raise UnknownError from error

class ComputhermConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Computherm."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except UnknownError:
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""

class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""

class UnknownError(HomeAssistantError):
    """Error to indicate there is an unknown error."""
