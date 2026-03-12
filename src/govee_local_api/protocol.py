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

        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        self.controller._logger.debug(
            "Protocol connected for listening address: %s", self.listening_address
        )

        broadcast_ip = ipaddress.ip_address(self.controller._broadcast_address)

        if broadcast_ip.is_multicast:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

            sock.setsockopt(
                socket.SOL_IP,
                socket.IP_MULTICAST_IF,
                socket.inet_aton(self.listening_address),
            )
            sock.setsockopt(
                socket.SOL_IP,
                socket.IP_ADD_MEMBERSHIP,
                socket.inet_aton(self.controller._broadcast_address)
                + socket.inet_aton(self.listening_address),
            )

    def connection_lost(self, *args, **kwargs):
        if self.transport:
            broadcast_ip = ipaddress.ip_address(self.controller._broadcast_address)
            if broadcast_ip.is_multicast:
                sock = self.transport.get_extra_info("socket")
                sock.setsockopt(
                    socket.SOL_IP,
                    socket.IP_DROP_MEMBERSHIP,
                    socket.inet_aton(self.controller._broadcast_address)
                    + socket.inet_aton(self.listening_address),
                )
        self.controller._logger.debug("Disconnected from %s", self.listening_address)
        self.controller._protocol_disconnected()

    def datagram_received(self, data: bytes, addr: tuple):
        if data:
            self.controller._loop.create_task(
                self.controller._handle_datagram_received(data, addr, self)
            )
