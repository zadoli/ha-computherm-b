"""Unit tests for WebSocketClient in computherm_b integration."""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.computherm_b.const import DeviceAttributes as DA
from custom_components.computherm_b.websocket import WebSocketClient


@pytest.mark.asyncio
async def test_handle_message_event_1():
    """Test _handle_message processing a valid event message from JSON fixture."""
    # Read event data from fixture file
    with open("tests/fixtures/message_1111111111.json", "r", encoding='utf8') as f:
        event_data = json.load(f)

    message_json = json.dumps(event_data)
    message = f"42/devices,{message_json}"

    # Mock data_callback
    data_callback = AsyncMock()

    # Create WebSocketClient instance
    client = WebSocketClient(
        auth_token="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpYXQiOjE3NTkzMjIxMjEsImV4cCI6MTc1OTQ5NDkyMSwic3ViIjoiNjA2ODYifQ.O4V7dfohNwGtYuNcR2O9SSiz3QY8dkzSpu6JGtmUxBo",
        device_serials=["1111111111", "2222222222"],
        data_callback=data_callback,
    )

    # Set up instance attributes for the test
    client.websocket = AsyncMock()  # Mock websocket, though not used in this path
    client._last_message_time = datetime.now()

    # Call the method under test
    await client._handle_message(message)


@pytest.mark.asyncio
async def test_handle_message_event_2():
    """Test _handle_message processing a valid event message from JSON fixture."""
    # Read event data from fixture file
    with open("tests/fixtures/message_2222222222.json", "r", encoding='utf8') as f:
        event_data = json.load(f)

    message_json = json.dumps(event_data)
    message = f"42/devices,{message_json}"

    # Mock data_callback
    data_callback = AsyncMock()

    # Create WebSocketClient instance
    client = WebSocketClient(
        auth_token="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpYXQiOjE3NTkzMjIxMjEsImV4cCI6MTc1OTQ5NDkyMSwic3ViIjoiNjA2ODYifQ.O4V7dfohNwGtYuNcR2O9SSiz3QY8dkzSpu6JGtmUxBo",
        device_serials=["1111111111", "2222222222"],
        data_callback=data_callback,
    )

    # Set up instance attributes for the test
    client.websocket = AsyncMock()  # Mock websocket, though not used in this path
    client._last_message_time = datetime.now()

    # Call the method under test
    await client._handle_message(message)
