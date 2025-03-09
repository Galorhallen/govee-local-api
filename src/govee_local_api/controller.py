from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, cast

from .device import GoveeDevice
from .light_capabilities import (
    GOVEE_LIGHT_CAPABILITIES,
    ON_OFF_CAPABILITIES,
    GoveeLightCapabilities,
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

BROADCAST_ADDRESS = "239.255.255.250"
BROADCAST_PORT = 4001
LISTENING_PORT = 4002
COMMAND_PORT = 4003

DISCOVERY_INTERVAL = 10
EVICT_INTERVAL = DISCOVERY_INTERVAL * 3
UPDATE_INTERVAL = 5

# This defines the wait times for retries (spread out over 30 seconds).
RETRY_PATTERN = [0.2, 0.3, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]


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
        self._pending_command_tasks: dict[str, asyncio.Task] = {}
        self._state_verification_events: dict[str, tuple[asyncio.Event, Callable]] = {}

    async def start(self):
        self._transport, self._protocol = await self._loop.create_datagram_endpoint(
            lambda: self, local_addr=(self._listening_address, self._listening_port)
        )

        if self._discovery_enabled:
            self.send_discovery_message()
        if self._update_enabled:
            self.send_update_message()

    async def _execute_command(
        self,
        device: GoveeDevice,
        message: GoveeMessage,
        verify_state_callback=None
    ) -> None:
        """
        Execute a command with retry queue and optional state verification.

        Args:
            device: The target device
            message: The message to send
            verify_state_callback: Optional callback that returns True when desired state is reached
        """
        device_key = f"{device.fingerprint}_{message.command}"

        # Cancel any existing task for this device and command
        if device_key in self._pending_command_tasks:
            existing_task = self._pending_command_tasks[device_key]
            if not existing_task.done():
                existing_task.cancel()
                try:
                    await existing_task
                except asyncio.CancelledError:
                    self._logger.debug(f"Cancelled pending {message.command} task for device {device}")

        # Create and store the new task
        task = self._loop.create_task(
            self._execute_with_retries(device, message, verify_state_callback)
        )
        self._pending_command_tasks[device_key] = task

        task.add_done_callback(
            lambda t: self._pending_command_tasks.pop(device_key, None)
        )

        await task

    async def _execute_with_retries(
        self,
        device: GoveeDevice,
        message: GoveeMessage,
        verify_state_callback=None,
        max_retries: int = 10
    ) -> None:
        """
        Execute a command with multiple retries and optional state verification.

        Args:
            device: The target device
            message: The message to send
            verify_state_callback: Function that returns True when desired state is reached
            max_retries: Maximum number of retry attempts
        """
        # Send the initial message immediately
        self._send_message(message, device)
        # Always wait 100ms between msg and status update to lessen spam.
        await asyncio.sleep(0.1)
        # Request initial status update
        self._send_update_message(device)

        # If no verification callback, just use retries without verification
        if not verify_state_callback:
            return await self._execute_basic_retries(device, message, max_retries)

        # Create a state verification event
        state_changed_event = asyncio.Event()
        device_key = device.fingerprint

        # Register our event and verification callback
        self._state_verification_events[device_key] = (state_changed_event, verify_state_callback)

        try:
            # Send retries with increasing delays
            for i, delay in enumerate(RETRY_PATTERN[:max_retries-1]):
                try:
                    # Wait for either the delay to complete or the state to change
                    state_changed_task = asyncio.create_task(state_changed_event.wait())
                    delay_task = asyncio.create_task(asyncio.sleep(delay))

                    # Wait for either task to complete
                    try:
                        done, pending = await asyncio.wait(
                            [state_changed_task, delay_task],
                            return_when=asyncio.FIRST_COMPLETED
                        )

                        # Cancel the pending task
                        for task in pending:
                            task.cancel()
                            try:
                                # Wait for the cancelled task to complete
                                await task
                            except asyncio.CancelledError:
                                # This is expected for cancelled tasks
                                pass

                        # If state changed, we're done
                        if state_changed_task in done and not state_changed_task.cancelled():
                            if state_changed_task.result():
                                self._logger.debug(f"Stopping retries for {device}: {message.command} - desired state reached")
                                return
                    except asyncio.CancelledError:
                        state_changed_task.cancel()
                        delay_task.cancel()
                        try:
                            await asyncio.gather(state_changed_task, delay_task, return_exceptions=True)
                        except asyncio.CancelledError:
                            pass
                        raise

                    # Check if we've been cancelled
                    if asyncio.current_task().cancelled():
                        return

                    # Send the command again
                    self._send_message(message, device)
                    await asyncio.sleep(0.1)
                    self._send_update_message(device)
                    self._logger.debug(f"Retry {i+1} for {device}: {message.command}")
                except asyncio.CancelledError:
                    self._logger.debug(f"Cancelled during retry {i+1} for {device}")
                    raise
        finally:
            # Clean up our event registration
            self._state_verification_events.pop(device_key, None)

    async def _execute_basic_retries(
        self,
        device: GoveeDevice,
        message: GoveeMessage,
        max_retries: int = 10
    ) -> None:
        """Simple retry pattern without state verification."""

        # Send retries with increasing delays
        for i, delay in enumerate(RETRY_PATTERN[:max_retries-1]):
            try:
                await asyncio.sleep(delay)
                # Check if we've been cancelled
                if asyncio.current_task().cancelled():
                    return
                self._send_message(message, device)
                # Request a status update after sending the command
                self._send_update_message(device)
                self._logger.debug(f"Retry {i+1} for {device}: {message.command}")
            except asyncio.CancelledError:
                self._logger.debug(f"Cancelled during retry {i+1} for {device}")
                raise

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
        capabilities: GoveeLightCapabilities,
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
        """Send an on/off command with robust retry and confirmation."""
        message = OnOffMessage(status)

        # Verification callback to check if device status matches desired state
        def verify_state(device_state):
            return device_state.on == status

        await self._execute_command(device, message, verify_state)

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
        """Set brightness with robust retry and confirmation."""
        message = BrightnessMessage(brightness)

        # Verification callback to check if device brightness matches desired value
        def verify_state(device_state):
            return device_state.brightness == brightness

        await self._execute_command(device, message, verify_state)

    async def set_color(
        self,
        device: GoveeDevice,
        *,
        rgb: tuple[int, int, int] | None,
        temperature: int | None,
    ) -> None:
        """Set color with robust retry and confirmation."""
        message = ColorMessage(rgb=rgb, temperature=temperature)

        # Verification callback to check if device color matches desired values
        def verify_state(device_state):
            if rgb and device_state._rgb_color:
                # Allow for small differences in RGB values
                return all(abs(a - b) <= 5 for a, b in zip(device_state._rgb_color, rgb))
            elif temperature and device_state._temperature_color:
                # Allow for small differences in temperature
                return abs(device_state._temperature_color - temperature) <= 100
            return False

        await self._execute_command(device, message, verify_state)

    async def send_raw_command(self, device: GoveeDevice, command: str) -> None:
        self._send_message(HexMessage([command]), device)

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
        if data:
            self._loop.create_task(self._handle_datagram_received(data, addr))

    async def _handle_datagram_received(self, data: bytes, addr: tuple):
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
            await self._handle_scan_response(cast(ScanResponse, message))
        elif message.command == DevStatusResponse.command:
            await self._handle_status_update_response(
                cast(DevStatusResponse, message), addr
            )

    async def _handle_status_update_response(self, message: DevStatusResponse, addr):
        self._logger.debug(f"Status update received from {addr}: {message}")
        ip = addr[0]
        if device := self.get_device_by_ip(ip):
            device.update(message)

            # Check if we're waiting for a state verification on this device
            device_key = device.fingerprint
            if device_key in self._state_verification_events:
                event, verify_callback = self._state_verification_events[device_key]
                # Check if the new state matches what we're waiting for
                if verify_callback(device):
                    self._logger.debug(f"Device {device} reached desired state")
                    event.set()

    async def _handle_scan_response(self, message: ScanResponse) -> None:
        fingerprint = message.device
        if device := self.get_device_by_fingerprint(fingerprint):
            if self._call_discovered_callback(device, False):
                device.update_lastseen()
                self._logger.debug("Device updated: %s", device)
        else:
            capabilities = GOVEE_LIGHT_CAPABILITIES.get(message.sku, None)
            if not capabilities:
                capabilities = ON_OFF_CAPABILITIES
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

        if self._evict_enabled:
            self._evict()

    def _call_discovered_callback(self, device: GoveeDevice, is_new: bool) -> bool:
        if not self._device_discovered_callback:
            return True
        return self._device_discovered_callback(device, is_new)

    def _send_message(self, message: GoveeMessage, device: GoveeDevice) -> None:
        self._transport.sendto(bytes(message), (device.ip, self._device_command_port))

    def _send_update_message(self, device: GoveeDevice):
        self._send_message(DevStatusMessage(), device)

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
