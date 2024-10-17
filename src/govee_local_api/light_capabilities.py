from enum import Enum, auto


class GoveeLightFeatures(Enum):
    """Govee Lights capabilities."""

    COLOR_RGB = auto()
    COLOR_KELVIN_TEMPERATURE = auto()
    BRIGHTNESS = auto()
    SEGMENT_CONTROL = auto()


class GoveeLightColorMode(Enum):
    """Govee Lights color mode."""

    MANUAL = auto()
    MUSIC = auto()
    SCENE = auto()


COMMON_FEATURES = {
    GoveeLightFeatures.COLOR_RGB,
    GoveeLightFeatures.COLOR_KELVIN_TEMPERATURE,
    GoveeLightFeatures.BRIGHTNESS,
}

# Devices with only brightness as a feature
BRIGHTNESS_ONLY = {GoveeLightFeatures.BRIGHTNESS}


class GoveeLightCapabilities:
    def __init__(
        self,
        features: set[GoveeLightFeatures],
        segments: list[bytes] = [],
        scenes: dict[str, str] = {},
    ) -> None:
        self.features = features
        self.segments = segments
        self.scenes = scenes

    @property
    def segments_count(self) -> int:
        return len(self.segments)

    def __repr__(self) -> str:
        return f"GoveeLightCapabilities(features={self.features!r}, segments={self.segments!r}, scenes={self.scenes!r})"

    def __str__(self) -> str:
        return f"GoveeLightCapabilities(features={self.features!r}, segments={len(self.segments)}, scenes={len(self.scenes)})"


SEGMENT_CODES: list[bytes] = [
    b"\x01\x00",  # 1
    b"\x02\x00",  # 2
    b"\x04\x00",  # 3
    b"\x08\x00",  # 4
    b"\x10\x00",  # 5
    b"\x20\x00",  # 6
    b"\x40\x00",  # 7
    b"\x80\x00",  # 8
    b"\x00\x01",  # 9
    b"\x00\x02",  # 10
    b"\x00\x04",  # 11
    b"\x00\x08",  # 12
    b"\x00\x10",  # 13
    b"\x00\x20",  # 14
    b"\x00\x40",  # 15
]

SCENE_CODES: dict[int, bytes] = {

}

def create_with_capabilities(rgb: bool, kelvin: bool, brightness: bool, segments: int, scenes: bool) -> GoveeLightCapabilities:
    features = set()
    segments_codes = []
    if rgb:
        features.add(GoveeLightFeatures.COLOR_RGB)
    if kelvin:
        features.add(GoveeLightFeatures.COLOR_KELVIN_TEMPERATURE)
    if brightness:
        features.add(GoveeLightFeatures.BRIGHTNESS)
    if segments > 0:
        features.add(GoveeLightFeatures.SEGMENT_CONTROL)
        segments_codes = SEGMENT_CODES[:segments]        
    return GoveeLightCapabilities(features, segments_codes, {})

COMMON_CAPABILITIES = create_with_capabilities(True, True, True, 0, True)

