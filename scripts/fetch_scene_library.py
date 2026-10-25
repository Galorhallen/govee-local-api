#!/usr/bin/env python3
"""Fetch Govee's per-model scene library for every registered device.

Queries the Govee app's light-effect-libraries endpoint for each SKU in
GOVEE_LIGHT_CAPABILITIES and writes a JSON file mapping each SKU to its
scenes and their sceneCode (scenes whose sceneCode is 0 are skipped).
Only sceneType 0 scenes are kept by default; --scene-type selects another
type or `all`.

From that library it then derives:
- scene_devices.json, next to the output file: every scene (name +
  sceneCode) with the devices that support it — the same name can map to
  different codes on different models;
- src/govee_local_api/data/model_scenes.json, the packaged per-model scene
  registry: the firmware scenes (sceneType 0 without a scenceParam blob,
  which SceneMessages can play from the code alone) as shared scene sets.

Run with `python scripts/fetch_scene_library.py [-o OUTPUT] [--scene-type T]`,
or regenerate one derived file from an existing library (no requests) with
`--scene-devices-only` or `--model-scenes-only`.
"""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import logging
from pathlib import Path
import re
import sys
import threading
import time
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "src"))

from govee_local_api.light_capabilities import GOVEE_LIGHT_CAPABILITIES  # noqa: E402

LIBRARY_URL = "https://app2.govee.com/appsku/v1/light-effect-libraries"
# Without an AppVersion header the endpoint answers with an empty library.
HEADERS = {
    "AppVersion": "6.5.02",
    "User-Agent": "GoveeHome/6.5.02 (com.ihoment.GoVeeSensor; build:2; iOS 17.0.0)",
}
DEFAULT_OUTPUT = REPO_ROOT / "scene_library.json"
WORKERS = 15
RETRIES = 3
TIMEOUT = 20
DEFAULT_SCENE_TYPE = 0
SCENE_DEVICES_FILE = "scene_devices.json"
MODEL_SCENES_FILE = REPO_ROOT / "src" / "govee_local_api" / "data" / "model_scenes.json"
# Firmware scenes: the only type whose codes play without a parameter blob.
MODEL_SCENE_TYPE = 0
# " B" in "Aurora B": a single capital letter ending a scene name.
VARIANT_SUFFIX = re.compile(r" [A-Z]$")
# Home Assistant translation keys must match [a-z0-9-_]+ (hassfest).
HA_KEY_INVALID = re.compile(r"[^a-z0-9]+")

Library = dict[str, list[dict[str, Any]]]

_LOGGER = logging.getLogger("fetch_scene_library")


def fetch_library(sku: str) -> dict[str, Any]:
    """Return the raw `data` object of the scene library for one SKU."""
    request = Request(f"{LIBRARY_URL}?{urlencode({'sku': sku})}", headers=HEADERS)
    for attempt in range(1, RETRIES + 1):
        _LOGGER.debug("%s: GET %s (attempt %d)", sku, request.full_url, attempt)
        try:
            with urlopen(request, timeout=TIMEOUT) as response:
                payload = json.load(response)
            if payload.get("status") != 200:
                raise ValueError(f"unexpected status: {payload.get('message')}")
            return payload.get("data") or {}
        except (URLError, TimeoutError, ValueError) as ex:
            if attempt == RETRIES:
                raise RuntimeError(f"{sku}: {ex}") from ex
            _LOGGER.debug("%s: attempt %d failed (%s), retrying", sku, attempt, ex)
            time.sleep(attempt)
    raise AssertionError("unreachable")


