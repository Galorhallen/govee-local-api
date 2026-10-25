#!/usr/bin/env python3
"""Generate src/govee_local_api/data/model_scenes.json from the registry.

Fetches Govee's scene library (one request per SKU) and writes the packaged
per-model scene sets: firmware scenes only (sceneType 0 without a scenceParam
blob), keyed by lowercase name. Models without firmware scenes are recorded
as null, so the file lists every model that was checked.

    uv run python scripts/generate_model_scenes.py              # new models only
    uv run python scripts/generate_model_scenes.py --all        # full refresh
    uv run python scripts/generate_model_scenes.py --skus H6008 # these models

By default only models in GOVEE_LIGHT_CAPABILITIES but not yet in the file
are fetched, and models no longer registered are dropped; run it after adding
a model. --all refetches everything (e.g. to pick up changes in Govee's
library), --skus refetches the given models. Nothing is written if any SKU
fails to fetch, so a flaky run can't drop a model's scenes. The fetching and
filtering live in fetch_scene_library.py.

It also writes ha_scene_names.json in the repo root for the Home Assistant
integration: every scene key (already a valid HA translation key, e.g.
"snow_flake") with its display name in Govee's casing ("Snow flake"), ready
for the effect states in HA's strings.json.
"""

import argparse
import json
import logging
import sys
import time
from typing import Any

from fetch_scene_library import (
    GOVEE_LIGHT_CAPABILITIES,
    MODEL_SCENE_TYPE,
    MODEL_SCENES_FILE,
    REPO_ROOT,
    build_ha_scene_names,
    build_model_scenes,
    fetch_all,
    write_json,
)

HA_SCENE_NAMES_FILE = REPO_ROOT / "ha_scene_names.json"

_LOGGER = logging.getLogger("generate_model_scenes")


def merge(existing: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """Overlay freshly fetched models on the existing file.

    Models no longer registered are dropped, and so are sets no model uses.
    Set ids hash their contents, so identical sets from both sides coincide.
    """
    models = {
        sku: set_id
        for sku, set_id in existing["models"].items()
        if sku in GOVEE_LIGHT_CAPABILITIES
    }
    models.update(update["models"])
    sets = {**existing["sets"], **update["sets"]}
    used = set(models.values())
    return {
        "sets": {set_id: sets[set_id] for set_id in sorted(sets) if set_id in used},
        "models": dict(sorted(models.items())),
    }


def merge_ha_names(
    existing: dict[str, str], update: dict[str, str], model_scenes: dict[str, Any]
) -> dict[str, str]:
    """Overlay fresh display names on the existing file, keeping only keys a
    scene set still uses. Fails if a key used by a set has no name (the file
    predates it: rerun with --all)."""
    used = {key for scenes in model_scenes["sets"].values() for key in scenes}
    names = {**existing, **update}
    missing = sorted(used - set(names))
    if missing:
        raise ValueError(
            f"{HA_SCENE_NAMES_FILE.name} lacks {', '.join(missing)}; "
            "rerun with --all"
        )
    return {key: names[key] for key in sorted(used)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--all", action="store_true", help="refetch every model")
    mode.add_argument(
        "--skus", nargs="+", metavar="SKU", help="refetch only these models"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="log every request and retry"
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(threadName)-10s %(message)s",
        datefmt="%H:%M:%S",
    )

    # Importing the registry already needs the file, so it always exists here.
    existing = json.loads(MODEL_SCENES_FILE.read_text())
    if args.all:
        skus = sorted(GOVEE_LIGHT_CAPABILITIES)
    elif args.skus:
        unknown = sorted(set(args.skus) - set(GOVEE_LIGHT_CAPABILITIES))
        if unknown:
            parser.error(f"not in GOVEE_LIGHT_CAPABILITIES: {', '.join(unknown)}")
        skus = args.skus
    elif not HA_SCENE_NAMES_FILE.is_file():
        # Without it, names of models not refetched would be unknown.
        parser.error(f"{HA_SCENE_NAMES_FILE.name} is missing; run with --all")
    else:
        skus = sorted(set(GOVEE_LIGHT_CAPABILITIES) - set(existing["models"]))
        removed = sorted(set(existing["models"]) - set(GOVEE_LIGHT_CAPABILITIES))
        if not skus and not removed:
            _LOGGER.info("%s is up to date", MODEL_SCENES_FILE.name)
            return 0
        if skus:
            _LOGGER.info("Added models: %s", ", ".join(skus))
        if removed:
            _LOGGER.info("Removed models: %s", ", ".join(removed))

    started = time.monotonic()
    library, failures = fetch_all(MODEL_SCENE_TYPE, skus)
    if failures:
        _LOGGER.error(
            "Not writing %s: %d devices failed: %s",
            MODEL_SCENES_FILE.name,
            len(failures),
            ", ".join(failures),
        )
        return 1

    model_scenes = build_model_scenes(library)
    if not args.all:
        model_scenes = merge(existing, model_scenes)
    existing_names = (
        json.loads(HA_SCENE_NAMES_FILE.read_text())
        if HA_SCENE_NAMES_FILE.is_file() and not args.all
        else {}
    )
    ha_names = merge_ha_names(
        existing_names, build_ha_scene_names(library), model_scenes
    )
    write_json(MODEL_SCENES_FILE, model_scenes)
    write_json(HA_SCENE_NAMES_FILE, ha_names)
    _LOGGER.info(
        "Wrote %s in %.1fs: %d of %d models have scenes, sharing %d scene sets",
        MODEL_SCENES_FILE,
        time.monotonic() - started,
        sum(1 for set_id in model_scenes["models"].values() if set_id),
        len(model_scenes["models"]),
        len(model_scenes["sets"]),
    )
    _LOGGER.info("Wrote %s: %d scene names", HA_SCENE_NAMES_FILE, len(ha_names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
