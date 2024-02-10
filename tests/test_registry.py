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
        self.assertIn(self.device.fingerprint, self.registry.discovered_devices)

    def test_remove_discovered_device(self):
        self.registry.add_discovered_device(self.device)
        self.registry.remove_discovered_device(self.device)
        self.assertNotIn(self.device.fingerprint, self.registry.discovered_devices)

    def test_add_custom_device(self):
        self.registry.add_custom_device("192.168.1.2")
        self.assertIn("192.168.1.2", self.registry.custom_devices_queue)

    def test_discovery_custom_device(self):
        self.registry.add_custom_device("192.168.1.2")
        GoveeDevice(self._mock_controller, "192.168.1.2", "device2", "sku2", None)

        self.assertIn("192.168.1.2", self.registry.custom_devices_queue)

    def test_cleanup(self):
        self.registry.add_discovered_device(self.device)
        self.registry.add_custom_device("192.168.1.2")
        self.registry.cleanup()
        self.assertEqual(len(self.registry.discovered_devices), 0)
        self.assertEqual(len(self.registry.custom_devices_queue), 0)

    def test_get_device_by_ip(self):
        self.registry.add_discovered_device(self.device)
        device = self.registry.get_device_by_ip("192.168.1.1")
        self.assertEqual(device, self.device)

    def test_get_device_by_sku(self):
        self.registry.add_discovered_device(self.device)
        device = self.registry.get_device_by_sku("sku1")
        self.assertEqual(device, self.device)

    def test_get_device_by_fingerprint(self):
        self.registry.add_discovered_device(self.device)
        device = self.registry.get_device_by_fingerprint("device1")
        self.assertEqual(device, self.device)