def extract_scenes(
    data: dict[str, Any], scene_type: int | None
) -> list[dict[str, Any]]:
    """Flatten the library into [{name, code, type, effects, param,
    scene_id, scene, variant}], skipping sceneCode 0.

    Scenes are filtered on the scene node's sceneType (`scene_type=None`
    keeps every type). The usable sceneCode lives on each scene's
    lightEffects; a scene with several effects gets the effect name appended
    to tell them apart, and `effects` records how many it has. `param` is
    whether the effect needs a scenceParam blob to play. `scene_id`, `scene`
    and `variant` keep the scene node's id, its own name and the effect's
    variant letter ("" for single-effect scenes) apart from `name`, so
    build_model_scenes can tell an appended variant letter from a letter that
    is part of Govee's scene name ("Sunset B").
    """
    scenes = []
    for category in data.get("categories", []):
        for scene in category.get("scenes", []):
            if scene_type is not None and scene.get("sceneType") != scene_type:
                continue
            effects = scene.get("lightEffects", [])
            for effect in effects:
                code = effect.get("sceneCode", 0)
                if not code:
                    continue
                name = scene.get("sceneName", "")
                if len(effects) > 1 and effect.get("scenceName"):
                    name = f"{name} {effect['scenceName']}"
                scenes.append(
                    {
                        "name": name,
                        "code": code,
                        "type": scene.get("sceneType"),
                        "effects": len(effects),
                        "param": bool(effect.get("scenceParam")),
                        "scene_id": scene.get("sceneId"),
                        "scene": scene.get("sceneName", ""),
                        "variant": (
                            effect.get("scenceName", "") if len(effects) > 1 else ""
                        ),
                    }
                )
    return scenes


