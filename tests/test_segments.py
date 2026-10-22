import asyncio
import base64
import json
import unittest
from unittest.mock import Mock

import pytest

from govee_local_api.controller import (
    COMMAND_BUSY_TIME,
    MAX_FRAMES_PER_PTREAL,
    GoveeController,
)
from govee_local_api.device import GoveeDevice, SegmentUpdate
from govee_local_api.light_capabilities import (
    GOVEE_LIGHT_CAPABILITIES,
    create_with_capabilities,
)
from govee_local_api.message import (
    BrightnessMessage,
    ColorMessage,
    OnOffMessage,
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
        self.later.append((self.now + delay, fn, args))
        return Mock()

    def run_next(self):
        """Advance to the next timer and run it."""
        self.later.sort(key=lambda t: t[0])
        when, fn, args = self.later.pop(0)
        self.now = when
        fn(*args)


T = COMMAND_BUSY_TIME


class TestPacing(unittest.TestCase):
    def setUp(self):
        self.controller = GoveeController.__new__(GoveeController)
        self.loop = self.controller._loop = FakeLoop()
        self.controller._endpoints = [Mock()]
        self.controller._device_command_port = 4003
        self.controller._outbox = {}
        self.controller._busy_until = {}
        self.controller._outbox_handles = {}
        self.transport = Mock()
        self.transport.is_closing.return_value = False

    def device(self, ip="192.168.1.10"):
        device = GoveeDevice(self.controller, ip, ip, "H6088")
        device.update_transport(self.transport)
        return device

    def ptreal(self, red=1, frames=1):
        return PtRealMessage([bytes([0x33, 0x05, 0x15, 0x01, red] + [0] * 14)] * frames)

    def sent(self):
        """(time, cmd, frame count) of every packet sent so far."""
        out = []
        for c in self.transport.sendto.call_args_list:
            msg = json.loads(c[0][0])["msg"]
            count = len(msg["data"]["command"]) if msg["cmd"] == "ptReal" else 0
            out.append((msg["cmd"], count))
        return out

    def test_idle_device_gets_ptreal_immediately(self):
        self.controller._send_message(self.ptreal(), self.device())
        assert self.sent() == [("ptReal", 1)]
        assert self.loop.later == []

    def test_ptreal_waits_and_queued_ptreal_share_one_packet(self):
        device = self.device()
        for red in range(15):
            self.controller._send_message(self.ptreal(red), device)
        assert self.sent() == [("ptReal", 1)]
        assert len(self.loop.later) == 1
        self.loop.run_next()
        assert self.loop.now == pytest.approx(100.0 + T)
        assert self.sent() == [("ptReal", 1), ("ptReal", 12)]
        self.loop.run_next()
        assert self.loop.now == pytest.approx(100.0 + 2 * T)
        assert self.sent() == [("ptReal", 1), ("ptReal", 12), ("ptReal", 2)]
        assert self.loop.later == []

    def test_merged_frames_keep_their_order(self):
        device = self.device()
        for red in range(4):
            self.controller._send_message(self.ptreal(red), device)
        self.loop.run_next()
        packet = json.loads(self.transport.sendto.call_args[0][0])
        reds = [base64.b64decode(f)[4] for f in packet["msg"]["data"]["command"]]
        assert reds == [1, 2, 3]

    def test_large_message_is_never_merged_or_split(self):
        device = self.device()
        self.controller._send_message(self.ptreal(), device)
        self.controller._send_message(self.ptreal(frames=1), device)
        self.controller._send_message(self.ptreal(frames=14), device)
        self.loop.run_next()
        self.loop.run_next()
        assert self.sent() == [("ptReal", 1), ("ptReal", 1), ("ptReal", 14)]

    def times_sent(self):
        """Run every timer, recording (time, cmd) for each packet sent."""
        log = [(self.loop.now, cmd) for cmd, _ in self.sent()]
        while self.loop.later:
            before = len(self.sent())
            self.loop.run_next()
            log += [(self.loop.now, cmd) for cmd, _ in self.sent()[before:]]
        return [(pytest.approx(t - 100.0), cmd) for t, cmd in log]

    def test_every_message_waits_its_turn(self):
        device = self.device()
        self.controller._send_message(
            ColorMessage(rgb=(1, 2, 3), temperature=None), device
        )
        self.controller._send_message(BrightnessMessage(50), device)
        self.controller._send_message(self.ptreal(), device)
        assert self.times_sent() == [
            (0, "colorwc"),
            (T, "brightness"),
            (2 * T, "ptReal"),
        ]

    def test_standard_message_after_ptreal_waits(self):
        device = self.device()
        self.controller._send_message(self.ptreal(frames=2), device)
        self.controller._send_message(BrightnessMessage(50), device)
        self.controller._send_message(OnOffMessage(True), device)
        assert self.times_sent() == [
            (0, "ptReal"),
            (T, "brightness"),
            (2 * T, "turn"),
        ]

    def test_order_is_kept_and_only_neighbouring_ptreal_merge(self):
        device = self.device()
        self.controller._send_message(self.ptreal(), device)
        self.controller._send_message(self.ptreal(), device)
        self.controller._send_message(BrightnessMessage(50), device)
        self.controller._send_message(self.ptreal(), device)
        self.controller._send_message(self.ptreal(), device)
        assert self.times_sent() == [
            (0, "ptReal"),
            (T, "ptReal"),
            (2 * T, "brightness"),
            (3 * T, "ptReal"),
        ]
        assert [n for _, n in self.sent()] == [1, 1, 0, 2]

    def test_devices_are_paced_independently(self):
        self.controller._send_message(self.ptreal(), self.device("192.168.1.10"))
        self.controller._send_message(self.ptreal(), self.device("192.168.1.11"))
        assert self.sent() == [("ptReal", 1), ("ptReal", 1)]

    def test_busy_time_expires(self):
        device = self.device()
        self.controller._send_message(self.ptreal(), device)
        self.loop.now += T
        self.controller._send_message(self.ptreal(), device)
        assert self.sent() == [("ptReal", 1), ("ptReal", 1)]
        assert self.loop.later == []

    def test_nothing_is_queued_without_endpoints(self):
        self.controller._endpoints = []
        self.controller._send_message(self.ptreal(), self.device())
        assert self.controller._outbox == {}


def test_h61e0_has_15_segments():
    capabilities = GOVEE_LIGHT_CAPABILITIES["H61E0"]
    assert capabilities.segments_count == 15
    assert capabilities.segments[14] == b"\x00\x40"


def test_h6088_has_6_segments():
    assert GOVEE_LIGHT_CAPABILITIES["H6088"].segments_count == 6
