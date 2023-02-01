from __future__ import annotations
import asyncio
import logging
import socket

from typing import Callable
from datetime import datetime, timedelta

from .message import (
    GoveeMessage,
    ScanMessage,
    ScanResponse,
    MessageResponseFactory,
    StatusResponse,
    StatusMessage,
    OnOffMessage,
    BrightnessMessage,
    ColorMessage,
)
from .device import GoveeDevice


BROADCAST_ADDRESS = "239.255.255.250"
BROADCAST_PORT = 4001
LISTENING_PORT = 4002
COMMAND_PORT = 4003

DISCOVERY_INTERVAL = 10
EVICTION_INTERVAL = DISCOVERY_INTERVAL * 3
UPDATE_INTERVAL = 5


class GoveeController:
    def __init__(
        self,
        loop=None,
        broadcast_address: str = BROADCAST_ADDRESS,
        broadcast_port: int = BROADCAST_PORT,
        listening_address: str = "0.0.0.0",
        listening_port: int = LISTENING_PORT,
        device_command_port: int = COMMAND_PORT,
        discovery: bool = False,
        discovery_interval: int = DISCOVERY_INTERVAL,
        eviction_interval: int = EVICTION_INTERVAL,
        autoupdate: bool = True,
        autoupdate_interval: int = UPDATE_INTERVAL,
        discovered_callback: Callable[[GoveeDevice, bool], None] = None,
        evicted_callback: Callable[[GoveeDevice], None] = None,
        logger: logging.Logger = None,
    ) -> None:
        """Build a controller that handle Govee devices that support local API on local network.

        Args:
            loop: The asyncio event loop. If None the loop is retreived by calling ``asyncio.get_running_loop()``
            broadcast_address (str): The multicast address to use to send discovery messages. Default: 239.255.255.250
            broadcast_port (int): Devices port where discovery messages are sent. Default: 4001
            listening_port (int): Local UDP port on which the controller listen for incoming devices' messages
            device_command_port (int): The devices' port where the commands should be sent
            discovery (bool): If true a discovery message is sent every ``discovery_interval`` seconds. Default: False
            discovery_interval (int): Interval between discovery messages (if discovery is enabled). Default: 10 seconds
            eviction_interval (int): Interval after which a device is evicted. Default 30 seconds
            autoupdate (bool): If true the devices status is updated automatically every ``autoupdate_interval`` seconds. A successful device update reset the eviction timer for the device. Default: True
            autoupdate_interval (int): Interval between a status update is requested to devices.
            discovery_callback (Callable[GoveeDevice, bool]): An optional function to call when a device is discovered (or rediscovered). Default None
            evicted_callback (Callable[GoveeDevice]): An optional function to call when a device is evicted.
        """

        self._transport = None
        self._protocol = None
        self._broadcast_address = broadcast_address
        self._broadcast_port = broadcast_port
        self._listening_address = listening_address
        self._listening_port = listening_port
        self._device_command_port = device_command_port

        self._loop = loop or asyncio.get_running_loop()
        self._message_factory = MessageResponseFactory()
        self._devices: dict[str, GoveeDevice] = {}

        self._discovery = discovery
        self._discovery_interval = discovery_interval
        self._autoupdate = autoupdate
        self._autoupdate_interval = autoupdate_interval
        self._eviction_interval = eviction_interval

        self._device_discovered_callback = discovered_callback
        self._device_evicted_callback = evicted_callback

        self._logger = logger or logging.getLogger(__name__)

    async def start(self):
        self._transport, self._protocol = await self._loop.create_datagram_endpoint(
            lambda: self, local_addr=(self._listening_address, self._listening_port)
        )

        self.send_discovery_message()
        self.send_update_message()

    def clenaup(self):
        if self._transport:
            self._transport.close()
        self._devices.clear()

    def set_discovery(self, enabled: bool) -> None:
        self._discovery = enabled
        if enabled:
            self.send_discovery_message()

    @property
    def discovery(self) -> bool:
        return self._discovery

    def set_discovery_interval(self, interval: int) -> None:
        self._discovery_interval = interval

    @property
    def discovery_interval(self) -> int:
        return self._discovery_interval

    def set_autoupdate(self, enabled: bool) -> None:
        self._autoupdate = enabled
        if enabled:
            self.send_update_message()

    @property
    def autoupdate(self) -> bool:
        return self._autoupdate

    def send_discovery_message(self):
        message: ScanMessage = ScanMessage()
        self._transport.sendto(
            bytes(message), (self._broadcast_address, self._broadcast_port)
        )

        if self._discovery:
            self._loop.call_later(self._discovery_interval, self.send_discovery_message)

    def send_update_message(self, device: GoveeDevice = None):
        if device:
            self._send_update_message(device=device)
        else:
            for d in self._devices.values():
                self._send_update_message(device=d)

        if self._autoupdate:
            self._loop.call_later(self._autoupdate_interval, self.send_update_message)

    async def turn_on_off(self, device: GoveeDevice, status: bool) -> None:
        self._send_message(OnOffMessage(status), device)

    async def set_brightness(self, device: GoveeDevice, brightness: int) -> None:
        self._send_message(BrightnessMessage(brightness), device)

    async def set_color(
        self, device: GoveeDevice, rgb: tuple(int, int, int), temperature: int = None
    ) -> None:
        if rgb:
            self._send_message(ColorMessage(rgb=rgb, temperature=None), device)
        else:
            self._send_message(ColorMessage(rgb=None, temperature=temperature), device)

    def get_device_by_ip(self, ip: str) -> GoveeDevice | None:
        return next(device for device in self._devices.values() if device.ip == ip)

    def get_device_by_sku(self, sku: str) -> GoveeDevice | None:
        return next(device for device in self._devices.values() if device.sku == sku)

    @property
    def devices(self) -> list(GoveeDevice):
        return list(self._devices.values())

    def connection_made(self, transport):
        self._transport = transport

        sock = self._transport.get_extra_info("socket")
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    def connection_lost(self, *args, **kwargs):
        self._logger.debug("Disconnected")

    def datagram_received(self, data: bytes, addr: tuple):
        if not data:
            return
        message = self._message_factory.create_message(data)
        if not message:
            if self._logger.isEnabledFor(logging.DEBUG):
                self._logger.debug(
                    "Unkown message received from %s. Message: %s", addr, data
                )
            self._logger.warning(
                "Unkown message received from %s. Message: %s", addr, data[:50]
            )

            return

        if message.command == ScanResponse.command:
            self._loop.create_task(self._handle_scan_response(message))
        elif message.command == StatusResponse.command:
            self._handle_status_update_response(message, addr)

    def _send_update_message(self, device: GoveeDevice):
        self._send_message(StatusMessage(), device)

    def _handle_status_update_response(self, message: StatusResponse, addr):
        ip = addr[0]
        device = self.get_device_by_ip(ip)
        if device:
            device.update(message)

    async def _handle_scan_response(self, message: ScanResponse) -> None:
        fingerprint = message.device
        device = self._devices.get(fingerprint, None)

        if device:
            device.update_lastseen()
            is_new = False
            self._logger.debug("Device updated: %s", device)
        else:
            device = GoveeDevice(self, message.ip, message.device, message.sku)
            self._devices[message.device] = device
            is_new = True
            self._logger.debug("Device discovered: %s", device)

        self._evict()

        if self._device_discovered_callback and callable(
            self._device_discovered_callback
        ):
            self._device_discovered_callback(device, is_new)

    def _send_message(self, message: GoveeMessage, device: GoveeDevice) -> None:
        self._transport.sendto(bytes(message), (device.ip, self._device_command_port))

    def _evict(self):
        now = datetime.now()
        for id, device in self._devices.items():
            diff: timedelta = now - device.lastseen
            if diff.total_seconds() >= self._eviction_interval:
                device._controller = None
                del self._devices[id]
                if self._device_evicted_callback and callable(
                    self._device_evicted_callback
                ):
                    self._logger.debug("Device evicted: %s", device)
                    self._device_evicted_callback(device)
