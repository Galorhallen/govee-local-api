import base64
from importlib.resources import files
import json
import re

import pytest

from govee_local_api.light_capabilities import (
    BASIC_CAPABILITIES,
    DEFAULT_TEMPERATURE_RANGE,
    GOVEE_LIGHT_CAPABILITIES,
    DATA_DIR,
    MODEL_SCENES_FILE,
    GoveeLightCapabilities,
    GoveeLightFeatures,
    SCENE_CODES,
    GoveeTemperatureRange,
    builtin_scenes,
    create_with_capabilities,
)
from govee_local_api.message import SceneCodeMessage


def test_default_temperature_range():
    assert DEFAULT_TEMPERATURE_RANGE == (2000, 9000)
    assert BASIC_CAPABILITIES.temperature_range == DEFAULT_TEMPERATURE_RANGE


def test_every_registered_model_has_a_range():
    for capabilities in GOVEE_LIGHT_CAPABILITIES.values():
        min_kelvin, max_kelvin = capabilities.temperature_range
        assert isinstance(capabilities.temperature_range, GoveeTemperatureRange)
        assert 0 < min_kelvin < max_kelvin


@pytest.mark.parametrize(
    "sku,expected_range",
    [
        ("H6076", (2700, 6500)),
        ("H60A1", (2200, 6500)),
        ("H60A6", (2700, 6500)),
        ("H612F", (2800, 9000)),
        ("H61B3", (2000, 7200)),
        ("H6006", DEFAULT_TEMPERATURE_RANGE),
    ],
)
def test_registered_models_with_a_reported_range(sku, expected_range):
    assert GOVEE_LIGHT_CAPABILITIES[sku].temperature_range == expected_range


def test_custom_temperature_range():
    capabilities = create_with_capabilities(
        True, True, True, 0, True, temperature_range=(2700, 6500)
    )
    assert capabilities.temperature_range == GoveeTemperatureRange(2700, 6500)
    assert capabilities.features & GoveeLightFeatures.COLOR_KELVIN_TEMPERATURE


def test_custom_temperature_range_on_constructor():
    capabilities = GoveeLightCapabilities(
        GoveeLightFeatures.COLOR_KELVIN_TEMPERATURE,
        temperature_range=(3000, 6000),
    )
    assert capabilities.temperature_range == (3000, 6000)


@pytest.mark.parametrize("bad_range", [(6500, 2700), (2700, 2700), (0, 6500), (-1, 10)])
def test_invalid_temperature_range(bad_range):
    with pytest.raises(ValueError):
        create_with_capabilities(True, True, True, 0, True, temperature_range=bad_range)


def test_repr_and_str_include_the_range():
    capabilities = create_with_capabilities(
        True, True, True, 0, False, temperature_range=(2700, 6500)
    )
    assert "temperature_range" in repr(capabilities)
    assert "(2700, 6500)" in str(capabilities)


def test_scenes_true_advertises_the_full_builtin_set():
    capabilities = create_with_capabilities(True, True, True, 0, True)
    assert capabilities.features & GoveeLightFeatures.SCENES
    assert capabilities.scenes == SCENE_CODES
    assert capabilities.scenes is not SCENE_CODES


def test_scenes_dict_advertises_only_that_subset():
    capabilities = create_with_capabilities(
        True, True, True, 0, builtin_scenes("snowflake", "breathe")
    )
    assert capabilities.features & GoveeLightFeatures.SCENES
    assert capabilities.scenes == {"snowflake": b"\x0f", "breathe": b"\x0a"}
    assert capabilities.available_scenes == ["snowflake", "breathe"]


def test_empty_scenes_dict_means_no_scene_support():
    capabilities = create_with_capabilities(True, True, True, 0, {})
    assert not capabilities.features & GoveeLightFeatures.SCENES
    assert capabilities.scenes == {}
    assert capabilities.available_scenes == []


