from __future__ import annotations

import base64
import json
from typing import Any, TypeVar


class GoveeMessage:
    command: str = ""
    _data: dict[str, Any]

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def as_dict(self) -> dict[str, Any]:
        return {"msg": {"cmd": self.command, "data": self.data}}

    def as_json(self) -> str:
        return json.dumps(self.as_dict(), separators=(",", ":"))

    def __bytes__(self) -> bytes:
        return self.as_json().encode("utf-8")

    def __str__(self) -> str:
        return self.as_json()

    @property
    def data(self) -> dict[str, Any]:
        return self._data


M = TypeVar("M", bound=GoveeMessage)


class ScanMessage(GoveeMessage):
    command = "scan"

    def __init__(self) -> None:
        super().__init__({"account_topic": "reserve"})


class DevStatusMessage(GoveeMessage):
    command = "devStatus"

    def __init__(self) -> None:
        super().__init__({})


class StatusMessage(GoveeMessage):
    command = "status"

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

    def __init__(
        self, *, rgb: tuple[int, int, int] | None, temperature: int | None
    ) -> None:
        if rgb:
            nrgb = [max(0, min(c, 255)) for c in rgb]
            data = {
                "color": {"r": nrgb[0], "g": nrgb[1], "b": nrgb[2]},
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
        else:
            raise ValueError(
                "ColorMessage requires either a non-empty rgb tuple or a "
                "non-zero temperature"
            )

        super().__init__(data)


class PtRealMessage(GoveeMessage):
    command = "ptReal"

    def __init__(self, data: list[bytes], do_checksum: bool = True) -> None:
        checksumed_data: list[str] = (
            [
                base64.b64encode(PtRealMessage._with_checksum(d)).decode("utf-8")
                for d in data
            ]
            if do_checksum
            else [base64.b64encode(d).decode("utf-8") for d in data]
        )

        super().__init__({"command": checksumed_data})

    @staticmethod
    def _with_checksum(data: bytes) -> bytes:
        xor_result: int = 0
        for byte in data:
            xor_result ^= byte
        return data + xor_result.to_bytes(1, "big")


class HexMessage(PtRealMessage):
    def __init__(self, data: list[str]) -> None:
        super().__init__([bytes.fromhex(d) for d in data], do_checksum=False)


class SegmentColorMessages(PtRealMessage):
    def __init__(self, segment: bytes, color: tuple[int, int, int]) -> None:
        capped_color = [max(0, min(c, 255)) for c in color]
        data = (
            b"\x33\x05\x15\x01"
            + bytes(capped_color)
            + b"\x00\x00\x00\x00\x00"
            + segment
            + b"\x00\x00\x00\x00\x00"
        )
        super().__init__([data])


class SceneMessages(PtRealMessage):
    def __init__(self, scene: bytes) -> None:
        data = (
            b"\x33\x05\x04"
            + scene
            + b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        )
        super().__init__([data])


class ScanResponse(GoveeMessage):
    command = "scan"

    def __init__(self, data: dict[str, Any]) -> None:
        super().__init__(data)

    @property
    def device(self):
        return self._data.get("device", None)

    @property
    def sku(self):
        return self._data.get("sku", None)

    @property
    def ip(self):
        return self._data.get("ip", None)

    def set_ip(self, ip_addr: str) -> None:
        self._data["ip"] = ip_addr


class DevStatusResponse(GoveeMessage):
    command = "devStatus"

    def __init__(self, data: dict[str, Any]) -> None:
        super().__init__(data)

    # All accessors use .get() with safe defaults. A firmware variant or a
    # malformed payload that omits a field must not crash device.update()
    # partway through (which would leave the device half-updated).

    @property
    def is_on(self) -> bool:
        return bool(self._data.get("onOff", 0))

    @property
    def color(self) -> tuple[int, int, int]:
        color = self._data.get("color") or {}
        return (color.get("r", 0), color.get("g", 0), color.get("b", 0))

    @property
    def brightness(self) -> int:
        return int(self._data.get("brightness", 0))

    @property
    def color_temperature(self) -> int:
        return int(self._data.get("colorTemInKelvin", 0))


class StatusResponse(GoveeMessage):
    command = "status"

    def __init__(self, data: dict[str, Any]) -> None:
        super().__init__(data)

    def hex(self) -> str:
        return base64.b64decode(self._data["pt"]).hex()


class MessageResponseFactory:
    def __init__(self) -> None:
        self._messages: set[type[GoveeMessage]] = {
            ScanResponse,
            DevStatusResponse,
            StatusResponse,
        }

    def create_message(self, data: bytes | bytearray | str) -> GoveeMessage | None:
        # Background UDP noise (mDNS, SSDP, other devices) lands on port 4002
        # too. Treat any parse failure as "not for us" and drop silently
        # instead of raising into the datagram handler.
        try:
            msg_json = json.loads(data)
            inner = msg_json["msg"]
            cmd = inner["cmd"]
            message_data = inner["data"]
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

        message_cls = next((m for m in self._messages if m.command == cmd), None)
        if message_cls is None:
            return None
        return message_cls(message_data)
