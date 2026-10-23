from importlib.resources import files
import json

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


def test_registry_scenes_come_from_the_model_scenes_file():
    data = _model_scenes_file()
    for sku, capabilities in GOVEE_LIGHT_CAPABILITIES.items():
        set_id = data["models"].get(sku)
        expected = (
            {name: bytes([code]) for name, code in data["sets"][set_id].items()}
            if set_id
            else {}
        )
        assert capabilities.scenes == expected, sku


def test_scene_feature_flag_matches_the_scene_set():
    for sku, capabilities in GOVEE_LIGHT_CAPABILITIES.items():
        has_flag = bool(capabilities.features & GoveeLightFeatures.SCENES)
        assert has_flag == bool(capabilities.scenes), sku


def test_model_scenes_file_is_consistent():
    data = _model_scenes_file()
    # null: the model was checked and has no firmware scenes.
    assert set(data["models"].values()) - {None} == set(data["sets"])
    for set_id, scenes in data["sets"].items():
        assert scenes, set_id
        for name, code in scenes.items():
            # SceneMessages carries one code byte; keys are lowercase names.
            assert 0 < code <= 0xFF, (set_id, name)
            assert name == name.lower(), (set_id, name)


def test_model_scenes_file_covers_exactly_the_registry():
    # Fails when a model is added or removed without running
    # scripts/generate_model_scenes.py.
    assert set(_model_scenes_file()["models"]) == set(GOVEE_LIGHT_CAPABILITIES)


def test_models_with_the_same_scene_set_share_it():
    data = _model_scenes_file()
    h1232, h1250 = (GOVEE_LIGHT_CAPABILITIES[sku] for sku in ("H1232", "H1250"))
    assert data["models"]["H1232"] == data["models"]["H1250"]
    assert h1232 is h1250
    assert h1232.scenes == {"white light": b"\x63", "illumination": b"\x19"}


def test_h619a_keeps_only_the_firmware_variant_of_multi_variant_scenes():
    scenes = GOVEE_LIGHT_CAPABILITIES["H619A"].scenes
    # Variant A plays from its code alone; variant B needs a parameter blob
    # and is dropped, so the variant letter is dropped with it.
    assert scenes["snow flake"] == b"\x0f"
    assert scenes["energetic"] == b"\x10"
    assert scenes["rainbow"] == b"\x16"
    assert not {"snow flake a", "snow flake b", "energetic a", "rainbow a"} & set(
        scenes
    )


def test_govee_variant_letter_is_dropped_when_its_sibling_is_not_kept():
    # H70B8 lists "Aurora" (blob only) and "Aurora B" (firmware): only the
    # firmware twin is kept, so its letter tells nothing apart.
    scenes = GOVEE_LIGHT_CAPABILITIES["H70B8"].scenes
    assert scenes["aurora"] == b"\x6b"
    assert scenes["rainbow heart"] == b"\x74"
    assert not {"aurora b", "rainbow b", "rainbow heart b"} & set(scenes)


def test_govee_variant_letter_stays_next_to_its_kept_sibling():
    # "Shiny" and "Shiny B" are both firmware scenes on H6870.
    scenes = GOVEE_LIGHT_CAPABILITIES["H6870"].scenes
    assert "shiny" in scenes
    assert "shiny b" in scenes
    assert scenes["shiny"] != scenes["shiny b"]


def test_no_model_lists_the_same_scene_code_twice():
    # Two names for one code would mean a variant was split in two.
    for sku, capabilities in GOVEE_LIGHT_CAPABILITIES.items():
        codes = list(capabilities.scenes.values())
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
