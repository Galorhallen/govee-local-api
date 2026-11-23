"""Zone control for multi-zone lamps (H60B0 Uplighter).

The expected frames are the exact base64 commands an H60B0 (wifi 1.06.24,
ble 1.00.12) accepted over LAN, with the visible result checked on the lamp.
"""

import asyncio
import logging
import unittest
from unittest.mock import Mock

import pytest

from govee_local_api.controller import GoveeController
from govee_local_api.device import GoveeDevice
from govee_local_api.light_capabilities import (
    BASIC_CAPABILITIES,
    GOVEE_LIGHT_CAPABILITIES,
    UPLIGHTER_ZONES,
    GoveeLightCapabilities,
    GoveeLightFeatures,
    GoveeLightZone,
    create_with_capabilities,
)
from govee_local_api.message import (
    ZoneBrightnessMessage,
    ZoneColorMessage,
    ZoneFlowSpeedMessage,
    ZoneOnOffMessage,
)

RIPPLE, SIDE, LOWER = 1, 2, 3


def _commands(message) -> list[str]:
    return message.as_dict()["msg"]["data"]["command"]


@pytest.mark.parametrize(
    "zone,on,expected",
    [
        (RIPPLE, True, "MzABAQAAAAAAAAAAAAAAAAAAAAM="),
        (RIPPLE, False, "MzABAAAAAAAAAAAAAAAAAAAAAAI="),
        (SIDE, True, "MzACAQAAAAAAAAAAAAAAAAAAAAA="),
        (SIDE, False, "MzACAAAAAAAAAAAAAAAAAAAAAAE="),
        (LOWER, True, "MzADAQAAAAAAAAAAAAAAAAAAAAE="),
        (LOWER, False, "MzADAAAAAAAAAAAAAAAAAAAAAAA="),
    ],
)
def test_zone_on_off_frames(zone, on, expected):
    message = ZoneOnOffMessage(zone, on)
    assert message.as_dict()["msg"]["cmd"] == "ptReal"
    assert _commands(message) == [expected]


@pytest.mark.parametrize(
    "zone,rgb,mask,expected",
    [
        (RIPPLE, (0x80, 0x00, 0xFF), None, "MwUsAQGAAP8AAAAAAAAAAAAAAGU="),
        (SIDE, (0xFF, 0x00, 0x00), 0xFF, "MwUsAgH/AAAAAP8AAAAAAAAAABk="),
        (SIDE, (0x00, 0x00, 0xFF), 0xFF, "MwUsAgEAAP8AAP8AAAAAAAAAABk="),
        (SIDE, (0x00, 0xFF, 0x00), 0x0F, "MwUsAgEA/wAAAA8AAAAAAAAAAOk="),
    ],
)
def test_zone_color_frames(zone, rgb, mask, expected):
    assert _commands(ZoneColorMessage(zone, rgb=rgb, segment_mask=mask)) == [expected]


@pytest.mark.parametrize(
    "kelvin,expected",
    [
        (2700, "MwUsAwEKjAAAAAAAAAAAAAAAAJ4="),
        (4000, "MwUsAwEPoAAAAAAAAAAAAAAAALc="),
        (6500, "MwUsAwEZZAAAAAAAAAAAAAAAAGU="),
    ],
)
def test_white_only_zone_temperature_has_no_rgb_bytes(kelvin, expected):
    message = ZoneColorMessage(LOWER, temperature=kelvin, white_only=True)
    assert _commands(message) == [expected]


@pytest.mark.parametrize(
    "zone,brightness,mask,expected",
    [
        (RIPPLE, 10, None, "MwUsAQIKAAAAAAAAAAAAAAAAABM="),
        (RIPPLE, 20, None, "MwUsAQIUAAAAAAAAAAAAAAAAAA0="),
        (RIPPLE, 100, None, "MwUsAQJkAAAAAAAAAAAAAAAAAH0="),
        (SIDE, 20, 0xFF, "MwUsAgIU/wAAAAAAAAAAAAAAAPE="),
        (SIDE, 100, 0xFF, "MwUsAgJk/wAAAAAAAAAAAAAAAIE="),
        (LOWER, 5, None, "MwUsAwIFAAAAAAAAAAAAAAAAAB4="),
        (LOWER, 50, None, "MwUsAwIyAAAAAAAAAAAAAAAAACk="),
        (LOWER, 100, None, "MwUsAwJkAAAAAAAAAAAAAAAAAH8="),
    ],
)
def test_zone_brightness_frames(zone, brightness, mask, expected):
    assert _commands(ZoneBrightnessMessage(zone, brightness, mask)) == [expected]