def build_scene_devices(library: Library) -> dict[str, dict[str, list[str]]]:
    """Reverse the library: {scene name: {sceneCode: [devices]}}.

    One name can carry different codes on different models, so each name
    maps every code it uses to the devices supporting it, most widely
    supported code first. Codes are strings because JSON keys must be.
    """
    devices: dict[str, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    for sku, scenes in library.items():
        for scene in scenes:
            devices[scene["name"]][scene["code"]].add(sku)

    return {
        name: {
            str(code): sorted(skus)
            for code, skus in sorted(codes.items(), key=lambda c: (-len(c[1]), c[0]))
        }
        for name, codes in sorted(devices.items())
    }


def name_model_scenes(scenes: list[dict[str, Any]]) -> list[tuple[str, int]]:
    """A model's firmware scenes as [(name, code)], names in Govee's casing.

    Keeps sceneType 0 without a scenceParam blob. Variant letters only appear
    where they tell two kept scenes apart: an effect's variant is appended
    only when two or more variants of the same scene are kept, and a variant
    letter in Govee's own scene name ("Aurora B", the firmware twin of a
    blob-only "Aurora") is dropped unless another kept scene already has the
    name without it ("Shiny" next to "Shiny B"). The library's scene keys
    are these names passed through scene_key().
    """
    kept = [
        scene
        for scene in scenes
        if scene["type"] == MODEL_SCENE_TYPE and not scene["param"]
    ]
    kept_variants = Counter(scene["scene_id"] for scene in kept)
    named = []
    for scene in kept:
        name = scene["scene"]
        if kept_variants[scene["scene_id"]] > 1 and scene["variant"]:
            name = f"{name} {scene['variant']}"
        named.append((name, scene["code"]))
    # A trailing capital letter is a variant marker (Govee only uses A-D
    # there); drop it when no other kept scene shares the base name.
    bases = Counter(VARIANT_SUFFIX.sub("", name).lower() for name, _ in named)
    result = []
    for name, code in named:
        base = VARIANT_SUFFIX.sub("", name)
        result.append((base if bases[base.lower()] == 1 else name, code))
    return result


def scene_key(name: str) -> str:
    """The library's key for a Govee scene name, usable as-is as a Home
    Assistant translation key ([a-z0-9-_]+): "Blue sky & white clouds" ->
    "blue_sky_white_clouds", "Mother's Hug" -> "mothers_hug"."""
    return HA_KEY_INVALID.sub("_", name.lower().replace("'", "")).strip("_")


def build_ha_scene_names(library: Library) -> dict[str, str]:
    """{scene key: display name} for Home Assistant's strings.json.

    The display name is Govee's own casing, with a capitalised first letter;
    when models spell one scene differently ("Snow flake" / "Snow Flake"),
    the most common spelling wins.
    """
    spellings: dict[str, Counter[str]] = defaultdict(Counter)
    for sku, scenes in library.items():
        if sku not in GOVEE_LIGHT_CAPABILITIES:
            continue
        for name, code in name_model_scenes(scenes):
            if code <= 0xFF:  # the same filter build_model_scenes applies
                spellings[scene_key(name)][name] += 1
    names = {}
    for key, counts in sorted(spellings.items()):
        display = sorted(counts.items(), key=lambda c: (-c[1], c[0]))[0][0]
        names[key] = display[:1].upper() + display[1:]
    return names


def build_model_scenes(library: Library) -> dict[str, dict[str, Any]]:
    """Build the packaged registry: {"sets": {id: {name: code}}, "models":
    {sku: id | None}}.

    Keeps each model's firmware scenes as named by name_model_scenes(), keyed
    by scene_key() ("snow_flake"). Two kept scenes with the same key raise
    ValueError rather than one silently replacing the other.
    Models with the same scenes share one set; a set's id is a hash of its contents, so regenerating
    keeps unchanged ids stable. Models without firmware scenes map to None, so
    the file records every model that was checked. Models no longer in
    GOVEE_LIGHT_CAPABILITIES (a library file can predate a registry change)
    are left out.
    """
    sets: dict[str, dict[str, int]] = {}
    models: dict[str, str | None] = {}
    unregistered = sorted(set(library) - set(GOVEE_LIGHT_CAPABILITIES))
    if unregistered:
        _LOGGER.warning(
            "Skipping %d models not in GOVEE_LIGHT_CAPABILITIES: %s",
            len(unregistered),
            ", ".join(unregistered),
        )
    for sku, scenes in library.items():
        if sku not in GOVEE_LIGHT_CAPABILITIES:
            continue
        if any("scene_id" not in scene for scene in scenes):
            raise ValueError(
                f"{sku}: library entries lack 'scene_id'; refetch the library"
            )
        model_scenes: dict[str, int] = {}
        for name, code in name_model_scenes(scenes):
            name = scene_key(name)
            if code > 0xFF:
                # SceneMessages carries a single code byte.
                _LOGGER.warning("%s: skipping %r, code %d > 255", sku, name, code)
            elif name in model_scenes:
                raise ValueError(
                    f"{sku}: two scenes with the key {name!r} "
                    f"(codes {model_scenes[name]} and {code})"
                )
            else:
                model_scenes[name] = code
        if not model_scenes:
            models[sku] = None
            continue
        canonical = json.dumps(sorted(model_scenes.items()))
        set_id = hashlib.sha1(canonical.encode()).hexdigest()[:8]
        sets[set_id] = model_scenes
        models[sku] = set_id
    return {"sets": dict(sorted(sets.items())), "models": dict(sorted(models.items()))}


def _depth(data: Any) -> int:
    """Nesting depth: 0 for a scalar, 1 for a container of scalars, ..."""
    if isinstance(data, dict):
        data = list(data.values())
    if not isinstance(data, list):
        return 0
    return 1 + max(map(_depth, data), default=0)


def format_json(data: Any, level: int = 0) -> str:
    """Compact JSON, one record per line: a container holding only scalars
    (a device list, a library scene entry) goes on one line; only containers
    that nest others, and the top two levels, are indented."""
    if (
        not isinstance(data, (dict, list))
        or not data
        or (_depth(data) <= 1 and level >= 2)
    ):
        return json.dumps(data, ensure_ascii=False)

    pad = "  " * (level + 1)
    if isinstance(data, dict):
        items = [
            f"{pad}{json.dumps(key, ensure_ascii=False)}: "
            f"{format_json(value, level + 1)}"
            for key, value in data.items()
        ]
        opening, closing = "{", "}"
    else:
        items = [f"{pad}{format_json(value, level + 1)}" for value in data]
        opening, closing = "[", "]"
    return f"{opening}\n" + ",\n".join(items) + f"\n{'  ' * level}{closing}"


def write_json(path: Path, data: Any) -> None:
    path.write_text(format_json(data) + "\n")


def fetch_all(
    scene_type: int | None, skus: list[str] | None = None
) -> tuple[Library, list[str]]:
    """Fetch the libraries of `skus` (default: every registered SKU); returns
    (library, failed SKUs)."""
    skus = sorted(GOVEE_LIGHT_CAPABILITIES if skus is None else skus)
    result: Library = {}
    failures: list[str] = []
    _LOGGER.info(
        "Fetching scene libraries for %d devices (%d workers, scene type: %s)",
        len(skus),
        WORKERS,
        "all" if scene_type is None else scene_type,
    )

    lock = threading.Lock()
    done = 0

    def fetch(sku: str) -> None:
        # Runs on a pool thread, so the log line names the worker that
        # pulled this SKU; the lock guards the shared progress state.
        nonlocal done
        try:
            scenes = extract_scenes(fetch_library(sku), scene_type)
        except RuntimeError as ex:
            scenes, error = None, ex
        with lock:
            done += 1
            progress = f"[{done:>{len(str(len(skus)))}}/{len(skus)}]"
            if scenes is None:
                failures.append(sku)
                _LOGGER.warning("%s %s", progress, error)
            else:
                result[sku] = scenes
                _LOGGER.info("%s %s: %d scenes", progress, sku, len(scenes))

    with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="worker") as pool:
        list(pool.map(fetch, skus))

    return dict(sorted(result.items())), failures


