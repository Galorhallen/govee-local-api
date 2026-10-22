from enum import IntFlag
from typing import NamedTuple


class GoveeTemperatureRange(NamedTuple):
    """Kelvin range supported by a device's white/color-temperature mode."""

    min_kelvin: int
    max_kelvin: int


DEFAULT_TEMPERATURE_RANGE = GoveeTemperatureRange(min_kelvin=2000, max_kelvin=9000)
"""Range assumed for every device that doesn't declare its own."""


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


def _normalize_temperature_range(
    temperature_range: tuple[int, int] | None,
) -> GoveeTemperatureRange:
    """Validate a (min, max) Kelvin pair, falling back to the default range."""
    if temperature_range is None:
        return DEFAULT_TEMPERATURE_RANGE

    min_kelvin, max_kelvin = temperature_range
    if min_kelvin <= 0 or max_kelvin <= 0:
        raise ValueError(
            f"Temperature range must be positive, got {temperature_range!r}"
        )
    if min_kelvin >= max_kelvin:
        raise ValueError(
            f"Temperature range minimum must be below its maximum, got "
            f"{temperature_range!r}"
        )
    return GoveeTemperatureRange(min_kelvin=min_kelvin, max_kelvin=max_kelvin)


class GoveeLightCapabilities:
    def __init__(
        self,
        features: GoveeLightFeatures,
        segments: list[bytes] | None = None,
        scenes: dict[str, bytes] | None = None,
        temperature_range: tuple[int, int] | None = None,
    ) -> None:
        self.features = features
        self.temperature_range = _normalize_temperature_range(temperature_range)
        # Copy the inputs: they are module-level shared tables
        # (SEGMENT_CODES / SCENE_CODES), and capability objects are shared
        # across devices — a consumer mutating one instance must not
        # corrupt every other device's capabilities.
        self.segments = (
            list(segments)
            if segments and features & GoveeLightFeatures.SEGMENT_CONTROL
            else []
        )
        self.scenes = (
            dict(scenes) if scenes and features & GoveeLightFeatures.SCENES else {}
        )

    @property
    def segments_count(self) -> int:
        return len(self.segments)

    @property
    def available_scenes(self) -> list[str]:
        return list(self.scenes.keys())

    def __repr__(self) -> str:
        return (
            f"GoveeLightCapabilities(features={self.features!r}, "
            f"segments={self.segments!r}, scenes={self.scenes!r}, "
            f"temperature_range={self.temperature_range!r})"
        )

    def __str__(self) -> str:
        return (
            f"GoveeLightCapabilities(features={self.features!r}, "
            f"segments={len(self.segments)}, scenes={len(self.scenes)}, "
            f"temperature_range={tuple(self.temperature_range)})"
        )


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
    "rainbow": b"\x16",  # Issue #120
}


def builtin_scenes(*scene_names: str) -> dict[str, bytes]:
    """Pick a subset of SCENE_CODES by name, for models that only honour some.

    The generic 1-byte codes in SCENE_CODES predate Govee's per-model scene
    libraries; on many models a code plays a different scene or nothing at
    all. Use this to advertise only the codes a model's library confirms.
    """
    unknown_names = [name for name in scene_names if name not in SCENE_CODES]
    if unknown_names:
        raise ValueError(f"Unknown built-in scene names: {unknown_names!r}")
    return {name: SCENE_CODES[name] for name in scene_names}


def create_with_capabilities(
    rgb: bool,
    temperature: bool,
    brightness: bool,
    segments: int,
    scenes: bool | dict[str, bytes],
    temperature_range: tuple[int, int] | None = None,
) -> GoveeLightCapabilities:
    """Build capabilities for a model.

    ``scenes`` is either a bool (``True`` advertises the full generic
    SCENE_CODES set) or an explicit ``{name: code}`` dict for models that
    only honour a subset; an empty dict means no scene support.
    """
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

    scene_codes: dict[str, bytes]
    if isinstance(scenes, dict):
        scene_codes = scenes
    else:
        scene_codes = SCENE_CODES if scenes else {}
    if scene_codes:
        features = features | GoveeLightFeatures.SCENES

    return GoveeLightCapabilities(
        features,
        segments_codes,
        scene_codes,
        temperature_range,
    )


