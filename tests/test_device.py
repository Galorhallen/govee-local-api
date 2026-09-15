import asyncio
import unittest
from unittest.mock import AsyncMock, Mock
from govee_local_api.device import GoveeDevice
from govee_local_api.controller import GoveeController
from govee_local_api.protocol import GoveeControllerProtocol
from govee_local_api.light_capabilities import (
    BASIC_CAPABILITIES,
    DEFAULT_TEMPERATURE_RANGE,
    create_with_capabilities,
)
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

    def _backdate_lastseen(self, seconds):
        from datetime import datetime, timedelta, timezone

        self.device._lastseen = datetime.now(timezone.utc) - timedelta(seconds=seconds)

    def test_is_connected_uses_controller_evict_interval(self):
        self._mock_controller.evict_interval = 60
        self._backdate_lastseen(45)
        assert self.device.is_connected

        self._mock_controller.evict_interval = 30
        assert not self.device.is_connected

    def test_is_connected_fresh_device(self):
        self._mock_controller.evict_interval = 30
        assert self.device.is_connected

    def test_set_rgb_color_clears_temperature_color(self):
        self._mock_controller.set_color = AsyncMock()

        asyncio.run(self.device.set_temperature(4000))
        assert self.device.temperature_color == 4000

        asyncio.run(self.device.set_rgb_color(255, 0, 0))

        assert self.device.temperature_color == 0
        assert self.device.rgb_color == (255, 0, 0)

        self._mock_controller.set_color.assert_called_with(
            self.device, rgb=(255, 0, 0), temperature=None
        )

    def test_set_temperature_does_not_clear_rgb_color(self):
        self._mock_controller.set_color = AsyncMock()

        asyncio.run(self.device.set_rgb_color(0, 255, 0))
        assert self.device.rgb_color == (0, 255, 0)

        asyncio.run(self.device.set_temperature(3000))

        assert self.device.temperature_color == 3000
        assert self.device.rgb_color == (0, 255, 0)


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
            self.controller._handle_scan_response(
                scan_response, ("192.168.1.100", 4002), self.mock_protocol
            )
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
            self.controller._handle_scan_response(
                scan_response, ("192.168.1.100", 4002), self.mock_protocol
            )
        )

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
        asyncio.run(
            self.controller._handle_scan_response(
                scan_response, ("192.168.1.100", 4002), self.mock_protocol
            )
        )

        # IP should remain unchanged when message has no IP
        assert self.device.ip == original_ip


class TestDeviceTemperatureRange(unittest.TestCase):
    def _device(self, capabilities):
        return GoveeDevice(
            Mock(spec=GoveeController),
            "192.168.1.100",
            "AA:BB:CC:DD:EE:FF",
            "H6001",
            capabilities,
        )

    def test_custom_range_is_exposed_on_the_device(self):
        device = self._device(
            create_with_capabilities(
                True, True, True, 0, False, temperature_range=(2700, 6500)
            )
        )

        assert device.temperature_range == (2700, 6500)

    def test_default_range_is_exposed_on_the_device(self):
        device = self._device(BASIC_CAPABILITIES)

        assert device.temperature_range == DEFAULT_TEMPERATURE_RANGE

    def test_device_without_capabilities_falls_back_to_the_default_range(self):
        device = self._device(None)

        assert device.temperature_range == DEFAULT_TEMPERATURE_RANGE


class TestControllerTemperatureRange(unittest.TestCase):
    def setUp(self):
        self.controller = GoveeController.__new__(GoveeController)
        self.controller._send_message = Mock()

    def _sent_temperature(self, device, temperature):
        asyncio.run(
            self.controller.set_color(device, rgb=None, temperature=temperature)
        )
        message = self.controller._send_message.call_args[0][0]
        return message.as_dict()["msg"]["data"]["colorTemInKelvin"]

    def test_set_color_clamps_to_the_device_temperature_range(self):
        capabilities = create_with_capabilities(
            True, True, True, 0, False, temperature_range=(2700, 6500)
        )
        device = GoveeDevice(
            self.controller, "192.168.1.100", "AA:BB:CC:DD:EE:FF", "H6001", capabilities
        )

        assert self._sent_temperature(device, 9000) == 6500
        assert self._sent_temperature(device, 2000) == 2700
        assert self._sent_temperature(device, 4000) == 4000

    def test_set_color_clamps_to_the_default_range(self):
        device = GoveeDevice(
            self.controller,
            "192.168.1.100",
            "AA:BB:CC:DD:EE:FF",
            "H6001",
            BASIC_CAPABILITIES,
        )

        assert self._sent_temperature(device, 99999) == 9000
        assert self._sent_temperature(device, 1) == 2000