@pytest.mark.parametrize(
    "speed,expected",
    [
        (0, "MwUsAQMAAAAAAAAAAAAAAAAAABg="),
        (100, "MwUsAQNkAAAAAAAAAAAAAAAAAHw="),
    ],
)
def test_zone_flow_speed_frames(speed, expected):
    assert _commands(ZoneFlowSpeedMessage(RIPPLE, speed)) == [expected]


def test_zone_values_are_clamped():
    assert _commands(ZoneBrightnessMessage(RIPPLE, 0)) == _commands(
        ZoneBrightnessMessage(RIPPLE, 1)
    )
    assert _commands(ZoneBrightnessMessage(RIPPLE, 250)) == _commands(
        ZoneBrightnessMessage(RIPPLE, 100)
    )
    assert _commands(ZoneFlowSpeedMessage(RIPPLE, 300)) == _commands(
        ZoneFlowSpeedMessage(RIPPLE, 100)
    )
    assert _commands(ZoneColorMessage(RIPPLE, rgb=(300, -5, 128))) == _commands(
        ZoneColorMessage(RIPPLE, rgb=(255, 0, 128))
    )


def test_zone_color_needs_exactly_one_of_rgb_or_temperature():
    with pytest.raises(ValueError):
        ZoneColorMessage(RIPPLE)
    with pytest.raises(ValueError):
        ZoneColorMessage(RIPPLE, rgb=(1, 2, 3), temperature=3000)
    with pytest.raises(ValueError):
        ZoneColorMessage(LOWER, rgb=(1, 2, 3), white_only=True)


def test_h60b0_registers_its_zones():
    capabilities = GOVEE_LIGHT_CAPABILITIES["H60B0"]
    assert capabilities.features & GoveeLightFeatures.ZONES
    assert capabilities.zones == UPLIGHTER_ZONES
    assert capabilities.max_active_zones == 2
    assert capabilities.temperature_range == (2700, 6500)
    # The scene rebuild at import keeps the zones and the base features.
    assert capabilities.features & GoveeLightFeatures.COLOR_RGB
    assert capabilities.get_zone(SIDE).segments == 8
    assert capabilities.get_zone(LOWER).rgb is False
    assert capabilities.get_zone(4) is None


def test_models_without_zones_have_none():
    assert BASIC_CAPABILITIES.zones == ()
    assert BASIC_CAPABILITIES.max_active_zones == 0
    assert not BASIC_CAPABILITIES.features & GoveeLightFeatures.ZONES


def test_zones_are_ignored_without_the_zones_feature():
    capabilities = GoveeLightCapabilities(
        GoveeLightFeatures.COLOR_RGB, zones=UPLIGHTER_ZONES, max_active_zones=2
    )
    assert capabilities.zones == ()
    assert capabilities.max_active_zones == 0


def test_max_active_zones_defaults_to_every_zone():
    zones = (GoveeLightZone(1, "a", True, True), GoveeLightZone(2, "b", True, True))
    capabilities = create_with_capabilities(True, True, True, 0, zones=zones)
    assert capabilities.max_active_zones == 2


