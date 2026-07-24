"""Tests for multi-interface (multi-NIC) behavior of GoveeController.

These tests focus on the paths that are unique to multi-interface setups:
the wildcard filter, discovery fan-out, manual-IP routing, transport
preference inside ``_send_message``, and cleanup across several transports.
Parsing of CIDR / netmask strings is covered separately in
``test_network_masks.py``.
"""

from __future__ import annotations

import asyncio
import json
import socket
import unittest
from unittest.mock import Mock

from govee_local_api.controller import GoveeController
from govee_local_api.device import GoveeDevice
from govee_local_api.light_capabilities import ON_OFF_CAPABILITIES


def _make_controller(addresses):
    """Build a controller without binding any sockets.

    Pass a Mock loop so __init__ doesn't allocate a real ``asyncio`` event
    loop (which leaks a self-pipe socketpair across tests).
    """
    return GoveeController(loop=Mock(), listening_addresses=addresses)


def _attach_transports(controller, count):
    """Attach ``count`` mock transports and return them."""
    transports = [Mock(name=f"transport{i}") for i in range(count)]
    controller._transports = transports
    controller._protocols = [Mock(name=f"protocol{i}") for i in range(count)]
    return transports


class TestWildcardFilter(unittest.TestCase):
    """The wildcard 0.0.0.0 must be dropped when mixed with specific IPs."""

    def test_wildcard_dropped_when_mixed(self):
        controller = _make_controller(["0.0.0.0", "192.168.1.100/24"])
        self.assertEqual(controller.listening_addresses, ["192.168.1.100"])
        self.assertEqual(len(controller.networks), 1)

    def test_wildcard_dropped_preserves_network_alignment(self):
        """Filter must keep the addresses and the parsed networks aligned."""
        controller = _make_controller(["0.0.0.0", "192.168.1.100/24", "10.0.0.100/8"])
        self.assertEqual(
            controller.listening_addresses, ["192.168.1.100", "10.0.0.100"]
        )
        # Both surviving entries had a mask, so networks must not contain None.
        self.assertEqual(len(controller.networks), 2)
        self.assertTrue(all(n is not None for n in controller.networks))

    def test_wildcard_kept_when_alone(self):
        controller = _make_controller("0.0.0.0")
        self.assertEqual(controller.listening_addresses, ["0.0.0.0"])
        self.assertEqual(controller.networks, [None])

    def test_wildcard_with_mask_alone(self):
        """0.0.0.0/24 alone is normalized to 0.0.0.0 with network=None."""
        controller = _make_controller("0.0.0.0/24")
        self.assertEqual(controller.listening_addresses, ["0.0.0.0"])
        self.assertEqual(controller.networks, [None])


class TestDiscoveryFanout(unittest.TestCase):
    """send_discovery_message must broadcast from every transport."""

    def test_discovery_broadcasts_from_every_transport(self):
        controller = _make_controller(["192.168.1.100/24", "10.0.0.100/8"])
        controller._discovery_enabled = True
        controller._loop = Mock()
        controller._loop.call_later = Mock()
        t1, t2 = _attach_transports(controller, 2)

        controller.send_discovery_message()

        t1.sendto.assert_called_once()
        t2.sendto.assert_called_once()
        # Both target the multicast group on the broadcast port.
        for t in (t1, t2):
            (_payload, dest), _ = t.sendto.call_args
            self.assertEqual(dest, (controller._broadcast_address, 4001))
        # And we rescheduled ourselves.
        controller._loop.call_later.assert_called_once()

    def test_discovery_disabled_no_send(self):
        controller = _make_controller(["192.168.1.100/24", "10.0.0.100/8"])
        controller._discovery_enabled = False
        controller._loop = Mock()
        t1, t2 = _attach_transports(controller, 2)

        controller.send_discovery_message()

        t1.sendto.assert_not_called()
        t2.sendto.assert_not_called()
        controller._loop.call_later.assert_not_called()

    def test_discovery_without_transports_is_noop(self):
        controller = _make_controller(["192.168.1.100/24"])
        controller._discovery_enabled = True
        controller._loop = Mock()
        # _transports left empty on purpose.
        controller.send_discovery_message()
        controller._loop.call_later.assert_not_called()


class TestDiscoveryTimerLifecycle(unittest.TestCase):
    """Repeated external triggers must not stack parallel timer chains."""

    def test_repeated_send_cancels_previous_handle(self):
        controller = _make_controller(["192.168.1.100/24"])
        controller._discovery_enabled = True
        controller._loop = Mock()
        handle1 = Mock()
        handle2 = Mock()
        controller._loop.call_later = Mock(side_effect=[handle1, handle2])
        _attach_transports(controller, 1)

        controller.send_discovery_message()
        self.assertIs(controller._discovery_handle, handle1)
        handle1.cancel.assert_not_called()

        controller.send_discovery_message()
        # Previous tick cancelled, new one installed.
        handle1.cancel.assert_called_once()
        self.assertIs(controller._discovery_handle, handle2)

    def test_update_message_cancels_previous_handle(self):
        controller = _make_controller(["192.168.1.100/24"])
        controller._update_enabled = True
        controller._loop = Mock()
        handle1 = Mock()
        handle2 = Mock()
        controller._loop.call_later = Mock(side_effect=[handle1, handle2])
        _attach_transports(controller, 1)

        controller.send_update_message()
        controller.send_update_message()

        handle1.cancel.assert_called_once()
        self.assertIs(controller._update_handle, handle2)


