"""H705E section addressing, verified against sanitized Govee app writes."""

import asyncio
import base64
import json
import logging
from pathlib import Path
from unittest.mock import Mock

import pytest

from govee_local_api.controller import GoveeController
from govee_local_api.device import GoveeDevice
from govee_local_api.light_capabilities import (
    GOVEE_LIGHT_CAPABILITIES,
    SEGMENT_CODES,
)
from govee_local_api.message import SegmentColorMessages


CAPTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "h705e_segment_colors.json").read_text()
)


def decode_frame(message):
    return base64.b64decode(message.as_dict()["msg"]["data"]["command"][0])


@pytest.mark.parametrize("command", CAPTURE["commands"])
def test_captured_extended_color_write(command):
    mask = GOVEE_LIGHT_CAPABILITIES["H705E"].segments[command["section"] - 1]
    message = SegmentColorMessages(mask, tuple(command["rgb"]))
    assert decode_frame(message).hex() == command["frame"]


@pytest.mark.parametrize("section", range(1, 16))
def test_legacy_sections_remain_byte_identical(section):
    rgb = (17, 85, 204)
    legacy_mask = (1 << (section - 1)).to_bytes(2, "little")
    payload = bytes.fromhex("33 05 15 01") + bytes(rgb) + bytes(5)
    payload += legacy_mask + bytes(5)
    checksum = 0
    for byte in payload:
        checksum ^= byte
    expected = payload + bytes([checksum])
    assert (
        decode_frame(SegmentColorMessages(SEGMENT_CODES[section - 1], rgb)) == expected
    )


@pytest.mark.parametrize("section", range(1, 22))
@pytest.mark.parametrize("rgb", [(0, 0, 0), (255, 137, 14)])
def test_all_sections_keep_frame_size_mask_and_checksum(section, rgb):
    frame = decode_frame(SegmentColorMessages(SEGMENT_CODES[section - 1], rgb))
    assert len(frame) == 20
    assert frame[:4] == bytes.fromhex("33 05 15 01")
    assert frame[4:7] == bytes(rgb)
    assert frame[7:12] == bytes(5)
    assert int.from_bytes(frame[12:19], "little") == 1 << (section - 1)
    checksum = 0
    for byte in frame:
        checksum ^= byte
    assert checksum == 0


def test_oversized_mask_is_rejected():
    with pytest.raises(ValueError, match="seven bytes"):
        SegmentColorMessages(bytes(8), (255, 0, 0))


def test_extended_sections_keep_color_clipping():
    frame = decode_frame(SegmentColorMessages(SEGMENT_CODES[20], (-1, 137, 256)))
    assert frame[4:7] == bytes([0, 137, 255])
    assert len(frame) == 20


def test_h705e_capabilities_expose_21_sections():
    assert GOVEE_LIGHT_CAPABILITIES["H705E"].segments_count == 21
    assert GOVEE_LIGHT_CAPABILITIES["H6076"].segments_count == 7
    assert GOVEE_LIGHT_CAPABILITIES["H705D"].segments_count == 9
    assert GOVEE_LIGHT_CAPABILITIES["H705F"].segments_count == 15
    # Existing counts above 15 are no longer truncated by the shared table.
    assert len(SEGMENT_CODES) == 21
    assert GOVEE_LIGHT_CAPABILITIES["H612D"].segments_count == 20
    assert GOVEE_LIGHT_CAPABILITIES["H6609"].segments_count == 18
    assert GOVEE_LIGHT_CAPABILITIES["H70A2"].segments_count == 20


@pytest.mark.parametrize("section", range(16, 22))
def test_extended_sections_use_normal_device_and_controller_path(section):
    controller = GoveeController.__new__(GoveeController)
    controller._logger = logging.getLogger(__name__)
    controller._send_message = Mock()
    device = GoveeDevice(
        controller,
        "192.0.2.1",
        "test-device",
        "H705E",
        GOVEE_LIGHT_CAPABILITIES["H705E"],
    )
    asyncio.run(device.set_segment_rgb_color(section, 255, 0, 0))
    controller._send_message.assert_called_once()
    message, target = controller._send_message.call_args.args
    assert target is device
    expected = next(
        c["frame"]
        for c in CAPTURE["commands"]
        if c["section"] == section and c["rgb"] == [255, 0, 0]
    )
    assert decode_frame(message).hex() == expected

    controller._send_message.reset_mock()
    asyncio.run(device.turn_segment_off(section))
    message, target = controller._send_message.call_args.args
    assert target is device
    frame = decode_frame(message)
    assert frame[4:7] == bytes(3)
    assert len(frame) == 20
    assert int.from_bytes(frame[12:19], "little") == 1 << (section - 1)


@pytest.mark.parametrize("sku,section", [("H705E", 0), ("H705E", 22), ("H705D", 16)])
def test_controller_keeps_model_specific_bounds(sku, section):
    controller = GoveeController.__new__(GoveeController)
    controller._logger = logging.getLogger(__name__)
    controller._send_message = Mock()
    device = GoveeDevice(
        controller, "192.0.2.1", "test-device", sku, GOVEE_LIGHT_CAPABILITIES[sku]
    )
    asyncio.run(device.set_segment_rgb_color(section, 255, 0, 0))
    controller._send_message.assert_not_called()
