import asyncio
import ipaddress
import logging
import socket
from collections.abc import Callable
from typing import Any


class GoveeLanProtocol(asyncio.DatagramProtocol):
    def __init__(
        self,
        loop,
        broadcast_address: str,
        broadcast_port: int,
        listening_address: str,
        listening_port: int,
        device_command_port: int,
        data_received_callback: Callable[
            ["GoveeLanProtocol", bytes, tuple[str | Any, int]], None
        ],
        connection_lost_callback: Callable[["GoveeLanProtocol"], None],
    ) -> None:
        self._transport: Any = None

        self._logger = logging.getLogger(__name__)
        self._broadcast_address = broadcast_address
        self._broadcast_port = broadcast_port
        self._listening_address = listening_address
        self._listening_port = listening_port
        self._device_command_port = device_command_port
        self._loop = loop or asyncio.get_running_loop()
        self._cleanup_done: asyncio.Event = asyncio.Event()
        self._data_received_callback = data_received_callback
        self._connection_lost_callback = connection_lost_callback

    @property
    def broadcast_address(self) -> str:
        return self._broadcast_address

    @property
    def broadcast_port(self) -> int:
        return self._broadcast_port

    @property
    def listening_address(self) -> str:
        return self._listening_address

    @property
    def listening_port(self) -> int:
        return self._listening_port

    async def start(self) -> None:
        await self._loop.create_datagram_endpoint(
            lambda: self,
            local_addr=(self._listening_address, self._listening_port),
        )

    def broadcast(self, data: bytes) -> None:
        if self._transport:
            self._transport.sendto(
                data, (self._broadcast_address, self._broadcast_port)
            )

    def send_to(self, data: bytes, address: str, port: int) -> None:
        if self._transport:
            self._transport.sendto(data, (address, port))

    def cleanup(self) -> asyncio.Event:
        self._cleanup_done.clear()

        if self._transport:
            self._transport.close()
        return self._cleanup_done

    def connection_made(self, transport: Any) -> None:
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

    def connection_lost(self, *args, **kwargs) -> None:
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
        self._connection_lost_callback(self)

    def datagram_received(self, data: bytes, addr: tuple):
        self._data_received_callback(self, data, addr)
