import pytest

from govee_local_api.message import (
    ScanMessage,
    ColorMessage,
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
    assert (
        factory.create_message(b'{"msg": {"cmd": "future-cmd", "data": {}}}')
        is None
    )


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
    msg = DevStatusResponse(
        {"onOff": 1, "brightness": 50, "colorTemInKelvin": 4000}
    )
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
