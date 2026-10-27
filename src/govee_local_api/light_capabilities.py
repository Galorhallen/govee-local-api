from enum import IntFlag
from importlib.resources import files
import json
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
    scenes: bool | dict[str, bytes] = False,
    temperature_range: tuple[int, int] | None = None,
) -> GoveeLightCapabilities:
    """Build capabilities for a model.

    ``scenes`` is either a bool (``True`` advertises the full generic
    SCENE_CODES set) or an explicit ``{name: code}`` dict for models that
    only honour a subset; an empty dict means no scene support. Entries in
    GOVEE_LIGHT_CAPABILITIES leave it out: their scenes come from
    model_scenes.json.
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


# Generated data files live in the package's data/ folder, apart from code.
DATA_DIR = "data"
MODEL_SCENES_FILE = "model_scenes.json"


def _load_model_scenes() -> dict[str, dict[str, bytes]]:
    """Per-model firmware scenes from the packaged data/model_scenes.json.

    The file is generated by scripts/generate_model_scenes.py from Govee's
    per-model scene library (app2.govee.com light-effect-libraries, see
    issue #370) and stores each distinct scene set once:
    ``{"sets": {id: {name: code}}, "models": {sku: id}}``; a model checked
    and found to have no firmware scenes maps to ``null``. Only firmware
    scenes are listed (sceneType 0, no parameter blob), so every code is a
    single byte SceneMessages can play.
    """
    data = json.loads(
        files("govee_local_api")
        .joinpath(DATA_DIR, MODEL_SCENES_FILE)
        .read_text("utf-8")
    )
    scene_sets = {
        set_id: {name: bytes([code]) for name, code in scenes.items()}
        for set_id, scenes in data["sets"].items()
    }
    return {
        sku: scene_sets[set_id]
        for sku, set_id in data["models"].items()
        if set_id is not None
    }


def _with_model_scenes(
    registry: dict[str, GoveeLightCapabilities],
) -> dict[str, GoveeLightCapabilities]:
    """Replace every entry's scenes with its model's set from
    model_scenes.json; models missing from it get no scenes.

    Models sharing both their base capabilities and their scene set share one
    capabilities object, like entries already share BASIC_CAPABILITIES.
    """
    model_scenes = _load_model_scenes()
    no_scenes: dict[str, bytes] = {}
    # Keyed on object identity: scene sets are shared dicts from the file.
    shared: dict[tuple[int, int], GoveeLightCapabilities] = {}
    result: dict[str, GoveeLightCapabilities] = {}
    for sku, base in registry.items():
        scenes = model_scenes.get(sku, no_scenes)
        key = (id(base), id(scenes))
        if key not in shared:
            features = base.features & ~GoveeLightFeatures.SCENES
            if scenes:
                features |= GoveeLightFeatures.SCENES
            shared[key] = GoveeLightCapabilities(
                features, base.segments, scenes, base.temperature_range
            )
        result[sku] = shared[key]
    return result


# Features, segments and temperature ranges per model. Scenes are not set
# here: _with_model_scenes() below replaces them with the model's firmware
# scenes from model_scenes.json (regenerate it with
# scripts/generate_model_scenes.py).
GOVEE_LIGHT_CAPABILITIES: dict[str, GoveeLightCapabilities] = {
    # Models with common features
    "H1232": BASIC_CAPABILITIES,
    "H1250": BASIC_CAPABILITIES,
    "H1270": BASIC_CAPABILITIES,
    "H1310": BASIC_CAPABILITIES,
    "H1401": BASIC_CAPABILITIES,
    "H14A1": BASIC_CAPABILITIES,
    "H14C0": BASIC_CAPABILITIES,
    "H14C1": BASIC_CAPABILITIES,
    "H1630": BASIC_CAPABILITIES,
    "H16B0": BASIC_CAPABILITIES,
    "H16C0": create_with_capabilities(True, True, True, 7),
    "H1A43": BASIC_CAPABILITIES,
    "H1A45": BASIC_CAPABILITIES,
    "H1AB1": create_with_capabilities(
        True, True, True, 15
    ),  # HA core #187226 - COB Strip Light 2, new SKU of H6008
    "H2A40": BASIC_CAPABILITIES,
    "H2A41": BASIC_CAPABILITIES,
    "H3200": BASIC_CAPABILITIES,
    "H3500": BASIC_CAPABILITIES,
    "H3501": BASIC_CAPABILITIES,
    "H3510": BASIC_CAPABILITIES,
    "H3511": BASIC_CAPABILITIES,
    "H3751": BASIC_CAPABILITIES,
    "H6004": BASIC_CAPABILITIES,
    "H6006": BASIC_CAPABILITIES,  # Issue #133 - temp confirmed via Cloud API (2000-9000K)
    "H6008": BASIC_CAPABILITIES,
    "H600A": BASIC_CAPABILITIES,
    "H600D": BASIC_CAPABILITIES,
    "H601A": BASIC_CAPABILITIES,  # Issue #129
    "H6020": BASIC_CAPABILITIES,
    "H6022": BASIC_CAPABILITIES,
    "H6038": BASIC_CAPABILITIES,
    "H6039": create_with_capabilities(True, True, True, 12),
    "H6042": create_with_capabilities(True, True, True, 5),
    "H6043": create_with_capabilities(
        True, False, True, 10
    ),  # Issue #254 - TV Light Bars 2, no temp
    "H6046": create_with_capabilities(True, True, True, 10),
    "H6047": create_with_capabilities(True, True, True, 10),
    "H6048": create_with_capabilities(True, True, True, 15),
    "H6051": BASIC_CAPABILITIES,
    "H6052": BASIC_CAPABILITIES,
    "H6056": BASIC_CAPABILITIES,
    "H6059": BASIC_CAPABILITIES,
    "H605D": BASIC_CAPABILITIES,
    "H6061": BASIC_CAPABILITIES,
    "H6062": BASIC_CAPABILITIES,
    "H6063": BASIC_CAPABILITIES,
    "H6065": BASIC_CAPABILITIES,
    "H6066": BASIC_CAPABILITIES,
    "H6069": create_with_capabilities(True, False, True, 15),
    "H6067": BASIC_CAPABILITIES,
    "H606A": BASIC_CAPABILITIES,
    "H6072": create_with_capabilities(True, True, True, 8),
    "H6073": BASIC_CAPABILITIES,
    "H6076": create_with_capabilities(
        True, True, True, 7, temperature_range=(2700, 6500)
    ),  # Issue #271 - range confirmed in the Govee app
    "H6076A": BASIC_CAPABILITIES,
    "H6078": BASIC_CAPABILITIES,
    "H6079": BASIC_CAPABILITIES,
    "H607C": create_with_capabilities(True, True, True, 13),
    "H6087": create_with_capabilities(True, True, True, 12),
    "H6088": create_with_capabilities(True, True, True, 6),
    "H608A": BASIC_CAPABILITIES,
    "H608B": create_with_capabilities(True, True, True, 15),
    "H608C": BASIC_CAPABILITIES,
    "H608D": BASIC_CAPABILITIES,
    "H6093": create_with_capabilities(False, True, True, 0),
    "H6094": BASIC_CAPABILITIES,
    "H6095": BASIC_CAPABILITIES,
    "H609D": BASIC_CAPABILITIES,
    "H60A0": BASIC_CAPABILITIES,
    "H60A1": create_with_capabilities(
        True, True, True, 13, temperature_range=(2200, 6500)
    ),  # Issue #39 - range from the Govee Cloud API
    "H60A4": create_with_capabilities(True, True, True, 11),
    "H60A6": create_with_capabilities(
        True, True, True, 0, temperature_range=(2700, 6500)
    ),  # H60A6 firmware 1.00.41: LAN requests clamp to 2700-6500K
    "H60B0": BASIC_CAPABILITIES,  # Issue #252 - segments TBD
    "H60B1": create_with_capabilities(True, True, True, 3),
    "H60B2": create_with_capabilities(True, True, True, 3),
    "H60C1": create_with_capabilities(True, True, True, 3),  # Issue #232
    "H610A": BASIC_CAPABILITIES,
    "H610B": BASIC_CAPABILITIES,
    "H610E": create_with_capabilities(True, True, True, 7),
    "H610F": create_with_capabilities(True, True, True, 7),
    "H6110": BASIC_CAPABILITIES,
    "H6117": BASIC_CAPABILITIES,
    "H612A": BASIC_CAPABILITIES,
    "H612B": BASIC_CAPABILITIES,
    "H612C": create_with_capabilities(True, True, True, 10),
    "H612D": create_with_capabilities(True, True, True, 20),
    "H612F": create_with_capabilities(
        True, True, True, 5, temperature_range=(2800, 9000)
    ),  # HA core #182244 - values below 2800K are ignored by the device
    "H6141": BASIC_CAPABILITIES,
    "H6143": BASIC_CAPABILITIES,
    "H6144": BASIC_CAPABILITIES,
    "H6159": BASIC_CAPABILITIES,
    "H615A": BASIC_CAPABILITIES,
    "H615B": BASIC_CAPABILITIES,
    "H615C": BASIC_CAPABILITIES,
    "H615D": BASIC_CAPABILITIES,
    "H615E": BASIC_CAPABILITIES,
    "H6163": BASIC_CAPABILITIES,
    "H6167": create_with_capabilities(True, True, True, 12),
    "H6168": BASIC_CAPABILITIES,
    "H6169": create_with_capabilities(True, True, True, 15),
    "H616C": BASIC_CAPABILITIES,
    "H616D": create_with_capabilities(True, True, True, 15),
    "H616E": BASIC_CAPABILITIES,
    "H6172": BASIC_CAPABILITIES,
    "H6173": BASIC_CAPABILITIES,
    "H6175": BASIC_CAPABILITIES,
    "H6176": BASIC_CAPABILITIES,
    "H617E": BASIC_CAPABILITIES,
    "H6182": BASIC_CAPABILITIES,
    "H618A": create_with_capabilities(True, True, True, 15),
    "H618C": create_with_capabilities(True, True, True, 15),
    "H618E": create_with_capabilities(True, True, True, 15),
    "H618F": create_with_capabilities(True, True, True, 15),
    "H618G": BASIC_CAPABILITIES,
    "H619A": create_with_capabilities(True, True, True, 10),
    "H619B": create_with_capabilities(True, True, True, 10),
    "H619C": create_with_capabilities(True, True, True, 10),
    "H619D": create_with_capabilities(True, True, True, 10),
    "H619E": create_with_capabilities(True, True, True, 10),
    "H619Z": BASIC_CAPABILITIES,
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
        True, True, True, 15, temperature_range=(2000, 7200)
    ),  # Issue #107 - range found by UDP testing
    "H61B5": BASIC_CAPABILITIES,
    "H61B6": BASIC_CAPABILITIES,
    "H61B8": create_with_capabilities(True, True, True, 15),
    "H61B9": BASIC_CAPABILITIES,
    "H61BA": BASIC_CAPABILITIES,
    "H61BC": BASIC_CAPABILITIES,
    "H61BE": BASIC_CAPABILITIES,
    "H61C2": BASIC_CAPABILITIES,
    "H61C3": BASIC_CAPABILITIES,
    "H61C5": BASIC_CAPABILITIES,
    "H61D3": create_with_capabilities(True, True, True, 15),
    "H61D4": create_with_capabilities(True, True, True, 0),  # Issues #146, #276, #330
    "H61D5": BASIC_CAPABILITIES,
    "H61D6": BASIC_CAPABILITIES,
    "H61E0": BASIC_CAPABILITIES,
    "H61E1": BASIC_CAPABILITIES,
    "H61E5": create_with_capabilities(True, True, True, 12),
    "H61E6": create_with_capabilities(True, True, True, 15),
    "H61F2": create_with_capabilities(True, True, True, 4),
    "H61F5": create_with_capabilities(True, True, True, 10),
    "H61F6": create_with_capabilities(True, True, True, 15),
    "H6609": create_with_capabilities(True, True, True, 18),
    "H6630": BASIC_CAPABILITIES,
    "H6631": BASIC_CAPABILITIES,
    "H6640": create_with_capabilities(True, True, True, 14),
    "H6641": create_with_capabilities(True, True, True, 14),
    "H6671": create_with_capabilities(True, True, True, 14),
    "H6672": BASIC_CAPABILITIES,
    "H6800": BASIC_CAPABILITIES,
    "H6810": BASIC_CAPABILITIES,
    "H6811": BASIC_CAPABILITIES,
    "H6840": BASIC_CAPABILITIES,
    "H6841": BASIC_CAPABILITIES,
    "H6860": BASIC_CAPABILITIES,
    "H6861": BASIC_CAPABILITIES,
    "H6870": BASIC_CAPABILITIES,
    "H6871": BASIC_CAPABILITIES,
    "H7012": create_with_capabilities(False, False, True, 0),
    "H7013": create_with_capabilities(False, False, True, 0),
    "H7020": BASIC_CAPABILITIES,
    "H7021": BASIC_CAPABILITIES,
    "H7025": create_with_capabilities(True, False, True, 15),
    "H7026": create_with_capabilities(True, False, True, 15),
    "H7027": BASIC_CAPABILITIES,
    "H7028": BASIC_CAPABILITIES,
    "H702A": create_with_capabilities(
        True, True, True, 15
    ),  # Issue #245 - Outdoor S14 Bulb String Lights 2
    "H702B": BASIC_CAPABILITIES,
    "H702C": create_with_capabilities(True, True, True, 0),  # Issue #262 - segments TBD
    "H7030": BASIC_CAPABILITIES,
    "H7033": BASIC_CAPABILITIES,
    "H7037": BASIC_CAPABILITIES,
    "H7038": BASIC_CAPABILITIES,
    "H7039": create_with_capabilities(True, True, True, 15),
    "H703A": BASIC_CAPABILITIES,
    "H703B": BASIC_CAPABILITIES,
    "H7041": BASIC_CAPABILITIES,
    "H7042": BASIC_CAPABILITIES,
    "H7045": BASIC_CAPABILITIES,
    "H7046": BASIC_CAPABILITIES,
    "H7050": BASIC_CAPABILITIES,
    "H7051": BASIC_CAPABILITIES,
    "H7052": create_with_capabilities(True, True, True, 15),
    "H7053": BASIC_CAPABILITIES,
    "H7055": BASIC_CAPABILITIES,
    "H7056": BASIC_CAPABILITIES,
    "H7057": BASIC_CAPABILITIES,
    "H7058": BASIC_CAPABILITIES,
    "H705A": BASIC_CAPABILITIES,
    "H705B": BASIC_CAPABILITIES,
    "H705C": BASIC_CAPABILITIES,
    "H705D": create_with_capabilities(True, True, True, 9),
    "H705E": create_with_capabilities(True, True, True, 15),
    "H705F": create_with_capabilities(True, True, True, 15),
    "H7060": BASIC_CAPABILITIES,
    "H7061": BASIC_CAPABILITIES,
    "H7062": BASIC_CAPABILITIES,
    "H7063": BASIC_CAPABILITIES,
    "H7065": BASIC_CAPABILITIES,
    "H7066": BASIC_CAPABILITIES,
    "H7067": BASIC_CAPABILITIES,
    "H706A": BASIC_CAPABILITIES,
    "H706B": BASIC_CAPABILITIES,
    "H706C": BASIC_CAPABILITIES,
    "H7070": BASIC_CAPABILITIES,
    "H7071": BASIC_CAPABILITIES,
    "H7072": BASIC_CAPABILITIES,
    "H7073": BASIC_CAPABILITIES,
    "H7075": BASIC_CAPABILITIES,
    "H7076": create_with_capabilities(True, True, True, 15),
    "H7078": create_with_capabilities(True, True, True, 4),
    "H707A": BASIC_CAPABILITIES,
    "H707B": BASIC_CAPABILITIES,
    "H707C": BASIC_CAPABILITIES,
    "H7086": BASIC_CAPABILITIES,
    "H7087": BASIC_CAPABILITIES,
    "H7093": create_with_capabilities(True, True, True, 2),
    "H7094": BASIC_CAPABILITIES,
    "H70A1": create_with_capabilities(True, True, True, 15),
    "H70A2": create_with_capabilities(True, True, True, 20),
    "H70A3": create_with_capabilities(True, True, True, 15),
    "H70B1": BASIC_CAPABILITIES,
    "H70B3": BASIC_CAPABILITIES,
    "H70B5": create_with_capabilities(True, True, True, 3),
    "H70B6": BASIC_CAPABILITIES,
    "H70B8": BASIC_CAPABILITIES,
    "H70BC": BASIC_CAPABILITIES,
    "H70C1": BASIC_CAPABILITIES,
    "H70C2": BASIC_CAPABILITIES,
    "H70C4": create_with_capabilities(True, True, True, 10),
    "H70C5": create_with_capabilities(True, True, True, 10),
    "H70C7": create_with_capabilities(True, True, True, 10),
    "H70C9": BASIC_CAPABILITIES,
    "H70D1": create_with_capabilities(True, True, True, 10),
    "H70D2": create_with_capabilities(True, True, True, 10),
    "H70D3": BASIC_CAPABILITIES,
    "H8015": BASIC_CAPABILITIES,
    "H801A": BASIC_CAPABILITIES,
    "H801B": BASIC_CAPABILITIES,
    "H801D": BASIC_CAPABILITIES,
    "H8022": BASIC_CAPABILITIES,
    "H8025": BASIC_CAPABILITIES,
    "H8026": BASIC_CAPABILITIES,
    "H802A": BASIC_CAPABILITIES,
    "H8048": BASIC_CAPABILITIES,
    "H8057": BASIC_CAPABILITIES,
    "H805A": BASIC_CAPABILITIES,
    "H805B": BASIC_CAPABILITIES,
    "H805C": create_with_capabilities(True, True, True, 9),
    "H8066": BASIC_CAPABILITIES,
    "H8069": BASIC_CAPABILITIES,
    "H8072": create_with_capabilities(True, True, True, 8),
    "H8076": BASIC_CAPABILITIES,
    "H8076A": BASIC_CAPABILITIES,
    "H807C": BASIC_CAPABILITIES,
    "H808A": create_with_capabilities(True, True, True, 5),
    "H80A1": create_with_capabilities(True, True, True, 14),
    "H80A4": BASIC_CAPABILITIES,
    "H80C4": BASIC_CAPABILITIES,
    "H80C5": create_with_capabilities(True, True, True, 10),
    "H80D1": create_with_capabilities(
        True, True, True, 0
    ),  # Issue #261 - Icicle lights
    "H8630": BASIC_CAPABILITIES,
    "H8811": BASIC_CAPABILITIES,
    "H8840": BASIC_CAPABILITIES,
    "H8841": BASIC_CAPABILITIES,
}

GOVEE_LIGHT_CAPABILITIES = _with_model_scenes(GOVEE_LIGHT_CAPABILITIES)
