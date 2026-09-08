"""Tests for ``GoveeController.start(require_all=...)`` partial-bind support.

Bind failures are simulated by patching ``_create_listening_socket`` — the
single funnel for socket creation and ``bind()`` — to raise ``OSError`` for
chosen addresses. ``create_datagram_endpoint`` is stubbed so no real socket
or event loop is needed.
"""

from __future__ import annotations

import asyncio
import errno
import ipaddress
import unittest
from unittest.mock import Mock

from govee_local_api.controller import GoveeController

ADDRESSES = ["192.168.1.100/24", "10.0.0.100/8", "172.16.1.100/16"]


def _make_controller(addresses=ADDRESSES) -> tuple[GoveeController, Mock]:
    """Controller with a Mock loop, periodic tasks disabled and a Mock logger."""
    logger = Mock()
    controller = GoveeController(
        loop=Mock(),
        listening_addresses=addresses,
        discovery_enabled=False,
        update_enabled=False,
        evict_enabled=False,
        logger=logger,
    )
    return controller, logger


def _install_endpoints(
    controller: GoveeController, failures: dict[str, OSError] | None = None
) -> dict[str, Mock]:
    """Stub socket creation + endpoint creation.

    Addresses in ``failures`` raise the given OSError from
    ``_create_listening_socket``; every other address yields a Mock transport
    (recorded in the returned dict by address) and a Mock protocol.
    """
    failures = failures or {}
    transports: dict[str, Mock] = {}

    def create_socket(address):
        if address in failures:
            raise failures[address]
        sock = Mock(name=f"sock-{address}")
        sock.address = address
        return sock

    async def create_endpoint(protocol_factory, sock=None):
        transport = Mock(name=f"transport-{sock.address}")
        transport.is_closing.return_value = False
        transports[sock.address] = transport
        return transport, protocol_factory()

    controller._create_listening_socket = create_socket  # type: ignore[method-assign]
    controller._loop.create_datagram_endpoint = create_endpoint  # type: ignore[method-assign]
    return transports


def _run(coro):
    return asyncio.run(coro)


class TestAllBind(unittest.TestCase):
    def test_all_bind_reports_no_failures(self):
        controller, logger = _make_controller()
        transports = _install_endpoints(controller)

        _run(controller.start(require_all=False))

        self.assertEqual(controller.bind_failures, [])
        self.assertEqual(
            controller.listening_addresses,
            ["192.168.1.100", "10.0.0.100", "172.16.1.100"],
        )
        self.assertEqual(len(controller.networks), 3)
        self.assertEqual(len(controller._transports), 3)
        self.assertEqual(len(controller._protocols), 3)
        self.assertEqual(
            controller._transports,
            [transports[a] for a in controller.listening_addresses],
        )
        logger.warning.assert_not_called()

    def test_default_is_require_all(self):
        controller, _ = _make_controller()
        _install_endpoints(controller)
        _run(controller.start())
        self.assertEqual(len(controller._transports), 3)
        self.assertEqual(controller.bind_failures, [])


class TestPartialBind(unittest.TestCase):
    def test_one_failure_keeps_the_rest(self):
        controller, logger = _make_controller()
        error = OSError(errno.EADDRNOTAVAIL, "Cannot assign requested address")
        _install_endpoints(controller, {"10.0.0.100": error})

        _run(controller.start(require_all=False))

        self.assertEqual(
            controller.listening_addresses, ["192.168.1.100", "172.16.1.100"]
        )
        self.assertEqual(
            controller.networks,
            [
                ipaddress.ip_network("192.168.1.0/24"),
                ipaddress.ip_network("172.16.0.0/16"),
            ],
        )
        self.assertEqual(len(controller._transports), 2)
        self.assertEqual(len(controller._protocols), 2)
        self.assertEqual(controller.bind_failures, [("10.0.0.100", error)])
        self.assertIs(controller.bind_failures[0][1], error)
        # One warning per failed address plus one summary line.
        self.assertEqual(logger.warning.call_count, 2)
        logger.error.assert_not_called()

    def test_index_alignment_after_partial_bind(self):
        """Dropping the failed address from only one of the parallel lists
        would silently route commands out of the wrong interface."""
        controller, _ = _make_controller()
        _install_endpoints(
            controller,
            {"192.168.1.100": OSError(errno.EADDRNOTAVAIL, "stale")},
        )

        _run(controller.start(require_all=False))

        transports = controller._transports
        self.assertIs(
            controller._get_best_transport_for_ip("10.20.30.40"), transports[0]
        )
        self.assertIs(
            controller._get_best_transport_for_ip("172.16.200.1"), transports[1]
        )
        # And the mapping is address → the transport actually bound there.
        by_address = dict(zip(controller.listening_addresses, transports))
        self.assertEqual(by_address["10.0.0.100"]._mock_name, "transport-10.0.0.100")
        self.assertEqual(
            by_address["172.16.1.100"]._mock_name, "transport-172.16.1.100"
        )

    def test_protocols_are_aligned_with_transports(self):
        controller, _ = _make_controller()
        _install_endpoints(
            controller, {"10.0.0.100": OSError(errno.EADDRNOTAVAIL, "stale")}
        )
        _run(controller.start(require_all=False))
        for address, protocol in zip(
            controller.listening_addresses, controller._protocols
        ):
            self.assertEqual(protocol.listening_address, address)

    def test_bind_failures_returns_copy(self):
        controller, _ = _make_controller()
        _install_endpoints(
            controller, {"10.0.0.100": OSError(errno.EADDRNOTAVAIL, "stale")}
        )
        _run(controller.start(require_all=False))
        controller.bind_failures.clear()
        self.assertEqual(len(controller.bind_failures), 1)


