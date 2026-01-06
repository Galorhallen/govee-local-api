# Govee Local API

[![Upload Python Package](https://github.com/Galorhallen/govee-local-api/actions/workflows/deploy.yml/badge.svg?event=release)](https://github.com/Galorhallen/govee-local-api/actions/workflows/deploy.yml)

Python library for controlling Govee smart lights via local UDP API.

> **Note:** Scene and segment support is experimental.

## Requirements

- Python >= 3.11
- Govee device with LAN API enabled ([Setup Guide](https://app-h5.govee.com/user-manual/wlan-guide))

## Installation

```bash
pip install govee-local-api
```

## Usage

```python
import asyncio
from govee_local_api import GoveeController, GoveeDevice

async def main():
    # Create controller with discovery
    controller = GoveeController(
        listening_address="0.0.0.0",
        discovery_enabled=True,
    )
    await controller.start()

    # Wait for devices
    await asyncio.sleep(3)

    # Control first discovered device
    if controller.devices:
        device = controller.devices[0]
        await device.turn_on()
        await device.set_brightness(80)
        await device.set_rgb_color(255, 0, 0)  # Red

    controller.cleanup()

asyncio.run(main())
```

### Manual Device Discovery

```python
controller = GoveeController(
    listening_address="0.0.0.0",
    discovery_enabled=False,
)
await controller.start()
controller.add_device_to_discovery_queue("192.168.1.100")
```

### Segment Control

For devices with segmented LEDs (RGBIC strips):

```python
# Set segments 1-3 to red
await device.set_segments_rgb_color([1, 2, 3], 255, 0, 0)

# Set segments with brightness (50%)
await device.set_segments_rgb_color([4, 5, 6], 0, 255, 0, brightness=50)

# Turn off specific segments
await device.turn_segments_off([7, 8, 9])
```

### Scenes

```python
# List available scenes
print(device.capabilities.available_scenes)

# Activate a scene
await device.set_scene("sunrise")
```

## Local Development

```bash
# Clone and install
git clone https://github.com/Galorhallen/govee-local-api.git
cd govee-local-api
poetry install

# Run tests
poetry run pytest

# Run example REPL
poetry run python example/main.py

# Run pre-commit hooks
poetry run pre-commit run --all-files
```

## Supported Devices

See [light_capabilities.py](src/govee_local_api/light_capabilities.py) for the list of supported SKUs. To request support for a new device, open an issue with your device's SKU and segment count.
