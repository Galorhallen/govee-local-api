from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .controller import GoveeController


class GoveeControllerProtocol(asyncio.DatagramProtocol):
    """Protocol handler for a single network interface."""

    def __init__(self, controller: GoveeController, listening_address: str):
        self.controller = controller
        self.listening_address = listening_address
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport
        sock = transport.get_extra_info("socket")

        # SO_REUSEADDR / SO_REUSEPORT / SO_BROADCAST are configured on the raw
        # socket before bind() in GoveeController._create_listening_socket;
        # they cannot be applied here because bind has already happened.

        self.controller._logger.debug(
            "Protocol connected for listening address: %s", self.listening_address
        )

        broadcast_ip = ipaddress.ip_address(self.controller._broadcast_address)

        if broadcast_ip.is_multicast:
            # IPPROTO_IP is portable; SOL_IP is Linux-only.
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
                sock.setsockopt(
                    socket.IPPROTO_IP,
                    socket.IP_MULTICAST_IF,
                    socket.inet_aton(self.listening_address),
                )
                sock.setsockopt(
                    socket.IPPROTO_IP,
                    socket.IP_ADD_MEMBERSHIP,
                    socket.inet_aton(self.controller._broadcast_address)
                    + socket.inet_aton(self.listening_address),
                )
            except OSError as exc:
                # Typical cause: listening_address is not a local interface,
                # so IP_MULTICAST_IF / IP_ADD_MEMBERSHIP fail. Without this
                # try/except the exception is swallowed by asyncio and the
                # transport looks healthy while silently never sending
                # multicast discovery on this interface.
                self.controller._logger.error(
                    "Failed to configure multicast on %s: %s. "
                    "Discovery on this interface will not work.",
                    self.listening_address,
                    exc,
                )

    def connection_lost(self, *args, **kwargs):
        self.controller._logger.debug("Disconnected from %s", self.listening_address)
        self.controller._protocol_disconnected()

    def datagram_received(self, data: bytes, addr: tuple):
        if data:
            self.controller._loop.create_task(
                self.controller._handle_datagram_received(data, addr, self)
            )

    def error_received(self, exc: Exception) -> None:
        # asyncio calls this when a sendto() or recvfrom() raises an OSError
        # asynchronously — typically ICMP "destination unreachable" or
        # ENETDOWN/EHOSTDOWN after a NIC goes down. The default base-class
        # implementation does nothing, so without this override the failure
        # is invisible and the controller keeps trying to use a dead
        # transport.
        self.controller._logger.warning(
            "UDP error on interface %s: %r", self.listening_address, exc
        )
