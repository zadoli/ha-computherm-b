"""Config flow for Computherm integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
import aiohttp
from aiohttp import ClientError, ClientResponseError, ClientTimeout

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, API_BASE_URL, API_LOGIN_ENDPOINT

_LOGGER = logging.getLogger(__package__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("username"): str,
        vol.Required("password"): str,
    }
)


async def validate_input(
        hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    session = async_get_clientsession(hass)

    try:
        login_payload = {
            "email": data["username"],
            "password": data["password"]
        }
        _LOGGER.debug("Attempting to authenticate with Computherm API")

        timeout = ClientTimeout(total=30)
        async with session.post(
            f"{API_BASE_URL}{API_LOGIN_ENDPOINT}",
            json=login_payload,
            timeout=timeout,
        ) as response:
            if response.status == 401:
                _LOGGER.error("Authentication failed: Invalid credentials")
                raise InvalidAuth("Invalid email or password")

            try:
                response.raise_for_status()
            except aiohttp.ClientResponseError as err:
                _LOGGER.error("HTTP error occurred: %s", err)
                raise CannotConnect(f"HTTP error: {err.status}") from err

            try:
                result = await response.json()
            except ValueError as err:
                _LOGGER.error("Failed to parse API response: %s", err)
                raise CannotConnect("Invalid API response") from err

            if not result.get("token") and not result.get("access_token"):
                _LOGGER.error("No authentication token in response")
                raise CannotConnect("No authentication token received")

            _LOGGER.debug("Successfully authenticated with Computherm API")
            return {"title": f"Computherm ({data['username']})"}

    except asyncio.TimeoutError as error:
        _LOGGER.error("Timeout connecting to Computherm API")
        raise CannotConnect("Connection timed out") from error
    except aiohttp.ClientConnectionError as error:
        _LOGGER.error("Failed to connect to Computherm API: %s", error)
        raise CannotConnect("Connection failed") from error
    except InvalidAuth as error:
        # Re-raise InvalidAuth without wrapping
        raise
    except CannotConnect as error:
        # Re-raise CannotConnect without wrapping
        raise
    except Exception as error:
        _LOGGER.exception("Unexpected error occurred during validation")
        raise UnknownError("Unexpected error occurred") from error


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
                # Check if already configured
                await self.async_set_unique_id(user_input["username"])
                self._abort_if_unique_id_configured()

                info = await validate_input(self.hass, user_input)
                _LOGGER.debug("Configuration validation successful")
                return self.async_create_entry(
                    title=info["title"], data=user_input)

            except CannotConnect as error:
                _LOGGER.error("Connection failed: %s", error)
                errors["base"] = "cannot_connect"
            except InvalidAuth as error:
                _LOGGER.error("Invalid authentication: %s", error)
                errors["base"] = "invalid_auth"
            except UnknownError as error:
                _LOGGER.exception("Unknown error: %s", error)
                errors["base"] = "unknown"

        # Show initial form or form with errors
        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "error_detail": errors.get("base", ""),
            },
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class UnknownError(HomeAssistantError):
    """Error to indicate there is an unknown error."""
