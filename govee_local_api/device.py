from __future__ import annotations

from typing import Tuple
from datetime import datetime

from .message import StatusResponse


class GoveeDevice:
    def __init__(self, controller, ip: str, fingerprint: str, sku: str) -> None:
        self._controller = controller
        self._fingerprint = fingerprint
        self._sku = sku
        self._ip = ip
        self._lastseen: datetime = datetime.now()

        self._is_on: bool = False
        self._rgb_color = (0, 0, 0)
        self._temperature_color = 0
        self._brightness = 0

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
    def rgb_color(self) -> Tuple(int, int, int):
        return self._rgb_color

    @property
    def brightness(self) -> int:
        return self._brightness

    @property
    def temperature_color(self) -> int:
        return self._temperature_color

    async def turn_on(self) -> None:
        await self._controller.turn_on_off(self, True)

    async def turn_off(self) -> None:
        await self._controller.turn_on_off(self, False)

    async def set_brightness(self, value: int) -> None:
        await self._controller.set_brightness(self, value)

    async def set_rgb_color(self, red: int, green: int, blue: int) -> None:
        await self._controller.set_color(self, rgb=(red, green, blue), temperature=None)

    async def set_temperature(self, temperature: int) -> None:
        await self._controller.set_color(self, temperature=temperature, rgb=None)

    def update(self, message: StatusResponse) -> None:
        self._is_on = message.is_on
        self._brightness = message.brightness
        self._rgb_color = message.color
        self._temperature_color = message.color_temperature
        self.update_lastseen()

    def update_lastseen(self) -> None:
        self._lastseen = datetime.now()

    def __str__(self) -> str:
        result = f"<GoveeDevice ip={self.ip}, fingerprint={self.fingerprint}, sku={self.sku}, lastseen={self._lastseen}, is_on={self._is_on}"
        return result + (
            f", brightness={self._brightness}, color={self._rgb_color}, temperature={self._temperature_color}>"
            if self._is_on
            else ">"
        )