def test_builtin_scenes_rejects_unknown_names():
    with pytest.raises(ValueError):
        builtin_scenes("snowflake", "aurora")


def _model_scenes_file():
    return json.loads(
        files("govee_local_api")
        .joinpath(DATA_DIR, MODEL_SCENES_FILE)
        .read_text("utf-8")
    )


def _expected_code(entry):
    # A bare code is a firmware scene (one byte); [code, blob id] is a
    # parameter scene (16-bit little-endian code).
    if isinstance(entry, int):
        return bytes([entry])
    return entry[0].to_bytes(2, "little")


def test_registry_scenes_come_from_the_model_scenes_file():
    data = _model_scenes_file()
    for sku, capabilities in GOVEE_LIGHT_CAPABILITIES.items():
        set_id = data["models"].get(sku)
        entries = data["sets"][set_id] if set_id else {}
        expected = {name: _expected_code(entry) for name, entry in entries.items()}
        expected_params = {
            name: base64.b64decode(data["blobs"][entry[1]])
            for name, entry in entries.items()
            if not isinstance(entry, int)
        }
        assert capabilities.scenes == expected, sku
        assert capabilities.scene_params == expected_params, sku


def test_scene_feature_flag_matches_the_scene_set():
    for sku, capabilities in GOVEE_LIGHT_CAPABILITIES.items():
        has_flag = bool(capabilities.features & GoveeLightFeatures.SCENES)
        assert has_flag == bool(capabilities.scenes), sku


def test_model_scenes_file_is_consistent():
    data = _model_scenes_file()
    # null: the model was checked and has no scenes this package can play.
    assert set(data["models"].values()) - {None} == set(data["sets"])
    used_blobs = set()
    for set_id, scenes in data["sets"].items():
        assert scenes, set_id
        for name, entry in scenes.items():
            # Keys are valid Home Assistant translation keys ([a-z0-9-_]+).
            assert re.fullmatch(r"[a-z0-9_-]+", name), (set_id, name)
            if isinstance(entry, int):
                # SceneMessages carries one code byte.
                assert 0 < entry <= 0xFF, (set_id, name)
            else:
                code, blob_id = entry
                assert 0 < code <= 0xFFFF, (set_id, name)
                assert blob_id in data["blobs"], (set_id, name)
                used_blobs.add(blob_id)
    assert used_blobs == set(data["blobs"])


def test_every_packaged_blob_decodes_and_fits_the_encoder():
    for blob_id, encoded in _model_scenes_file()["blobs"].items():
        blob = base64.b64decode(encoded, validate=True)
        assert blob, blob_id
        SceneCodeMessage(1, blob)  # raises if the blob needs too many frames


def test_h805a_lists_its_parameter_scenes():
    capabilities = GOVEE_LIGHT_CAPABILITIES["H805A"]
    assert capabilities.scenes["christmas"] == (11271).to_bytes(2, "little")
    assert capabilities.scenes["candy_cane"] == (12368).to_bytes(2, "little")
    assert capabilities.scene_params["candy_cane"]
    # Two different scenes are named "Halloween" on this model.
    assert capabilities.scenes["halloween"] == (11275).to_bytes(2, "little")
    assert capabilities.scenes["halloween_2"] == (12492).to_bytes(2, "little")


def test_h805a_firmware_scenes_are_unchanged():
    capabilities = GOVEE_LIGHT_CAPABILITIES["H805A"]
    firmware = {
        name: code
        for name, code in capabilities.scenes.items()
        if name not in capabilities.scene_params
    }
    assert firmware == {
        "rainbow": b"\x16",
        "white_light": b"\x28",
        "fluctuate": b"\x4c",
        "stacking": b"\x29",
        "gradient": b"\x03",
    }


def test_scene_params_default_to_empty():
    capabilities = create_with_capabilities(True, True, True, 0, True)
    assert capabilities.scene_params == {}


