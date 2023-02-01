from __future__ import annotations, absolute_import

from typing import Any, Tuple
import json


class GoveeMessage:
    command: str = None

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def as_dict(self) -> dict[str, Any]:
        return {"msg": {"cmd": self.command, "data": self.data}}

    def as_json(self) -> str:
        return json.dumps(self.as_dict())

    def __bytes__(self) -> bytearray | bytes:
        return self.as_json().encode("utf-8")

    def __str__(self) -> str:
        return self.as_json()

    @property
    def data(self) -> dict[str, Any]:
        return self._data


class ScanMessage(GoveeMessage):
    command = "scan"

    def __init__(self) -> None:
        super().__init__({"account_topic": "reserve"})


class StatusMessage(GoveeMessage):
    command = "devStatus"

    def __init__(self) -> None:
        super().__init__({})


class OnOffMessage(GoveeMessage):
    command = "turn"

    def __init__(self, on: bool) -> None:
        super().__init__({"value": int(on)})


class BrightnessMessage(GoveeMessage):
    command = "brightness"

    def __init__(self, brightness_pct: int) -> None:
        super().__init__({"value": max(0, min(brightness_pct, 100))})


class ColorMessage(GoveeMessage):
    TEMPERATURE_MAX_KELVIN = 9000
    TEMPERATURE_MIN_KELVIN = 2000

    command = "colorwc"

    def __init__(self, *, rgb: Tuple(int, int, int), temperature: int) -> None:
        if rgb:
            rgb = [max(0, min(c, 255)) for c in rgb]
            data = {
                "color": {"r": rgb[0], "g": rgb[1], "b": rgb[2]},
                "colorTemInKelvin": 0,
            }
        elif temperature:
            data = {
                "color": {"r": 0, "g": 0, "b": 0},
                "colorTemInKelvin": max(
                    self.TEMPERATURE_MIN_KELVIN,
                    min(temperature, self.TEMPERATURE_MAX_KELVIN),
                ),
            }

        super().__init__(data)


class ScanResponse(GoveeMessage):
    command = "scan"

    def __init__(self, data: dict[str, Any]) -> None:
        super().__init__(data)

    @property
    def device(self):
        return self._data["device"]

    @property
    def sku(self):
        return self._data["sku"]

    @property
    def ip(self):
        return self._data["ip"]


class StatusResponse(GoveeMessage):
    command = "devStatus"

    def __init__(self, data: dict[str, Any]) -> None:
        super().__init__(data)

    @property
    def is_on(self) -> bool:
        return bool(self._data["onOff"])

    @property
    def color(self) -> tuple(int, int, int):
        color = self._data["color"]
        return (color["r"], color["g"], color["b"])

    @property
    def brightness(self) -> int:
        return self._data["brightness"]

    @property
    def color_temperature(self) -> int:
        return self._data["colorTemInKelvin"]


class MessageResponseFactory:
    def __init__(self) -> None:
        self._messages: dict[str, GoveeMessage] = {ScanResponse, StatusResponse}

    def add_message(self, cls: GoveeMessage) -> None:
        self._messages[cls.command] = cls

    def remove_message(self, command: str) -> None:
        if command in self._messages:
            del self._messages[command]

    def create_message(self, data: bytes | bytearray | str) -> GoveeMessage:
        msg_json = json.loads(data)
        if (
            "msg" not in msg_json
            or "cmd" not in msg_json["msg"]
            and "data" not in msg_json["msg"]
        ):
            return None
        cmd = msg_json["msg"]["cmd"]
        data = msg_json["msg"]["data"]
        message = next(m for m in self._messages if m.command == cmd)
        if not message:
            return None
        return message(data)
