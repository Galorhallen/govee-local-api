# Govee Local API

[![Upload Python Package](https://github.com/Galorhallen/govee-local-api/actions/workflows/deploy.yml/badge.svg?event=release)](https://github.com/Galorhallen/govee-local-api/actions/workflows/deploy.yml)

Please note that scene and segment support is still **very** experimental.

# Requirements

- Python >= 3.9
- Govee Local API enabled. Refer to https://app-h5.govee.com/user-manual/wlan-guide

# Installaction

From your terminal, run

    pip install govee-local-api

or

    python3 -m pip install govee-local-api

# Dynamic Registry (Custom SKU Support)

This library supports dynamic capability loading via an external JSON file. This allows users to add support for new or experimental Govee devices without modifying the library source code.

## Usage

When initializing the `GoveeController`, provide the path to your custom capabilities JSON file:

```python
from govee_local_api import GoveeController

controller = GoveeController(
    custom_capabilities_path="/path/to/your/govee_custom.json"
)
```

## JSON Format

Create a JSON file with the SKU as the key and the desired capabilities as the values.

```json
{
  "H9999": {
    "rgb": true,
    "temperature": true,
    "brightness": true,
    "segments": 10,
    "scenes": true
  }
}
```

### Parameters:
- `rgb` (bool): Enables RGB color control. Defaults to `true`.
- `temperature` (bool): Enables color temperature control. Defaults to `true`.
- `brightness` (bool): Enables brightness control. Defaults to `true`.
- `segments` (int): The number of addressable segments (for RGBIC devices). Defaults to `0`.
- `scenes` (bool): Enables scene/effect support. Defaults to `true`.

## Home Assistant Integration

If you are using this library within Home Assistant, you can place your `govee_custom.json` in your `/config` directory and ensure the integration path is updated to point to this file location.
