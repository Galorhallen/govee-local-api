import base64

import pytest

from govee_local_api.light_capabilities import DEFAULT_TEMPERATURE_RANGE
from govee_local_api.message import (
    ScanMessage,
    ColorMessage,
    PtRealMessage,
    SceneCodeMessage,
    SceneMessages,
    BrightnessMessage,
    OnOffMessage,
    MessageResponseFactory,
    ScanResponse,
    DevStatusResponse,
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


def test_color_clipping_falls_back_to_the_default_range():
    """The unclamped default comes from the capability registry, not a
    constant duplicated in the message layer."""
    min_kelvin, max_kelvin = DEFAULT_TEMPERATURE_RANGE

    msg = ColorMessage(rgb=None, temperature=min_kelvin - 1)
    assert msg.as_dict()["msg"]["data"]["colorTemInKelvin"] == min_kelvin

    msg = ColorMessage(rgb=None, temperature=max_kelvin + 1)
    assert msg.as_dict()["msg"]["data"]["colorTemInKelvin"] == max_kelvin


def test_color_clipping_with_custom_temperature_range():
    msg = ColorMessage(rgb=None, temperature=2000, temperature_range=(2700, 6500))
    assert msg.as_dict()["msg"]["data"]["colorTemInKelvin"] == 2700

    msg = ColorMessage(rgb=None, temperature=9000, temperature_range=(2700, 6500))
    assert msg.as_dict()["msg"]["data"]["colorTemInKelvin"] == 6500

    msg = ColorMessage(rgb=None, temperature=4000, temperature_range=(2700, 6500))
    assert msg.as_dict()["msg"]["data"]["colorTemInKelvin"] == 4000


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


# --- MessageResponseFactory robustness (C2) ---


def test_factory_returns_none_for_invalid_json() -> None:
    factory = MessageResponseFactory()
    assert factory.create_message(b"not-json") is None
    assert factory.create_message(b"") is None
    assert factory.create_message(b"\x00\x01\x02") is None


def test_factory_returns_none_for_missing_msg_wrapper() -> None:
    factory = MessageResponseFactory()
    assert factory.create_message(b'{"foo": "bar"}') is None
    assert factory.create_message(b"[]") is None
    assert factory.create_message(b'"string"') is None


def test_factory_returns_none_for_missing_data_field() -> None:
    """Previously this raised KeyError because the guard only triggered when
    BOTH cmd and data were missing."""
    factory = MessageResponseFactory()
    assert factory.create_message(b'{"msg": {"cmd": "scan"}}') is None


def test_factory_returns_none_for_missing_cmd_field() -> None:
    factory = MessageResponseFactory()
    assert factory.create_message(b'{"msg": {"data": {}}}') is None


def test_factory_returns_none_for_unknown_command() -> None:
    """Previously this raised StopIteration."""
    factory = MessageResponseFactory()
    assert factory.create_message(b'{"msg": {"cmd": "future-cmd", "data": {}}}') is None


def test_factory_returns_scan_response_for_valid_scan() -> None:
    factory = MessageResponseFactory()
    payload = (
        b'{"msg": {"cmd": "scan", "data": '
        b'{"device": "ab:cd", "sku": "H6008", "ip": "192.168.1.42"}}}'
    )
    message = factory.create_message(payload)
    assert isinstance(message, ScanResponse)
    assert message.device == "ab:cd"
    assert message.sku == "H6008"
    assert message.ip == "192.168.1.42"


def test_factory_returns_dev_status_response_for_valid_dev_status() -> None:
    factory = MessageResponseFactory()
    payload = (
        b'{"msg": {"cmd": "devStatus", "data": '
        b'{"onOff": 1, "brightness": 50, "color": {"r": 1, "g": 2, "b": 3},'
        b' "colorTemInKelvin": 4000}}}'
    )
    message = factory.create_message(payload)
    assert isinstance(message, DevStatusResponse)
    assert message.is_on is True
    assert message.brightness == 50
    assert message.color == (1, 2, 3)
    assert message.color_temperature == 4000


# --- ColorMessage input validation (C4) ---


def test_color_message_raises_on_no_input() -> None:
    """rgb=None + temperature=None|0 used to raise UnboundLocalError."""
    with pytest.raises(ValueError):
        ColorMessage(rgb=None, temperature=None)
    with pytest.raises(ValueError):
        ColorMessage(rgb=None, temperature=0)


# --- DevStatusResponse defensive accessors (H1) ---


def test_dev_status_response_handles_missing_onoff() -> None:
    """A partial payload must not raise; defaults are safe."""
    msg = DevStatusResponse(
        {"brightness": 50, "color": {"r": 1, "g": 2, "b": 3}, "colorTemInKelvin": 4000}
    )
    assert msg.is_on is False  # safe default
    assert msg.brightness == 50
    assert msg.color == (1, 2, 3)
    assert msg.color_temperature == 4000


def test_dev_status_response_handles_missing_color() -> None:
    msg = DevStatusResponse({"onOff": 1, "brightness": 50, "colorTemInKelvin": 4000})
    assert msg.is_on is True
    assert msg.color == (0, 0, 0)
    assert msg.color_temperature == 4000


def test_dev_status_response_handles_partial_color_dict() -> None:
    """Only some of r/g/b are present."""
    msg = DevStatusResponse(
        {"onOff": 1, "color": {"r": 200}, "brightness": 50, "colorTemInKelvin": 4000}
    )
    assert msg.color == (200, 0, 0)


def test_dev_status_response_handles_null_color() -> None:
    """color = None in the payload — previously raised TypeError."""
    msg = DevStatusResponse(
        {"onOff": 1, "color": None, "brightness": 50, "colorTemInKelvin": 4000}
    )
    assert msg.color == (0, 0, 0)


def test_dev_status_response_handles_empty_payload() -> None:
    """No fields at all. Every accessor must return its safe default."""
    msg = DevStatusResponse({})
    assert msg.is_on is False
    assert msg.color == (0, 0, 0)
    assert msg.brightness == 0
    assert msg.color_temperature == 0


# --- SceneCodeMessage (library scenes) ---

# "Forest" scene test vector from wez/govee2mqtt src/ble.rs (scene_command test).
FOREST_SCENE_CODE = 212
FOREST_SCENE_PARAM = base64.b64decode(
    "AyYAAQAKAgH/GQG0CgoCyBQF//8AAP//////AP//lP8AFAGWAAAAACMAAg8FAgH/FAH7AAAB+goE"
    "BP8AtP8AR///4/8AAAAAAAAAABoAAAABAgH/BQHIFBQC7hQBAP8AAAAAAAAAAA=="
)
FOREST_EXPECTED_FRAMES = [
    bytes.fromhex(line)
    for line in (
        "a3 00 01 07 02 03 26 00 01 00 0a 02 01 ff 19 01 b4 0a 0a d9",
        "a3 01 02 c8 14 05 ff ff 00 00 ff ff ff ff ff 00 ff ff 94 12",
        "a3 02 ff 00 14 01 96 00 00 00 00 23 00 02 0f 05 02 01 ff 0a",
        "a3 03 14 01 fb 00 00 01 fa 0a 04 04 ff 00 b4 ff 00 47 ff b3",
        "a3 04 ff e3 ff 00 00 00 00 00 00 00 00 1a 00 00 00 01 02 5d",
        "a3 05 01 ff 05 01 c8 14 14 02 ee 14 01 00 ff 00 00 00 00 92",
        "a3 ff 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 5c",
        "33 05 04 d4 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 e6",
    )
]


def _frames(message: PtRealMessage) -> list[bytes]:
    return [
        base64.b64decode(frame) for frame in message.as_dict()["msg"]["data"]["command"]
    ]


def test_scene_code_message_matches_govee2mqtt_forest_vector() -> None:
    msg = SceneCodeMessage(FOREST_SCENE_CODE, FOREST_SCENE_PARAM)
    assert msg.as_dict()["msg"]["cmd"] == "ptReal"
    assert _frames(msg) == FOREST_EXPECTED_FRAMES


def test_scene_code_message_frames_are_20_bytes_with_xor_checksum() -> None:
    for frame in _frames(SceneCodeMessage(FOREST_SCENE_CODE, FOREST_SCENE_PARAM)):
        assert len(frame) == 20
        checksum = 0
        for byte in frame[:19]:
            checksum ^= byte
        assert frame[19] == checksum


def test_scene_code_message_without_param_equals_scene_messages() -> None:
    """A library scene with no parameters is the same single frame the
    built-in scene list sends."""
    assert _frames(SceneCodeMessage(8)) == _frames(SceneMessages(b"\x08"))


def test_scene_code_message_encodes_code_little_endian() -> None:
    (frame,) = _frames(SceneCodeMessage(0x2B96))
    assert frame[:5] == b"\x33\x05\x04\x96\x2b"


def test_scene_code_message_param_fitting_in_first_frame() -> None:
    """Up to 14 parameter bytes fit after the 5-byte header, so the first
    frame is also the last one: index 0xff and a frame count of 1."""
    frames = _frames(SceneCodeMessage(1, bytes(range(14))))
    assert len(frames) == 2
    assert frames[0][:5] == b"\xa3\xff\x01\x01\x02"
    assert frames[0][5:19] == bytes(range(14))


def test_scene_code_message_rejects_out_of_range_code() -> None:
    with pytest.raises(ValueError):
        SceneCodeMessage(-1)
    with pytest.raises(ValueError):
        SceneCodeMessage(0x10000)
