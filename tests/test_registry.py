import unittest
from unittest.mock import Mock
from govee_local_api.device_registry import DeviceRegistry
from govee_local_api.device import GoveeDevice
from govee_local_api.controller import GoveeController


class TestDeviceRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = DeviceRegistry()
        self._mock_controller = Mock(spec=GoveeController)
        self.device = GoveeDevice(
            self._mock_controller, "192.168.1.1", "device1", "sku1", None
        )

    def test_add_discovered_device(self):
        self.registry.add_discovered_device(self.device)
        assert self.device.fingerprint in self.registry.discovered_devices

    def test_remove_discovered_device(self):
        self.registry.add_discovered_device(self.device)
        self.registry.remove_discovered_device(self.device)
        assert self.device.fingerprint not in self.registry.discovered_devices

    def test_add_custom_device(self):
        self.registry.add_device_to_queue("192.168.1.2")
        assert "192.168.1.2" in self.registry.devices_queue

    def test_discovery_custom_device(self):
        self.registry.add_device_to_queue("192.168.1.2")
        GoveeDevice(self._mock_controller, "192.168.1.2", "device2", "sku2", None)
        assert "192.168.1.2" in self.registry.devices_queue

    def test_cleanup(self):
        self.registry.add_discovered_device(self.device)
        self.registry.add_device_to_queue("192.168.1.2")
        self.registry.cleanup()
        assert len(self.registry.discovered_devices) == 0
        assert len(self.registry.devices_queue) == 0

    def test_get_device_by_ip(self):
        self.registry.add_discovered_device(self.device)
        device = self.registry.get_device_by_ip("192.168.1.1")
        assert device == self.device

    def test_get_device_by_sku(self):
        self.registry.add_discovered_device(self.device)
        device = self.registry.get_device_by_sku("sku1")
        assert device == self.device

    def test_get_device_by_fingerprint(self):
        self.registry.add_discovered_device(self.device)
        device = self.registry.get_device_by_fingerprint("device1")
        assert device == self.device
