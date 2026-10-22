import pytest

from govee_local_api.light_capabilities import (
    BASIC_CAPABILITIES,
    DEFAULT_TEMPERATURE_RANGE,
    GOVEE_LIGHT_CAPABILITIES,
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


def test_h619c_keeps_the_full_builtin_scene_set():
    assert GOVEE_LIGHT_CAPABILITIES["H619C"].scenes == SCENE_CODES
    assert len(GOVEE_LIGHT_CAPABILITIES["H619C"].available_scenes) == 12
    assert GOVEE_LIGHT_CAPABILITIES["H619C"].scenes["rainbow"] == b"\x16"


def test_h6052_keeps_only_the_scenes_its_library_confirms():
    assert set(GOVEE_LIGHT_CAPABILITIES["H6052"].available_scenes) == {
        "snowflake",
        "breathe",
        "rainbow",
    }
    assert GOVEE_LIGHT_CAPABILITIES["H6052"].scenes["snowflake"] == b"\x0f"


def test_h706c_keeps_only_rainbow():
    capabilities = GOVEE_LIGHT_CAPABILITIES["H706C"]
    assert capabilities.features & GoveeLightFeatures.SCENES
    assert capabilities.available_scenes == ["rainbow"]
    assert capabilities.scenes == {"rainbow": b"\x16"}


def test_h60a1_keeps_only_candlelight_and_no_rainbow():
    capabilities = GOVEE_LIGHT_CAPABILITIES["H60A1"]
    assert capabilities.available_scenes == ["candlelight"]


def test_h1232_has_no_builtin_scenes():
    capabilities = GOVEE_LIGHT_CAPABILITIES["H1232"]
    assert not capabilities.features & GoveeLightFeatures.SCENES
    assert capabilities.available_scenes == []
    assert capabilities.features & GoveeLightFeatures.COLOR_RGB


def test_every_advertised_scene_is_a_known_builtin_code():
    for sku, capabilities in GOVEE_LIGHT_CAPABILITIES.items():
        for name, code in capabilities.scenes.items():
            assert SCENE_CODES[name] == code, sku
