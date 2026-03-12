import ipaddress
import unittest
from unittest.mock import Mock
from govee_local_api.controller import GoveeController


class TestNetworkMaskFunctionality(unittest.TestCase):
    """Test the network mask functionality via listening_addresses with CIDR/netmask notation."""

    def test_address_with_cidr_mask(self):
        """Test initialization with CIDR notation in listening_addresses."""
        controller = GoveeController(listening_addresses="192.168.1.100/24")
        self.assertEqual(controller.listening_addresses, ["192.168.1.100"])
        self.assertEqual(
            controller.networks,
            [ipaddress.ip_network("192.168.1.0/24", strict=False)],
        )

    def test_address_with_netmask(self):
        """Test initialization with dotted netmask notation."""
        controller = GoveeController(listening_addresses="192.168.1.100/255.255.255.0")
        self.assertEqual(controller.listening_addresses, ["192.168.1.100"])
        self.assertEqual(
            controller.networks,
            [ipaddress.ip_network("192.168.1.0/24", strict=False)],
        )

    def test_address_without_mask(self):
        """Test initialization without a mask (heuristic fallback)."""
        controller = GoveeController(listening_addresses="192.168.1.100")
        self.assertEqual(controller.listening_addresses, ["192.168.1.100"])
        self.assertEqual(controller.networks, [None])

    def test_wildcard_address(self):
        """Test that 0.0.0.0 has no network even with a mask."""
        controller = GoveeController(listening_addresses="0.0.0.0/24")
        self.assertEqual(controller.listening_addresses, ["0.0.0.0"])
        self.assertEqual(controller.networks, [None])

    def test_multiple_addresses_mixed(self):
        """Test multiple addresses with mixed mask formats."""
        addresses = ["192.168.1.100/24", "10.0.0.100/8", "172.16.1.100"]
        controller = GoveeController(listening_addresses=addresses)
        self.assertEqual(
            controller.listening_addresses,
            ["192.168.1.100", "10.0.0.100", "172.16.1.100"],
        )
        self.assertEqual(
            controller.networks,
            [
                ipaddress.ip_network("192.168.1.0/24", strict=False),
                ipaddress.ip_network("10.0.0.0/8", strict=False),
                None,
            ],
        )

    def test_precise_subnet_matching_cidr(self):
        """Test precise subnet matching using CIDR notation."""
        controller = GoveeController(
            listening_addresses=["192.168.1.100/24", "10.0.0.100/8"],
        )

        transport1 = Mock()
        transport2 = Mock()
        controller._transports = [transport1, transport2]

        selected = controller._get_best_transport_for_ip("192.168.1.200")
        self.assertEqual(selected, transport1)

        selected = controller._get_best_transport_for_ip("10.50.100.200")
        self.assertEqual(selected, transport2)

        # Non-matching IP falls back to first specific address
        selected = controller._get_best_transport_for_ip("172.16.1.100")
        self.assertEqual(selected, transport1)

    def test_precise_subnet_matching_netmask(self):
        """Test precise subnet matching using netmask notation."""
        controller = GoveeController(
            listening_addresses=[
                "192.168.1.100/255.255.255.0",
                "192.168.2.100/255.255.254.0",
            ],
        )

        transport1 = Mock()
        transport2 = Mock()
        controller._transports = [transport1, transport2]

        selected = controller._get_best_transport_for_ip("192.168.1.200")
        self.assertEqual(selected, transport1)

        selected = controller._get_best_transport_for_ip("192.168.2.200")
        self.assertEqual(selected, transport2)

        # /23 includes 192.168.3.x
        selected = controller._get_best_transport_for_ip("192.168.3.100")
        self.assertEqual(selected, transport2)

    def test_mixed_notation_support(self):
        """Test support for mixed CIDR and netmask notation."""
        controller = GoveeController(
            listening_addresses=[
                "192.168.1.100/24",
                "10.0.0.100/255.0.0.0",
                "172.16.1.100/20",
            ],
        )

        t1, t2, t3 = Mock(), Mock(), Mock()
        controller._transports = [t1, t2, t3]

        selected = controller._get_best_transport_for_ip("192.168.1.200")
        self.assertEqual(selected, t1)

        selected = controller._get_best_transport_for_ip("10.50.100.200")
        self.assertEqual(selected, t2)

        selected = controller._get_best_transport_for_ip("172.16.5.100")
        self.assertEqual(selected, t3)

    def test_wildcard_address_handling_with_masks(self):
        """Test that wildcard addresses are skipped in network matching."""
        controller = GoveeController(
            listening_addresses=["0.0.0.0/24", "192.168.1.100/24"],
        )

        transport1 = Mock()
        transport2 = Mock()
        controller._transports = [transport1, transport2]

        selected = controller._get_best_transport_for_ip("192.168.1.200")
        self.assertEqual(selected, transport2)

        # Non-matching IP prefers specific address over wildcard
        selected = controller._get_best_transport_for_ip("10.0.0.100")
        self.assertEqual(selected, transport2)

    def test_fallback_to_heuristic_without_masks(self):
        """Test fallback to heuristic matching when no masks provided."""
        controller = GoveeController(
            listening_addresses=["192.168.1.100", "10.0.0.100"],
        )

        transport1 = Mock()
        transport2 = Mock()
        controller._transports = [transport1, transport2]

        selected = controller._get_best_transport_for_ip("192.168.1.200")
        self.assertEqual(selected, transport1)

        selected = controller._get_best_transport_for_ip("10.50.100.200")
        self.assertEqual(selected, transport2)

    def test_subnet_edge_cases(self):
        """Test subnet matching edge cases with small subnets."""
        controller = GoveeController(
            listening_addresses=["192.168.1.100/30"],
        )

        transport1 = Mock()
        controller._transports = [transport1]

        # /30 network includes .100, .101, .102, .103
        selected = controller._get_best_transport_for_ip("192.168.1.101")
        self.assertEqual(selected, transport1)

        selected = controller._get_best_transport_for_ip("192.168.1.103")
        self.assertEqual(selected, transport1)

    def test_large_subnet_matching(self):
        """Test matching in large subnets."""
        controller = GoveeController(
            listening_addresses=["10.0.0.100/8"],
        )

        transport1 = Mock()
        controller._transports = [transport1]

        test_ips = ["10.0.0.1", "10.255.255.255", "10.123.45.67"]
        for ip in test_ips:
            selected = controller._get_best_transport_for_ip(ip)
            self.assertEqual(selected, transport1)

    def test_ipv6_handling(self):
        """Test that IPv6 addresses are handled gracefully."""
        controller = GoveeController(listening_addresses=["192.168.1.100/24"])

        transport1 = Mock()
        controller._transports = [transport1]

        selected = controller._get_best_transport_for_ip("2001:db8::1")
        self.assertEqual(selected, transport1)


if __name__ == "__main__":
    unittest.main()