class TestTotalFailure(unittest.TestCase):
    def test_all_fail_raises_oserror_with_errno(self):
        controller, _ = _make_controller()
        _install_endpoints(
            controller,
            {a.split("/")[0]: OSError(errno.EADDRNOTAVAIL, "stale") for a in ADDRESSES},
        )

        with self.assertRaises(OSError) as cm:
            _run(controller.start(require_all=False))

        self.assertIs(type(cm.exception), OSError)
        self.assertEqual(cm.exception.errno, errno.EADDRNOTAVAIL)
        self.assertEqual(controller._transports, [])
        self.assertEqual(controller._protocols, [])
        self.assertEqual(len(controller.bind_failures), 3)

    def test_mixed_errnos_prefer_eaddrinuse(self):
        controller, _ = _make_controller()
        inuse = OSError(errno.EADDRINUSE, "Address already in use")
        _install_endpoints(
            controller,
            {
                "192.168.1.100": OSError(errno.EADDRNOTAVAIL, "stale"),
                "10.0.0.100": inuse,
                "172.16.1.100": OSError(errno.EACCES, "denied"),
            },
        )

        with self.assertRaises(OSError) as cm:
            _run(controller.start(require_all=False))

        self.assertIs(cm.exception, inuse)
        self.assertEqual(cm.exception.errno, errno.EADDRINUSE)

    def test_no_eaddrinuse_raises_first_collected(self):
        controller, _ = _make_controller()
        first = OSError(errno.EADDRNOTAVAIL, "stale")
        _install_endpoints(
            controller,
            {
                "192.168.1.100": first,
                "10.0.0.100": OSError(errno.EACCES, "denied"),
                "172.16.1.100": OSError(errno.EPERM, "denied"),
            },
        )
        with self.assertRaises(OSError) as cm:
            _run(controller.start(require_all=False))
        self.assertIs(cm.exception, first)


class TestRequireAll(unittest.TestCase):
    def test_one_failure_raises_and_closes_everything(self):
        """Regression guard for the socket-leak protection: with
        require_all=True a single failure must leave no transport open."""
        controller, _ = _make_controller()
        error = OSError(errno.EADDRINUSE, "Address already in use")
        transports = _install_endpoints(controller, {"10.0.0.100": error})

        with self.assertRaises(OSError) as cm:
            _run(controller.start())

        self.assertIs(cm.exception, error)
        self.assertEqual(controller._transports, [])
        self.assertEqual(controller._protocols, [])
        # The endpoint bound before the failure was closed; the one after
        # the failure was never attempted.
        self.assertEqual(set(transports), {"192.168.1.100"})
        transports["192.168.1.100"].close.assert_called_once()
        # Nothing was tolerated, so nothing is reported as tolerated either.
        self.assertEqual(controller.bind_failures, [])

    def test_endpoint_creation_failure_closes_socket_and_raises(self):
        controller, _ = _make_controller()
        socks: list[Mock] = []

        def create_socket(address):
            sock = Mock(name=f"sock-{address}")
            socks.append(sock)
            return sock

        async def create_endpoint(protocol_factory, sock=None):
            raise OSError(errno.EBADF, "bad fd")

        controller._create_listening_socket = create_socket  # type: ignore[method-assign]
        controller._loop.create_datagram_endpoint = create_endpoint  # type: ignore[method-assign]

        with self.assertRaises(OSError):
            _run(controller.start())
        self.assertEqual(len(socks), 1)
        socks[0].close.assert_called_once()


class TestRestart(unittest.TestCase):
    def test_second_start_retries_full_configured_set(self):
        controller, _ = _make_controller()
        _install_endpoints(
            controller, {"10.0.0.100": OSError(errno.EADDRNOTAVAIL, "stale")}
        )
        _run(controller.start(require_all=False))
        self.assertEqual(len(controller.listening_addresses), 2)
        self.assertEqual(len(controller.bind_failures), 1)

        # The adapter came back: every configured address binds this time.
        attempted: list[str] = []
        real_create = _install_endpoints(controller)
        original = controller._create_listening_socket

        def recording(address):
            attempted.append(address)
            return original(address)

        controller._create_listening_socket = recording  # type: ignore[method-assign]
        _run(controller.start(require_all=False))

        self.assertEqual(attempted, ["192.168.1.100", "10.0.0.100", "172.16.1.100"])
        self.assertEqual(
            controller.listening_addresses,
            ["192.168.1.100", "10.0.0.100", "172.16.1.100"],
        )
        self.assertEqual(len(controller.networks), 3)
        self.assertEqual(len(controller._transports), 3)
        self.assertEqual(len(real_create), 3)
        # bind_failures reflects only the most recent start().
        self.assertEqual(controller.bind_failures, [])

    def test_bind_failures_reset_even_when_start_raises(self):
        controller, _ = _make_controller()
        _install_endpoints(
            controller,
            {a.split("/")[0]: OSError(errno.EADDRNOTAVAIL, "stale") for a in ADDRESSES},
        )
        with self.assertRaises(OSError):
            _run(controller.start(require_all=False))
        self.assertEqual(len(controller.bind_failures), 3)

        _install_endpoints(controller)
        _run(controller.start(require_all=False))
        self.assertEqual(controller.bind_failures, [])
        self.assertEqual(len(controller._transports), 3)


if __name__ == "__main__":
    unittest.main()