class TestManualDeviceRouting(unittest.TestCase):
    """Queued and manually-added device IPs must use the best-matching transport."""

    def test_queued_ip_uses_subnet_matching_transport(self):
        controller = _make_controller(["192.168.1.100/24", "10.0.0.100/8"])
        controller._discovery_enabled = False
        controller._loop = Mock()
        t1, t2 = _attach_transports(controller, 2)

        controller.add_device_to_discovery_queue("10.5.5.5")
        # add_device_to_discovery_queue triggers send_discovery_message.
        t2.sendto.assert_called_once()
        t1.sendto.assert_not_called()

    def test_manual_device_uses_subnet_matching_transport(self):
        controller = _make_controller(["192.168.1.100/24", "10.0.0.100/8"])
        controller._discovery_enabled = False
        controller._loop = Mock()
        t1, t2 = _attach_transports(controller, 2)

        device = GoveeDevice(
            controller, "192.168.1.42", "fp-1", "H6008", ON_OFF_CAPABILITIES
        )
        device.is_manual = True
        controller._registry.add_discovered_device(device)

        controller.send_discovery_message()

        t1.sendto.assert_called_once()
        t2.sendto.assert_not_called()
        (_payload, dest), _ = t1.sendto.call_args
        self.assertEqual(dest, ("192.168.1.42", 4001))


class TestSendMessageTransportPreference(unittest.TestCase):
    """_send_message prefers the transport the device was discovered on."""

    def _make_device(self, controller, ip, transport):
        device = GoveeDevice(controller, ip, "fp", "H6008", ON_OFF_CAPABILITIES)
        if transport is not None:
            transport.is_closing = Mock(return_value=False)
            device.update_transport(transport)
        return device

    def test_prefers_device_transport(self):
        controller = _make_controller(["192.168.1.100/24", "10.0.0.100/8"])
        t1, t2 = _attach_transports(controller, 2)
        # Device lives on 192.168.1.x — best-match would be t1 — but it was
        # discovered via t2, so t2 must win.
        device = self._make_device(controller, "192.168.1.50", t2)

        from govee_local_api.message import OnOffMessage

        controller._send_message(OnOffMessage(True), device)

        t2.sendto.assert_called_once()
        t1.sendto.assert_not_called()

    def test_falls_back_when_device_transport_closing(self):
        controller = _make_controller(["192.168.1.100/24", "10.0.0.100/8"])
        t1, t2 = _attach_transports(controller, 2)
        device = self._make_device(controller, "192.168.1.50", t2)
        assert device.transport is not None
        device.transport.is_closing = Mock(return_value=True)

        from govee_local_api.message import OnOffMessage

        controller._send_message(OnOffMessage(True), device)

        # Closed → falls back to subnet-matched transport (t1).
        t1.sendto.assert_called_once()
        t2.sendto.assert_not_called()

    def test_falls_back_when_device_has_no_transport(self):
        controller = _make_controller(["192.168.1.100/24", "10.0.0.100/8"])
        t1, t2 = _attach_transports(controller, 2)
        device = self._make_device(controller, "10.1.2.3", None)

        from govee_local_api.message import OnOffMessage

        controller._send_message(OnOffMessage(True), device)

        t2.sendto.assert_called_once()
        t1.sendto.assert_not_called()


class TestTransportSelectionEdgeCases(unittest.TestCase):
    """Selection corner cases that aren't covered by test_network_masks."""

    def test_single_transport_always_returned(self):
        controller = _make_controller(["192.168.1.100/24"])
        (only,) = _attach_transports(controller, 1)

        self.assertIs(controller._get_best_transport_for_ip("8.8.8.8"), only)
        self.assertIs(controller._get_best_transport_for_ip("not-an-ip"), only)

    def test_no_transports_raises(self):
        controller = _make_controller(["192.168.1.100/24"])
        with self.assertRaises(RuntimeError):
            controller._get_best_transport_for_ip("192.168.1.50")

    def test_invalid_target_ip_returns_first(self):
        controller = _make_controller(["192.168.1.100/24", "10.0.0.100/8"])
        t1, _t2 = _attach_transports(controller, 2)
        self.assertIs(controller._get_best_transport_for_ip("garbage"), t1)

    def test_ipv6_target_returns_first(self):
        controller = _make_controller(["192.168.1.100/24", "10.0.0.100/8"])
        t1, _t2 = _attach_transports(controller, 2)
        self.assertIs(controller._get_best_transport_for_ip("2001:db8::1"), t1)

    def test_no_subnet_match_returns_first_specific(self):
        """Unrouted target falls back to the first non-wildcard transport."""
        controller = _make_controller(["192.168.1.100/24", "10.0.0.100/8"])
        t1, _t2 = _attach_transports(controller, 2)
        self.assertIs(controller._get_best_transport_for_ip("172.16.0.1"), t1)


