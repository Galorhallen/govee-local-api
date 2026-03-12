from __future__ import annotations

import asyncio
import ipaddress
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, cast

from .device import GoveeDevice
from .device_registry import DeviceRegistry
from .light_capabilities import (
    GOVEE_LIGHT_CAPABILITIES,
    ON_OFF_CAPABILITIES,
    GoveeLightFeatures,
)
from .message import (
    HexMessage,
    BrightnessMessage,
    ColorMessage,
    SceneMessages,
    GoveeMessage,
    MessageResponseFactory,
    OnOffMessage,
    ScanMessage,
    ScanResponse,
    SegmentColorMessages,
    DevStatusMessage,
    DevStatusResponse,
)
from .network import (
    _parse_listening_addresses,
    _is_ip_in_same_network_heuristic,
)
from .protocol import GoveeControllerProtocol

BROADCAST_ADDRESS = "239.255.255.250"
BROADCAST_PORT = 4001
LISTENING_PORT = 4002
COMMAND_PORT = 4003

DISCOVERY_INTERVAL = 10
EVICT_INTERVAL = DISCOVERY_INTERVAL * 3
UPDATE_INTERVAL = 5


class GoveeController(asyncio.DatagramProtocol):
    def __init__(
        self,
        loop=None,
        broadcast_address: str = BROADCAST_ADDRESS,
        broadcast_port: int = BROADCAST_PORT,
        listening_addresses: str | list[str] = "0.0.0.0",
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
            listening_addresses (str | list[str]): Local IP addresses on which the controller listens for incoming
                devices' messages. Can be a single address or a list of addresses. Supports optional CIDR or netmask
                notation (e.g., "192.168.1.100/24" or "192.168.1.100/255.255.255.0"). When a mask is provided,
                precise subnet matching is used for transport selection. Default: "0.0.0.0"
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
        self._logger = logger or logging.getLogger(__name__)

        self._transports: list[Any] = []
        self._protocols: list[Any] = []
        self._broadcast_address = broadcast_address
        self._broadcast_port = broadcast_port
        self._listening_port = listening_port
        self._device_command_port = device_command_port
        self._listening_addresses, self._networks = _parse_listening_addresses(
            listening_addresses
        )

        # Initialize loop, handling case when no loop is running (for testing)
        try:
            self._loop = loop or asyncio.get_running_loop()
        except RuntimeError:
            # No running loop, use a new event loop (mainly for testing)
            self._loop = loop or asyncio.new_event_loop()

        self._cleanup_done: asyncio.Event = asyncio.Event()
        self._message_factory = MessageResponseFactory()
        self._registry: DeviceRegistry = DeviceRegistry(self._logger)

        self._discovery_enabled = discovery_enabled
        self._discovery_interval = discovery_interval
        self._update_enabled = update_enabled
        self._update_interval = update_interval
        self._evict_enabled = evict_enabled
        self._evict_interval = evict_interval

        self._device_discovered_callback = discovered_callback
        self._device_evicted_callback = evicted_callback

        self._discovery_handle: asyncio.TimerHandle | None = None
        self._update_handle: asyncio.TimerHandle | None = None

        self._response_handler: dict[str, Callable] = {
            ScanResponse.command: self._handle_scan_response,
            DevStatusResponse.command: self._handle_status_update_response,
        }

    async def start(self):
        # Create datagram endpoints for each listening address
        for listening_address in self._listening_addresses:
            transport, protocol = await self._loop.create_datagram_endpoint(
                lambda addr=listening_address: GoveeControllerProtocol(self, addr),
                local_addr=(listening_address, self._listening_port),
                reuse_port=True,
            )
            self._transports.append(transport)
            self._protocols.append(protocol)

        if self._discovery_enabled or self._registry.has_queued_devices:
            self.send_discovery_message()
        if self._update_enabled:
            self.send_update_message()

    def cleanup(self) -> asyncio.Event:
        self._cleanup_done.clear()
        self.set_update_enabled(False)
        self.set_discovery_enabled(False)

        for transport in self._transports:
            if transport:
                transport.close()

        self._transports.clear()
        self._protocols.clear()
        self._registry.cleanup()
        return self._cleanup_done

    def add_device_to_discovery_queue(self, ip: str) -> bool:
        ip_added: bool = self._registry.add_device_to_queue(ip)
        if not self._discovery_enabled and ip_added:
            self.send_discovery_message()
        return ip_added

    def remove_device_from_discovery_queue(self, ip: str) -> bool:
        return self._registry.remove_device_from_queue(ip)

    @property
    def discovery_queue(self) -> set[str]:
        return self._registry.devices_queue

    def remove_device(self, device: str | GoveeDevice) -> None:
        if isinstance(device, GoveeDevice):
            device = device.fingerprint
        self._registry.remove_discovered_device(device)

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

    @property
    def listening_addresses(self) -> list[str]:
        """Get the list of listening addresses."""
        return self._listening_addresses.copy()

    @property
    def networks(self) -> list[ipaddress.IPv4Network | None]:
        """Get the list of parsed networks for each listening address."""
        return self._networks.copy()

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
        message: bytes = bytes(ScanMessage())
        call_later: bool = False
        if not self._transports:
            return

        if self._discovery_enabled:
            call_later = True
            # Send broadcast messages from each listening address/transport
            for i, transport in enumerate(self._transports):
                self._logger.debug(
                    "Sending discovery broadcast from interface %s (%s) to %s:%s",
                    i,
                    self._listening_addresses[i],
                    self._broadcast_address,
                    self._broadcast_port,
                )
                transport.sendto(
                    message, (self._broadcast_address, self._broadcast_port)
                )

        if self._registry.has_queued_devices:
            call_later = True
            # Send to specific devices using the most appropriate transport for each IP
            for ip in self._registry.devices_queue:
                transport = self._get_best_transport_for_ip(ip)
                transport.sendto(message, (ip, self._broadcast_port))

        manually_added_devices = [
            device.ip
            for device in self._registry.discovered_devices.values()
            if device.is_manual
        ]
        if manually_added_devices:
            call_later = True
            # Send to manually added devices using the most appropriate transport for each IP
            for ip in manually_added_devices:
                transport = self._get_best_transport_for_ip(ip)
                transport.sendto(message, (ip, self._broadcast_port))

        if call_later:
            self._discovery_handle = self._loop.call_later(
                self._discovery_interval, self.send_discovery_message
            )

    def send_update_message(self) -> None:
        if self._transports:
            for d in self._registry.discovered_devices.values():
                self._send_update_message(device=d)

            if self._update_enabled:
                self._update_handle = self._loop.call_later(
                    self._update_interval, self.send_update_message
                )

    async def turn_on_off(self, device: GoveeDevice, status: bool) -> None:
        self._send_message(OnOffMessage(status), device)

    async def set_segment_rgb_color(
        self, device: GoveeDevice, segment: int, rgb: tuple[int, int, int]
    ) -> None:
        if not device.capabilities:
            self._logger.warning("Capabilities not available for device %s", device)
            return

        if device.capabilities.features & GoveeLightFeatures.SEGMENT_CONTROL == 0:
            self._logger.warning(
                "Segment control is not supported by device %s", device
            )
            return

        if segment < 1 or segment > len(device.capabilities.segments):
            self._logger.warning(
                "Segment index %s is not valid for device %s", segment, device
            )
            return

        segment_data: bytes = device.capabilities.segments[segment - 1]
        if not segment_data:
            self._logger.warning(
                "Segment %s is not supported by device %s", segment, device
            )
            return
        message = SegmentColorMessages(segment_data, rgb)
        self._logger.debug(f"Sending message {message} to device {device}")
        self._send_message(message, device)

    async def set_scene(self, device: GoveeDevice, scene: str) -> None:
        if (
            not device.capabilities
            or device.capabilities.features & GoveeLightFeatures.SCENES == 0
        ):
            self._logger.warning("Scenes are not supported by device %s", device)
            return

        scene_code: bytes | None = device.capabilities.scenes.get(scene.lower(), None)
        if not scene_code:
            self._logger.warning(
                "Scene %s is not available for device %s", scene, device
            )
            return
        self._send_message(SceneMessages(scene_code), device)

    async def set_brightness(self, device: GoveeDevice, brightness: int) -> None:
        self._send_message(BrightnessMessage(brightness), device)

    async def set_color(
        self,
        device: GoveeDevice,
        *,
        rgb: tuple[int, int, int] | None,
        temperature: int | None,
    ) -> None:
        if rgb:
            self._send_message(ColorMessage(rgb=rgb, temperature=None), device)
        else:
            self._send_message(ColorMessage(rgb=None, temperature=temperature), device)

    async def send_raw_command(self, device: GoveeDevice, command: str) -> None:
        self._send_message(HexMessage([command]), device)

    def get_device_by_ip(self, ip: str) -> GoveeDevice | None:
        return self._registry.get_device_by_ip(ip)

    def get_device_by_sku(self, sku: str) -> GoveeDevice | None:
        return self._registry.get_device_by_sku(sku)

    def get_device_by_fingerprint(self, fingerprint: str) -> GoveeDevice | None:
        return self._registry.get_device_by_fingerprint(fingerprint)

    @property
    def devices(self) -> list[GoveeDevice]:
        return list(self._registry.discovered_devices.values())

    def _protocol_disconnected(self):
        """Called when a protocol is disconnected. Sets cleanup done when all protocols are disconnected."""
        # Check if all transports are closed
        active_transports = [t for t in self._transports if not t.is_closing()]
        if not active_transports:
            self._cleanup_done.set()

    async def _handle_datagram_received(
        self, data: bytes, addr: tuple, protocol: GoveeControllerProtocol
    ):
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
            scan_message = cast(ScanResponse, message)
            if not scan_message.ip:
                sender_ip, _sender_port = addr
                self._logger.debug(
                    "No ip returned in data from device %s!\nMessage: %s",
                    scan_message.device,
                    data,
                )

                scan_message.set_ip(sender_ip)
                self._logger.debug(
                    "Set ip for device %s to %s (sending address).\nData: %s",
                    scan_message.device,
                    sender_ip,
                    scan_message.data,
                )

            await self._handle_scan_response(scan_message, protocol)
        elif message.command == DevStatusResponse.command:
            await self._handle_status_update_response(
                cast(DevStatusResponse, message), addr, protocol
            )

    async def _handle_status_update_response(
        self, message: DevStatusResponse, addr, protocol: GoveeControllerProtocol
    ):
        self._logger.debug("Status update received from {}: {}", addr, message)
        ip = addr[0]
        if device := self.get_device_by_ip(ip):
            if protocol.transport:
                device.update_transport(protocol.transport)
            device.update(message)

    async def _handle_scan_response(
        self, message: ScanResponse, protocol: GoveeControllerProtocol
    ) -> None:
        fingerprint = message.device
        if not fingerprint:
            self._logger.warning(
                "Scan response missing device fingerprint: %s", message
            )
            return

        if device := self.get_device_by_fingerprint(fingerprint):
            if self._call_discovered_callback(device, False):
                if message.ip and message.ip != device.ip:
                    self._logger.debug(
                        "Device %s IP changed from %s to %s",
                        fingerprint,
                        device.ip,
                        message.ip,
                    )
                    device.update_ip(message.ip)
                if protocol.transport:
                    device.update_transport(protocol.transport)
                device.update_lastseen()
                self._logger.debug("Device updated: %s", device)
        else:
            sku = message.sku
            if not sku:
                self._logger.warning(
                    "Scan response missing sku for device %s", fingerprint
                )
                capabilities = ON_OFF_CAPABILITIES
            else:
                capabilities = GOVEE_LIGHT_CAPABILITIES.get(sku) or ON_OFF_CAPABILITIES
                if sku not in GOVEE_LIGHT_CAPABILITIES:
                    self._logger.warning(
                        "Device %s is not supported. Only power control is available. Please open an issue at 'https://github.com/Galorhallen/govee-local-api/issues'",
                        sku,
                    )

            ip = message.ip
            if not ip:
                self._logger.warning(
                    "Scan response missing ip for device %s", fingerprint
                )
                return

            device = GoveeDevice(self, ip, fingerprint, sku or "UNKNOWN", capabilities)
            if protocol.transport:
                device.update_transport(protocol.transport)
            if self._call_discovered_callback(device, True):
                device = self._registry.add_discovered_device(device)
                self._logger.debug("Device discovered: %s", device)
            else:
                self._logger.debug("Device %s ignored", device)

        if self._evict_enabled:
            self._evict()

    def _call_discovered_callback(self, device: GoveeDevice, is_new: bool) -> bool:
        if not self._device_discovered_callback:
            return True
        return self._device_discovered_callback(device, is_new)

    def _send_message(self, message: GoveeMessage, device: GoveeDevice) -> None:
        if self._transports:
            # Prefer the transport the device was discovered on
            transport = device.transport
            if transport is None or transport.is_closing():
                transport = self._get_best_transport_for_ip(device.ip)
            if transport is not None:
                transport.sendto(bytes(message), (device.ip, self._device_command_port))

    def _get_best_transport_for_ip(self, target_ip: str) -> Any:
        """
        Select the best transport for communicating with a specific IP address.
        Uses parsed network information for accurate subnet matching when available,
        falling back to heuristic matching for addresses without a mask.
        """
        if not self._transports:
            raise RuntimeError("No transports available")

        if len(self._transports) == 1:
            return self._transports[0]

        try:
            target_addr = ipaddress.ip_address(target_ip)

            for i, (listening_addr, network) in enumerate(
                zip(self._listening_addresses, self._networks)
            ):
                if listening_addr == "0.0.0.0":
                    continue

                # Use precise subnet matching if a network mask was provided
                if network is not None:
                    if target_addr in network:
                        self._logger.debug(
                            "Selected transport %d (%s/%s) for target %s (subnet match)",
                            i,
                            listening_addr,
                            network.prefixlen,
                            target_ip,
                        )
                        return self._transports[i]
                else:
                    # Fallback to heuristic matching for addresses without a mask
                    try:
                        listen_addr = ipaddress.ip_address(listening_addr)
                        if (
                            target_addr.version == listen_addr.version == 4
                            and isinstance(target_addr, ipaddress.IPv4Address)
                            and isinstance(listen_addr, ipaddress.IPv4Address)
                            and _is_ip_in_same_network_heuristic(
                                target_addr, listen_addr
                            )
                        ):
                            self._logger.debug(
                                "Selected transport %d (%s) for target %s (heuristic match)",
                                i,
                                listening_addr,
                                target_ip,
                            )
                            return self._transports[i]
                    except ValueError:
                        continue

            # If no network match found, prefer non-wildcard addresses
            for i, listening_addr in enumerate(self._listening_addresses):
                if listening_addr != "0.0.0.0":
                    self._logger.debug(
                        "Selected transport %d (%s) for target %s (first specific address)",
                        i,
                        listening_addr,
                        target_ip,
                    )
                    return self._transports[i]

        except ValueError:
            # Invalid IP address, fall back to first transport
            pass

        # Fallback to first transport
        self._logger.debug(
            "Selected transport 0 (%s) for target %s (fallback)",
            self._listening_addresses[0],
            target_ip,
        )
        return self._transports[0]

    def _send_update_message(self, device: GoveeDevice):
        self._send_message(DevStatusMessage(), device)

    def _evict(self) -> None:
        now = datetime.now()
        devices = dict(self._registry.discovered_devices)
        for fingerprint, device in devices.items():
            diff: timedelta = now - device.lastseen
            if diff.total_seconds() >= self._evict_interval:
                device._controller = None
                self._registry.remove_discovered_device(fingerprint)
                self._logger.debug("Device evicted: %s", device)
                if self._device_evicted_callback and callable(
                    self._device_evicted_callback
                ):
                    self._device_evicted_callback(device)