def test_scene_params_are_dropped_without_the_scene_feature():
    capabilities = GoveeLightCapabilities(
        GoveeLightFeatures.COLOR_RGB,
        scenes={"sled": b"\x0a\x2c"},
        scene_params={"sled": b"\x01"},
    )
    assert capabilities.scene_params == {}


def test_scene_params_without_a_matching_scene_are_rejected():
    with pytest.raises(ValueError):
        GoveeLightCapabilities(
            GoveeLightFeatures.SCENES,
            scenes={"rainbow": b"\x16"},
            scene_params={"sled": b"\x01"},
        )


def test_model_scenes_file_covers_exactly_the_registry():
    # Fails when a model is added or removed without running
    # scripts/generate_model_scenes.py.
    assert set(_model_scenes_file()["models"]) == set(GOVEE_LIGHT_CAPABILITIES)


def test_models_with_the_same_scene_set_share_it():
    data = _model_scenes_file()
    h1232, h1250 = (GOVEE_LIGHT_CAPABILITIES[sku] for sku in ("H1232", "H1250"))
    assert data["models"]["H1232"] == data["models"]["H1250"]
    assert h1232 is h1250
    assert h1232.scenes["white_light"] == b"\x63"
    assert h1232.scenes["illumination"] == b"\x19"


def test_h619a_firmware_variant_keeps_the_bare_key():
    capabilities = GOVEE_LIGHT_CAPABILITIES["H619A"]
    scenes = capabilities.scenes
    # Variant A plays from its code alone and keeps the key it always had.
    assert scenes["snow_flake"] == b"\x0f"
    assert scenes["energetic"] == b"\x10"
    assert scenes["rainbow"] == b"\x16"
    assert not {"snow_flake_a", "energetic_a", "rainbow_a"} & set(scenes)
    # Variant B needs a parameter blob and is listed under its own key.
    assert scenes["snow_flake_b"] == (2154).to_bytes(2, "little")
    assert "snow_flake_b" in capabilities.scene_params
    assert "snow_flake" not in capabilities.scene_params


def test_govee_variant_letter_is_dropped_when_its_sibling_is_not_kept():
    # H70B8 lists "Aurora" (blob only) and "Aurora B" (firmware): only the
    # firmware twin is kept, so its letter tells nothing apart.
    scenes = GOVEE_LIGHT_CAPABILITIES["H70B8"].scenes
    assert scenes["aurora"] == b"\x6b"
    assert scenes["rainbow_heart"] == b"\x74"
    assert not {"aurora_b", "rainbow_b", "rainbow_heart_b"} & set(scenes)


def test_govee_variant_letter_stays_next_to_its_kept_sibling():
    # "Shiny" and "Shiny B" are both firmware scenes on H6870.
    scenes = GOVEE_LIGHT_CAPABILITIES["H6870"].scenes
    assert "shiny" in scenes
    assert "shiny_b" in scenes
    assert scenes["shiny"] != scenes["shiny_b"]


def test_no_model_lists_the_same_scene_code_twice():
    # Two names for one code would mean a variant was split in two.
    for sku, capabilities in GOVEE_LIGHT_CAPABILITIES.items():
        codes = [
            (code, capabilities.scene_params.get(name))
            for name, code in capabilities.scenes.items()
        ]
        assert len(codes) == len(set(codes)), sku


def test_h60a0_uses_its_own_codes_for_sunrise_and_sunset():
    # Differs from the generic SCENE_CODES (sunrise 0x00, sunset 0x01).
    scenes = GOVEE_LIGHT_CAPABILITIES["H60A0"].scenes
    assert scenes["sunrise"] == b"\x01"
    assert scenes["sunset"] == b"\x02"


def test_model_unknown_to_the_scene_library_has_no_scenes():
    capabilities = GOVEE_LIGHT_CAPABILITIES["H6076A"]
    assert capabilities.scenes == {}
    assert capabilities.features & GoveeLightFeatures.COLOR_RGB
