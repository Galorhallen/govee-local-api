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


BASIC_CAPABILITIES = create_with_capabilities(
    rgb=True, temperature=True, brightness=True, segments=0, scenes=True
)

ON_OFF_CAPABILITIES = create_with_capabilities(
    rgb=False, temperature=False, brightness=False, segments=0, scenes=False
)


GOVEE_LIGHT_CAPABILITIES: dict[str, GoveeLightCapabilities] = {
    # Models with common features
    "H600D": BASIC_CAPABILITIES,
    "H6022": BASIC_CAPABILITIES,
    "H6042": create_with_capabilities(True, True, True, 5, True),
    "H6046": create_with_capabilities(True, True, True, 10, True),
    "H6047": BASIC_CAPABILITIES,
    "H6051": BASIC_CAPABILITIES,
    "H6052": BASIC_CAPABILITIES,
    "H6056": BASIC_CAPABILITIES,
    "H6059": BASIC_CAPABILITIES,
    "H605D": BASIC_CAPABILITIES,
    "H6061": BASIC_CAPABILITIES,
    "H6062": BASIC_CAPABILITIES,
    "H6063": create_with_capabilities(True, True, True, 0, False),
    "H6065": BASIC_CAPABILITIES,
    "H6066": BASIC_CAPABILITIES,
    "H6069": create_with_capabilities(True, False, True, 20, True),
    "H6067": BASIC_CAPABILITIES,
    "H606A": BASIC_CAPABILITIES,
    "H6088": BASIC_CAPABILITIES,
    "H608A": BASIC_CAPABILITIES,
    "H6079": BASIC_CAPABILITIES,
    "H607C": BASIC_CAPABILITIES,
    "H608B": BASIC_CAPABILITIES,
    "H608D": BASIC_CAPABILITIES,
    "H60A1": BASIC_CAPABILITIES,
    "H60A4": create_with_capabilities(True, True, True, 11, False),
    "H60A6": BASIC_CAPABILITIES,
    "H6072": BASIC_CAPABILITIES,
    "H6073": BASIC_CAPABILITIES,
    "H6076": BASIC_CAPABILITIES,
    "H6078": BASIC_CAPABILITIES,
    "H6087": BASIC_CAPABILITIES,
    "H610A": BASIC_CAPABILITIES,
    "H610B": BASIC_CAPABILITIES,
    "H6110": BASIC_CAPABILITIES,
    "H6117": BASIC_CAPABILITIES,
    "H612A": BASIC_CAPABILITIES,
    "H612B": BASIC_CAPABILITIES,
    "H612C": create_with_capabilities(True, True, True, 0, True),
    "H612D": create_with_capabilities(True, True, True, 20, True),
    "H612F": create_with_capabilities(True, True, True, 5, True),
    "H6143": BASIC_CAPABILITIES,
    "H6144": BASIC_CAPABILITIES,
    "H6159": BASIC_CAPABILITIES,
    "H615A": create_with_capabilities(True, True, True, 0, True),
    "H615B": create_with_capabilities(True, True, True, 0, True),
    "H615C": create_with_capabilities(True, True, True, 0, True),
    "H615D": create_with_capabilities(True, True, True, 0, True),
    "H615E": create_with_capabilities(True, True, True, 0, True),
    "H6163": BASIC_CAPABILITIES,
    "H6167": create_with_capabilities(True, True, True, 12, True),
    "H6168": BASIC_CAPABILITIES,
    "H6172": BASIC_CAPABILITIES,
    "H6173": BASIC_CAPABILITIES,
    "H6175": BASIC_CAPABILITIES,
    "H6176": BASIC_CAPABILITIES,
    "H618A": create_with_capabilities(True, True, True, 15, True),
    "H618C": create_with_capabilities(True, True, True, 15, True),
    "H618E": create_with_capabilities(True, True, True, 15, True),
    "H618F": create_with_capabilities(True, True, True, 15, True),
    "H619A": create_with_capabilities(True, True, True, 10, True),
    "H619B": create_with_capabilities(True, True, True, 10, True),
    "H619C": create_with_capabilities(True, True, True, 10, True),
    "H619D": create_with_capabilities(True, True, True, 10, True),
    "H619E": create_with_capabilities(True, True, True, 10, True),
    "H619Z": BASIC_CAPABILITIES,
    "H61A0": BASIC_CAPABILITIES,
    "H61A1": BASIC_CAPABILITIES,
    "H61A2": BASIC_CAPABILITIES,
    "H61A3": BASIC_CAPABILITIES,
    "H61A5": BASIC_CAPABILITIES,
    "H61A8": BASIC_CAPABILITIES,
    "H61B2": BASIC_CAPABILITIES,
    "H61B3": create_with_capabilities(True, True, True, 15, True),
    "H61B5": BASIC_CAPABILITIES,
    "H61BA": BASIC_CAPABILITIES,
    "H61BE": BASIC_CAPABILITIES,
    "H61BC": BASIC_CAPABILITIES,
    "H61C2": BASIC_CAPABILITIES,
    "H61C5": BASIC_CAPABILITIES,
    "H61C3": BASIC_CAPABILITIES,
    "H61D3": BASIC_CAPABILITIES,
    "H61D5": BASIC_CAPABILITIES,
    "H61E0": BASIC_CAPABILITIES,
    "H61E1": BASIC_CAPABILITIES,
    "H61E5": create_with_capabilities(True, True, True, 12, True),
    "H61E6": create_with_capabilities(True, True, True, 15, True),
    "H61F2": create_with_capabilities(True, True, True, 4, True),
    "H61F5": create_with_capabilities(True, True, True, 10, True),
    "H61F6": create_with_capabilities(True, True, True, 20, True),
    "H6609": create_with_capabilities(True, True, True, 18, True),
    "H6640": create_with_capabilities(True, True, True, 8, True),
    "H6641": create_with_capabilities(True, True, True, 14, True),
    "H7012": create_with_capabilities(False, False, True, 0, False),
    "H7013": create_with_capabilities(False, False, True, 0, False),
    "H7021": BASIC_CAPABILITIES,
    "H7028": BASIC_CAPABILITIES,
    "H7041": BASIC_CAPABILITIES,
    "H7042": BASIC_CAPABILITIES,
    "H7050": BASIC_CAPABILITIES,
    "H7051": BASIC_CAPABILITIES,
    "H7058": create_with_capabilities(True, True, True, 0, True),
    "H7055": BASIC_CAPABILITIES,
    "H705A": BASIC_CAPABILITIES,
    "H705B": BASIC_CAPABILITIES,
    "H705C": BASIC_CAPABILITIES,
    "H705D": create_with_capabilities(True, True, True, 9, True),
    "H705E": create_with_capabilities(True, True, True, 18, True),
    "H705F": create_with_capabilities(True, True, True, 27, True),
    "H7060": BASIC_CAPABILITIES,
    "H7063": BASIC_CAPABILITIES,
    "H7061": BASIC_CAPABILITIES,
    "H7062": BASIC_CAPABILITIES,
    "H7065": BASIC_CAPABILITIES,
    "H7066": BASIC_CAPABILITIES,
    "H706A": BASIC_CAPABILITIES,
    "H706B": BASIC_CAPABILITIES,
    "H706C": BASIC_CAPABILITIES,
    "H7093": create_with_capabilities(True, True, True, 2, True),
    "H7033": BASIC_CAPABILITIES,
    "H70C1": BASIC_CAPABILITIES,
    "H70C2": BASIC_CAPABILITIES,
    "H70C4": create_with_capabilities(True, True, True, 10, True),
    "H70C5": create_with_capabilities(True, True, True, 10, True),
    "H7020": BASIC_CAPABILITIES,
    "H7037": BASIC_CAPABILITIES,
    "H7038": BASIC_CAPABILITIES,
    "H7039": create_with_capabilities(True, True, True, 45, True),
    "H7052": BASIC_CAPABILITIES,
    "H7075": BASIC_CAPABILITIES,
    "H70A1": create_with_capabilities(True, True, True, 15, True),
    "H70A2": create_with_capabilities(True, True, True, 20, True),
    "H70A3": create_with_capabilities(True, True, True, 15, True),
    "H70B1": BASIC_CAPABILITIES,
    "H70B3": BASIC_CAPABILITIES,
    "H70BC": BASIC_CAPABILITIES,
    "H70D1": BASIC_CAPABILITIES,
    "H805A": create_with_capabilities(True, True, True, 0, True),
    "H805C": BASIC_CAPABILITIES,
    "H8072": create_with_capabilities(True, True, True, 8, True),
}
