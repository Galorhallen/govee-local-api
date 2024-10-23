from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from .light_capabilities import GoveeLightCapabilities, ON_OFF_CAPABILITIES
from .message import DevStatusResponse


class GoveeSegment:
    def __init__(self, is_on: bool, color: tuple[int, int, int]) -> None:
        self.is_on = is_on
        self.color = color

    def as_dict(self) -> dict[str, Any]:
        return {"is_on": self.is_on, "color": self.color}

    def __str__(self) -> str:
        return f"<GoveeSegment is_on={self.is_on}, color={self.color}>"


class GoveeDevice:
    def __init__(
        self,
        controller,
        ip: str,
        fingerprint: str,
        sku: str,
        capabilities: GoveeLightCapabilities = ON_OFF_CAPABILITIES,
    ) -> None:
        self._controller = controller
        self._fingerprint = fingerprint
        self._sku = sku
        self._ip = ip
        self._lastseen: datetime = datetime.now()
        self._capabilities: GoveeLightCapabilities = capabilities

        self._is_on: bool = False
        self._rgb_color = (0, 0, 0)
        self._temperature_color = 0
        self._brightness = 0
        self._update_callback: Callable[[GoveeDevice], None] | None = None

    @property
    def controller(self):
        return self._controller

    @property
    def capabilities(self) -> GoveeLightCapabilities:
        return self._capabilities

    @property
    def ip(self) -> str:
        return self._ip

    @property
    def fingerprint(self) -> str:
        return self._fingerprint

    @property
    def sku(self) -> str:
        return self._sku

    @property
    def lastseen(self) -> datetime:
        return self._lastseen

    @property
    def on(self) -> bool:
        return self._is_on

    @property
    def rgb_color(self) -> tuple[int, int, int]:
        return self._rgb_color

    @property
    def brightness(self) -> int:
        return self._brightness

    @property
    def temperature_color(self) -> int:
        return self._temperature_color

    @property
    def update_callback(self) -> Callable[[GoveeDevice], None] | None:
        return self._update_callback

    def set_update_callback(
        self, callback: Callable[[GoveeDevice], None] | None
    ) -> Callable[[GoveeDevice], None] | None:
        old_callback = self._update_callback
        self._update_callback = callback
        return old_callback

    async def turn_on(self) -> None:
        await self._controller.turn_on_off(self, True)
        self._is_on = True

    async def set_segment_rgb_color(
        self, segment: int, red: int, green: int, blue: int
    ) -> None:
        rgb: tuple[int, int, int] = (red, green, blue)
        await self._controller.set_segment_rgb_color(self, segment, rgb)

    async def turn_segment_off(self, segment: int) -> None:
        await self._controller.set_segment_rgb_color(self, segment, (0, 0, 0))

    async def turn_off(self) -> None:
        await self._controller.turn_on_off(self, False)
        self._is_on = False

    async def set_brightness(self, value: int) -> None:
        await self._controller.set_brightness(self, value)
        self._brightness = value

    async def set_rgb_color(self, red: int, green: int, blue: int) -> None:
        rgb = (red, green, blue)
        await self._controller.set_color(self, rgb=rgb, temperature=None)
        self._rgb_color = rgb

    async def set_temperature(self, temperature: int) -> None:
        await self._controller.set_color(self, temperature=temperature, rgb=None)
        self._temperature_color = temperature

    async def set_scene(self, scene: str) -> None:
        await self._controller.set_scene(self, scene)

    async def send_raw_command(self, command: str) -> None:
        await self._controller.send_raw_command(self, command)

    def update(self, message: DevStatusResponse) -> None:
        self._is_on = message.is_on
        self._brightness = message.brightness
        self._rgb_color = message.color
        self._temperature_color = message.color_temperature
        self.update_lastseen()
        if self._update_callback and callable(self._update_callback):
            self._update_callback(self)

    def update_lastseen(self) -> None:
        self._lastseen = datetime.now()

    def as_dict(self) -> dict[str, Any]:
        return {
            "ip": self._ip,
            "fingerprint": self._fingerprint,
            "sku": self._sku,
            "lastseen": self._lastseen,
            "on": self._is_on,
            "brightness": self._brightness,
            "color": self._rgb_color,
            "colorTemperature": self._temperature_color,
        }

    def __str__(self) -> str:
        result = f"<GoveeDevice ip={self.ip}, fingerprint={self.fingerprint}, sku={self.sku}, lastseen={self._lastseen}, is_on={self._is_on}"
        return result + (
            f", brightness={self._brightness}, color={self._rgb_color}, temperature={self._temperature_color}>"
            if self._is_on
            else ">"
        )
