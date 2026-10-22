import asyncio
import base64
import unittest
from unittest.mock import Mock

from govee_local_api.controller import (
    MAX_FRAMES_PER_PTREAL,
    PTREAL_MIN_INTERVAL,
    GoveeController,
)
from govee_local_api.device import GoveeDevice, SegmentUpdate
from govee_local_api.light_capabilities import (
    GOVEE_LIGHT_CAPABILITIES,
    create_with_capabilities,
)
from govee_local_api.message import (
    BrightnessMessage,
    PtRealMessage,
    SegmentBrightnessMessage,
    SegmentColorMessages,
    SegmentTemperatureMessage,
)


def frames_of(message: PtRealMessage) -> list[str]:
    """Hex of each frame in a ptReal message, without the checksum byte."""
    return [
        base64.b64decode(c)[:-1].hex(" ")
        for c in message.as_dict()["msg"]["data"]["command"]
    ]


def checksum_ok(message: PtRealMessage) -> bool:
    for c in message.as_dict()["msg"]["data"]["command"]:
        raw = base64.b64decode(c)
        x = 0
        for b in raw[:-1]:
            x ^= b
        if len(raw) != 20 or x != raw[-1]:
            return False
    return True


SEG_1_3 = b"\x07\x00"
SEG_9 = b"\x00\x01"


class TestSegmentMessages(unittest.TestCase):
    """Frames as verified on H6088 and H61E0 hardware."""

    def test_color_frame_unchanged(self):
        message = SegmentColorMessages(b"\x01\x00", (255, 0, 0))
        assert frames_of(message) == [
            "33 05 15 01 ff 00 00 00 00 00 00 00 01 00 00 00 00 00 00"
        ]
        assert checksum_ok(message)

    def test_temperature_frame(self):
        message = SegmentTemperatureMessage(SEG_1_3, 2700)
        assert frames_of(message) == [
            "33 05 15 01 00 00 00 0a 8c 00 00 00 07 00 00 00 00 00 00"
        ]
        assert checksum_ok(message)

    def test_brightness_frame_has_mask_right_after_the_value(self):
        message = SegmentBrightnessMessage(SEG_1_3, 5)
        assert frames_of(message) == [
            "33 05 15 02 05 07 00 00 00 00 00 00 00 00 00 00 00 00 00"
        ]
        assert checksum_ok(message)

    def test_brightness_is_clamped(self):
        assert frames_of(SegmentBrightnessMessage(SEG_9, 250))[0].startswith(
            "33 05 15 02 64 00 01"
        )


class SegmentControllerTest(unittest.TestCase):
    def setUp(self):
        self.controller = GoveeController.__new__(GoveeController)
        self.controller._send_message = Mock()
        self.controller._logger = Mock()

    def device(self, segments=6, temperature_range=None, sku="H6088"):
        capabilities = create_with_capabilities(
            True, True, True, segments, False, temperature_range=temperature_range
        )
        return GoveeDevice(self.controller, "192.168.1.100", "AA:BB", sku, capabilities)

    def sent(self) -> list[list[str]]:
        return [
            frames_of(c[0][0]) for c in self.controller._send_message.call_args_list
        ]


class TestSegmentMethods(SegmentControllerTest):
    def test_set_segment_temperature_clamps_to_the_device_range(self):
        device = self.device(temperature_range=(2700, 6500))
        asyncio.run(device.set_segment_temperature(2, 9000))
        assert self.sent() == [
            ["33 05 15 01 00 00 00 19 64 00 00 00 02 00 00 00 00 00 00"]
        ]

    def test_set_segment_brightness(self):
        device = self.device()
        asyncio.run(device.set_segment_brightness(3, 40))
        assert self.sent()[0][0].startswith("33 05 15 02 28 04 00")

    def test_invalid_segment_sends_nothing(self):
        device = self.device(segments=6)
        asyncio.run(device.set_segment_brightness(7, 40))
        asyncio.run(device.set_segment_temperature(0, 3000))
        self.controller._send_message.assert_not_called()

    def test_device_without_segments_sends_nothing(self):
        device = self.device(segments=0)
        asyncio.run(device.set_segments([SegmentUpdate(1, rgb=(1, 2, 3))]))
        self.controller._send_message.assert_not_called()


