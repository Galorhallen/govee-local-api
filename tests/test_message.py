import base64

from govee_local_api.message import (
    ScanMessage,
    ColorMessage,
    BrightnessMessage,
    OnOffMessage,
    MultiSegmentColorMessage,
)


def test_scan_message() -> None:
    msg: ScanMessage = ScanMessage()
    assert msg.as_dict() == {
        "msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}
    }


def test_color_message_ok():
    msg: ColorMessage = ColorMessage(rgb=(64, 128, 255), temperature=None)
    assert msg.as_dict() == {
        "msg": {
            "cmd": "colorwc",
            "data": {"color": {"r": 64, "g": 128, "b": 255}, "colorTemInKelvin": 0},
        }
    }

    msg = ColorMessage(rgb=None, temperature=5000)
    assert msg.as_dict() == {
        "msg": {
            "cmd": "colorwc",
            "data": {"color": {"r": 0, "g": 0, "b": 0}, "colorTemInKelvin": 5000},
        }
    }

    msg: ColorMessage = ColorMessage(rgb=(64, 128, 255), temperature=5000)
    assert msg.as_dict() == {
        "msg": {
            "cmd": "colorwc",
            "data": {"color": {"r": 64, "g": 128, "b": 255}, "colorTemInKelvin": 0},
        }
    }


def test_color_clipping():
    msg: ColorMessage = ColorMessage(rgb=(-500, 42, 500), temperature=None)
    assert msg.as_dict() == {
        "msg": {
            "cmd": "colorwc",
            "data": {"color": {"r": 0, "g": 42, "b": 255}, "colorTemInKelvin": 0},
        }
    }

    msg = ColorMessage(rgb=None, temperature=1)
    assert msg.as_dict() == {
        "msg": {
            "cmd": "colorwc",
            "data": {"color": {"r": 0, "g": 0, "b": 0}, "colorTemInKelvin": 2000},
        }
    }

    msg = ColorMessage(rgb=None, temperature=9999)
    assert msg.as_dict() == {
        "msg": {
            "cmd": "colorwc",
            "data": {"color": {"r": 0, "g": 0, "b": 0}, "colorTemInKelvin": 9000},
        }
    }


def test_brightness():
    msg: BrightnessMessage = BrightnessMessage(42)
    assert msg.as_dict() == {
        "msg": {
            "cmd": "brightness",
            "data": {"value": 42},
        }
    }


def test_brightness_clipping():
    msg: BrightnessMessage = BrightnessMessage(-5)
    assert msg.as_dict() == {
        "msg": {
            "cmd": "brightness",
            "data": {"value": 0},
        }
    }

    msg: BrightnessMessage = BrightnessMessage(101)
    assert msg.as_dict() == {
        "msg": {
            "cmd": "brightness",
            "data": {"value": 100},
        }
    }


def test_on_off():
    msg: OnOffMessage = OnOffMessage(True)
    assert msg.as_dict() == {"msg": {"cmd": "turn", "data": {"value": 1}}}

    msg: OnOffMessage = OnOffMessage(False)
    assert msg.as_dict() == {"msg": {"cmd": "turn", "data": {"value": 0}}}


def test_multi_segment_color_single():
    """Test single segment color message."""
    msg = MultiSegmentColorMessage([1], (255, 0, 0))
    data = msg.data["command"][0]
    decoded = base64.b64decode(data)
    assert decoded[0:4] == b"\x33\x05\x15\x01"
    assert decoded[4:7] == bytes([255, 0, 0])
    assert decoded[12:14] == b"\x01\x00"


def test_multi_segment_color_multiple():
    """Test multiple segments color message with bitmask."""
    msg = MultiSegmentColorMessage([1, 2, 3], (0, 255, 0))
    data = msg.data["command"][0]
    decoded = base64.b64decode(data)
    assert decoded[4:7] == bytes([0, 255, 0])
    assert decoded[12:14] == b"\x07\x00"


def test_multi_segment_color_all_nine():
    """Test all 9 segments (bitmask 0x1FF)."""
    msg = MultiSegmentColorMessage([1, 2, 3, 4, 5, 6, 7, 8, 9], (0, 0, 255))
    data = msg.data["command"][0]
    decoded = base64.b64decode(data)
    assert decoded[4:7] == bytes([0, 0, 255])
    assert decoded[12:14] == b"\xff\x01"


def test_multi_segment_color_with_brightness():
    """Test segment color with brightness scaling."""
    msg = MultiSegmentColorMessage([1], (255, 100, 50), brightness=50)
    data = msg.data["command"][0]
    decoded = base64.b64decode(data)
    assert decoded[4:7] == bytes([127, 50, 25])


def test_multi_segment_color_brightness_zero():
    """Test segment with 0% brightness (off)."""
    msg = MultiSegmentColorMessage([1, 2, 3], (255, 255, 255), brightness=0)
    data = msg.data["command"][0]
    decoded = base64.b64decode(data)
    assert decoded[4:7] == bytes([0, 0, 0])


def test_multi_segment_color_invalid_segments():
    """Test that invalid segment indices are ignored."""
    msg = MultiSegmentColorMessage([0, 1, 16, 20], (255, 0, 0))
    data = msg.data["command"][0]
    decoded = base64.b64decode(data)
    assert decoded[12:14] == b"\x01\x00"
