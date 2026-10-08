"""Unit tests for WebSocketClient in computherm_b integration."""

import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from websockets.exceptions import ConnectionClosedError

from custom_components.computherm_b.const import DeviceAttributes as DA
from custom_components.computherm_b.websocket import (DEVICE_DATA_TIMEOUT,
                                                      WebSocketClient,
                                                      WebSocketMessageHandler)


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
        device_serials=[
            "1111111111",
            "2222222222"],
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
        device_serials=[
            "1111111111",
            "2222222222"],
        data_callback=data_callback,
    )

    # Set up instance attributes for the test
    client.websocket = AsyncMock()  # Mock websocket, though not used in this path
    client._last_message_time = datetime.now()

    # Call the method under test
    await client._handle_message(message)


@pytest.mark.asyncio
async def test_process_messages_connection_closed_without_close_frame(caplog):
    """A connection dropped without a close frame (rcvd is None) exits for reconnect, not as an error."""
    client = WebSocketClient(
        auth_token="token",
        device_serials=["1111111111"],
        data_callback=MagicMock(),
    )
    client.websocket = AsyncMock()
    client.websocket.recv.side_effect = ConnectionClosedError(None, None)

    await client._process_messages()

    assert "Error receiving message" not in caplog.text
    assert "WebSocket connection closed" in caplog.text


def test_process_relays_and_readings_store_diagnostic_fields():
    """Error flags and relay settings from a WebSocket event are stored for the entities."""
    device_update = {}
    WebSocketMessageHandler._process_readings(
        [{"src": "RELAY", "sensor": 1, "type": "TEMPERATURE", "reading": 27.7, "err": True}],
        "1111111111", device_update)
    WebSocketMessageHandler._process_relays(
        [{"relay": 1, "err": False, "boost_active": True, "boost_remaining": 30, "boost_set_point": 27.5,
          "hysteresis_low": 0.1, "hysteresis_high": "N/A", "active_schedule": 1}],
        "1111111111", device_update)

    assert device_update[DA.SENSOR_READINGS]["RELAY_1"][DA.ERROR] is True
    assert device_update[DA.RELAY_ERROR] is False
    assert device_update[DA.BOOST_ACTIVE] is True
    assert device_update[DA.BOOST_REMAINING] == 30
    assert device_update[DA.BOOST_SET_POINT] == 27.5
    assert device_update[DA.HYSTERESIS_LOW] == 0.1
    assert device_update[DA.HYSTERESIS_HIGH] is None
    assert device_update[DA.ACTIVE_SCHEDULE] == 1


def test_process_relays_without_diagnostic_fields_leaves_them_unset():
    """Partial relay updates must not overwrite stored values with None."""
    device_update = {}
    WebSocketMessageHandler._process_relays([{"relay": 1, "relay_state": "ON"}], "1111111111", device_update)

    for key in (DA.RELAY_ERROR, DA.BOOST_ACTIVE, DA.HYSTERESIS_LOW, DA.ACTIVE_SCHEDULE):
        assert key not in device_update


def _client():
    return WebSocketClient(auth_token="token", device_serials=["1111111111"], data_callback=MagicMock())


@pytest.mark.asyncio
async def test_namespace_disconnect_closes_connection_for_reconnect():
    """After '41/devices' no device events arrive, so the connection is closed to resubscribe."""
    client = _client()
    client.websocket = AsyncMock()
    client._last_message_time = datetime.now()

    await client._handle_message("41/devices,")

    client.websocket.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_watchdog_reconnects_when_device_data_is_stale(monkeypatch):
    """Pings keep the connection alive; stale device data must still force a reconnect."""
    client = _client()
    client.websocket = AsyncMock()
    client._last_message_time = datetime.now()
    client._ping_interval = 25.0
    client._last_event_time = datetime.now() - timedelta(seconds=DEVICE_DATA_TIMEOUT + 1)

    async def stop_after_one_round(_):
        client._stopping = True
    monkeypatch.setattr(asyncio, "sleep", stop_after_one_round)

    await client._connection_watchdog()
    await asyncio.gather(*[t for t in asyncio.all_tasks() if t is not asyncio.current_task()])

    client.websocket.close.assert_awaited_once()
    assert client._last_event_time is None


@pytest.mark.asyncio
async def test_watchdog_keeps_connection_with_recent_device_data(monkeypatch):
    """Fresh device data and pings: no reconnect."""
    client = _client()
    client.websocket = AsyncMock()
    client._last_message_time = datetime.now()
    client._ping_interval = 25.0
    client._last_event_time = datetime.now()

    async def stop_after_one_round(_):
        client._stopping = True
    monkeypatch.setattr(asyncio, "sleep", stop_after_one_round)

    await client._connection_watchdog()

    client.websocket.close.assert_not_awaited()
