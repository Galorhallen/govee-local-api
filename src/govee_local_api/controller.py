from __future__ import annotations

import asyncio
import errno
import functools
import ipaddress
import logging
import socket
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, NamedTuple

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


class _Listener(NamedTuple):
    """One configured listening address (after dedup and wildcard filtering)."""

    address: str
    network: ipaddress.IPv4Network | None


@dataclass(slots=True)
class _Endpoint:
    """One live UDP endpoint: the address it is bound to and its asyncio pair."""

    address: str
    network: ipaddress.IPv4Network | None
    transport: Any
    protocol: GoveeControllerProtocol


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

        # Live endpoints, one record per bound address. Empty until start().
        self._endpoints: list[_Endpoint] = []
        self._bind_failures: list[tuple[str, OSError]] = []
        self._broadcast_address = broadcast_address
        self._broadcast_port = broadcast_port
        self._listening_port = listening_port
        self._device_command_port = device_command_port
        addresses, networks = _parse_listening_addresses(listening_addresses)
        self._configured: list[_Listener] = [
            _Listener(address, network) for address, network in zip(addresses, networks)
        ]

        # Reject obviously bad input up front so it doesn't surface as a
        # cryptic OSError from socket.bind() later.
        for listener in self._configured:
            try:
                ipaddress.IPv4Address(listener.address)
            except (ipaddress.AddressValueError, ValueError) as exc:
                raise ValueError(
                    f"Invalid IPv4 listening address: {listener.address!r}"
                ) from exc

        # Drop duplicate entries while preserving order; two sockets bound to
        # the same (ip, port) get load-balanced by SO_REUSEPORT and flip the
        # device's preferred transport on every status frame.
        seen: set[str] = set()
        deduped: list[_Listener] = []
        for listener in self._configured:
            if listener.address in seen:
                self._logger.warning(
                    "Duplicate listening address %s; ignoring extra entry",
                    listener.address,
                )
                continue
            seen.add(listener.address)
            deduped.append(listener)
        self._configured = deduped

        # If specific addresses are provided alongside 0.0.0.0, drop the wildcard
        # to avoid duplicate packet processing (0.0.0.0 receives on all interfaces)
        configured_addresses = [listener.address for listener in self._configured]
        if len(configured_addresses) > 1 and "0.0.0.0" in configured_addresses:
            self._logger.warning(
                "Wildcard address 0.0.0.0 mixed with specific addresses %s; "
                "dropping 0.0.0.0 to avoid duplicate packet processing",
                [a for a in configured_addresses if a != "0.0.0.0"],
            )
            self._configured = [
                listener
                for listener in self._configured
                if listener.address != "0.0.0.0"
            ]

        # Empty configuration (e.g. user passed []) would silently produce a
        # working-looking controller that never binds anything. Fail loudly.
        if not self._configured:
            raise ValueError("listening_addresses resulted in an empty configuration")

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

    async def start(self, *, require_all: bool = True) -> None:
        """Bind the listening endpoints and kick off discovery/updates.

        Args:
            require_all: When True (default) every configured address must
                bind; a single failure closes any endpoint already opened by
                this call and re-raises, leaving the controller unbound. When
                False the controller keeps whatever binds successfully and
                raises only if *nothing* binds; the addresses that failed are
                reported through :attr:`bind_failures`.

        Raises:
            OSError: A bind failed (``require_all=True``) or every bind failed
                (``require_all=False``). The ``errno`` of the original error
                is preserved so callers can special-case e.g. ``EADDRINUSE``.
        """
        self._closing = False
        self._bind_failures = []

        # Create datagram endpoints for the full configuration (an unexpected
        # connection_lost or a previous partial start may have dropped some).
        # We build the socket by hand so SO_REUSEADDR / SO_REUSEPORT /
        # SO_BROADCAST are set before bind() — the kernel only honors them at
        # bind time.
        #
        # Successful endpoints are accumulated locally and committed in one
        # go after the loop, so a failing start() never leaves half a set
        # behind.
        bound: list[_Endpoint] = []
        try:
            for listener in self._configured:
                try:
                    transport, protocol = await self._open_endpoint(listener.address)
                except OSError as ex:
                    if require_all:
                        raise
                    self._bind_failures.append((listener.address, ex))
                    self._log_bind_failure(listener.address, ex)
                    continue
                bound.append(
                    _Endpoint(listener.address, listener.network, transport, protocol)
                )
        except Exception:
            # Don't leave earlier endpoints bound: a partially started
            # controller would leak a socket on every setup retry. Clearing
            # the instance lists before closing keeps the ensuing
            # connection_lost callbacks from taking the "unexpected loss"
            # path; the endpoints opened by this call were never in them.
            self._close_all_transports([endpoint.transport for endpoint in bound])
            raise

        if not bound:
            # require_all=False and every bind failed. Re-raise a real OSError
            # (never a wrapper type) so consumers branching on errno keep
            # working. EADDRINUSE is the errno most often treated as
            # transient/retryable, so don't let an unrelated error on another
            # adapter mask it.
            self._close_all_transports([])
            errors = [ex for _, ex in self._bind_failures]
            raise next((ex for ex in errors if ex.errno == errno.EADDRINUSE), errors[0])

        self._endpoints = bound

        if self._bind_failures:
            self._logger.warning(
                "Started with %d of %d listening addresses; live on %s, failed on %s",
                len(bound),
                len(self._configured),
                self.listening_addresses,
                [addr for addr, _ in self._bind_failures],
            )

        if self._discovery_enabled or self._registry.has_queued_devices:
            self.send_discovery_message()
        if self._update_enabled:
            self.send_update_message()
        if self._evict_enabled:
            self._schedule_evict()

    async def rebind_failed(self) -> list[str]:
        """Retry the configured addresses that are not currently bound.

        Covers both the addresses that ``start(require_all=False)`` failed to
        bind and endpoints later dropped by an unexpected ``connection_lost``.
        Each address is tried independently: a bind failure is logged, kept
        in :attr:`bind_failures` (with the fresh error) and never raised, so
        this is safe to call periodically (e.g. on a timer or a network-change
        event) without disturbing the live endpoints or the discovered
        devices. A recovered address is put back at its configured position
        so transport selection order is unchanged.

        Returns:
            The addresses that were bound by this call (empty when nothing
            was missing or nothing came back).

        Raises:
            RuntimeError: The controller is shut(ting) down or has no live
                endpoint. Use :meth:`start` in that case — only ``start()``
                arms the discovery/update/evict timers.
        """
        if self._closing or not self._endpoints:
            raise RuntimeError(
                "rebind_failed() requires a running controller; call start() instead"
            )

        live = {endpoint.address for endpoint in self._endpoints}
        missing = [
            listener for listener in self._configured if listener.address not in live
        ]
        if not missing:
            return []

        rebound: list[str] = []
        for address, network in missing:
            try:
                transport, protocol = await self._open_endpoint(address)
            except OSError as ex:
                self._bind_failures = [
                    (a, e) for a, e in self._bind_failures if a != address
                ]
                self._bind_failures.append((address, ex))
                self._log_bind_failure(address, ex)
                continue

            if self._closing:
                # cleanup() ran while we were awaiting the endpoint. The new
                # transport was never added to the instance lists, so its
                # connection_lost is ignored by _protocol_disconnected.
                transport.close()
                break

            self._bind_failures = [
                (a, e) for a, e in self._bind_failures if a != address
            ]
            self._endpoints.append(_Endpoint(address, network, transport, protocol))
            rebound.append(address)

        if rebound:
            # Put recovered endpoints back at their configured position:
            # _get_best_transport_for_ip returns the first match, so order
            # is behavior.
            order = {listener.address: i for i, listener in enumerate(self._configured)}
            self._endpoints.sort(key=lambda endpoint: order[endpoint.address])
            self._bind_failures.sort(key=lambda failure: order[failure[0]])
            self._logger.info(
                "Rebound UDP endpoint on %s:%d; live on %s",
                rebound,
                self._listening_port,
                self.listening_addresses,
            )
            if self._discovery_enabled or self._registry.has_queued_devices:
                self.send_discovery_message()

        if self._bind_failures:
            self._logger.warning(
                "Still unable to bind %s", [addr for addr, _ in self._bind_failures]
            )

        return rebound

    async def _open_endpoint(self, listening_address: str) -> tuple[Any, Any]:
        """Bind a listening socket on ``listening_address`` and wrap it in a
        datagram endpoint. The socket is closed if the endpoint fails."""
        sock = self._create_listening_socket(listening_address)
        try:
            return await self._loop.create_datagram_endpoint(
                functools.partial(GoveeControllerProtocol, self, listening_address),
                sock=sock,
            )
        except Exception:
            sock.close()
            raise

    def _log_bind_failure(self, listening_address: str, ex: OSError) -> None:
        self._logger.warning(
            "Failed to bind UDP endpoint on %s:%d (errno %s: %s); "
            "continuing with the remaining addresses",
            listening_address,
            self._listening_port,
            ex.errno,
            ex.strerror or ex,
        )

    def _close_all_transports(self, extra: list[Any]) -> None:
        """Close ``extra`` plus every live transport, clearing the endpoint
        list first so connection_lost sees a shutdown."""
        transports = [endpoint.transport for endpoint in self._endpoints] + extra
        self._endpoints.clear()
        for transport in transports:
            if not transport.is_closing():
                transport.close()

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
        if not self._endpoints and self._cleanup_done.is_set():
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

        if not self._endpoints:
            self._cleanup_done.set()
            self._registry.cleanup()
            return self._cleanup_done

        # Completion is signalled after this many connection_lost callbacks.
        # A second cleanup() while the first drain is in flight must NOT
        # reset the countdown — some callbacks have already been counted.
        if not already_closing:
            self._pending_close = len(self._endpoints)
        for endpoint in self._endpoints:
            if not endpoint.transport.is_closing():
                endpoint.transport.close()

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
            endpoint.address
            for endpoint in self._endpoints
            if not endpoint.transport.is_closing()
        ]
        if stragglers:
            self._logger.warning(
                "cleanup() timed out waiting for connection_lost; "
                "forcing completion. Stragglers: %s",
                stragglers,
            )
        self._endpoints.clear()
        self._cleanup_done.set()

    @property
    def protocols(self) -> list[GoveeControllerProtocol]:
        """Protocols of the live endpoints, aligned with :attr:`listening_addresses`.

        Returns a copy.
        """
        return [endpoint.protocol for endpoint in self._endpoints]

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
        """The addresses currently bound, or the effective configuration when
        no endpoint is live (before ``start()``, after a failed one, or after
        ``cleanup()``). Index-aligned with :attr:`networks`. Returns a copy.
        """
        if self._endpoints:
            return [endpoint.address for endpoint in self._endpoints]
        return [listener.address for listener in self._configured]

    @property
    def networks(self) -> list[ipaddress.IPv4Network | None]:
        """The parsed network of each entry in :attr:`listening_addresses`
        (``None`` when supplied without a mask). Returns a copy.
        """
        if self._endpoints:
            return [endpoint.network for endpoint in self._endpoints]
        return [listener.network for listener in self._configured]

    @property
    def bind_failures(self) -> list[tuple[str, OSError]]:
        """Addresses that failed to bind during the last start(), with the error.

        Only populated when ``start(require_all=False)`` tolerated failures;
        reset on every ``start()`` call. :meth:`rebind_failed` removes the
        addresses that come back and refreshes the error of those that still
        fail. Returns a copy.
        """
        return self._bind_failures.copy()

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
        if not self._endpoints:
            return

        if self._discovery_enabled:
            call_later = True
            # Send broadcast messages from each listening address/transport
            for i, endpoint in enumerate(self._endpoints):
                self._logger.debug(
                    "Sending discovery broadcast from interface %s (%s) to %s:%s",
                    i,
                    endpoint.address,
                    self._broadcast_address,
                    self._broadcast_port,
                )
                endpoint.transport.sendto(
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
        if self._endpoints:
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
                self._endpoints.clear()
                if self._cleanup_timeout_handle is not None:
                    self._cleanup_timeout_handle.cancel()
                    self._cleanup_timeout_handle = None
                self._cleanup_done.set()
            return

        endpoint = next((e for e in self._endpoints if e.protocol is protocol), None)
        if endpoint is None:
            return

        self._endpoints.remove(endpoint)
        if not endpoint.transport.is_closing():
            endpoint.transport.close()
        if self._endpoints:
            self._logger.error(
                "UDP endpoint on %s closed unexpectedly; continuing on %s",
                endpoint.address,
                self.listening_addresses,
            )
        else:
            self._logger.error(
                "UDP endpoint on %s closed unexpectedly and no endpoints "
                "remain; the controller is inoperative until restarted",
                endpoint.address,
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
        if self._endpoints:
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
        if not self._endpoints:
            raise RuntimeError("No transports available")

        if len(self._endpoints) == 1:
            return self._endpoints[0].transport

        try:
            target_addr = ipaddress.ip_address(target_ip)

            for i, endpoint in enumerate(self._endpoints):
                listening_addr, network = endpoint.address, endpoint.network
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
                        return self._endpoints[i].transport
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
                            return self._endpoints[i].transport
                    except ValueError:
                        continue

            # If no network match found, prefer non-wildcard addresses. This
            # is a best-effort fallback: the packet leaves with a source IP
            # that may not belong to the target's subnet, so the device's
            # reply may never come back. Warn so this is diagnosable.
            for i, endpoint in enumerate(self._endpoints):
                listening_addr = endpoint.address
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
                    return self._endpoints[i].transport

        except ValueError:
            # Invalid IP address, fall back to first transport
            pass

        # Fallback to first transport
        self._logger.debug(
            "Selected transport 0 (%s) for target %s (fallback)",
            self._endpoints[0].address,
            target_ip,
        )
        return self._endpoints[0].transport

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
