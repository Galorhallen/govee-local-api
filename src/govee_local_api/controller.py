from __future__ import annotations

import asyncio
import logging
import socket
from datetime import datetime, timedelta
from typing import Callable, Tuple, Any, cast
import ipaddress

from .device import GoveeDevice
from .light_capabilities import GOVEE_LIGHT_CAPABILITIES, GoveeLightCapability
from .message import (
    BrightnessMessage,
    ColorMessage,
    GoveeMessage,
    MessageResponseFactory,
    OnOffMessage,
    ScanMessage,
    ScanResponse,
    StatusMessage,
    StatusResponse,
)

BROADCAST_ADDRESS = "239.255.255.250"
BROADCAST_PORT = 4001
LISTENING_PORT = 4002
COMMAND_PORT = 4003

DISCOVERY_INTERVAL = 10
EVICT_INTERVAL = DISCOVERY_INTERVAL * 3
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
        discovery_enabled: bool = False,
        discovery_interval: int = DISCOVERY_INTERVAL,
        evict_enabled: bool = False,
        evict_interval: int = EVICT_INTERVAL,
        update_enabled: bool = True,
        update_interval: int = UPDATE_INTERVAL,
        discovered_callback: Callable[[GoveeDevice, bool], bool] | None = None,
        evicted_callback: Callable[[GoveeDevice], None] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Build a controller that handle Govee devices that support local API on local network.

        Args:
            loop: The asyncio event loop. If None the loop is retrieved by calling ``asyncio.get_running_loop()``
            broadcast_address (str): The multicast address to use to send discovery messages. Default: 239.255.255.250
            broadcast_port (int): Devices port where discovery messages are sent. Default: 4001
            listening_port (int): Local UDP port on which the controller listen for incoming devices' messages
            device_command_port (int): The devices' port where the commands should be sent
            discovery_enabled (bool): If true a discovery message is sent every ``discovery_interval`` seconds. Default: False
            discovery_interval (int): Interval between discovery messages (if discovery is enabled). Default: 10 seconds
            evict_enabled (bool): If true the controller automatically remove devices not seen for ``evict_interval`` seconds (requires discovery to be enabled)
            evict_interval (int): Interval after which a device is evicted. Default 30 seconds
            update_enabled (bool): If true the devices status is updated automatically every ``update_interval`` seconds. A successful device update reset the eviction timer for the device. Default: True
            update_interval (int): Interval between a status update is requested to devices.
            discovered_callback (Callable[GoveeDevice, bool]): An optional function to call when a device is discovered (or rediscovered). Default None
            evicted_callback (Callable[GoveeDevice]): An optional function to call when a device is evicted.
        """

        self._transport: Any = None
        self._protocol = None
        self._broadcast_address = broadcast_address
        self._broadcast_port = broadcast_port
        self._listening_address = listening_address
        self._listening_port = listening_port
        self._device_command_port = device_command_port

        self._loop = loop or asyncio.get_running_loop()
        self._cleanup_done: asyncio.Event = asyncio.Event()
        self._message_factory = MessageResponseFactory()
        self._devices: dict[str, GoveeDevice] = {}

        self._discovery_enabled = discovery_enabled
        self._discovery_interval = discovery_interval
        self._update_enabled = update_enabled
        self._update_interval = update_interval
        self._evict_enabled = evict_enabled
        self._evict_interval = evict_interval

        self._device_discovered_callback = discovered_callback
        self._device_evicted_callback = evicted_callback

        self._logger = logger or logging.getLogger(__name__)

        self._discovery_handle: asyncio.TimerHandle | None = None
        self._update_handle: asyncio.TimerHandle | None = None

    async def start(self):
        self._transport, self._protocol = await self._loop.create_datagram_endpoint(
            lambda: self, local_addr=(self._listening_address, self._listening_port)
        )

        if self._discovery_enabled:
            self.send_discovery_message()
        if self._update_enabled:
            self.send_update_message()

    def cleanup(self) -> asyncio.Event:
        self._cleanup_done.clear()
        self.set_update_enabled(False)
        self.set_discovery_enabled(False)

        if self._transport:
            self._transport.close()
        self._devices.clear()
        return self._cleanup_done

    def add_device(
        self,
        ip: str,
        sku: str,
        fingerprint,
        capabilities: set[GoveeLightCapability] | None,
    ) -> None:
        device: GoveeDevice = GoveeDevice(self, ip, fingerprint, sku, capabilities)
        self._devices[fingerprint] = device

    def remove_device(self, device: str | GoveeDevice) -> None:
        if isinstance(device, GoveeDevice):
            device = device.fingerprint
        if device in self._devices:
            del self._devices[device]

    @property
    def evict_enabled(self) -> bool:
        return self._evict_enabled

    def set_evict_enabled(self, enabled: bool) -> None:
        self._evict_enabled = enabled

    def set_discovery_enabled(self, enabled: bool) -> None:
        if self._discovery_enabled == enabled:
            return
        self._discovery_enabled = enabled
        if enabled:
            self.send_discovery_message()
        elif self._discovery_handle:
            self._discovery_handle.cancel()
            self._discovery_handle = None

    @property
    def discovery(self) -> bool:
        return self._discovery_enabled

    def set_discovery_interval(self, interval: int) -> None:
        self._discovery_interval = interval

    @property
    def discovery_interval(self) -> int:
        return self._discovery_interval

    def set_device_discovered_callback(
        self, callback: Callable[[GoveeDevice, bool], bool] | None
    ) -> Callable[[GoveeDevice, bool], bool] | None:
        old_callback = self._device_discovered_callback
        self._device_discovered_callback = callback
        return old_callback

    def set_update_enabled(self, enabled: bool) -> None:
        if self._update_enabled == enabled:
            return
        self._update_enabled = enabled
        if enabled:
            self.send_update_message()
        elif self._update_handle:
            self._update_handle.cancel()
            self._update_handle = None

    @property
    def update_enabled(self) -> bool:
        return self._update_enabled

    def send_discovery_message(self) -> None:
        message: ScanMessage = ScanMessage()
        if self._transport:
            self._transport.sendto(
                bytes(message), (self._broadcast_address, self._broadcast_port)
            )

            if self._discovery_enabled:
                self._discovery_handle = self._loop.call_later(
                    self._discovery_interval, self.send_discovery_message
                )

    def send_update_message(self, device: GoveeDevice | None = None) -> None:
        if self._transport:
            if device:
                self._send_update_message(device=device)
            else:
                for d in self._devices.values():
                    self._send_update_message(device=d)

            if self._update_enabled:
                self._update_handle = self._loop.call_later(
                    self._update_interval, self.send_update_message
                )

    async def turn_on_off(self, device: GoveeDevice, status: bool) -> None:
        self._send_message(OnOffMessage(status), device)

    async def set_brightness(self, device: GoveeDevice, brightness: int) -> None:
        self._send_message(BrightnessMessage(brightness), device)

    async def set_color(
        self,
        device: GoveeDevice,
        *,
        rgb: Tuple[int, int, int] | None,
        temperature: int | None,
    ) -> None:
        if rgb:
            self._send_message(ColorMessage(rgb=rgb, temperature=None), device)
        else:
            self._send_message(ColorMessage(rgb=None, temperature=temperature), device)

    def get_device_by_ip(self, ip: str) -> GoveeDevice | None:
        return next(
            (device for device in self._devices.values() if device.ip == ip),
            None,
        )

    def get_device_by_sku(self, sku: str) -> GoveeDevice | None:
        return next(
            (device for device in self._devices.values() if device.sku == sku), None
        )

    def get_device_by_fingerprint(self, fingerprint: str) -> GoveeDevice | None:
        return self._devices.get(fingerprint, None)

    @property
    def devices(self) -> list[GoveeDevice]:
        return list(self._devices.values())

    def connection_made(self, transport):
        self._transport = transport
        sock = self._transport.get_extra_info("socket")

        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        broadcast_ip = ipaddress.ip_address(self._broadcast_address)

        if broadcast_ip.is_multicast:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

            sock.setsockopt(
                socket.SOL_IP,
                socket.IP_MULTICAST_IF,
                socket.inet_aton(self._listening_address),
            )
            sock.setsockopt(
                socket.SOL_IP,
                socket.IP_ADD_MEMBERSHIP,
                socket.inet_aton(self._broadcast_address)
                + socket.inet_aton(self._listening_address),
            )

    def connection_lost(self, *args, **kwargs):
        if self._transport:
            broadcast_ip = ipaddress.ip_address(self._broadcast_address)
            if broadcast_ip.is_multicast:
                sock = self._transport.get_extra_info("socket")
                sock.setsockopt(
                    socket.SOL_IP,
                    socket.IP_DROP_MEMBERSHIP,
                    socket.inet_aton(self._broadcast_address)
                    + socket.inet_aton(self._listening_address),
                )
        self._cleanup_done.set()
        self._logger.debug("Disconnected")

    def datagram_received(self, data: bytes, addr: tuple):
        if not data:
            return
        message = self._message_factory.create_message(data)
        if not message:
            if self._logger.isEnabledFor(logging.DEBUG):
                self._logger.debug(
                    "Unknown message received from %s. Message: %s", addr, data
                )
            self._logger.warning(
                "Unknown message received from %s. Message: %s", addr, data[:50]
            )

            return

        if message.command == ScanResponse.command:
            self._loop.create_task(
                self._handle_scan_response(cast(ScanResponse, message))
            )
        elif message.command == StatusResponse.command:
            self._handle_status_update_response(cast(StatusResponse, message), addr)

    def _send_update_message(self, device: GoveeDevice):
        self._send_message(StatusMessage(), device)

    def _handle_status_update_response(self, message: StatusResponse, addr):
        ip = addr[0]
        device = self.get_device_by_ip(ip)
        if device:
            device.update(message)

    async def _handle_scan_response(self, message: ScanResponse) -> None:
        fingerprint = message.device
        device = self.get_device_by_fingerprint(fingerprint)

        if device is None:
            capabilities = GOVEE_LIGHT_CAPABILITIES.get(message.sku, None)
            if not capabilities:
                self._logger.warning(
                    "Device %s is not supported. Only power control is available. Please open an issue at 'https://github.com/Galorhallen/govee-local-api/issues'",
                    message.sku,
                )
            device = GoveeDevice(
                self, message.ip, fingerprint, message.sku, capabilities
            )
            if self._call_discovered_callback(device, True):
                self._devices[fingerprint] = device
                self._logger.debug("Device discovered: %s", device)
            else:
                self._logger.debug("Device %s ignored", device)
        else:
            if self._call_discovered_callback(device, False):
                device.update_lastseen()
                self._logger.debug("Device updated: %s", device)

        if self._evict_enabled:
            self._evict()

    def _call_discovered_callback(self, device: GoveeDevice, is_new: bool) -> bool:
        if not self._device_discovered_callback:
            return True
        return self._device_discovered_callback(device, is_new)

    def _send_message(self, message: GoveeMessage, device: GoveeDevice) -> None:
        self._transport.sendto(bytes(message), (device.ip, self._device_command_port))

    def _evict(self) -> None:
        now = datetime.now()
        devices = dict(self._devices)
        for fingerprint, device in devices.items():
            diff: timedelta = now - device.lastseen
            if diff.total_seconds() >= self._evict_interval:
                device._controller = None
                del self._devices[fingerprint]
                if self._device_evicted_callback and callable(
                    self._device_evicted_callback
                ):
                    self._logger.debug("Device evicted: %s", device)
                    self._device_evicted_callback(device)
        self._devices = devices
