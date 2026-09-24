import pytest

from govee_local_api.light_capabilities import (
    BASIC_CAPABILITIES,
    DEFAULT_TEMPERATURE_RANGE,
    GOVEE_LIGHT_CAPABILITIES,
    GoveeLightCapabilities,
    GoveeLightFeatures,
    GoveeTemperatureRange,
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
