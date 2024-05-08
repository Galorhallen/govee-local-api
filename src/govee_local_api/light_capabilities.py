from enum import Enum, auto


class GoveeLightCapability(Enum):
    """Govee Lights capabilities."""

    COLOR_RGB = auto()
    COLOR_KELVIN_TEMPERATURE = auto()
    BRIGHTNESS = auto()


GOVEE_LIGHT_CAPABILITIES: dict[str, set[GoveeLightCapability]] = {
    "H6046": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H6047": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H6051": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H6056": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H6059": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H6061": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H6062": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H6065": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H6066": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H6067": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H6072": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H6073": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H6076": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H6078": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H6087": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H610A": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H610B": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H6117": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H6159": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H615A": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H615E": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H6163": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H6168": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H6172": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H6173": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H618A": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H618C": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H618E": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H618F": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H619A": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H619B": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H619C": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H619D": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H619E": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H619Z": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H61A0": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H61A1": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H61A2": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H61A3": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H61A5": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H61A8": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H61B2": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H61E1": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H7012": {
        GoveeLightCapability.BRIGHTNESS,
    },
    "H7013": {
        GoveeLightCapability.BRIGHTNESS,
    },
    "H7021": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H7028": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H7041": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H7042": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H7050": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H7051": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H7055": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H705A": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H705B": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H705C": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H7060": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H7061": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H7062": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H7065": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H7066": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    # User reported devices
    "H70C1": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H6052": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H6088": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H608A": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H606A": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H61C5": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H7020": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H61BE": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H61B5": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H61C3": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H61D3": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
    "H608B": {
        GoveeLightCapability.COLOR_RGB,
        GoveeLightCapability.COLOR_KELVIN_TEMPERATURE,
        GoveeLightCapability.BRIGHTNESS,
    },
}