GOVEE_LIGHT_CAPABILITIES: dict[str, GoveeLightCapabilities] = {
    # Models with common features
    "H6046": COMMON_CAPABILITIES,
    "H6047": COMMON_CAPABILITIES,
    "H6051": COMMON_CAPABILITIES,
    "H6056": COMMON_CAPABILITIES,
    "H6059": COMMON_CAPABILITIES,
    "H6061": COMMON_CAPABILITIES,
    "H6062": COMMON_CAPABILITIES,
    "H6065": COMMON_CAPABILITIES,
    "H6066": COMMON_CAPABILITIES,
    "H6067": COMMON_CAPABILITIES,
    "H6072": COMMON_CAPABILITIES,
    "H6073": COMMON_CAPABILITIES,
    "H6076": COMMON_CAPABILITIES,
    "H6078": COMMON_CAPABILITIES,
    "H6087": COMMON_CAPABILITIES,
    "H610A": COMMON_CAPABILITIES,
    "H610B": COMMON_CAPABILITIES,
    "H6110": COMMON_CAPABILITIES,
    "H6117": COMMON_CAPABILITIES,
    "H6159": COMMON_CAPABILITIES,
    "H615A": create_with_capabilities(True, True, True, 0, True),
    "H615B": create_with_capabilities(True, True, True, 0, True),
    "H615C": create_with_capabilities(True, True, True, 0, True),
    "H615D": create_with_capabilities(True, True, True, 0, True),
    "H615E": create_with_capabilities(True, True, True, 0, True),
    "H6163": COMMON_CAPABILITIES,
    "H6168": COMMON_CAPABILITIES,
    "H6172": COMMON_CAPABILITIES,
    "H6173": COMMON_CAPABILITIES,
    "H618A": create_with_capabilities(True, True, True, 15, True),
    "H618C": create_with_capabilities(True, True, True, 15, True),
    "H618E": create_with_capabilities(True, True, True, 15, True),
    "H618F": create_with_capabilities(True, True, True, 15, True),
    "H619A": create_with_capabilities(True, True, True, 10, True),
    "H619B": create_with_capabilities(True, True, True, 10, True),
    "H619C": create_with_capabilities(True, True, True, 10, True),
    "H619D": create_with_capabilities(True, True, True, 10, True),
    "H619E": create_with_capabilities(True, True, True, 10, True),
    "H619Z": COMMON_CAPABILITIES,
    "H61A0": COMMON_CAPABILITIES,
    "H61A1": COMMON_CAPABILITIES,
    "H61A2": COMMON_CAPABILITIES,
    "H61A3": COMMON_CAPABILITIES,
    "H61A5": COMMON_CAPABILITIES,
    "H61A8": COMMON_CAPABILITIES,
    "H61B2": COMMON_CAPABILITIES,
    "H61BA": COMMON_CAPABILITIES,
    "H61BC": COMMON_CAPABILITIES,
    "H61E1": COMMON_CAPABILITIES,
    "H7021": COMMON_CAPABILITIES,
    "H7028": COMMON_CAPABILITIES,
    "H7041": COMMON_CAPABILITIES,
    "H7042": COMMON_CAPABILITIES,
    "H7050": COMMON_CAPABILITIES,
    "H7051": COMMON_CAPABILITIES,
    "H7055": COMMON_CAPABILITIES,
    "H705A": COMMON_CAPABILITIES,
    "H705B": COMMON_CAPABILITIES,
    "H705C": COMMON_CAPABILITIES,
    "H705E": COMMON_CAPABILITIES,
    "H7060": COMMON_CAPABILITIES,
    "H7063": COMMON_CAPABILITIES,
    "H7061": COMMON_CAPABILITIES,
    "H7062": COMMON_CAPABILITIES,
    "H7065": COMMON_CAPABILITIES,
    "H7066": COMMON_CAPABILITIES,
    "H7033": COMMON_CAPABILITIES,
    "H70C1": COMMON_CAPABILITIES,
    "H70C2": COMMON_CAPABILITIES,
    "H6052": COMMON_CAPABILITIES,
    "H6088": COMMON_CAPABILITIES,
    "H608A": COMMON_CAPABILITIES,
    "H606A": COMMON_CAPABILITIES,
    "H61C5": COMMON_CAPABILITIES,
    "H7020": COMMON_CAPABILITIES,
    "H61BE": COMMON_CAPABILITIES,
    "H61B5": COMMON_CAPABILITIES,
    "H61C3": COMMON_CAPABILITIES,
    "H61D3": COMMON_CAPABILITIES,
    "H61D5": COMMON_CAPABILITIES,
    "H608B": COMMON_CAPABILITIES,
    "H608D": COMMON_CAPABILITIES,
    "H6175": COMMON_CAPABILITIES,
    "H6176": COMMON_CAPABILITIES,
    "H7037": COMMON_CAPABILITIES,
    "H7038": COMMON_CAPABILITIES,
    "H7039": COMMON_CAPABILITIES,
    "H7052": COMMON_CAPABILITIES,
    "H61E0": COMMON_CAPABILITIES,
    "H6079": COMMON_CAPABILITIES,
    "H607C": COMMON_CAPABILITIES,
    "H7075": COMMON_CAPABILITIES,
    "H60A1": COMMON_CAPABILITIES,
    "H70B1": COMMON_CAPABILITIES,
    "H70A1": COMMON_CAPABILITIES,
    # Models with only brightness
    "H7012": create_with_capabilities(False, False, True, 0, False),
    "H7013": create_with_capabilities(False, False, True, 0, False),
}