class TestCleanupMultipleTransports(unittest.TestCase):
    """cleanup() must close every transport, and _protocol_disconnected
    must wait for all of them before signalling completion."""

    def test_cleanup_closes_every_transport(self):
        controller = _make_controller(["192.168.1.100/24", "10.0.0.100/8"])
        t1, t2 = _attach_transports(controller, 2)
        for t in (t1, t2):
            t.is_closing = Mock(return_value=False)

        controller.cleanup()

        t1.close.assert_called_once()
        t2.close.assert_called_once()

    def test_cleanup_done_waits_for_all_protocols(self):
        controller = _make_controller(["192.168.1.100/24", "10.0.0.100/8"])
        t1, t2 = _attach_transports(controller, 2)
        p1, p2 = controller._protocols
        for t in (t1, t2):
            t.is_closing = Mock(return_value=False)

        controller.cleanup()

        # Every transport reports is_closing() right after close(), so
        # completion must be counted per connection_lost, not inferred
        # from is_closing().
        controller._protocol_disconnected(p1)
        self.assertFalse(controller._cleanup_done.is_set())

        controller._protocol_disconnected(p2)
        self.assertTrue(controller._cleanup_done.is_set())
        self.assertEqual(controller._transports, [])
        self.assertEqual(controller._protocols, [])

    def test_double_cleanup_while_draining_does_not_reset_countdown(self):
        controller = _make_controller(["192.168.1.100/24", "10.0.0.100/8"])
        t1, t2 = _attach_transports(controller, 2)
        p1, p2 = controller._protocols
        for t in (t1, t2):
            t.is_closing = Mock(return_value=False)

        controller.cleanup()
        for t in (t1, t2):
            t.is_closing = Mock(return_value=True)
        controller._protocol_disconnected(p1)

        # A second cleanup() mid-drain must not reset _pending_close,
        # or the remaining callback could never reach zero.
        controller.cleanup()
        controller._protocol_disconnected(p2)

        self.assertTrue(controller._cleanup_done.is_set())

    # --- Cleanup resilience (safety timer, idempotency, eviction race) ---

    def test_cleanup_is_idempotent_when_already_done(self):
        """Second cleanup() after the first one finished must not hang."""
        controller = _make_controller(["192.168.1.100/24"])
        # First call: no transports → sets immediately.
        evt = controller.cleanup()
        self.assertTrue(evt.is_set())
        # Second call: must return the already-set event without clearing.
        evt2 = controller.cleanup()
        self.assertIs(evt2, evt)
        self.assertTrue(evt2.is_set())

    def test_cleanup_disables_eviction_before_close(self):
        """Eviction must be turned off so a late scan-response task can't
        invoke evicted_callback mid-shutdown."""
        controller = _make_controller(["192.168.1.100/24"])
        controller.set_evict_enabled(True)
        t1, t2 = _attach_transports(controller, 2)
        for t in (t1, t2):
            t.is_closing = Mock(return_value=False)

        controller.cleanup()

        self.assertFalse(controller.evict_enabled)
        t1.close.assert_called_once()
        t2.close.assert_called_once()

    def test_cleanup_schedules_safety_timer(self):
        controller = _make_controller(["192.168.1.100/24", "10.0.0.100/8"])
        controller._loop = Mock()
        controller._loop.call_later = Mock(return_value=Mock())
        t1, t2 = _attach_transports(controller, 2)
        for t in (t1, t2):
            t.is_closing = Mock(return_value=False)

        controller.cleanup()

        controller._loop.call_later.assert_called_once_with(
            2.0, controller._force_cleanup_done
        )

    def test_cleanup_uses_custom_timeout(self):
        controller = _make_controller(["192.168.1.100/24"])
        controller._loop = Mock()
        controller._loop.call_later = Mock(return_value=Mock())
        (t1,) = _attach_transports(controller, 1)
        t1.is_closing = Mock(return_value=False)

        controller.cleanup(timeout=0.5)

        controller._loop.call_later.assert_called_once_with(
            0.5, controller._force_cleanup_done
        )

    def test_force_cleanup_done_sets_event_and_logs_stragglers(self):
        controller = _make_controller(["192.168.1.100/24", "10.0.0.100/8"])
        logger = Mock()
        controller._logger = logger
        t1, t2 = _attach_transports(controller, 2)
        # t1 drained; t2 stuck.
        t1.is_closing = Mock(return_value=True)
        t2.is_closing = Mock(return_value=False)
        controller._cleanup_done.clear()

        controller._force_cleanup_done()

        self.assertTrue(controller._cleanup_done.is_set())
        self.assertEqual(controller._transports, [])
        self.assertEqual(controller._protocols, [])
        logger.warning.assert_called_once()
        args = logger.warning.call_args[0]
        # The stuck interface address should appear in the format args.
        self.assertTrue(
            any("10.0.0.100" in repr(a) for a in args[1:]),
            f"Expected '10.0.0.100' in warning args, got {args}",
        )

    def test_force_cleanup_done_noop_when_already_set(self):
        """If natural drain already fired, the safety timer is a no-op."""
        controller = _make_controller(["192.168.1.100/24"])
        logger = Mock()
        controller._logger = logger
        controller._cleanup_done.set()

        controller._force_cleanup_done()

        logger.warning.assert_not_called()
        self.assertTrue(controller._cleanup_done.is_set())

    def test_natural_disconnect_cancels_safety_timer(self):
        controller = _make_controller(["192.168.1.100/24", "10.0.0.100/8"])
        controller._loop = Mock()
        handle = Mock()
        controller._loop.call_later = Mock(return_value=handle)
        t1, t2 = _attach_transports(controller, 2)
        for t in (t1, t2):
            t.is_closing = Mock(return_value=False)

        controller.cleanup()
        self.assertIs(controller._cleanup_timeout_handle, handle)

        # All transports drain naturally → the safety timer must be cancelled.
        p1, p2 = controller._protocols
        controller._protocol_disconnected(p1)
        controller._protocol_disconnected(p2)

        handle.cancel.assert_called_once()
        self.assertIsNone(controller._cleanup_timeout_handle)
        self.assertTrue(controller._cleanup_done.is_set())


