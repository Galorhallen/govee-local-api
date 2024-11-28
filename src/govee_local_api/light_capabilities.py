from enum import IntFlag


class GoveeLightFeatures(IntFlag):
    """Govee Lights capabilities."""

    COLOR_RGB = 0x01
    COLOR_KELVIN_TEMPERATURE = 0x02
    BRIGHTNESS = 0x04
    SEGMENT_CONTROL = 0x08
    SCENES = 0x10


COMMON_FEATURES: GoveeLightFeatures = (
    GoveeLightFeatures.COLOR_RGB
    | GoveeLightFeatures.COLOR_KELVIN_TEMPERATURE
    | GoveeLightFeatures.BRIGHTNESS
)


class GoveeLightCapabilities:
    def __init__(
        self,
        features: GoveeLightFeatures,
        segments: list[bytes] = [],
        scenes: dict[str, bytes] = {},
    ) -> None:
        self.features = features
        self.segments = (
            segments if features & GoveeLightFeatures.SEGMENT_CONTROL else []
        )
        self.scenes = scenes if features & GoveeLightFeatures.SCENES else {}

    @property
    def segments_count(self) -> int:
        return len(self.segments)

    @property
    def available_scenes(self) -> list[str]:
        return list(self.scenes.keys())

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

SCENE_CODES: dict[str, bytes] = {
    "sunrise": b"\x00",
    "sunset": b"\x01",
    "movie": b"\x04",
    "dating": b"\x05",
    "romantic": b"\x07",
    "twinkle": b"\x08",
    "candlelight": b"\x09",
    "snowflake": b"\x0f",
    "energetic": b"\x10",
    "breathe": b"\x0a",
    "crossing": b"\x15",
}


def create_with_capabilities(
    rgb: bool, temperature: bool, brightness: bool, segments: int, scenes: bool
) -> GoveeLightCapabilities:
    features: GoveeLightFeatures = GoveeLightFeatures(0)
    segments_codes = []

    if rgb:
        features = features | GoveeLightFeatures.COLOR_RGB
    if temperature:
        features = features | GoveeLightFeatures.COLOR_KELVIN_TEMPERATURE
    if brightness:
        features = features | GoveeLightFeatures.BRIGHTNESS
    if segments > 0:
        features = features | GoveeLightFeatures.SEGMENT_CONTROL
        segments_codes = SEGMENT_CODES[:segments]

    if scenes:
        features = features | GoveeLightFeatures.SCENES

    return GoveeLightCapabilities(
        features, segments_codes, SCENE_CODES if scenes else {}
    )


COMMON_CAPABILITIES = create_with_capabilities(
    rgb=True, temperature=True, brightness=True, segments=0, scenes=True
)

ON_OFF_CAPABILITIES = create_with_capabilities(
    rgb=False, temperature=False, brightness=False, segments=0, scenes=False
)

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
    "H6144": COMMON_CAPABILITIES,
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
    "H61F5": COMMON_CAPABILITIES,
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
    "H705D": COMMON_CAPABILITIES,
    "H705E": COMMON_CAPABILITIES,
    "H705F": COMMON_CAPABILITIES,
    "H7060": COMMON_CAPABILITIES,
    "H7063": COMMON_CAPABILITIES,
    "H7061": COMMON_CAPABILITIES,
    "H7062": COMMON_CAPABILITIES,
    "H7065": COMMON_CAPABILITIES,
    "H7066": COMMON_CAPABILITIES,
    "H706A": COMMON_CAPABILITIES,
    "H706B": COMMON_CAPABILITIES,
    "H706C": COMMON_CAPABILITIES,
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
    "H7012": create_with_capabilities(False, False, True, 0, False),
    "H7013": create_with_capabilities(False, False, True, 0, False),
    "H805C": COMMON_CAPABILITIES,
}
