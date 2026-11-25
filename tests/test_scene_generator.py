"""Tests for the scene generator in scripts/ (no network access)."""

import base64
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fetch_scene_library as fsl  # noqa: E402
import generate_model_scenes as gms  # noqa: E402

BLOB_A = bytes(range(1, 40))
BLOB_B = bytes(range(40, 100))


def _b64(blob: bytes) -> str:
    return base64.b64encode(blob).decode()


def _scene(
    name: str,
    code: int,
    blob: bytes | str = b"",
    *,
    scene_type: int = 2,
    effect_type: int | None = None,
    special: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """One raw library scene node with a single light effect."""
    param = blob if isinstance(blob, str) else _b64(blob)
    return {
        "sceneId": code,
        "sceneName": name,
        "sceneType": scene_type,
        "lightEffects": [
            {
                "scenceName": "",
                "sceneCode": code,
                "scenceParam": param,
                "sceneType": scene_type if effect_type is None else effect_type,
                "specialEffect": special or [],
            }
        ],
    }


def _firmware(name: str, code: int) -> dict[str, Any]:
    return _scene(name, code, scene_type=0)


def _raw(*scenes: dict[str, Any]) -> dict[str, Any]:
    return {"categories": [{"categoryName": "Festival", "scenes": list(scenes)}]}


def _build(*scenes: dict[str, Any], sku: str = "H805A") -> dict[str, Any]:
    return fsl.build_model_scenes({sku: fsl.extract_scenes(_raw(*scenes), None, sku)})


def _only_set(model_scenes: dict[str, Any], sku: str = "H805A") -> dict[str, Any]:
    return model_scenes["sets"][model_scenes["models"][sku]]


def test_extract_records_effect_type_blob_and_override():
    special = [{"supportSku": ["H805A"], "scenceParam": _b64(BLOB_B)}]
    (scene,) = fsl.extract_scenes(
        _raw(
            _scene("Sled", 11274, BLOB_A, scene_type=0, effect_type=2, special=special)
        ),
        None,
        "H805A",
    )
    assert scene["type"] == 0
    assert scene["effect_type"] == 2
    assert scene["blob"] == _b64(BLOB_A)
    assert scene["override"] is True


def test_firmware_scene_is_stored_as_a_bare_code():
    data = _build(_firmware("Rainbow", 22))
    assert _only_set(data) == {"rainbow": 22}
    assert data["blobs"] == {}


def test_firmware_only_set_keeps_the_id_it_had_before_parameter_scenes():
    # 075f1b0e is this set's id in the file generated before this change.
    data = _build(_firmware("White Light", 99), _firmware("Illumination", 98))
    assert data["models"]["H805A"] == "075f1b0e"


def test_parameter_scene_is_stored_with_a_reference_to_its_blob():
    data = _build(_scene("Candy Cane", 12368, BLOB_A))
    code, blob_id = _only_set(data)["candy_cane"]
    assert code == 12368
    assert data["blobs"] == {blob_id: _b64(BLOB_A)}


def test_scenes_sharing_a_name_get_numbered_keys_in_code_order():
    data = _build(
        _scene("Halloween", 12492, BLOB_B), _scene("Halloween", 11275, BLOB_A)
    )
    scenes = _only_set(data)
    assert scenes["halloween"][0] == 11275
    assert scenes["halloween_2"][0] == 12492


def test_parameter_scene_never_takes_a_firmware_scene_key():
    # "Aurora B" is the firmware twin and already owns the key "aurora".
    data = _build(_firmware("Aurora B", 107), _scene("Aurora", 11300, BLOB_A))
    scenes = _only_set(data)
    assert scenes["aurora"] == 107
    assert scenes["aurora_2"][0] == 11300


def test_scene_with_a_different_blob_for_this_sku_is_left_out():
    special = [{"supportSku": ["H805A"], "scenceParam": _b64(BLOB_B)}]
    data = _build(
        _firmware("Rainbow", 22), _scene("Sled", 11274, BLOB_A, special=special)
    )
    assert _only_set(data) == {"rainbow": 22}


def test_override_for_another_sku_does_not_remove_the_scene():
    special = [{"supportSku": ["H6173"], "scenceParam": _b64(BLOB_B)}]
    data = _build(_scene("Sled", 11274, BLOB_A, special=special))
    assert "sled" in _only_set(data)


def test_only_effect_type_2_parameter_scenes_are_kept():
    data = _build(
        _firmware("Rainbow", 22), _scene("Mona Lisa", 500, BLOB_A, scene_type=5)
    )
    assert _only_set(data) == {"rainbow": 22}


def test_blob_that_is_not_base64_is_left_out():
    data = _build(_firmware("Rainbow", 22), _scene("Birthday", 300, "AB\\/C=="))
    assert _only_set(data) == {"rainbow": 22}


def test_blob_too_long_for_the_encoder_is_left_out():
    data = _build(_firmware("Rainbow", 22), _scene("Huge", 300, bytes(4333)))
    assert _only_set(data) == {"rainbow": 22}


def test_identical_blobs_are_stored_once():
    data = _build(_scene("Sled", 11274, BLOB_A), _scene("Beer", 12494, BLOB_A))
    assert len(data["blobs"]) == 1
    assert _only_set(data)["sled"][1] == _only_set(data)["beer"][1]


def test_scene_listed_twice_is_kept_once():
    data = _build(_scene("Sled", 11274, BLOB_A), _scene("Sled", 11274, BLOB_A))
    assert list(_only_set(data)) == ["sled"]


def test_model_with_only_parameter_scenes_gets_a_set():
    data = _build(_scene("Sled", 11274, BLOB_A))
    assert data["models"]["H805A"] is not None


def test_display_names_cover_parameter_scenes_and_numbered_keys():
    library = {
        "H805A": fsl.extract_scenes(
            _raw(
                _firmware("Rainbow", 22),
                _scene("Halloween", 12492, BLOB_B),
                _scene("Halloween", 11275, BLOB_A),
            ),
            None,
            "H805A",
        )
    }
    assert fsl.build_ha_scene_names(library) == {
        "halloween": "Halloween",
        "halloween_2": "Halloween 2",
        "rainbow": "Rainbow",
    }


def test_merge_keeps_only_the_blobs_a_set_still_uses():
    existing = {
        "blobs": {"old": "AAAA", "kept": "BBBB"},
        "sets": {"s1": {"sled": [11274, "old"]}, "s2": {"beer": [12494, "kept"]}},
        "models": {"H805A": "s1", "H805B": "s2"},
    }
    update = {
        "blobs": {"new": "CCCC"},
        "sets": {"s3": {"sled": [11274, "new"]}},
        "models": {"H805A": "s3"},
    }
    merged = gms.merge(existing, update)
    assert merged["blobs"] == {"kept": "BBBB", "new": "CCCC"}
    assert set(merged["sets"]) == {"s2", "s3"}


def test_merge_accepts_a_file_written_before_blobs_existed():
    existing = {"sets": {"s1": {"rainbow": 22}}, "models": {"H805A": "s1"}}
    merged = gms.merge(existing, {"blobs": {}, "sets": {}, "models": {}})
    assert merged == {
        "blobs": {},
        "sets": {"s1": {"rainbow": 22}},
        "models": {"H805A": "s1"},
    }


def test_scene_whose_name_gives_no_key_is_left_out():
    data = _build(_firmware("Rainbow", 22), _scene("圣诞", 300, BLOB_A))
    assert _only_set(data) == {"rainbow": 22}