BASIC_CAPABILITIES = create_with_capabilities(
    rgb=True, temperature=True, brightness=True, segments=0, scenes=True
)

BASIC_CAPABILITIES_NO_SCENES = create_with_capabilities(
    rgb=True, temperature=True, brightness=True, segments=0, scenes=False
)

ON_OFF_CAPABILITIES = create_with_capabilities(
    rgb=False, temperature=False, brightness=False, segments=0, scenes=False
)


# Scene support per model follows Govee's per-model scene library
# (app2.govee.com light-effect-libraries, see issue #370): a built-in code is
# advertised only where that library maps the same 1-byte code to the same
# scene name. ``scenes=True`` means the model honours all of SCENE_CODES,
# ``builtin_scenes(...)`` a confirmed subset, ``False`` none of them.
GOVEE_LIGHT_CAPABILITIES: dict[str, GoveeLightCapabilities] = {
    # Models with common features
    "H1232": BASIC_CAPABILITIES_NO_SCENES,
    "H1250": BASIC_CAPABILITIES_NO_SCENES,
    "H1270": BASIC_CAPABILITIES_NO_SCENES,
    "H1310": create_with_capabilities(
        True, True, True, 0, builtin_scenes("sunset", "rainbow")
    ),
    "H1401": BASIC_CAPABILITIES_NO_SCENES,
    "H14A1": BASIC_CAPABILITIES_NO_SCENES,
    "H14C0": BASIC_CAPABILITIES_NO_SCENES,
    "H14C1": BASIC_CAPABILITIES_NO_SCENES,
    "H1630": create_with_capabilities(True, True, True, 0, builtin_scenes("rainbow")),
    "H16B0": create_with_capabilities(
        True, True, True, 0, builtin_scenes("crossing", "rainbow")
    ),
    "H16C0": create_with_capabilities(
        True, True, True, 7, builtin_scenes("crossing", "rainbow")
    ),
    "H1A43": create_with_capabilities(
        True, True, True, 0, builtin_scenes("snowflake", "rainbow")
    ),
    "H1A45": create_with_capabilities(
        True, True, True, 0, builtin_scenes("snowflake", "rainbow")
    ),
    "H2A40": BASIC_CAPABILITIES,
    "H2A41": BASIC_CAPABILITIES,
    "H3200": create_with_capabilities(
        True, True, True, 0, builtin_scenes("sunrise", "sunset", "rainbow")
    ),
    "H3500": create_with_capabilities(
        True, True, True, 0, builtin_scenes("sunrise", "sunset")
    ),
    "H3501": create_with_capabilities(
        True, True, True, 0, builtin_scenes("sunrise", "sunset")
    ),
    "H3510": create_with_capabilities(
        True, True, True, 0, builtin_scenes("breathe", "rainbow")
    ),
    "H3511": create_with_capabilities(
        True, True, True, 0, builtin_scenes("breathe", "rainbow")
    ),
    "H3751": BASIC_CAPABILITIES_NO_SCENES,
    "H6004": BASIC_CAPABILITIES_NO_SCENES,
    "H6006": BASIC_CAPABILITIES_NO_SCENES,  # Issue #133 - temp confirmed via Cloud API (2000-9000K)
    "H6008": BASIC_CAPABILITIES_NO_SCENES,
    "H600A": BASIC_CAPABILITIES_NO_SCENES,
    "H600D": BASIC_CAPABILITIES_NO_SCENES,
    "H601A": BASIC_CAPABILITIES_NO_SCENES,  # Issue #129
    "H6020": BASIC_CAPABILITIES_NO_SCENES,
    "H6022": BASIC_CAPABILITIES_NO_SCENES,
    "H6038": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes("sunset", "romantic", "snowflake", "crossing", "rainbow"),
    ),
    "H6039": create_with_capabilities(True, True, True, 12, True),
    "H6042": create_with_capabilities(True, True, True, 5, builtin_scenes("rainbow")),
    "H6043": create_with_capabilities(
        True, False, True, 10, builtin_scenes("rainbow")
    ),  # Issue #254 - TV Light Bars 2, no temp
    "H6046": create_with_capabilities(
        True,
        True,
        True,
        10,
        builtin_scenes(
            "movie",
            "romantic",
            "candlelight",
            "snowflake",
            "energetic",
            "breathe",
            "crossing",
            "rainbow",
        ),
    ),
    "H6047": create_with_capabilities(
        True, True, True, 10, builtin_scenes("snowflake", "rainbow")
    ),
    "H6048": create_with_capabilities(
        True, True, True, 15, builtin_scenes("snowflake", "rainbow")
    ),
    "H6051": BASIC_CAPABILITIES_NO_SCENES,
    "H6052": create_with_capabilities(
        True, True, True, 0, builtin_scenes("snowflake", "breathe", "rainbow")
    ),
    "H6056": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes(
            "movie",
            "romantic",
            "candlelight",
            "snowflake",
            "energetic",
            "breathe",
            "crossing",
            "rainbow",
        ),
    ),
    "H6059": BASIC_CAPABILITIES_NO_SCENES,
    "H605D": BASIC_CAPABILITIES_NO_SCENES,
    "H6061": create_with_capabilities(True, True, True, 0, builtin_scenes("breathe")),
    "H6062": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes("romantic", "energetic", "breathe", "rainbow"),
    ),
    "H6063": BASIC_CAPABILITIES_NO_SCENES,
    "H6065": create_with_capabilities(True, True, True, 0, builtin_scenes("breathe")),
    "H6066": create_with_capabilities(True, True, True, 0, builtin_scenes("breathe")),
    "H6069": create_with_capabilities(True, False, True, 15, False),
    "H6067": create_with_capabilities(True, True, True, 0, builtin_scenes("breathe")),
    "H606A": BASIC_CAPABILITIES_NO_SCENES,
    "H6072": create_with_capabilities(
        True,
        True,
        True,
        8,
        builtin_scenes("romantic", "energetic", "breathe", "crossing", "rainbow"),
    ),
    "H6073": BASIC_CAPABILITIES_NO_SCENES,
    "H6076": create_with_capabilities(
        True, True, True, 7, builtin_scenes("rainbow"), temperature_range=(2700, 6500)
    ),  # Issue #271 - range confirmed in the Govee app
    "H6076A": BASIC_CAPABILITIES,
    "H6078": BASIC_CAPABILITIES_NO_SCENES,
    "H6079": create_with_capabilities(
        True, True, True, 0, builtin_scenes("crossing", "rainbow")
    ),
    "H607C": create_with_capabilities(
        True, True, True, 13, builtin_scenes("crossing", "rainbow")
    ),
    "H6087": create_with_capabilities(True, True, True, 12, builtin_scenes("breathe")),
    "H6088": create_with_capabilities(True, True, True, 6, False),
    "H608A": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes("sunrise", "sunset", "movie", "romantic", "rainbow"),
    ),
    "H608B": create_with_capabilities(
        True,
        True,
        True,
        15,
        builtin_scenes("sunrise", "sunset", "movie", "romantic", "rainbow"),
    ),
    "H608C": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes("sunrise", "sunset", "movie", "romantic", "rainbow"),
    ),
    "H608D": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes("sunrise", "sunset", "movie", "romantic", "rainbow"),
    ),
    "H6093": create_with_capabilities(False, True, True, 0, False),
    "H6094": BASIC_CAPABILITIES_NO_SCENES,
    "H6095": BASIC_CAPABILITIES_NO_SCENES,
    "H609D": BASIC_CAPABILITIES_NO_SCENES,
    "H60A0": create_with_capabilities(
        True, True, True, 0, builtin_scenes("candlelight")
    ),
    "H60A1": create_with_capabilities(
        True,
        True,
        True,
        13,
        builtin_scenes("candlelight"),
        temperature_range=(2200, 6500),
    ),  # Issue #39 - range from the Govee Cloud API
    "H60A4": create_with_capabilities(True, True, True, 11, False),
    "H60A6": create_with_capabilities(
        True, True, True, 0, False, temperature_range=(2700, 6500)
    ),  # H60A6 firmware 1.00.41: LAN requests clamp to 2700-6500K
    "H60B0": BASIC_CAPABILITIES_NO_SCENES,  # Issue #252 - segments TBD
    "H60B1": create_with_capabilities(
        True, True, True, 3, builtin_scenes("sunrise", "sunset")
    ),
    "H60B2": create_with_capabilities(
        True, True, True, 3, builtin_scenes("twinkle", "breathe", "rainbow")
    ),
    "H60C1": create_with_capabilities(
        True, True, True, 3, builtin_scenes("sunrise", "sunset", "rainbow")
    ),  # Issue #232
    "H610A": create_with_capabilities(
        True, True, True, 0, builtin_scenes("sunrise", "sunset", "breathe", "rainbow")
    ),
    "H610B": BASIC_CAPABILITIES_NO_SCENES,
    "H610E": create_with_capabilities(True, True, True, 7, False),
    "H610F": create_with_capabilities(True, True, True, 7, False),
    "H6110": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "dating",
            "romantic",
            "twinkle",
            "candlelight",
            "energetic",
            "breathe",
        ),
    ),
    "H6117": BASIC_CAPABILITIES,
    "H612A": BASIC_CAPABILITIES,
    "H612B": BASIC_CAPABILITIES,
    "H612C": create_with_capabilities(True, True, True, 10, True),
    "H612D": create_with_capabilities(True, True, True, 20, True),
    "H612F": create_with_capabilities(
        True,
        True,
        True,
        5,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "romantic",
            "twinkle",
            "candlelight",
            "energetic",
            "breathe",
            "rainbow",
        ),
        temperature_range=(2800, 9000),
    ),  # HA core #182244 - values below 2800K are ignored by the device
    "H6141": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "dating",
            "romantic",
            "twinkle",
            "candlelight",
            "energetic",
            "breathe",
        ),
    ),
    "H6143": BASIC_CAPABILITIES,
    "H6144": BASIC_CAPABILITIES,
    "H6159": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "dating",
            "romantic",
            "twinkle",
            "candlelight",
            "energetic",
            "breathe",
        ),
    ),
    "H615A": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "dating",
            "romantic",
            "twinkle",
            "candlelight",
            "energetic",
            "breathe",
        ),
    ),
    "H615B": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "dating",
            "romantic",
            "twinkle",
            "candlelight",
            "energetic",
            "breathe",
        ),
    ),
    "H615C": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "dating",
            "romantic",
            "twinkle",
            "candlelight",
            "energetic",
            "breathe",
        ),
    ),
    "H615D": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "dating",
            "romantic",
            "twinkle",
            "candlelight",
            "energetic",
            "breathe",
        ),
    ),
    "H615E": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "dating",
            "romantic",
            "twinkle",
            "candlelight",
            "energetic",
            "breathe",
        ),
    ),
    "H6163": BASIC_CAPABILITIES,
    "H6167": create_with_capabilities(
        True,
        True,
        True,
        12,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "romantic",
            "twinkle",
            "candlelight",
            "energetic",
            "breathe",
            "rainbow",
        ),
    ),
    "H6168": BASIC_CAPABILITIES,
    "H6169": create_with_capabilities(True, True, True, 15, True),
    "H616C": BASIC_CAPABILITIES,
    "H616D": create_with_capabilities(True, True, True, 15, True),
    "H616E": BASIC_CAPABILITIES,
    "H6172": BASIC_CAPABILITIES,
    "H6173": BASIC_CAPABILITIES,
    "H6175": BASIC_CAPABILITIES,
    "H6176": BASIC_CAPABILITIES,
    "H617E": create_with_capabilities(True, True, True, 0, True),
    "H6182": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "dating",
            "romantic",
            "twinkle",
            "candlelight",
            "energetic",
            "breathe",
        ),
    ),
    "H618A": create_with_capabilities(
        True,
        True,
        True,
        15,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "romantic",
            "twinkle",
            "candlelight",
            "energetic",
            "breathe",
            "rainbow",
        ),
    ),
    "H618C": create_with_capabilities(True, True, True, 15, True),
    "H618E": create_with_capabilities(True, True, True, 15, True),
    "H618F": create_with_capabilities(True, True, True, 15, True),
    "H618G": BASIC_CAPABILITIES,
    "H619A": create_with_capabilities(True, True, True, 10, True),
    "H619B": create_with_capabilities(True, True, True, 10, True),
    "H619C": create_with_capabilities(True, True, True, 10, True),
    "H619D": create_with_capabilities(True, True, True, 10, True),
    "H619E": create_with_capabilities(True, True, True, 10, True),
    "H619Z": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "romantic",
            "twinkle",
            "candlelight",
            "energetic",
            "breathe",
            "rainbow",
        ),
    ),
    "H61A0": BASIC_CAPABILITIES,
    "H61A1": BASIC_CAPABILITIES,
    "H61A2": BASIC_CAPABILITIES,
    "H61A3": BASIC_CAPABILITIES,
    "H61A5": BASIC_CAPABILITIES,
    "H61A8": BASIC_CAPABILITIES,
    "H61A9": BASIC_CAPABILITIES,
    "H61B1": BASIC_CAPABILITIES,
    "H61B2": BASIC_CAPABILITIES,
    "H61B3": create_with_capabilities(
        True, True, True, 15, True, temperature_range=(2000, 7200)
    ),  # Issue #107 - range found by UDP testing
    "H61B5": BASIC_CAPABILITIES,
    "H61B6": create_with_capabilities(True, True, True, 0, True),
    "H61B8": create_with_capabilities(
        True, True, True, 15, builtin_scenes("snowflake", "rainbow")
    ),
    "H61B9": create_with_capabilities(
        True, True, True, 0, builtin_scenes("snowflake", "rainbow")
    ),
    "H61BA": BASIC_CAPABILITIES,
    "H61BC": BASIC_CAPABILITIES,
    "H61BE": BASIC_CAPABILITIES,
    "H61C2": BASIC_CAPABILITIES,
    "H61C3": BASIC_CAPABILITIES,
    "H61C5": BASIC_CAPABILITIES,
    "H61D3": create_with_capabilities(
        True,
        True,
        True,
        15,
        builtin_scenes("movie", "romantic", "snowflake", "rainbow"),
    ),
    "H61D4": create_with_capabilities(
        True, True, True, 0, builtin_scenes("movie", "romantic", "snowflake", "rainbow")
    ),  # Issues #146, #276, #330
    "H61D5": create_with_capabilities(
        True, True, True, 0, builtin_scenes("movie", "romantic", "snowflake", "rainbow")
    ),
    "H61D6": create_with_capabilities(
        True, True, True, 0, builtin_scenes("movie", "romantic", "snowflake", "rainbow")
    ),
    "H61E0": BASIC_CAPABILITIES,
    "H61E1": BASIC_CAPABILITIES,
    "H61E5": create_with_capabilities(
        True,
        True,
        True,
        12,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "romantic",
            "twinkle",
            "candlelight",
            "snowflake",
            "energetic",
            "breathe",
            "crossing",
            "rainbow",
        ),
    ),
    "H61E6": create_with_capabilities(
        True,
        True,
        True,
        15,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "romantic",
            "twinkle",
            "candlelight",
            "snowflake",
            "energetic",
            "breathe",
            "crossing",
            "rainbow",
        ),
    ),
    "H61F2": create_with_capabilities(
        True, True, True, 4, builtin_scenes("snowflake", "rainbow")
    ),
    "H61F5": create_with_capabilities(
        True, True, True, 10, builtin_scenes("snowflake", "rainbow")
    ),
    "H61F6": create_with_capabilities(
        True, True, True, 15, builtin_scenes("snowflake", "rainbow")
    ),
    "H6609": create_with_capabilities(True, True, True, 18, True),
    "H6630": BASIC_CAPABILITIES_NO_SCENES,
    "H6631": BASIC_CAPABILITIES_NO_SCENES,
    "H6640": create_with_capabilities(True, True, True, 14, True),
    "H6641": create_with_capabilities(True, True, True, 14, True),
    "H6671": create_with_capabilities(True, True, True, 14, True),
    "H6672": BASIC_CAPABILITIES,
    "H6800": BASIC_CAPABILITIES_NO_SCENES,
    "H6810": BASIC_CAPABILITIES_NO_SCENES,
    "H6811": BASIC_CAPABILITIES_NO_SCENES,
    "H6840": BASIC_CAPABILITIES_NO_SCENES,
    "H6841": BASIC_CAPABILITIES_NO_SCENES,
    "H6860": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes("sunrise", "sunset", "movie", "romantic", "rainbow"),
    ),
    "H6861": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes("sunrise", "sunset", "movie", "romantic", "rainbow"),
    ),
    "H6870": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "romantic",
            "twinkle",
            "candlelight",
            "energetic",
            "breathe",
            "crossing",
            "rainbow",
        ),
    ),
    "H6871": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "romantic",
            "twinkle",
            "candlelight",
            "energetic",
            "breathe",
            "crossing",
            "rainbow",
        ),
    ),
    "H7012": create_with_capabilities(False, False, True, 0, False),
    "H7013": create_with_capabilities(False, False, True, 0, False),
    "H7020": BASIC_CAPABILITIES_NO_SCENES,
    "H7021": BASIC_CAPABILITIES_NO_SCENES,
    "H7025": create_with_capabilities(
        True, False, True, 15, builtin_scenes("sunrise", "sunset", "rainbow")
    ),
    "H7026": create_with_capabilities(
        True, False, True, 15, builtin_scenes("sunrise", "sunset", "rainbow")
    ),
    "H7027": create_with_capabilities(
        True, True, True, 0, builtin_scenes("sunrise", "sunset", "rainbow")
    ),
    "H7028": BASIC_CAPABILITIES_NO_SCENES,
    "H702A": create_with_capabilities(
        True, True, True, 15, builtin_scenes("sunrise", "sunset", "rainbow")
    ),  # Issue #245 - Outdoor S14 Bulb String Lights 2
    "H702B": create_with_capabilities(
        True, True, True, 0, builtin_scenes("sunrise", "sunset", "rainbow")
    ),
    "H702C": create_with_capabilities(
        True, True, True, 0, builtin_scenes("sunrise", "sunset", "rainbow")
    ),  # Issue #262 - segments TBD
    "H7030": BASIC_CAPABILITIES_NO_SCENES,
    "H7033": BASIC_CAPABILITIES_NO_SCENES,
    "H7037": BASIC_CAPABILITIES_NO_SCENES,
    "H7038": BASIC_CAPABILITIES_NO_SCENES,
    "H7039": create_with_capabilities(True, True, True, 15, False),
    "H703A": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes(
            "sunrise",
            "sunset",
            "romantic",
            "candlelight",
            "snowflake",
            "breathe",
            "rainbow",
        ),
    ),
    "H703B": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes(
            "sunrise",
            "sunset",
            "romantic",
            "candlelight",
            "snowflake",
            "breathe",
            "rainbow",
        ),
    ),
    "H7041": BASIC_CAPABILITIES_NO_SCENES,
    "H7042": BASIC_CAPABILITIES_NO_SCENES,
    "H7045": BASIC_CAPABILITIES_NO_SCENES,
    "H7046": BASIC_CAPABILITIES_NO_SCENES,
    "H7050": BASIC_CAPABILITIES_NO_SCENES,
    "H7051": BASIC_CAPABILITIES_NO_SCENES,
    "H7052": create_with_capabilities(
        True,
        True,
        True,
        15,
        builtin_scenes(
            "sunrise",
            "sunset",
            "romantic",
            "candlelight",
            "snowflake",
            "breathe",
            "rainbow",
        ),
    ),
    "H7053": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes(
            "sunrise",
            "sunset",
            "romantic",
            "candlelight",
            "snowflake",
            "breathe",
            "rainbow",
        ),
    ),
    "H7055": create_with_capabilities(True, True, True, 0, builtin_scenes("breathe")),
    "H7056": create_with_capabilities(True, True, True, 0, builtin_scenes("sunset")),
    "H7057": create_with_capabilities(
        True, True, True, 0, builtin_scenes("sunrise", "sunset", "rainbow")
    ),
    "H7058": create_with_capabilities(
        True, True, True, 0, builtin_scenes("sunrise", "sunset", "rainbow")
    ),
    "H705A": create_with_capabilities(True, True, True, 0, builtin_scenes("rainbow")),
    "H705B": create_with_capabilities(True, True, True, 0, builtin_scenes("rainbow")),
    "H705C": create_with_capabilities(True, True, True, 0, builtin_scenes("rainbow")),
    "H705D": create_with_capabilities(True, True, True, 9, builtin_scenes("rainbow")),
    "H705E": create_with_capabilities(True, True, True, 15, builtin_scenes("rainbow")),
    "H705F": create_with_capabilities(True, True, True, 15, builtin_scenes("rainbow")),
    "H7060": BASIC_CAPABILITIES_NO_SCENES,
    "H7061": BASIC_CAPABILITIES_NO_SCENES,
    "H7062": create_with_capabilities(
        True, True, True, 0, builtin_scenes("sunrise", "sunset")
    ),
    "H7063": create_with_capabilities(
        True, True, True, 0, builtin_scenes("sunrise", "sunset", "rainbow")
    ),
    "H7065": BASIC_CAPABILITIES_NO_SCENES,
    "H7066": BASIC_CAPABILITIES_NO_SCENES,
    "H7067": create_with_capabilities(
        True, True, True, 0, builtin_scenes("sunrise", "sunset", "rainbow")
    ),
    "H706A": create_with_capabilities(True, True, True, 0, builtin_scenes("rainbow")),
    "H706B": create_with_capabilities(True, True, True, 0, builtin_scenes("rainbow")),
    "H706C": create_with_capabilities(True, True, True, 0, builtin_scenes("rainbow")),
    "H7070": BASIC_CAPABILITIES_NO_SCENES,
    "H7071": BASIC_CAPABILITIES_NO_SCENES,
    "H7072": create_with_capabilities(
        True, True, True, 0, builtin_scenes("sunset", "rainbow")
    ),
    "H7073": BASIC_CAPABILITIES_NO_SCENES,
    "H7075": create_with_capabilities(True, True, True, 0, builtin_scenes("rainbow")),
    "H7076": create_with_capabilities(True, True, True, 15, builtin_scenes("rainbow")),
    "H7078": create_with_capabilities(True, True, True, 4, builtin_scenes("rainbow")),
    "H707A": create_with_capabilities(
        True, True, True, 0, builtin_scenes("sunrise", "sunset", "rainbow")
    ),
    "H707B": create_with_capabilities(
        True, True, True, 0, builtin_scenes("sunrise", "sunset", "rainbow")
    ),
    "H707C": create_with_capabilities(
        True, True, True, 0, builtin_scenes("sunrise", "sunset", "rainbow")
    ),
    "H7086": create_with_capabilities(
        True, True, True, 0, builtin_scenes("sunrise", "sunset", "rainbow")
    ),
    "H7087": create_with_capabilities(True, True, True, 0, builtin_scenes("rainbow")),
    "H7093": create_with_capabilities(
        True, True, True, 2, builtin_scenes("sunrise", "sunset", "rainbow")
    ),
    "H7094": create_with_capabilities(
        True, True, True, 0, builtin_scenes("sunrise", "sunset", "rainbow")
    ),
    "H70A1": create_with_capabilities(True, True, True, 15, True),
    "H70A2": create_with_capabilities(True, True, True, 20, True),
    "H70A3": create_with_capabilities(True, True, True, 15, True),
    "H70B1": BASIC_CAPABILITIES_NO_SCENES,
    "H70B3": BASIC_CAPABILITIES_NO_SCENES,
    "H70B5": create_with_capabilities(True, True, True, 3, False),
    "H70B6": BASIC_CAPABILITIES_NO_SCENES,
    "H70B8": BASIC_CAPABILITIES_NO_SCENES,
    "H70BC": BASIC_CAPABILITIES_NO_SCENES,
    "H70C1": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "romantic",
            "twinkle",
            "candlelight",
            "snowflake",
            "energetic",
            "breathe",
            "crossing",
            "rainbow",
        ),
    ),
    "H70C2": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "romantic",
            "twinkle",
            "candlelight",
            "snowflake",
            "energetic",
            "breathe",
            "crossing",
            "rainbow",
        ),
    ),
    "H70C4": create_with_capabilities(
        True,
        True,
        True,
        10,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "romantic",
            "twinkle",
            "candlelight",
            "energetic",
            "breathe",
            "crossing",
            "rainbow",
        ),
    ),
    "H70C5": create_with_capabilities(
        True,
        True,
        True,
        10,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "romantic",
            "twinkle",
            "candlelight",
            "energetic",
            "breathe",
            "crossing",
            "rainbow",
        ),
    ),
    "H70C7": create_with_capabilities(
        True,
        True,
        True,
        10,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "romantic",
            "twinkle",
            "candlelight",
            "energetic",
            "breathe",
            "crossing",
            "rainbow",
        ),
    ),
    "H70C9": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "romantic",
            "twinkle",
            "candlelight",
            "energetic",
            "breathe",
            "crossing",
            "rainbow",
        ),
    ),
    "H70D1": create_with_capabilities(True, True, True, 10, builtin_scenes("rainbow")),
    "H70D2": create_with_capabilities(True, True, True, 10, builtin_scenes("rainbow")),
    "H70D3": create_with_capabilities(True, True, True, 0, builtin_scenes("rainbow")),
    "H8015": BASIC_CAPABILITIES,
    "H801A": BASIC_CAPABILITIES_NO_SCENES,
    "H801B": create_with_capabilities(True, True, True, 0, builtin_scenes("rainbow")),
    "H801D": BASIC_CAPABILITIES_NO_SCENES,
    "H8022": BASIC_CAPABILITIES_NO_SCENES,
    "H8025": create_with_capabilities(
        True, True, True, 0, builtin_scenes("sunrise", "sunset", "rainbow")
    ),
    "H8026": create_with_capabilities(
        True, True, True, 0, builtin_scenes("sunrise", "sunset", "rainbow")
    ),
    "H802A": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "romantic",
            "twinkle",
            "candlelight",
            "energetic",
            "breathe",
            "rainbow",
        ),
    ),
    "H8048": create_with_capabilities(
        True, True, True, 0, builtin_scenes("snowflake", "rainbow")
    ),
    "H8057": create_with_capabilities(
        True, True, True, 0, builtin_scenes("sunrise", "sunset", "rainbow")
    ),
    "H805A": create_with_capabilities(True, True, True, 0, builtin_scenes("rainbow")),
    "H805B": create_with_capabilities(True, True, True, 0, builtin_scenes("rainbow")),
    "H805C": create_with_capabilities(True, True, True, 9, builtin_scenes("rainbow")),
    "H8066": create_with_capabilities(
        True, True, True, 0, builtin_scenes("sunrise", "sunset", "rainbow")
    ),
    "H8069": BASIC_CAPABILITIES_NO_SCENES,
    "H8072": create_with_capabilities(
        True,
        True,
        True,
        8,
        builtin_scenes("romantic", "energetic", "breathe", "crossing", "rainbow"),
    ),
    "H8076": create_with_capabilities(True, True, True, 0, builtin_scenes("rainbow")),
    "H8076A": BASIC_CAPABILITIES,
    "H807C": create_with_capabilities(
        True, True, True, 0, builtin_scenes("crossing", "rainbow")
    ),
    "H808A": create_with_capabilities(
        True,
        True,
        True,
        5,
        builtin_scenes("sunrise", "sunset", "movie", "romantic", "rainbow"),
    ),
    "H80A1": create_with_capabilities(
        True, True, True, 14, builtin_scenes("candlelight")
    ),
    "H80A4": BASIC_CAPABILITIES_NO_SCENES,
    "H80C4": create_with_capabilities(
        True,
        True,
        True,
        0,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "romantic",
            "twinkle",
            "candlelight",
            "energetic",
            "breathe",
            "crossing",
            "rainbow",
        ),
    ),
    "H80C5": create_with_capabilities(
        True,
        True,
        True,
        10,
        builtin_scenes(
            "sunrise",
            "sunset",
            "movie",
            "romantic",
            "twinkle",
            "candlelight",
            "energetic",
            "breathe",
            "crossing",
            "rainbow",
        ),
    ),
    "H80D1": create_with_capabilities(
        True, True, True, 0, builtin_scenes("rainbow")
    ),  # Issue #261 - Icicle lights
    "H8630": BASIC_CAPABILITIES_NO_SCENES,
    "H8811": BASIC_CAPABILITIES_NO_SCENES,
    "H8840": BASIC_CAPABILITIES_NO_SCENES,
    "H8841": BASIC_CAPABILITIES_NO_SCENES,
}