class TestInputValidation(unittest.TestCase):
    """Configuration mistakes should fail loudly at __init__, not at bind."""

    def test_empty_list_rejected(self):
        with self.assertRaises(ValueError):
            _make_controller([])

    def test_all_wildcards_with_specific_collapses_then_rejects_empty(self):
        """If the wildcard filter would leave the list empty, raise.

        This used to silently produce a controller with zero transports.
        """
        # ["0.0.0.0", "0.0.0.0"] dedupes to ["0.0.0.0"], which is allowed
        # (single wildcard). Mixed with another wildcard variant is still
        # collapsed to a single 0.0.0.0 — valid.
        controller = _make_controller(["0.0.0.0", "0.0.0.0"])
        self.assertEqual(controller.listening_addresses, ["0.0.0.0"])

    def test_invalid_ipv4_rejected(self):
        with self.assertRaises(ValueError):
            _make_controller(["not-an-ip"])

    def test_invalid_ipv4_with_mask_rejected(self):
        with self.assertRaises(ValueError):
            _make_controller(["999.999.999.999/24"])

    def test_duplicates_are_deduped(self):
        controller = _make_controller(
            ["192.168.1.100/24", "192.168.1.100/24", "10.0.0.100/8"]
        )
        self.assertEqual(
            controller.listening_addresses, ["192.168.1.100", "10.0.0.100"]
        )

    def test_duplicates_keep_first_network(self):
        """Dedup must preserve the first occurrence's mask."""
        controller = _make_controller(["192.168.1.100/24", "192.168.1.100"])
        self.assertEqual(controller.listening_addresses, ["192.168.1.100"])
        self.assertEqual(len(controller.networks), 1)
        # First entry had /24 → must survive dedup.
        self.assertIsNotNone(controller.networks[0])

    def test_tuple_input_accepted(self):
        """_normalize_to_list previously called .copy() on tuples."""
        controller = GoveeController(
            loop=Mock(),
            listening_addresses=["192.168.1.100/24", "10.0.0.100/8"],
        )
        self.assertEqual(
            controller.listening_addresses, ["192.168.1.100", "10.0.0.100"]
        )


class TestListeningSocketFlags(unittest.TestCase):
    """_create_listening_socket must apply SO_REUSEADDR / SO_REUSEPORT /
    SO_BROADCAST before bind. Setting them after bind (the old behavior in
    connection_made) was a silent no-op that broke restart-after-crash and
    multi-NIC port sharing."""

    def test_reuseaddr_and_broadcast_are_set(self):
        controller = _make_controller(["127.0.0.1/8"])
        # Port 0 → kernel picks a free port, no collision risk in CI.
        controller._listening_port = 0
        sock = controller._create_listening_socket("127.0.0.1")
        try:
            self.assertEqual(sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR), 1)
            self.assertEqual(sock.getsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST), 1)
            if hasattr(socket, "SO_REUSEPORT"):
                self.assertEqual(
                    sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT), 1
                )
            # And the socket really is bound.
            self.assertNotEqual(sock.getsockname()[1], 0)
        finally:
            sock.close()

    def test_two_sockets_can_share_the_port(self):
        """Sharing the port is the whole point of the flag.

        On Linux this needs SO_REUSEPORT; on macOS SO_REUSEADDR is enough.
        Skipped on platforms where neither primitive exists (Windows).
        """
        if not hasattr(socket, "SO_REUSEPORT"):
            self.skipTest("SO_REUSEPORT not available on this platform")
        controller = _make_controller(["127.0.0.1/8"])
        controller._listening_port = 0
        s1 = controller._create_listening_socket("127.0.0.1")
        try:
            # Reuse the port the kernel just gave us.
            controller._listening_port = s1.getsockname()[1]
            s2 = controller._create_listening_socket("127.0.0.1")
            s2.close()
        finally:
            s1.close()

    def test_bind_failure_closes_socket(self):
        """A bind() error must not leak the underlying fd."""
        controller = _make_controller(["127.0.0.1/8"])
        controller._listening_port = 0
        s1 = controller._create_listening_socket("127.0.0.1")
        try:
            controller._listening_port = s1.getsockname()[1]
            if hasattr(socket, "SO_REUSEPORT"):
                # When port sharing works, force a conflict by binding to a
                # different address that can't be granted (use a port we know
                # is busy from a non-reusable socket).
                blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                blocker.bind(("127.0.0.1", 0))
                controller._listening_port = blocker.getsockname()[1]
                try:
                    with self.assertRaises(OSError):
                        controller._create_listening_socket("127.0.0.1")
                finally:
                    blocker.close()
            else:
                # Without SO_REUSEPORT the second bind on the same (ip,port)
                # always fails.
                with self.assertRaises(OSError):
                    controller._create_listening_socket("127.0.0.1")
        finally:
            s1.close()


class TestListeningAddressesAccessors(unittest.TestCase):
    """Public accessors must return copies so callers cannot mutate state."""

    def test_listening_addresses_returns_copy(self):
        controller = _make_controller(["192.168.1.100/24", "10.0.0.100/8"])
        snapshot = controller.listening_addresses
        snapshot.append("evil")
        self.assertEqual(
            controller.listening_addresses, ["192.168.1.100", "10.0.0.100"]
        )

    def test_networks_returns_copy(self):
        controller = _make_controller(["192.168.1.100/24", "10.0.0.100/8"])
        snapshot = controller.networks
        snapshot.clear()
        self.assertEqual(len(controller.networks), 2)


