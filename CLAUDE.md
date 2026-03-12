# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python library (`govee-local-api`) for communicating with Govee smart light devices over the local network using UDP multicast. Used as a dependency by the Home Assistant Govee integration. Published to PyPI.

## Build & Development

Uses **Poetry** for dependency management. Python >= 3.11.

```bash
poetry install --no-interaction --no-root   # Install dependencies
poetry run pytest                            # Run all tests
poetry run pytest tests/test_message.py      # Run a single test file
poetry run pytest -k test_scan_message       # Run a single test
poetry build                                 # Build package
```

## Linting

CI runs **Black** for formatting. Pre-commit hooks include Black, Ruff (with `--fix`), codespell, prettier, and mypy.

```bash
pre-commit run --all-files                   # Run all pre-commit hooks
```

## Architecture

The library is a pure asyncio UDP protocol implementation with no external runtime dependencies.

- **`controller.py`** — `GoveeController(asyncio.DatagramProtocol)`: Main entry point. Manages device discovery via UDP multicast (239.255.255.250), periodic status polling, and device eviction. Sends commands to devices on port 4003, listens on port 4002, broadcasts discovery on port 4001.
- **`device.py`** — `GoveeDevice`: Represents a single Govee light. Holds state (on/off, brightness, color, temperature) and exposes async control methods that delegate back to the controller.
- **`message.py`** — Message protocol. `GoveeMessage` is the base class; subclasses handle specific commands (`ScanMessage`, `OnOffMessage`, `ColorMessage`, `BrightnessMessage`, etc.). `PtRealMessage` handles binary commands with XOR checksum encoding via base64. `MessageResponseFactory` parses incoming JSON messages into typed response objects.
- **`light_capabilities.py`** — Device capability registry. `GoveeLightCapabilities` defines what features a device model supports (RGB, color temperature, brightness, segments, scenes). `GOVEE_LIGHT_CAPABILITIES` is the dict mapping SKU strings to capabilities. New device support is added here.
- **`device_registry.py`** — `DeviceRegistry`: Internal store of discovered devices and a queue for manually-added device IPs.

## Adding Support for New Devices

To add a new Govee device model, add an entry to `GOVEE_LIGHT_CAPABILITIES` in `src/govee_local_api/light_capabilities.py`. Use `create_with_capabilities(rgb, temperature, brightness, segments, scenes)` or reference `BASIC_CAPABILITIES` for standard devices. The segments parameter is the number of individually controllable LED segments.

## Key Conventions

- Version is maintained in both `pyproject.toml` and `src/govee_local_api/__init__.py`
- Tests are in `tests/` and use plain pytest (no fixtures framework)
- `pythonpath = "src"` is configured in pytest settings — imports use `govee_local_api.*`
- CI tests against Python 3.11, 3.12, and 3.13
