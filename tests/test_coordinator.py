"""Unit tests for ComputhermDataUpdateCoordinator data merging."""

from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.computherm_b.const import DeviceAttributes as DA
from custom_components.computherm_b.coordinator import \
    ComputhermDataUpdateCoordinator as Coordinator


def _coordinator(sensor_readings):
    """A coordinator stand-in holding one device with the given sensor readings."""
    coordinator = SimpleNamespace(
        devices={"1111111111": {}},
        device_data={"1111111111": {DA.SENSOR_READINGS: sensor_readings, DA.ONLINE: True}},
        devices_with_base_info={},
        async_set_updated_data=MagicMock(),
        _fetch_sensor_metadata=AsyncMock(),
        _fetch_wifi_state=AsyncMock(),
    )
    for name in ("_process_device_update", "_process_base_info_update", "_process_state_update"):
        setattr(coordinator, name, MethodType(getattr(Coordinator, name), coordinator))
    return coordinator


@pytest.mark.asyncio
async def test_base_info_keeps_sensor_readings_missing_from_the_event():
    """A base_info event listing only some sensors must not drop the others' readings and error flags."""
    coordinator = _coordinator({
        "RELAY_1": {"name": "Primer előremenő", "reading": 25.4, DA.ERROR: False},
        "RELAY_2": {"name": "Primer visszatérő", "reading": 25.1, DA.ERROR: False},
    })

    coordinator._process_device_update("1111111111", {
        "base_info": {"id": 1},
        DA.ONLINE: True,
        DA.SENSOR_READINGS: {"RELAY_1": {"reading": 25.5}},
    })

    readings = coordinator.device_data["1111111111"][DA.SENSOR_READINGS]
    assert readings["RELAY_1"] == {"name": "Primer előremenő", "reading": 25.5, DA.ERROR: False}
    assert readings["RELAY_2"] == {"name": "Primer visszatérő", "reading": 25.1, DA.ERROR: False}