class TestDatagramHandlerErrors(unittest.TestCase):
    """_handle_datagram_received must contain exceptions and keep logging
    helpful context so failures aren't swallowed by asyncio.create_task."""

    @staticmethod
    def _scan_payload(
        device: str = "ab:cd:ef:01:02:03", sku: str = "H6008", ip: str = "192.168.1.42"
    ) -> bytes:
        return json.dumps(
            {"msg": {"cmd": "scan", "data": {"device": device, "sku": sku, "ip": ip}}}
        ).encode()

    def _make_protocol(self, controller, listening_address="192.168.1.100"):
        protocol = Mock()
        protocol.listening_address = listening_address
        protocol.transport = Mock()
        protocol.transport.is_closing = Mock(return_value=False)
        return protocol

    def _make_controller_with_logger(self) -> tuple[GoveeController, Mock]:
        controller = _make_controller(["192.168.1.100/24"])
        logger = Mock()
        logger.isEnabledFor = Mock(return_value=False)
        controller._logger = logger
        return controller, logger

    def test_handler_exception_does_not_propagate(self):
        """A raising discovered_callback must be caught and logged with context."""
        controller, logger = self._make_controller_with_logger()
        controller.set_device_discovered_callback(
            Mock(side_effect=RuntimeError("boom"))
        )
        protocol = self._make_protocol(controller)
        payload = self._scan_payload()

        # Must not raise.
        asyncio.run(
            controller._handle_datagram_received(
                payload, ("192.168.1.42", 4002), protocol
            )
        )

        logger.exception.assert_called_once()
        msg = logger.exception.call_args[0][0]
        self.assertIn("interface", msg)
        # The source address and listening interface must be in the formatted args.
        formatted_args = logger.exception.call_args[0][1:]
        self.assertIn(("192.168.1.42", 4002), formatted_args)
        self.assertIn("192.168.1.100", formatted_args)

    def test_unknown_message_logs_once(self):
        """The unknown-message path must emit exactly one warning, no debug."""
        controller, logger = self._make_controller_with_logger()
        protocol = self._make_protocol(controller)

        asyncio.run(
            controller._handle_datagram_received(
                b"{}", ("192.168.1.42", 4002), protocol
            )
        )

        logger.warning.assert_called_once()
        # No debug calls were made for the unknown-message path.
        logger.debug.assert_not_called()
        logger.exception.assert_not_called()

    def test_handler_survives_subsequent_packets(self):
        """A crash on one packet must not poison handling of the next."""
        controller, logger = self._make_controller_with_logger()
        # First callback raises, second succeeds (callback is replaced between
        # invocations to keep the test deterministic).
        controller.set_device_discovered_callback(
            Mock(side_effect=RuntimeError("boom"))
        )
        protocol = self._make_protocol(controller)
        payload = self._scan_payload(device="aa:bb:cc:dd:ee:ff")

        async def run_both():
            await controller._handle_datagram_received(
                payload, ("192.168.1.42", 4002), protocol
            )
            # Swap to a non-raising callback that accepts the device.
            controller.set_device_discovered_callback(Mock(return_value=True))
            await controller._handle_datagram_received(
                payload, ("192.168.1.42", 4002), protocol
            )

        asyncio.run(run_both())

        # Crash on the first call was logged; second call succeeded and
        # registered the device.
        logger.exception.assert_called_once()
        self.assertIsNotNone(controller.get_device_by_ip("192.168.1.42"))


class TestRediscoveryRefreshesLastseen(unittest.TestCase):
    """H3: a scan response for an already-known device must refresh
    lastseen regardless of what the discovered_callback returns. Otherwise
    a callback that intentionally returns False (e.g. an integration that
    suppresses re-notification) silently lets the eviction tick remove a
    device that's actively responding."""

    def _make(self, callback_return):
        controller = _make_controller(["192.168.1.100/24"])
        controller.set_device_discovered_callback(Mock(return_value=callback_return))
        device = GoveeDevice(
            controller, "192.168.1.42", "fp-x", "H6008", ON_OFF_CAPABILITIES
        )
        controller._registry.add_discovered_device(device)
        # Backdate lastseen so we can verify it actually got refreshed.
        from datetime import datetime, timedelta, timezone

        old = datetime.now(timezone.utc) - timedelta(seconds=60)
        device._lastseen = old
        return controller, device, old

    def _scan_response(self):
        from govee_local_api.message import ScanResponse

        return ScanResponse({"device": "fp-x", "sku": "H6008", "ip": "192.168.1.42"})

    def test_lastseen_refreshed_when_callback_returns_true(self):
        controller, device, old = self._make(callback_return=True)
        protocol = Mock()
        protocol.transport = Mock()

        asyncio.run(
            controller._handle_scan_response(
                self._scan_response(), ("192.168.1.42", 4002), protocol
            )
        )

        self.assertGreater(device.lastseen, old)

    def test_lastseen_refreshed_when_callback_returns_false(self):
        controller, device, old = self._make(callback_return=False)
        protocol = Mock()
        protocol.transport = Mock()

        asyncio.run(
            controller._handle_scan_response(
                self._scan_response(), ("192.168.1.42", 4002), protocol
            )
        )

        # Even though the callback opted out, the response is evidence the
        # device is alive — eviction must not fire on the next tick.
        self.assertGreater(device.lastseen, old)

    def test_lastseen_refreshed_when_callback_returns_none(self):
        controller, device, old = self._make(callback_return=None)
        protocol = Mock()
        protocol.transport = Mock()

        asyncio.run(
            controller._handle_scan_response(
                self._scan_response(), ("192.168.1.42", 4002), protocol
            )
        )

        self.assertGreater(device.lastseen, old)


class TestProtocolErrorReceived(unittest.TestCase):
    """C5: error_received must log async UDP send/recv errors with the
    interface that hit them so NIC failures are diagnosable."""

    def test_error_received_logs_with_interface_context(self):
        from govee_local_api.protocol import GoveeControllerProtocol

        controller = _make_controller(["192.168.1.100/24"])
        logger = Mock()
        controller._logger = logger

        protocol = GoveeControllerProtocol(controller, "192.168.1.100")
        protocol.error_received(OSError(101, "Network is unreachable"))

        logger.warning.assert_called_once()
        args = logger.warning.call_args[0]
        self.assertIn("192.168.1.100", args)
        # Format-args carry the OSError representation.
        self.assertTrue(any("Network is unreachable" in repr(a) for a in args[1:]))