class TestSetSegments(SegmentControllerTest):
    def test_shared_settings_are_merged_into_one_frame(self):
        device = self.device(segments=6)
        red, blue = (255, 0, 0), (0, 0, 255)
        updates = [
            SegmentUpdate(i, rgb=red if i % 2 else blue, brightness=100)
            for i in range(1, 7)
        ]
        asyncio.run(device.set_segments(updates))
        assert self.sent() == [
            [
                "33 05 15 01 ff 00 00 00 00 00 00 00 15 00 00 00 00 00 00",
                "33 05 15 01 00 00 ff 00 00 00 00 00 2a 00 00 00 00 00 00",
                "33 05 15 02 64 3f 00 00 00 00 00 00 00 00 00 00 00 00 00",
            ]
        ]

    def test_temperature_and_brightness_mix(self):
        device = self.device(segments=15, temperature_range=(2700, 6500))
        asyncio.run(
            device.set_segments(
                [
                    SegmentUpdate(1, temperature=2700, brightness=10),
                    SegmentUpdate(9, temperature=2700, brightness=100),
                ]
            )
        )
        assert self.sent() == [
            [
                "33 05 15 01 00 00 00 0a 8c 00 00 00 01 01 00 00 00 00 00",
                "33 05 15 02 0a 01 00 00 00 00 00 00 00 00 00 00 00 00 00",
                "33 05 15 02 64 00 01 00 00 00 00 00 00 00 00 00 00 00 00",
            ]
        ]

    def test_large_changes_are_split_into_packets(self):
        device = self.device(segments=15)
        updates = [SegmentUpdate(i, rgb=(i, i, i), brightness=i) for i in range(1, 16)]
        asyncio.run(device.set_segments(updates))
        packets = self.sent()
        assert [len(p) for p in packets] == [
            MAX_FRAMES_PER_PTREAL,
            MAX_FRAMES_PER_PTREAL,
            30 - 2 * MAX_FRAMES_PER_PTREAL,
        ]

    def test_invalid_segments_are_skipped(self):
        device = self.device(segments=6)
        asyncio.run(
            device.set_segments(
                [SegmentUpdate(9, rgb=(1, 1, 1)), SegmentUpdate(1, rgb=(2, 2, 2))]
            )
        )
        assert self.sent() == [
            ["33 05 15 01 02 02 02 00 00 00 00 00 01 00 00 00 00 00 00"]
        ]


class FakeLoop:
    def __init__(self):
        self.now = 100.0
        self.later = []

    def time(self):
        return self.now

    def call_later(self, delay, fn, *args):
        self.later.append((delay, fn, args))


class TestPtRealPacing(unittest.TestCase):
    def setUp(self):
        self.controller = GoveeController.__new__(GoveeController)
        self.controller._loop = FakeLoop()
        self.controller._endpoints = [Mock()]
        self.controller._device_command_port = 4003
        self.transport = Mock()
        self.transport.is_closing.return_value = False

    def device(self, ip):
        device = GoveeDevice(self.controller, ip, ip, "H6088")
        device.update_transport(self.transport)
        return device

    def test_back_to_back_ptreal_packets_are_spaced(self):
        device = self.device("192.168.1.10")
        for _ in range(3):
            self.controller._send_message(
                SegmentColorMessages(b"\x01\x00", (1, 2, 3)), device
            )
        assert self.transport.sendto.call_count == 1
        delays = [round(d, 6) for d, _, _ in self.controller._loop.later]
        assert delays == [PTREAL_MIN_INTERVAL, 2 * PTREAL_MIN_INTERVAL]

    def test_standard_messages_are_never_delayed(self):
        device = self.device("192.168.1.10")
        self.controller._send_message(
            SegmentColorMessages(b"\x01\x00", (1, 2, 3)), device
        )
        self.controller._send_message(BrightnessMessage(50), device)
        assert self.transport.sendto.call_count == 2
        assert self.controller._loop.later == []

    def test_devices_are_paced_independently(self):
        a, b = self.device("192.168.1.10"), self.device("192.168.1.11")
        self.controller._send_message(SegmentColorMessages(b"\x01\x00", (1, 2, 3)), a)
        self.controller._send_message(SegmentColorMessages(b"\x01\x00", (1, 2, 3)), b)
        assert self.transport.sendto.call_count == 2

    def test_spacing_expires(self):
        device = self.device("192.168.1.10")
        self.controller._send_message(
            SegmentColorMessages(b"\x01\x00", (1, 2, 3)), device
        )
        self.controller._loop.now += 1
        self.controller._send_message(
            SegmentColorMessages(b"\x01\x00", (1, 2, 3)), device
        )
        assert self.transport.sendto.call_count == 2


def test_h61e0_has_15_segments():
    capabilities = GOVEE_LIGHT_CAPABILITIES["H61E0"]
    assert capabilities.segments_count == 15
    assert capabilities.segments[14] == b"\x00\x40"


def test_h6088_has_6_segments():
    assert GOVEE_LIGHT_CAPABILITIES["H6088"].segments_count == 6
