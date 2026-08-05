# Govee Local API

[![Upload Python Package](https://github.com/Galorhallen/govee-local-api/actions/workflows/deploy.yml/badge.svg?event=release)](https://github.com/Galorhallen/govee-local-api/actions/workflows/deploy.yml)

Please note that scene and segment support is still **very** experimental.

See [SUPPORTED_DEVICES.md](SUPPORTED_DEVICES.md) for the full list of known device models and their capabilities.

# Requirements

- Python >= 3.11
- Govee Local API enabled. Refer to https://app-h5.govee.com/user-manual/wlan-guide

# Installation

From your terminal, run

    pip install govee-local-api

or

    python3 -m pip install govee-local-api

# Usage

## Basic Usage

```python
import asyncio
from govee_local_api import GoveeController

async def main():
    # Simple single-interface setup
    controller = GoveeController()

    # Discover devices
    devices = await controller.scan_devices()

    # Control a device
    if devices:
        device = devices[0]
        await device.turn_on()
        await device.set_brightness(80)
        await device.set_color(255, 0, 0)  # Red

asyncio.run(main())
```

## Multi-Interface Setup

For complex network environments with multiple interfaces:

```python
# Multiple listening addresses (basic)
controller = GoveeController(
    listening_addresses=["192.168.1.100", "10.0.0.100", "172.16.1.100"]
)
```

## Network Mask Configuration

For precise subnet-aware device routing (recommended for enterprise/VLAN environments), embed the network mask directly in the address using CIDR or netmask notation:

```python
# Precise subnet matching with embedded network masks
controller = GoveeController(
    listening_addresses=[
        "192.168.1.100/24",             # Main LAN (CIDR)
        "192.168.10.100/255.255.255.0", # IoT VLAN (dotted netmask)
        "10.0.0.100/8"                  # Management network
    ]
)
```

### Supported Network Mask Formats

- **CIDR Notation**: `192.168.1.100/24`, `10.0.0.100/8`, etc.
- **Dotted Decimal**: `192.168.1.100/255.255.255.0`, etc.
- **No mask**: `192.168.1.100` (uses heuristic subnet matching)
- **Wildcard**: `0.0.0.0` (listens on all interfaces, no subnet matching)

## Advanced Features

### Device Discovery and Control

```python
async def discover_and_control():
    controller = GoveeController(
        listening_addresses=["192.168.1.100/24", "192.168.10.100/24"]
    )

    # Scan for devices across all networks
    devices = await controller.scan_devices()

    # Filter devices by network
    main_lan_devices = [d for d in devices if d.ip.startswith("192.168.1.")]
    iot_vlan_devices = [d for d in devices if d.ip.startswith("192.168.10.")]

    # Control devices on specific networks
    for device in main_lan_devices:
        await device.turn_on()
        await device.set_brightness(50)

    for device in iot_vlan_devices:
        await device.turn_off()
```

### Direct Device Control

```python
# Control device by IP address (uses intelligent transport selection)
await controller.control_device("192.168.1.100", turn_on=True)
await controller.control_device("192.168.1.100", brightness=75)
await controller.control_device("192.168.1.100", color_rgb=(0, 255, 0))
```

## Documentation

- **[Supported Devices](SUPPORTED_DEVICES.md)** - Auto-generated list of known device models and their capabilities
- **[Network Mask Configuration Guide](NETWORK_MASKS.md)** - Comprehensive guide for multi-network setups
- **[API Reference](https://github.com/Galorhallen/govee-local-api)** - Full API documentation

## Use Cases

- **Home Networks**: Simple single-interface setup
- **Small Office**: Multi-interface with heuristic matching
- **Enterprise/VLAN**: Network mask configuration for precise routing
- **IoT Deployments**: Isolated network segments with dedicated interfaces
- **Multi-Building**: Physically separated networks with same IP ranges