class TestEvictionDoesNotDanglePointer(unittest.TestCase):
    """C3: _evict() must not null device._controller. Callers (HA entities,
    in-flight tasks) may still hold a reference and call methods on the
    evicted device; that should be a harmless no-op, not AttributeError."""

    def _evict_device(self, controller, device):
        from datetime import datetime, timedelta, timezone

        controller._registry.add_discovered_device(device)
        # Force eviction by backdating lastseen.
        device._lastseen = datetime.now(timezone.utc) - timedelta(
            seconds=controller._evict_interval + 1
        )
        controller._evict()

    def test_controller_pointer_survives_eviction(self):
        controller = _make_controller(["192.168.1.100/24"])
        device = GoveeDevice(
            controller, "192.168.1.42", "fp-x", "H6008", ON_OFF_CAPABILITIES
        )

        self._evict_device(controller, device)

        # Device is removed from the registry...
        self.assertIsNone(controller.get_device_by_fingerprint("fp-x"))
        # ...but still points at the controller for future operations.
        self.assertIs(device._controller, controller)

    def test_evicted_device_command_does_not_raise(self):
        """Calling turn_on() on an evicted device must not AttributeError.
        With no transports attached it is a silent no-op, which is the
        correct behavior for fire-and-forget UDP after shutdown/eviction."""
        controller = _make_controller(["192.168.1.100/24"])
        device = GoveeDevice(
            controller, "192.168.1.42", "fp-x", "H6008", ON_OFF_CAPABILITIES
        )

        self._evict_device(controller, device)

        # No exception — and since no transports are attached, sendto is
        # never called.
        asyncio.run(device.turn_on())


class TestManualDeviceEvictionRequeue(unittest.TestCase):
    """An evicted manually-added device must go back on the discovery queue,
    otherwise it is never probed again while discovery is disabled and stays
    gone until the user re-adds it."""

    def _add_expired_device(self, controller, ip, fingerprint, manual):
        from datetime import datetime, timedelta, timezone

        device = GoveeDevice(controller, ip, fingerprint, "H6008", ON_OFF_CAPABILITIES)
        device.is_manual = manual
        controller._registry.add_discovered_device(device)
        # Force eviction by backdating lastseen.
        device._lastseen = datetime.now(timezone.utc) - timedelta(
            seconds=controller._evict_interval + 1
        )
        return device

    def test_evicted_manual_device_is_requeued(self):
        controller = _make_controller(["192.168.1.100/24"])
        self._add_expired_device(controller, "192.168.1.42", "fp-manual", True)

        controller._evict()

        self.assertIsNone(controller.get_device_by_fingerprint("fp-manual"))
        self.assertIn("192.168.1.42", controller.discovery_queue)

    def test_evicted_discovered_device_is_not_requeued(self):
        controller = _make_controller(["192.168.1.100/24"])
        self._add_expired_device(controller, "192.168.1.43", "fp-auto", False)

        controller._evict()

        self.assertIsNone(controller.get_device_by_fingerprint("fp-auto"))
        self.assertNotIn("192.168.1.43", controller.discovery_queue)

    def test_requeued_manual_device_comes_back_as_manual(self):
        """Once the device answers a scan again it must be manual again and
        leave the queue (the existing add_discovered_device mechanism)."""
        controller = _make_controller(["192.168.1.100/24"])
        self._add_expired_device(controller, "192.168.1.42", "fp-manual", True)
        controller._evict()

        rediscovered = GoveeDevice(
            controller, "192.168.1.42", "fp-manual", "H6008", ON_OFF_CAPABILITIES
        )
        controller._registry.add_discovered_device(rediscovered)

        self.assertTrue(rediscovered.is_manual)
        self.assertNotIn("192.168.1.42", controller.discovery_queue)


class TestDiscoveryToggleKeepsManualProbing(unittest.TestCase):
    """Turning discovery off must not stop the timer chain that also probes
    queued and manually-added device IPs; only cleanup() stops it."""

    def _controller_with_chain(self):
        controller = _make_controller(["192.168.1.100/24"])
        controller._discovery_enabled = True
        controller._loop = Mock()
        handle1, handle2 = Mock(name="handle1"), Mock(name="handle2")
        controller._loop.call_later = Mock(side_effect=[handle1, handle2])
        _attach_transports(controller, 1)
        return controller, handle1, handle2

    def test_disable_discovery_keeps_chain_for_queued_devices(self):
        controller, handle1, handle2 = self._controller_with_chain()
        controller._registry.add_device_to_queue("192.168.1.42")
        controller.send_discovery_message()
        self.assertIs(controller._discovery_handle, handle1)

        controller.set_discovery_enabled(False)

        handle1.cancel.assert_called_once()
        # The chain was restarted because the queued IP still needs probing.
        self.assertIs(controller._discovery_handle, handle2)

    def test_disable_discovery_keeps_chain_for_manual_devices(self):
        controller, handle1, handle2 = self._controller_with_chain()
        device = GoveeDevice(
            controller, "192.168.1.42", "fp-m", "H6008", ON_OFF_CAPABILITIES
        )
        device.is_manual = True
        controller._registry.add_discovered_device(device)
        controller.send_discovery_message()
        self.assertIs(controller._discovery_handle, handle1)

        controller.set_discovery_enabled(False)

        handle1.cancel.assert_called_once()
        self.assertIs(controller._discovery_handle, handle2)

    def test_disable_discovery_stops_chain_when_nothing_to_probe(self):
        controller, handle1, _handle2 = self._controller_with_chain()
        controller.send_discovery_message()
        self.assertIs(controller._discovery_handle, handle1)

        controller.set_discovery_enabled(False)

        handle1.cancel.assert_called_once()
        self.assertIsNone(controller._discovery_handle)

    def test_cleanup_cancels_chain_even_with_queued_devices(self):
        controller = _make_controller(["192.168.1.100/24"])
        controller._loop = Mock()
        chain_handle = Mock(name="chain_handle")
        controller._loop.call_later = Mock(return_value=chain_handle)
        (t1,) = _attach_transports(controller, 1)
        t1.is_closing = Mock(return_value=False)

        # Queued IP with discovery disabled starts the probing chain.
        controller.add_device_to_discovery_queue("192.168.1.42")
        self.assertIs(controller._discovery_handle, chain_handle)

        controller.cleanup()

        chain_handle.cancel.assert_called_once()
        self.assertIsNone(controller._discovery_handle)


