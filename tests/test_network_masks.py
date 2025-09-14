import unittest
from unittest.mock import Mock, patch
from govee_local_api.controller import GoveeController


class TestNetworkMaskFunctionality(unittest.TestCase):
    """Test the network mask functionality for precise subnet matching."""

    def test_network_mask_initialization_single(self):
        """Test initialization with single address and mask."""
        controller = GoveeController(
            listening_addresses="192.168.1.100", network_masks="255.255.255.0"
        )
        self.assertEqual(controller.listening_addresses, ["192.168.1.100"])
        self.assertEqual(controller.network_masks, ["255.255.255.0"])

    def test_network_mask_initialization_multiple(self):
        """Test initialization with multiple addresses and masks."""
        addresses = ["192.168.1.100", "10.0.0.100", "172.16.1.100"]
        masks = ["255.255.255.0", "/8", "/16"]

        controller = GoveeController(listening_addresses=addresses, network_masks=masks)
        self.assertEqual(controller.listening_addresses, addresses)
        self.assertEqual(controller.network_masks, masks)

    def test_network_mask_count_mismatch(self):
        """Test error when mask count doesn't match address count."""
        with self.assertRaises(ValueError) as context:
            GoveeController(
                listening_addresses=["192.168.1.100", "10.0.0.100"],
                network_masks=["255.255.255.0"],  # Only 1 mask for 2 addresses
            )

        self.assertIn("must match", str(context.exception))

    def test_network_mask_none_handling(self):
        """Test that None network_masks works correctly."""
        controller = GoveeController(
            listening_addresses=["192.168.1.100", "10.0.0.100"], network_masks=None
        )
        self.assertEqual(controller.network_masks, None)

    def test_precise_subnet_matching_cidr(self):
        """Test precise subnet matching using CIDR notation."""
        controller = GoveeController(
            listening_addresses=["192.168.1.100", "10.0.0.100"],
            network_masks=["/24", "/8"],
        )

        # Mock transports
        transport1 = Mock()
        transport2 = Mock()
        controller._transports = [transport1, transport2]

        # Test /24 network matching
        selected = controller._get_best_transport_for_ip("192.168.1.200")
        self.assertEqual(selected, transport1)

        # Test /8 network matching
        selected = controller._get_best_transport_for_ip("10.50.100.200")
        self.assertEqual(selected, transport2)

        # Test non-matching IP (should fallback)
        selected = controller._get_best_transport_for_ip("172.16.1.100")
        self.assertEqual(selected, transport1)  # Fallback to first

    def test_precise_subnet_matching_netmask(self):
        """Test precise subnet matching using netmask notation."""
        controller = GoveeController(
            listening_addresses=["192.168.1.100", "192.168.2.100"],
            network_masks=["255.255.255.0", "255.255.254.0"],  # /24 and /23
        )

        # Mock transports
        transport1 = Mock()
        transport2 = Mock()
        controller._transports = [transport1, transport2]

        # Test /24 network (192.168.1.0/24)
        selected = controller._get_best_transport_for_ip("192.168.1.200")
        self.assertEqual(selected, transport1)

        # Test /23 network (192.168.2.0/23 includes 192.168.2.x and 192.168.3.x)
        selected = controller._get_best_transport_for_ip("192.168.2.200")
        self.assertEqual(selected, transport2)

        selected = controller._get_best_transport_for_ip("192.168.3.100")
        self.assertEqual(selected, transport2)  # Should match /23 network

    def test_mixed_notation_support(self):
        """Test support for mixed CIDR and netmask notation."""
        controller = GoveeController(
            listening_addresses=["192.168.1.100", "10.0.0.100", "172.16.1.100"],
            network_masks=["/24", "255.0.0.0", "/20"],
        )

        # Mock transports
        t1, t2, t3 = Mock(), Mock(), Mock()
        controller._transports = [t1, t2, t3]

        # Test CIDR /24
        selected = controller._get_best_transport_for_ip("192.168.1.200")
        self.assertEqual(selected, t1)

        # Test netmask 255.0.0.0 (/8)
        selected = controller._get_best_transport_for_ip("10.50.100.200")
        self.assertEqual(selected, t2)

        # Test CIDR /20
        selected = controller._get_best_transport_for_ip("172.16.5.100")
        self.assertEqual(selected, t3)

    def test_invalid_mask_handling(self):
        """Test graceful handling of invalid network masks."""
        controller = GoveeController(
            listening_addresses=["192.168.1.100", "10.0.0.100"],
            network_masks=["255.255.255.0", "invalid.mask"],
        )

        # Mock transports
        transport1 = Mock()
        transport2 = Mock()
        controller._transports = [transport1, transport2]

        # Should handle invalid mask gracefully and fall back
        with patch.object(controller._logger, "warning") as mock_warning:
            selected = controller._get_best_transport_for_ip("10.0.0.200")
            mock_warning.assert_called()  # Should log warning about invalid mask
            self.assertEqual(selected, transport1)  # Should fallback to first transport

    def test_wildcard_address_handling_with_masks(self):
        """Test that wildcard addresses are skipped in network matching."""
        controller = GoveeController(
            listening_addresses=["0.0.0.0", "192.168.1.100"],
            network_masks=["/24", "/24"],  # Masks for both addresses
        )

        # Mock transports
        transport1 = Mock()  # For 0.0.0.0
        transport2 = Mock()  # For 192.168.1.100
        controller._transports = [transport1, transport2]

        # Should skip wildcard and use specific address
        selected = controller._get_best_transport_for_ip("192.168.1.200")
        self.assertEqual(selected, transport2)

        # For non-matching IP, should prefer specific address over wildcard
        selected = controller._get_best_transport_for_ip("10.0.0.100")
        self.assertEqual(selected, transport2)

    def test_fallback_to_heuristic_without_masks(self):
        """Test fallback to heuristic matching when no masks provided."""
        controller = GoveeController(
            listening_addresses=["192.168.1.100", "10.0.0.100"], network_masks=None
        )

        # Mock transports
        transport1 = Mock()
        transport2 = Mock()
        controller._transports = [transport1, transport2]

        # Should use heuristic matching
        selected = controller._get_best_transport_for_ip("192.168.1.200")
        self.assertEqual(selected, transport1)  # Heuristic should match

        selected = controller._get_best_transport_for_ip("10.50.100.200")
        self.assertEqual(selected, transport2)  # Heuristic should match

    def test_subnet_edge_cases(self):
        """Test subnet matching edge cases."""
        controller = GoveeController(
            listening_addresses=["192.168.1.100"],
            network_masks=["/30"],  # Very small subnet: 192.168.1.100/30
        )

        # Mock transport
        transport1 = Mock()
        controller._transports = [transport1]

        # /30 network includes .100, .101, .102, .103
        selected = controller._get_best_transport_for_ip("192.168.1.101")
        self.assertEqual(selected, transport1)

        selected = controller._get_best_transport_for_ip("192.168.1.103")
        self.assertEqual(selected, transport1)

        # .104 should NOT match /30 network
        selected = controller._get_best_transport_for_ip("192.168.1.104")
        self.assertEqual(selected, transport1)  # Still returns transport (fallback)

    def test_large_subnet_matching(self):
        """Test matching in large subnets."""
        controller = GoveeController(
            listening_addresses=["10.0.0.100"],
            network_masks=["/8"],  # Entire 10.x.x.x range
        )

        # Mock transport
        transport1 = Mock()
        controller._transports = [transport1]

        # All 10.x.x.x addresses should match
        test_ips = ["10.0.0.1", "10.255.255.255", "10.123.45.67"]
        for ip in test_ips:
            selected = controller._get_best_transport_for_ip(ip)
            self.assertEqual(selected, transport1)

    def test_ipv6_handling(self):
        """Test that IPv6 addresses are handled gracefully."""
        controller = GoveeController(
            listening_addresses=["192.168.1.100"], network_masks=["/24"]
        )

        # Mock transport
        transport1 = Mock()
        controller._transports = [transport1]

        # IPv6 should fall back to first transport
        selected = controller._get_best_transport_for_ip("2001:db8::1")
        self.assertEqual(selected, transport1)


if __name__ == "__main__":
    unittest.main()
