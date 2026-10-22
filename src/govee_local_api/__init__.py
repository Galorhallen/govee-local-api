from importlib.metadata import PackageNotFoundError, version

from .controller import GoveeController
from .device import GoveeDevice
from .light_capabilities import (
    DEFAULT_TEMPERATURE_RANGE,
    GoveeLightFeatures,
    GoveeLightCapabilities,
    GoveeTemperatureRange,
)

__all__ = [
    "GoveeController",
    "GoveeDevice",
    "GoveeLightFeatures",
    "GoveeLightCapabilities",
    "GoveeTemperatureRange",
    "DEFAULT_TEMPERATURE_RANGE",
]

try:
    __version__ = version("govee-local-api")
except PackageNotFoundError:  # imported from a source tree without being installed
    __version__ = "0.0.0"