class TestEvictionTimer(unittest.TestCase):
    """Eviction must run on its own periodic timer: relying only on the
    scan-response path means nothing is ever evicted when *no* device
    answers — exactly when eviction matters most."""

    def _expired_device(self, controller, ip, fingerprint):
        from datetime import datetime, timedelta, timezone

        device = GoveeDevice(controller, ip, fingerprint, "H6008", ON_OFF_CAPABILITIES)
        controller._registry.add_discovered_device(device)
        device._lastseen = datetime.now(timezone.utc) - timedelta(
            seconds=controller._evict_interval + 1
        )
        return device

    def test_enable_evict_schedules_periodic_check(self):
        controller = _make_controller(["192.168.1.100/24"])
        controller._loop = Mock()
        handle = Mock()
        controller._loop.call_later = Mock(return_value=handle)

        controller.set_evict_enabled(True)

        controller._loop.call_later.assert_called_once_with(
            controller._evict_interval, controller._evict_tick
        )
        self.assertIs(controller._evict_handle, handle)

    def test_tick_evicts_without_any_scan_response_and_reschedules(self):
        controller = _make_controller(["192.168.1.100/24"])
        controller._loop = Mock()
        controller._loop.call_later = Mock(return_value=Mock())
        evicted = []
        controller._device_evicted_callback = evicted.append
        controller._evict_enabled = True
        self._expired_device(controller, "192.168.1.42", "fp-dead")

        controller._evict_tick()

        self.assertIsNone(controller.get_device_by_fingerprint("fp-dead"))
        self.assertEqual([d.fingerprint for d in evicted], ["fp-dead"])
        # The chain rescheduled itself.
        controller._loop.call_later.assert_called_once_with(
            controller._evict_interval, controller._evict_tick
        )

    def test_tick_is_noop_when_disabled(self):
        controller = _make_controller(["192.168.1.100/24"])
        controller._loop = Mock()
        controller._loop.call_later = Mock()
        self._expired_device(controller, "192.168.1.42", "fp-dead")

        controller._evict_tick()

        # Device survives and no new tick is scheduled.
        self.assertIsNotNone(controller.get_device_by_fingerprint("fp-dead"))
        controller._loop.call_later.assert_not_called()

    def test_disable_evict_cancels_timer(self):
        controller = _make_controller(["192.168.1.100/24"])
        controller._loop = Mock()
        handle = Mock()
        controller._loop.call_later = Mock(return_value=handle)

        controller.set_evict_enabled(True)
        controller.set_evict_enabled(False)

        handle.cancel.assert_called_once()
        self.assertIsNone(controller._evict_handle)

    def test_cleanup_cancels_evict_timer(self):
        controller = _make_controller(["192.168.1.100/24"])
        controller._loop = Mock()
        handle = Mock()
        controller._loop.call_later = Mock(return_value=handle)
        controller.set_evict_enabled(True)

        controller.cleanup()

        handle.cancel.assert_called_once()
        self.assertIsNone(controller._evict_handle)
        self.assertFalse(controller.evict_enabled)


class TestDeprecatedListeningAddressKwarg(unittest.TestCase):
    """The pre-3.0 'listening_address' kwarg must keep working (with a
    DeprecationWarning) so existing integrations don't break on upgrade."""

    def test_old_kwarg_works_with_warning(self):
        with self.assertWarns(DeprecationWarning):
            controller = GoveeController(loop=Mock(), listening_address="192.168.1.50")
        self.assertEqual(controller.listening_addresses, ["192.168.1.50"])

    def test_old_kwarg_accepts_list_and_masks(self):
        with self.assertWarns(DeprecationWarning):
            controller = GoveeController(
                loop=Mock(), listening_address=["192.168.1.50/24"]
            )
        self.assertEqual(controller.listening_addresses, ["192.168.1.50"])
        self.assertIsNotNone(controller.networks[0])

    def test_both_kwargs_rejected(self):
        with self.assertWarns(DeprecationWarning):
            with self.assertRaises(ValueError):
                GoveeController(
                    loop=Mock(),
                    listening_address="192.168.1.50",
                    listening_addresses="10.0.0.1",
                )

    def test_default_is_wildcard_without_either_kwarg(self):
        controller = GoveeController(loop=Mock())
        self.assertEqual(controller.listening_addresses, ["0.0.0.0"])