class TestControllerZones(unittest.TestCase):
    def setUp(self):
        self.controller = GoveeController.__new__(GoveeController)
        self.controller._send_message = Mock()
        self.controller._logger = logging.getLogger("test_zones")
        self.device = GoveeDevice(
            self.controller,
            "192.168.1.100",
            "AA:BB:CC:DD:EE:FF",
            "H60B0",
            GOVEE_LIGHT_CAPABILITIES["H60B0"],
        )

    def _run(self, coroutine):
        asyncio.run(coroutine)

    def _sent(self) -> list[str]:
        self.controller._send_message.assert_called_once()
        message, device = self.controller._send_message.call_args[0]
        assert device is self.device
        return _commands(message)

    def test_zone_on_off(self):
        self._run(self.device.set_zone_on_off(SIDE, True))
        assert self._sent() == ["MzACAQAAAAAAAAAAAAAAAAAAAAA="]

    def test_segmented_zone_color_defaults_to_every_segment(self):
        self._run(self.device.set_zone_rgb_color(SIDE, 255, 0, 0))
        assert self._sent() == ["MwUsAgH/AAAAAP8AAAAAAAAAABk="]

    def test_segmented_zone_color_on_some_segments(self):
        self._run(self.device.set_zone_rgb_color(SIDE, 0, 255, 0, [1, 2, 3, 4]))
        assert self._sent() == ["MwUsAgEA/wAAAA8AAAAAAAAAAOk="]

    def test_zone_without_segments_sends_no_mask(self):
        self._run(self.device.set_zone_rgb_color(RIPPLE, 0x80, 0, 0xFF))
        assert self._sent() == ["MwUsAQGAAP8AAAAAAAAAAAAAAGU="]

    def test_white_only_zone_temperature(self):
        self._run(self.device.set_zone_temperature(LOWER, 2700))
        assert self._sent() == ["MwUsAwEKjAAAAAAAAAAAAAAAAJ4="]

    def test_zone_temperature_is_clamped_to_the_device_range(self):
        # Outside 2700-6500 K the lower light blacks out (issue #296).
        self._run(self.device.set_zone_temperature(LOWER, 9000))
        assert self._sent() == ["MwUsAwEZZAAAAAAAAAAAAAAAAGU="]

    def test_zone_brightness(self):
        self._run(self.device.set_zone_brightness(LOWER, 5))
        assert self._sent() == ["MwUsAwIFAAAAAAAAAAAAAAAAAB4="]

    def test_segmented_zone_brightness(self):
        self._run(self.device.set_zone_brightness(SIDE, 20))
        assert self._sent() == ["MwUsAgIU/wAAAAAAAAAAAAAAAPE="]

    def test_zone_flow_speed(self):
        self._run(self.device.set_zone_flow_speed(RIPPLE, 100))
        assert self._sent() == ["MwUsAQNkAAAAAAAAAAAAAAAAAHw="]

    def test_rgb_on_a_white_only_zone_is_not_sent(self):
        self._run(self.device.set_zone_rgb_color(LOWER, 255, 0, 0))
        self.controller._send_message.assert_not_called()

    def test_ripple_temperature(self):
        self._run(self.device.set_zone_temperature(RIPPLE, 2700))
        assert self._sent() == ["MwUsAQH///8KjAAAAAAAAAAAAGM="]

    def test_side_temperature_uses_white_rgb_and_every_segment(self):
        self._run(self.device.set_zone_temperature(SIDE, 6500))
        assert self._sent() == ["MwUsAgH///8ZZP8AAAAAAAAAAGQ="]

    def test_flow_speed_on_a_zone_without_it_is_not_sent(self):
        self._run(self.device.set_zone_flow_speed(LOWER, 50))
        self.controller._send_message.assert_not_called()

    def test_unknown_zone_is_not_sent(self):
        self._run(self.device.set_zone_on_off(4, True))
        self.controller._send_message.assert_not_called()

    def test_invalid_segment_is_not_sent(self):
        self._run(self.device.set_zone_rgb_color(SIDE, 1, 2, 3, [9]))
        self.controller._send_message.assert_not_called()

    def test_segments_on_a_zone_without_segments_are_not_sent(self):
        self._run(self.device.set_zone_brightness(RIPPLE, 50, [1]))
        self.controller._send_message.assert_not_called()

    def test_device_without_zones_is_not_sent(self):
        device = GoveeDevice(
            self.controller, "192.168.1.101", "AA:BB", "H6004", BASIC_CAPABILITIES
        )
        self._run(device.set_zone_on_off(RIPPLE, True))
        self.controller._send_message.assert_not_called()
