import asyncio
import unittest
from unittest.mock import Mock
from govee_local_api.device import GoveeDevice
from govee_local_api.controller import GoveeController
from govee_local_api.light_capabilities import (
    GoveeLightCapabilities,
    COMMON_FEATURES,
    TemperatureRange,
    create_with_capabilities,
)
from govee_local_api.protocol import GoveeControllerProtocol
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
        self.mock_protocol = Mock(spec=GoveeControllerProtocol)
        self.mock_protocol.transport = Mock()

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

        asyncio.run(
            self.controller._handle_scan_response(scan_response, self.mock_protocol)
        )

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

        asyncio.run(
            self.controller._handle_scan_response(scan_response, self.mock_protocol)
        )

        assert self.device.ip == "192.168.1.100"
        # Logger should not have logged an IP change
        for call in self.controller._logger.debug.call_args_list:
            assert "IP changed" not in str(call)


class TestGoveeLightCapabilities(unittest.TestCase):
    def test_default_temperature_range(self):
        caps = GoveeLightCapabilities(COMMON_FEATURES)
        assert caps.temperature_range == TemperatureRange(2000, 9000)

    def test_custom_temperature_range(self):
        caps = GoveeLightCapabilities(
            COMMON_FEATURES, temperature_range=TemperatureRange(3000, 6500)
        )
        assert caps.temperature_range == TemperatureRange(3000, 6500)

    def test_create_with_capabilities_custom_range(self):
        caps = create_with_capabilities(
            True,
            True,
            True,
            0,
            False,
            temperature_range=TemperatureRange(2700, 6500),
        )
        assert caps.temperature_range == TemperatureRange(2700, 6500)

    def test_create_with_capabilities_default_range(self):
        caps = create_with_capabilities(True, True, True, 0, False)
        assert caps.temperature_range == TemperatureRange(2000, 9000)

    def test_repr_default_range_excluded(self):
        caps = GoveeLightCapabilities(COMMON_FEATURES)
        assert "temperature_range" not in repr(caps)

    def test_repr_custom_range_included(self):
        caps = GoveeLightCapabilities(
            COMMON_FEATURES, temperature_range=TemperatureRange(3000, 6500)
        )
        assert "temperature_range=3000-6500K" in repr(caps)
        assert "temperature_range=3000-6500K" in str(caps)

    def test_device_delegates_temperature_range(self):
        caps = create_with_capabilities(
            True,
            True,
            True,
            0,
            False,
            temperature_range=TemperatureRange(2700, 6500),
        )
        mock_controller = Mock(spec=GoveeController)
        device = GoveeDevice(mock_controller, "192.168.1.1", "AA:BB:CC", "H6001", caps)
        assert device.temperature_range == TemperatureRange(2700, 6500)


class TestControllerIpUpdateMissingIp(unittest.TestCase):
    def setUp(self):
        self.controller = GoveeController.__new__(GoveeController)
        self.controller._registry = Mock()
        self.controller._device_discovered_callback = None
        self.controller._evict_enabled = False
        self.controller._logger = Mock()
        self.device = GoveeDevice(
            self.controller, "192.168.1.100", "AA:BB:CC:DD:EE:FF", "H6001", None
        )
        self.mock_protocol = Mock(spec=GoveeControllerProtocol)
        self.mock_protocol.transport = Mock()

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
        asyncio.run(
            self.controller._handle_scan_response(scan_response, self.mock_protocol)
        )

        # IP should remain unchanged when message has no IP
        assert self.device.ip == original_ip
