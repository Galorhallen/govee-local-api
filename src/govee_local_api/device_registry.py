from .device import GoveeDevice

import logging

from typing import Optional


class DeviceRegistry:
    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self._discovered_devices: dict[str, GoveeDevice] = {}
        self._custom_devices_queue: set[str] = set()
        self._logger = logger or logging.getLogger(__name__)

    def add_discovered_device(self, device: GoveeDevice) -> GoveeDevice:
        if device.ip in self._custom_devices_queue:
            self._logger.debug(
                f"Found manullay added device {device}. Removing from queue."
            )
            self._custom_devices_queue.remove(device.ip)
            device.is_manual = True
        self._discovered_devices[device.fingerprint] = device
        return device

    def remove_discovered_device(self, device: str | GoveeDevice) -> None:
        if isinstance(device, GoveeDevice):
            device = device.fingerprint
        if device in self._discovered_devices:
            del self._discovered_devices[device]

    def add_device_to_queue(self, ip: str) -> bool:
        if ip not in self._custom_devices_queue:
            self._custom_devices_queue.add(ip)
            return True
        return False

    def remove_device_from_queue(self, ip: str) -> bool:
        if ip in self._custom_devices_queue:
            self._custom_devices_queue.remove(ip)
            if device := self.get_device_by_ip(ip):
                if device.is_manual:
                    self.remove_discovered_device(device)
            return True
        return False

    def cleanup(self) -> None:
        self._discovered_devices.clear()
        self._custom_devices_queue.clear()

    def get_device_by_ip(self, ip: str) -> GoveeDevice | None:
        return next(
            (device for device in self._discovered_devices.values() if device.ip == ip),
            None,
        )

    def get_device_by_sku(self, sku: str) -> GoveeDevice | None:
        return next(
            (
                device
                for device in self._discovered_devices.values()
                if device.sku == sku
            ),
            None,
        )

    def get_device_by_fingerprint(self, fingerprint: str) -> GoveeDevice | None:
        return self._discovered_devices.get(fingerprint, None)

    @property
    def discovered_devices(self) -> dict[str, GoveeDevice]:
        return self._discovered_devices

    @property
    def devices_queue(self) -> set[str]:
        return self._custom_devices_queue

    @property
    def has_queued_devices(self) -> bool:
        return bool(self._custom_devices_queue)