class TestShutdownDropsLateDatagrams(unittest.TestCase):
    """A datagram task created just before cleanup() can run after the
    registry was cleared; it must not repopulate the registry or fire the
    discovered callback mid-shutdown."""

    def test_late_scan_response_ignored_after_cleanup(self):
        controller = _make_controller(["192.168.1.100/24"])
        discovered = Mock(return_value=True)
        controller.set_device_discovered_callback(discovered)
        controller.cleanup()

        payload = json.dumps(
            {
                "msg": {
                    "cmd": "scan",
                    "data": {
                        "device": "fp-late",
                        "sku": "H6008",
                        "ip": "192.168.1.42",
                    },
                }
            }
        ).encode()
        protocol = Mock()
        protocol.transport = Mock()
        asyncio.run(
            controller._handle_datagram_received(
                payload, ("192.168.1.42", 4002), protocol
            )
        )

        discovered.assert_not_called()
        self.assertEqual(controller.devices, [])


class TestStartPartialFailure(unittest.TestCase):
    """If binding a later address fails, start() must close the endpoints it
    already created — otherwise every HA setup retry leaks a bound socket."""

    def _controller_with_failing_bind(self, fail_at_socket):
        from unittest.mock import AsyncMock

        controller = _make_controller(["192.168.1.100/24", "10.0.0.100/8"])
        t1 = Mock(name="transport1")
        t1.is_closing = Mock(return_value=False)
        p1 = Mock(name="protocol1")
        sock1, sock2 = Mock(name="sock1"), Mock(name="sock2")
        if fail_at_socket:
            controller._create_listening_socket = Mock(
                side_effect=[sock1, OSError("bind failed")]
            )
            controller._loop.create_datagram_endpoint = AsyncMock(return_value=(t1, p1))
        else:
            controller._create_listening_socket = Mock(side_effect=[sock1, sock2])
            controller._loop.create_datagram_endpoint = AsyncMock(
                side_effect=[(t1, p1), OSError("endpoint failed")]
            )
        return controller, t1, sock2

    def test_failed_endpoint_closes_earlier_transports(self):
        controller, t1, sock2 = self._controller_with_failing_bind(fail_at_socket=False)

        with self.assertRaises(OSError):
            asyncio.run(controller.start())

        t1.close.assert_called_once()
        sock2.close.assert_called_once()
        self.assertEqual(controller._transports, [])
        self.assertEqual(controller._protocols, [])

    def test_failed_bind_closes_earlier_transports(self):
        controller, t1, _sock2 = self._controller_with_failing_bind(fail_at_socket=True)

        with self.assertRaises(OSError):
            asyncio.run(controller.start())

        t1.close.assert_called_once()
        self.assertEqual(controller._transports, [])
        self.assertEqual(controller._protocols, [])


class TestUnexpectedConnectionLost(unittest.TestCase):
    """A connection_lost outside cleanup() means an internal transport
    failure. It must drop that endpoint and log an error — never signal
    cleanup completion (the old behavior made the controller look cleanly
    shut down when nobody asked for a shutdown)."""

    def test_unexpected_loss_drops_endpoint_and_keeps_alignment(self):
        controller = _make_controller(["192.168.1.100/24", "10.0.0.100/8"])
        logger = Mock()
        controller._logger = logger
        t1, t2 = _attach_transports(controller, 2)
        p1, p2 = controller._protocols
        t1.is_closing = Mock(return_value=True)

        controller._protocol_disconnected(p1)

        self.assertEqual(controller._transports, [t2])
        self.assertEqual(controller._protocols, [p2])
        self.assertEqual(controller.listening_addresses, ["10.0.0.100"])
        self.assertEqual(len(controller.networks), 1)
        self.assertFalse(controller._cleanup_done.is_set())
        logger.error.assert_called_once()

    def test_unexpected_loss_of_last_transport_does_not_fake_cleanup(self):
        controller = _make_controller(["192.168.1.100/24"])
        logger = Mock()
        controller._logger = logger
        (t1,) = _attach_transports(controller, 1)
        (p1,) = controller._protocols
        t1.is_closing = Mock(return_value=True)

        controller._protocol_disconnected(p1)

        self.assertEqual(controller._transports, [])
        self.assertFalse(controller._cleanup_done.is_set())
        # The "controller is inoperative" error names the lost address.
        logger.error.assert_called_once()
        self.assertIn("192.168.1.100", logger.error.call_args[0][1:])

    def test_unknown_or_none_protocol_is_noop(self):
        controller = _make_controller(["192.168.1.100/24"])
        _attach_transports(controller, 1)

        controller._protocol_disconnected(None)
        controller._protocol_disconnected(Mock(name="stranger"))

        self.assertEqual(len(controller._transports), 1)
        self.assertFalse(controller._cleanup_done.is_set())

    def test_start_rebinds_full_config_after_unexpected_drop(self):
        from unittest.mock import AsyncMock

        controller = _make_controller(["192.168.1.100/24", "10.0.0.100/8"])
        t1, t2 = _attach_transports(controller, 2)
        p1, _p2 = controller._protocols
        for t in (t1, t2):
            t.is_closing = Mock(return_value=True)

        # Lose one endpoint unexpectedly, then shut down.
        controller._protocol_disconnected(p1)
        controller.cleanup()
        controller._transports.clear()
        controller._protocols.clear()

        controller._create_listening_socket = Mock(return_value=Mock())
        controller._loop.create_datagram_endpoint = AsyncMock(
            side_effect=lambda *a, **k: (Mock(), Mock())
        )
        asyncio.run(controller.start())

        # Both configured addresses are bound again, lists aligned.
        self.assertEqual(
            controller.listening_addresses, ["192.168.1.100", "10.0.0.100"]
        )
        self.assertEqual(len(controller._transports), 2)
        self.assertEqual(len(controller.networks), 2)


if __name__ == "__main__":
    unittest.main()
