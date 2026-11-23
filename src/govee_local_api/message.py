from __future__ import annotations

import base64
import json
from typing import Any, TypeVar

from .light_capabilities import DEFAULT_TEMPERATURE_RANGE


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
    command = "colorwc"

    def __init__(
        self,
        *,
        rgb: tuple[int, int, int] | None,
        temperature: int | None,
        temperature_range: tuple[int, int] | None = None,
    ) -> None:
        if rgb:
            nrgb = [max(0, min(c, 255)) for c in rgb]
            data = {
                "color": {"r": nrgb[0], "g": nrgb[1], "b": nrgb[2]},
                "colorTemInKelvin": 0,
            }
        elif temperature:
            min_kelvin, max_kelvin = temperature_range or DEFAULT_TEMPERATURE_RANGE
            data = {
                "color": {"r": 0, "g": 0, "b": 0},
                "colorTemInKelvin": max(min_kelvin, min(temperature, max_kelvin)),
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


ZONE_FRAME_SIZE = 19  # 20-byte frame minus the checksum byte


def _zone_frame(data: bytes) -> bytes:
    return data.ljust(ZONE_FRAME_SIZE, b"\x00")


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))


class ZoneOnOffMessage(PtRealMessage):
    """Switch one zone of a multi-zone lamp: ``33 30 <zone> 01|00``."""

    def __init__(self, zone: int, on: bool) -> None:
        super().__init__([_zone_frame(bytes([0x33, 0x30, zone, 0x01 if on else 0x00]))])


class ZoneColorMessage(PtRealMessage):
    """Set a zone's color or white temperature.

    ``33 05 2c <zone> 01 RR GG BB KK KK [mask]``: Kelvin is big-endian and
    ``00 00`` for a plain color. A white temperature is sent with RGB
    ``ff ff ff``; with ``00 00 00`` the side light of the H60B0 ignores it.
    ``segment_mask`` (one bit per segment) is only sent for zones with
    segments. White-only zones take the temperature alone, without RGB
    bytes: ``33 05 2c <zone> 01 KK KK``.
    """

    def __init__(
        self,
        zone: int,
        *,
        rgb: tuple[int, int, int] | None = None,
        temperature: int | None = None,
        segment_mask: int | None = None,
        white_only: bool = False,
    ) -> None:
        if (rgb is None) == (temperature is None):
            raise ValueError("Pass exactly one of rgb or temperature")
        kelvin = (temperature or 0).to_bytes(2, "big")
        data = bytes([0x33, 0x05, 0x2C, zone, 0x01])
        if white_only:
            if temperature is None:
                raise ValueError(f"Zone {zone} only takes a white temperature")
            data += kelvin
        else:
            color = rgb if rgb is not None else (255, 255, 255)
            data += bytes(_clamp(c, 0, 255) for c in color) + kelvin
            if segment_mask is not None:
                data += bytes([segment_mask & 0xFF])
        super().__init__([_zone_frame(data)])


class ZoneBrightnessMessage(PtRealMessage):
    """Set a zone's brightness: ``33 05 2c <zone> 02 <1-100> [mask]``."""

    def __init__(
        self, zone: int, brightness_pct: int, segment_mask: int | None = None
    ) -> None:
        data = bytes([0x33, 0x05, 0x2C, zone, 0x02, _clamp(brightness_pct, 1, 100)])
        if segment_mask is not None:
            data += bytes([segment_mask & 0xFF])
        super().__init__([_zone_frame(data)])


class ZoneFlowSpeedMessage(PtRealMessage):
    """Set a zone's animation speed: ``33 05 2c <zone> 03 <0-100>``."""

    def __init__(self, zone: int, speed: int) -> None:
        super().__init__(
            [_zone_frame(bytes([0x33, 0x05, 0x2C, zone, 0x03, _clamp(speed, 0, 100)]))]
        )


class SceneMessages(PtRealMessage):
    def __init__(self, scene: bytes) -> None:
        data = (
            b"\x33\x05\x04"
            + scene
            + b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        )
        super().__init__([data])


class SceneCodeMessage(PtRealMessage):
    """Activate a scene from Govee's per-model scene library.

    ``scene_code`` and ``scene_param`` are the library entry's ``sceneCode``
    and its base64-decoded ``scenceParam``. A non-empty parameter blob is
    sent first as a run of ``0xa3`` frames (the first one also carries the
    frame count, the last one is indexed ``0xff``), then a
    ``33 05 04 <code lo> <code hi>`` frame activates the scene. Scenes
    without parameters are a single activation frame, identical to
    ``SceneMessages``. Encoding follows wez/govee2mqtt (``src/ble.rs``,
    ``SetSceneCode::encode``).
    """

    FRAME_PAYLOAD_SIZE = 19  # 20-byte BLE frame minus the checksum byte

    def __init__(self, scene_code: int, scene_param: bytes = b"") -> None:
        if not 0 <= scene_code <= 0xFFFF:
            raise ValueError(f"scene_code must be between 0 and 65535: {scene_code}")
        frames = self._parameter_frames(scene_param) if scene_param else []
        activation = b"\x33\x05\x04" + scene_code.to_bytes(2, "little")
        frames.append(activation.ljust(self.FRAME_PAYLOAD_SIZE, b"\x00"))
        super().__init__(frames)

    @classmethod
    def _parameter_frames(cls, scene_param: bytes) -> list[bytes]:
        # Header a3 00 01 <frame count> 02, then the parameter bytes; every
        # further frame starts with a3 <frame index>.
        stream = bytearray(b"\xa3\x00\x01\x00\x02")
        frame_count = 0
        last_index_position = 1
        for byte in scene_param:
            if len(stream) % cls.FRAME_PAYLOAD_SIZE == 0:
                frame_count += 1
                stream.append(0xA3)
                last_index_position = len(stream)
                stream.append(frame_count)
            stream.append(byte)
        stream[last_index_position] = 0xFF
        stream[3] = frame_count + 1
        return [
            bytes(stream[offset : offset + cls.FRAME_PAYLOAD_SIZE]).ljust(
                cls.FRAME_PAYLOAD_SIZE, b"\x00"
            )
            for offset in range(0, len(stream), cls.FRAME_PAYLOAD_SIZE)
        ]


class ScanResponse(GoveeMessage):
    command = "scan"

    def __init__(self, data: dict[str, Any]) -> None:
        super().__init__(data)

    @property
    def device(self) -> str | None:
        return self._data.get("device", None)

    @property
    def sku(self) -> str | None:
        return self._data.get("sku", None)

    @property
    def ip(self) -> str | None:
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
