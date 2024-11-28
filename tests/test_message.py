from govee_local_api.message import (
    ScanMessage,
    ColorMessage,
    BrightnessMessage,
    OnOffMessage,
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