def parse_scene_type(value: str) -> int | None:
    """argparse type for --scene-type: an integer code, or `all` (None)."""
    if value.lower() == "all":
        return None
    try:
        return int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected an integer scene type or 'all', got {value!r}"
        ) from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="library JSON to write, or to read with --scene-devices-only "
        f"(default: {DEFAULT_OUTPUT.name})",
    )
    parser.add_argument(
        "-t",
        "--scene-type",
        type=parse_scene_type,
        default=DEFAULT_SCENE_TYPE,
        metavar="TYPE",
        help=f"sceneType code to keep, or 'all' (default: {DEFAULT_SCENE_TYPE})",
    )
    only = parser.add_mutually_exclusive_group()
    only.add_argument(
        "--scene-devices-only",
        action="store_true",
        help="skip fetching: regenerate scene_devices.json from the library "
        "at --output",
    )
    only.add_argument(
        "--model-scenes-only",
        action="store_true",
        help="skip fetching: regenerate the packaged model_scenes.json from "
        "the library at --output",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="log every request and retry"
    )
    args = parser.parse_args()
    from_library = args.scene_devices_only or args.model_scenes_only
    if from_library and not args.output.is_file():
        parser.error(f"skipping the fetch needs an existing library: {args.output}")
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(threadName)-10s %(message)s",
        datefmt="%H:%M:%S",
    )

    started = time.monotonic()
    failures: list[str] = []
    if from_library:
        library: Library = json.loads(args.output.read_text())
        _LOGGER.info("Loaded %s: %d devices", args.output, len(library))
    else:
        library, failures = fetch_all(args.scene_type)
        write_json(args.output, library)
        with_scenes = sum(1 for scenes in library.values() if scenes)
        _LOGGER.info(
            "Wrote %s in %.1fs: %d devices, %d with scenes, %d without",
            args.output,
            time.monotonic() - started,
            len(library),
            with_scenes,
            len(library) - with_scenes,
        )
        if failures:
            _LOGGER.error("%d devices failed: %s", len(failures), ", ".join(failures))

    if not args.model_scenes_only:
        scene_devices = build_scene_devices(library)
        scene_devices_path = args.output.parent / SCENE_DEVICES_FILE
        write_json(scene_devices_path, scene_devices)
        _LOGGER.info(
            "Wrote %s: %d scene names, %d distinct scenes",
            scene_devices_path,
            len(scene_devices),
            sum(len(codes) for codes in scene_devices.values()),
        )

    if args.scene_devices_only:
        pass
    elif args.scene_type not in (MODEL_SCENE_TYPE, None):
        _LOGGER.warning(
            "Not writing %s: it needs sceneType %d scenes, fetched type %d",
            MODEL_SCENES_FILE.name,
            MODEL_SCENE_TYPE,
            args.scene_type,
        )
    elif failures:
        # A partial fetch would silently drop the failed models' scenes.
        _LOGGER.error("Not writing %s: some devices failed", MODEL_SCENES_FILE.name)
    else:
        model_scenes = build_model_scenes(library)
        write_json(MODEL_SCENES_FILE, model_scenes)
        _LOGGER.info(
            "Wrote %s: %d of %d models have scenes, sharing %d scene sets",
            MODEL_SCENES_FILE,
            sum(1 for set_id in model_scenes["models"].values() if set_id),
            len(model_scenes["models"]),
            len(model_scenes["sets"]),
        )

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
