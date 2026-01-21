import asyncio
import unittest
from unittest.mock import Mock
from govee_local_api.device import GoveeDevice
from govee_local_api.controller import GoveeController
from govee_local_api.message import ScanResponse


class TestGoveeDevice(unittest.TestCase):
    def setUp(self):
        self._mock_controller = Mock(spec=GoveeController)
        self.device = GoveeDevice(
            self._mock_controller, "192.168.1.100", "AA:BB:CC:DD:EE:FF", "H6001", None
        )

    def test_initial_ip(self):
        assert self.device.ip == "192.168.1.100"

    def test_update_ip(self):
        self.device.update_ip("192.168.1.200")
        assert self.device.ip == "192.168.1.200"

    def test_update_ip_multiple_times(self):
        self.device.update_ip("192.168.1.200")
        assert self.device.ip == "192.168.1.200"
        self.device.update_ip("10.0.0.50")
        assert self.device.ip == "10.0.0.50"


class TestControllerIpUpdate(unittest.TestCase):
    def setUp(self):
        self.controller = GoveeController.__new__(GoveeController)
        self.controller._registry = Mock()
        self.controller._device_discovered_callback = None
        self.controller._evict_enabled = False
        self.controller._logger = Mock()
        self.device = GoveeDevice(
            self.controller, "192.168.1.100", "AA:BB:CC:DD:EE:FF", "H6001", None
        )

    def test_scan_response_updates_ip_when_changed(self):
        self.controller._registry.get_device_by_fingerprint = Mock(
            return_value=self.device
        )

        scan_data = {
            "device": "AA:BB:CC:DD:EE:FF",
            "sku": "H6001",
            "ip": "192.168.1.200",
        }
        scan_response = ScanResponse(scan_data)

        asyncio.run(self.controller._handle_scan_response(scan_response))

        assert self.device.ip == "192.168.1.200"

    def test_scan_response_does_not_update_ip_when_same(self):
        self.controller._registry.get_device_by_fingerprint = Mock(
            return_value=self.device
        )

        scan_data = {
            "device": "AA:BB:CC:DD:EE:FF",
            "sku": "H6001",
            "ip": "192.168.1.100",
        }
        scan_response = ScanResponse(scan_data)

        asyncio.run(self.controller._handle_scan_response(scan_response))

        assert self.device.ip == "192.168.1.100"
        # Logger should not have logged an IP change
        for call in self.controller._logger.debug.call_args_list:
            assert "IP changed" not in str(call)

    def test_scan_response_handles_missing_ip(self):
        self.controller._registry.get_device_by_fingerprint = Mock(
            return_value=self.device
        )

        scan_data = {
            "device": "AA:BB:CC:DD:EE:FF",
            "sku": "H6001",
        }
        scan_response = ScanResponse(scan_data)

        original_ip = self.device.ip
        asyncio.run(self.controller._handle_scan_response(scan_response))

        # IP should remain unchanged when message has no IP
        assert self.device.ip == original_ip
