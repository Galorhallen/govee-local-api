from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import warnings
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

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


class GoveeController:
    def __init__(
        self,
        loop=None,
        broadcast_address: str = BROADCAST_ADDRESS,
        broadcast_port: int = BROADCAST_PORT,
        listening_addresses: str | list[str] | None = None,
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
        listening_address: str | list[str] | None = None,
    ) -> None:
        """Build a controller that handle Govee devices that support local API on local network.

        Args:
            loop: The asyncio event loop. If None the loop is retrieved by calling ``asyncio.get_running_loop()``
            broadcast_address (str): The multicast address to use to send discovery messages. Default: 239.255.255.250
            broadcast_port (int): Devices port where discovery messages are sent. Default: 4001
            listening_addresses (str | list[str]): Local IP addresses on which the controller listens for incoming
                devices' messages. Can be a single address or a list of addresses. Supports optional CIDR or netmask
                notation (e.g., "192.168.1.100/24" or "192.168.1.100/255.255.255.0"). When a mask is provided,
                precise subnet matching is used for transport selection; an invalid mask raises ValueError.
                Default: "0.0.0.0"
            listening_port (int): Local UDP port on which the controller listen for incoming devices' messages
            device_command_port (int): The devices' port where the commands should be sent
            discovery_enabled (bool): If true a discovery message is sent every ``discovery_interval`` seconds. Default: False
            discovery_interval (int): Interval between discovery messages (if discovery is enabled). Default: 10 seconds
            evict_enabled (bool): If true the controller automatically removes devices not seen for ``evict_interval`` seconds. Eviction runs on its own periodic check (every ``evict_interval`` seconds) and opportunistically when scan responses arrive.
            evict_interval (int): Interval after which a device is evicted. Default 30 seconds
            update_enabled (bool): If true the devices status is updated automatically every ``update_interval`` seconds. A successful device update reset the eviction timer for the device. Default: True
            update_interval (int): Interval between a status update is requested to devices.
            discovered_callback (Callable[GoveeDevice, bool]): An optional function to call when a device is discovered (or rediscovered). Default None
            evicted_callback (Callable[GoveeDevice]): An optional function to call when a device is evicted.
            listening_address (str | list[str]): Deprecated alias of ``listening_addresses`` kept for
                backward compatibility (pre-3.0 name); emits a DeprecationWarning.
        """
        if listening_address is not None:
            warnings.warn(
                "The 'listening_address' argument is deprecated and will be "
                "removed in a future release; use 'listening_addresses' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            if listening_addresses is not None:
                raise ValueError(
                    "Pass either 'listening_addresses' or the deprecated "
                    "'listening_address', not both"
                )
            listening_addresses = listening_address
        if listening_addresses is None:
            listening_addresses = "0.0.0.0"

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

        # Reject obviously bad input up front so it doesn't surface as a
        # cryptic OSError from socket.bind() later.
        for addr in self._listening_addresses:
            try:
                ipaddress.IPv4Address(addr)
            except (ipaddress.AddressValueError, ValueError) as exc:
                raise ValueError(f"Invalid IPv4 listening address: {addr!r}") from exc

        # Drop duplicate entries while preserving order; two sockets bound to
        # the same (ip, port) get load-balanced by SO_REUSEPORT and flip the
        # device's preferred transport on every status frame.
        seen: set[str] = set()
        deduped: list[tuple[str, ipaddress.IPv4Network | None]] = []
        for addr, net in zip(self._listening_addresses, self._networks):
            if addr in seen:
                self._logger.warning(
                    "Duplicate listening address %s; ignoring extra entry",
                    addr,
                )
                continue
            seen.add(addr)
            deduped.append((addr, net))
        self._listening_addresses = [a for a, _ in deduped]
        self._networks = [n for _, n in deduped]

        # If specific addresses are provided alongside 0.0.0.0, drop the wildcard
        # to avoid duplicate packet processing (0.0.0.0 receives on all interfaces)
        if (
            len(self._listening_addresses) > 1
            and "0.0.0.0" in self._listening_addresses
        ):
            self._logger.warning(
                "Wildcard address 0.0.0.0 mixed with specific addresses %s; "
                "dropping 0.0.0.0 to avoid duplicate packet processing",
                [a for a in self._listening_addresses if a != "0.0.0.0"],
            )
            filtered = [
                (addr, net)
                for addr, net in zip(self._listening_addresses, self._networks)
                if addr != "0.0.0.0"
            ]
            self._listening_addresses = [a for a, _ in filtered]
            self._networks = [n for _, n in filtered]

        # Empty configuration (e.g. user passed []) would silently produce a
        # working-looking controller that never binds anything. Fail loudly.
        if not self._listening_addresses:
            raise ValueError("listening_addresses resulted in an empty configuration")

        # Snapshot the effective configuration so start() can always bind the
        # full set, even after an unexpected connection_lost dropped an
        # endpoint from the working lists.
        self._configured_addresses: list[str] = list(self._listening_addresses)
        self._configured_networks: list[ipaddress.IPv4Network | None] = list(
            self._networks
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
        self._evict_handle: asyncio.TimerHandle | None = None
        self._cleanup_timeout_handle: asyncio.TimerHandle | None = None

        # Shutdown bookkeeping: connection_lost fires both during cleanup()
        # and (in theory) on an internal transport failure. _closing marks a
        # requested shutdown; _pending_close counts the connection_lost
        # callbacks still owed before cleanup is actually complete.
        self._closing: bool = False
        self._pending_close: int = 0

        # Dispatch table for incoming messages: maps the message's "cmd"
        # string to its handler. All handlers share the signature
        # (message, addr, protocol).
        self._response_handler: dict[str, Callable] = {
            ScanResponse.command: self._handle_scan_response,
            DevStatusResponse.command: self._handle_status_update_response,
        }

    async def start(self):
        self._closing = False
        # Rebind the full configuration: an unexpected connection_lost may
        # have dropped an endpoint from the working lists.
        self._listening_addresses = list(self._configured_addresses)
        self._networks = list(self._configured_networks)

        # Create datagram endpoints for each listening address. We build the
        # socket by hand so SO_REUSEADDR / SO_REUSEPORT / SO_BROADCAST are set
        # before bind() — the kernel only honors them at bind time.
        try:
            for listening_address in self._listening_addresses:
                sock = self._create_listening_socket(listening_address)
                try:
                    transport, protocol = await self._loop.create_datagram_endpoint(
                        lambda addr=listening_address: GoveeControllerProtocol(
                            self, addr
                        ),
                        sock=sock,
                    )
                except Exception:
                    sock.close()
                    raise
                self._transports.append(transport)
                self._protocols.append(protocol)
        except Exception:
            # Don't leave earlier endpoints bound: a partially started
            # controller would leak a socket on every setup retry. Clearing
            # the lists first keeps the ensuing connection_lost callbacks
            # from taking the "unexpected loss" path.
            transports = self._transports[:]
            self._transports.clear()
            self._protocols.clear()
            for transport in transports:
                if transport is not None and not transport.is_closing():
                    transport.close()
            raise

        if self._discovery_enabled or self._registry.has_queued_devices:
            self.send_discovery_message()
        if self._update_enabled:
            self.send_update_message()
        if self._evict_enabled:
            self._schedule_evict()

    def _create_listening_socket(self, listening_address: str) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # SO_REUSEPORT is the right primitive for "multiple sockets share this
        # port" on Linux >=3.9 and macOS, but is missing on Windows and some
        # older systems — fall through if the kernel rejects it.
        reuse_port = getattr(socket, "SO_REUSEPORT", None)
        if reuse_port is not None:
            try:
                sock.setsockopt(socket.SOL_SOCKET, reuse_port, 1)
            except OSError:
                pass
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            sock.bind((listening_address, self._listening_port))
        except OSError:
            sock.close()
            raise
        return sock

    def cleanup(self, timeout: float = 2.0) -> asyncio.Event:
        # Idempotent: if a previous cleanup() already finished, hand the
        # already-set event back without clearing it. Second callers
        # would otherwise wait forever because the transports are gone
        # and nothing will fire connection_lost again.
        if not self._transports and self._cleanup_done.is_set():
            return self._cleanup_done

        self._cleanup_done.clear()
        already_closing = self._closing
        self._closing = True
        self.set_update_enabled(False)
        # Don't go through set_discovery_enabled(False) here: it keeps the
        # timer chain alive while queued/manual devices still need probing,
        # which is exactly what shutdown must stop. Cancel it directly.
        self._discovery_enabled = False
        if self._discovery_handle is not None:
            self._discovery_handle.cancel()
            self._discovery_handle = None
        # Stop the eviction loop before tearing down transports so an
        # in-flight _handle_scan_response task can't invoke the user's
        # evicted_callback mid-shutdown.
        self.set_evict_enabled(False)

        if not self._transports:
            self._cleanup_done.set()
            self._registry.cleanup()
            return self._cleanup_done

        # Completion is signalled after this many connection_lost callbacks.
        # A second cleanup() while the first drain is in flight must NOT
        # reset the countdown — some callbacks have already been counted.
        if not already_closing:
            self._pending_close = len(self._transports)
        for transport in self._transports:
            if transport is not None and not transport.is_closing():
                transport.close()

        # Safety net: a transport whose fd was revoked (NIC unplugged,
        # container network teardown) may never deliver connection_lost.
        # Without this timer, HA's async_unload_entry hangs forever.
        if self._cleanup_timeout_handle is not None:
            self._cleanup_timeout_handle.cancel()
        self._cleanup_timeout_handle = self._loop.call_later(
            timeout, self._force_cleanup_done
        )

        self._registry.cleanup()
        return self._cleanup_done

    def _force_cleanup_done(self) -> None:
        self._cleanup_timeout_handle = None
        if self._cleanup_done.is_set():
            return
        stragglers = [
            self._listening_addresses[i]
            for i, t in enumerate(self._transports)
            if t is not None
            and not t.is_closing()
            and i < len(self._listening_addresses)
        ]
        if stragglers:
            self._logger.warning(
                "cleanup() timed out waiting for connection_lost; "
                "forcing completion. Stragglers: %s",
                stragglers,
            )
        self._transports.clear()
        self._protocols.clear()
        self._cleanup_done.set()

    @property
    def protocols(self) -> list:
        """Return the list of active protocols."""
        return self._protocols

    def add_device_to_discovery_queue(self, ip: str) -> bool:
        ip_added: bool = self._registry.add_device_to_queue(ip)
        if not self._discovery_enabled and ip_added:
            self.send_discovery_message()
        return ip_added

    def reconnect(self) -> None:
        """Trigger a fresh discovery and update all known devices."""
        self._logger.info("Triggering aggressive reconnection/discovery...")
        self.send_discovery_message()
        self.send_update_message()

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

    @property
    def evict_interval(self) -> int:
        return self._evict_interval

    def set_evict_enabled(self, enabled: bool) -> None:
        if self._evict_enabled == enabled:
            return
        self._evict_enabled = enabled
        if enabled:
            self._schedule_evict()
        elif self._evict_handle is not None:
            self._evict_handle.cancel()
            self._evict_handle = None

    def set_discovery_enabled(self, enabled: bool) -> None:
        if self._discovery_enabled == enabled:
            return
        self._discovery_enabled = enabled
        if enabled:
            self.send_discovery_message()
        elif self._discovery_handle:
            self._discovery_handle.cancel()
            self._discovery_handle = None
            # The same timer chain also probes queued and manually-added
            # devices; keep it running when they still need it.
            has_manual_devices = any(
                device.is_manual
                for device in self._registry.discovered_devices.values()
            )
            if self._registry.has_queued_devices or has_manual_devices:
                self.send_discovery_message()

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
            for ip in list(self._registry.devices_queue):
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
            # Cancel any prior pending tick — external triggers like
            # add_device_to_discovery_queue() can call this method between
            # scheduled ticks, and without cancelling we'd accumulate
            # parallel timer chains and storm the network.
            if self._discovery_handle is not None:
                self._discovery_handle.cancel()
            self._discovery_handle = self._loop.call_later(
                self._discovery_interval, self.send_discovery_message
            )

    def send_update_message(self) -> None:
        if self._transports:
            for d in self._registry.discovered_devices.values():
                self._send_update_message(device=d)

            if self._update_enabled:
                if self._update_handle is not None:
                    self._update_handle.cancel()
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

    def _protocol_disconnected(
        self, protocol: GoveeControllerProtocol | None = None
    ) -> None:
        """Called from connection_lost of each protocol.

        During cleanup() this counts down the protocols still owed a
        connection_lost and signals completion only once ALL of them have
        delivered it — a transport reports is_closing() immediately after
        close(), so checking that (the old behavior) fired cleanup_done on
        the first callback while other sockets were still tearing down.

        Outside cleanup() a connection_lost means an internal transport
        failure (no realistic UDP trigger on Linux — OSErrors go to
        error_received — but abort()/fatal errors reach here). Drop the dead
        endpoint and complain loudly; never fake cleanup completion.
        """
        if self._closing:
            self._pending_close = max(0, self._pending_close - 1)
            if self._pending_close == 0:
                self._transports.clear()
                self._protocols.clear()
                if self._cleanup_timeout_handle is not None:
                    self._cleanup_timeout_handle.cancel()
                    self._cleanup_timeout_handle = None
                self._cleanup_done.set()
            return

        if protocol is None or protocol not in self._protocols:
            return

        # Pop the dead endpoint from all four parallel lists so transport
        # selection stays index-aligned.
        index = self._protocols.index(protocol)
        self._protocols.pop(index)
        transport = self._transports.pop(index)
        if transport is not None and not transport.is_closing():
            transport.close()
        address = self._listening_addresses.pop(index)
        self._networks.pop(index)
        if self._transports:
            self._logger.error(
                "UDP endpoint on %s closed unexpectedly; continuing on %s",
                address,
                self._listening_addresses,
            )
        else:
            self._logger.error(
                "UDP endpoint on %s closed unexpectedly and no endpoints "
                "remain; the controller is inoperative until restarted",
                address,
            )

    async def _handle_datagram_received(
        self, data: bytes, addr: tuple, protocol: GoveeControllerProtocol
    ):
        # datagram_received() schedules this coroutine via create_task() and
        # never observes the resulting task, so an uncaught exception here
        # surfaces only as asyncio's generic "Task exception was never
        # retrieved" with no context. Contain it.
        try:
            if self._closing:
                # A task created just before cleanup() can run after the
                # registry was cleared; processing it would repopulate the
                # registry and fire the discovered callback mid-shutdown.
                return

            message = self._message_factory.create_message(data)
            if not message:
                self._logger.warning(
                    "Unknown message received from %s: %r", addr, data[:128]
                )
                return

            handler = self._response_handler.get(message.command)
            if handler is None:
                # Parseable Govee message we deliberately don't act on
                # (e.g. "status") — not noise, so no warning.
                self._logger.debug(
                    "No handler for message %r from %s; ignoring",
                    message.command,
                    addr,
                )
                return
            await handler(message, addr, protocol)
        except Exception:
            self._logger.exception(
                "Datagram handler crashed (addr=%s, interface=%s, data=%r)",
                addr,
                protocol.listening_address,
                data[:64],
            )

    async def _handle_status_update_response(
        self, message: DevStatusResponse, addr, protocol: GoveeControllerProtocol
    ):
        self._logger.debug("Status update received from %s: %s", addr, message)
        ip = addr[0]
        if device := self.get_device_by_ip(ip):
            if protocol.transport:
                device.update_transport(protocol.transport)
            device.update(message)

    async def _handle_scan_response(
        self, message: ScanResponse, addr: tuple, protocol: GoveeControllerProtocol
    ) -> None:
        if not message.ip:
            sender_ip = addr[0]
            self._logger.debug(
                "No ip returned in data from device %s! Using sending "
                "address %s.\nData: %s",
                message.device,
                sender_ip,
                message.data,
            )
            message.set_ip(sender_ip)

        fingerprint = message.device
        if not fingerprint:
            self._logger.warning(
                "Scan response missing device fingerprint: %s", message
            )
            return

        if device := self.get_device_by_fingerprint(fingerprint):
            # The scan response itself is evidence the device is alive, so
            # refresh lastseen unconditionally — otherwise the eviction tick
            # removes a device that just answered us. The callback's
            # return value gates re-notification of the integration and
            # the IP/transport updates that are tied to that, not the
            # liveness bookkeeping.
            device.update_lastseen()
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

            # If no network match found, prefer non-wildcard addresses. This
            # is a best-effort fallback: the packet leaves with a source IP
            # that may not belong to the target's subnet, so the device's
            # reply may never come back. Warn so this is diagnosable.
            for i, listening_addr in enumerate(self._listening_addresses):
                if listening_addr != "0.0.0.0":
                    self._logger.warning(
                        "No interface matches target %s; falling back to "
                        "transport %d (%s). Device may not reply if its "
                        "subnet is not reachable from this interface.",
                        target_ip,
                        i,
                        listening_addr,
                    )
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

    def _schedule_evict(self) -> None:
        if self._evict_handle is not None:
            self._evict_handle.cancel()
        self._evict_handle = self._loop.call_later(
            self._evict_interval, self._evict_tick
        )

    def _evict_tick(self) -> None:
        # Periodic eviction pass. _evict() also runs opportunistically from
        # _handle_scan_response, but that path alone never fires when *no*
        # device answers — exactly the situation where eviction matters most.
        self._evict_handle = None
        if not self._evict_enabled:
            return
        self._evict()
        self._schedule_evict()

    def _evict(self) -> None:
        # lastseen is timezone-aware UTC; a naive now() would raise on
        # subtraction.
        now = datetime.now(timezone.utc)
        devices = dict(self._registry.discovered_devices)
        for fingerprint, device in devices.items():
            diff: timedelta = now - device.lastseen
            if diff.total_seconds() >= self._evict_interval:
                self._registry.remove_discovered_device(fingerprint)
                if device.is_manual:
                    # A manually-added device must keep being probed after
                    # eviction — with discovery disabled nothing else would
                    # ever contact its IP again, so it would stay gone until
                    # the user re-added it.
                    self._registry.add_device_to_queue(device.ip)
                self._logger.debug("Device evicted: %s", device)
                if self._device_evicted_callback and callable(
                    self._device_evicted_callback
                ):
                    self._device_evicted_callback(device)
