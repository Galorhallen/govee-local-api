from .device import GoveeDevice


class DeviceRegistry:
    def __init__(self) -> None:
        self._discovered_devices: dict[str, GoveeDevice] = {}
        self._custom_devices_queue: set[str] = set()

    def add_discovered_device(self, device: GoveeDevice) -> GoveeDevice:
        if device.ip in self._custom_devices_queue:
            self._custom_devices_queue.remove(device.ip)
        self._discovered_devices[device.fingerprint] = device
        return device

    def remove_discovered_device(self, device: str | GoveeDevice) -> None:
        if isinstance(device, GoveeDevice):
            device = device.fingerprint
        if device in self._discovered_devices:
            del self._discovered_devices[device]

    def add_custom_device(self, ip: str) -> None:
        self._custom_devices_queue.add(ip)

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
    def custom_devices_queue(self) -> set[str]:
        return self._custom_devices_queue
