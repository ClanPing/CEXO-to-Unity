"""Export zone-context -> asset-set training records from compiled scenes.

Each record corresponds to one primary optimized layout zone. The input is the
zone specification plus surrounding-zone context. The target is the set of
prefabs/assets attached to that zone by the current scene compiler.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FACILITY_TYPES = ["office", "rest_area", "core", "storage", "crane"]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def vec3(data: dict[str, Any] | None) -> dict[str, float]:
    if not data:
        return {"x": 0.0, "y": 0.0, "z": 0.0}
    return {
        "x": float(data.get("x", 0.0)),
        "y": float(data.get("y", 0.0)),
        "z": float(data.get("z", 0.0)),
    }


def distance_xz(a: dict[str, float], b: dict[str, float]) -> float:
    return math.hypot(a["x"] - b["x"], a["z"] - b["z"])


def source_label(obj: dict[str, Any]) -> str:
    source = obj.get("source", {})
    return f"{source.get('kind', 'unknown')}:{source.get('facility_type', 'unknown')}"


def site_features(scene: dict[str, Any]) -> dict[str, Any]:
    bounds = scene.get("site", {}).get("bounds", {})
    source = scene.get("source_layout", {})
    width = float(bounds.get("max_x", 0.0)) - float(bounds.get("min_x", 0.0))
    length = float(bounds.get("max_z", 0.0)) - float(bounds.get("min_z", 0.0))
    return {
        "site_width": width,
        "site_length": length,
        "site_area": max(0.0, width * length),
        "entrance_count": len(scene.get("site", {}).get("anchors", {}).get("entrances", [])),
        "road_zone_count": len(scene.get("site_visuals", {}).get("road_zones", [])),
        "source_layout_id": source.get("id"),
        "source_objectives": source.get("objectives", {}),
        "source_behaviors": source.get("behaviors", {}),
        "source_feasibility": source.get("feasibility", {}),
    }


def normalized_position(position: dict[str, float], site: dict[str, Any]) -> dict[str, float]:
    return {
        "x": position["x"] / max(1e-6, float(site["site_width"])),
        "z": position["z"] / max(1e-6, float(site["site_length"])),
    }


def child_prefab_names(obj: dict[str, Any]) -> list[str]:
    prefab = obj.get("prefab", {})
    names = []
    for child in prefab.get("children", []) or []:
        name = child.get("name") or Path(child.get("path", "")).stem
        if name:
            names.append(str(name))
    return names


def asset_names_for_zone(zone: dict[str, Any], objects: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    zone_id = zone["id"]
    asset_names = [zone.get("prefab", {}).get("name")]
    component_names = child_prefab_names(zone)

    for obj in objects:
        if obj["id"] == zone_id:
            continue
        source = obj.get("source", {})
        anchors = obj.get("anchors", {})
        if source.get("parent_id") == zone_id or anchors.get("functional_id") == zone_id:
            name = obj.get("prefab", {}).get("name")
            if name:
                asset_names.append(name)
            component_names.extend(child_prefab_names(obj))

    return sorted({name for name in asset_names if name}), sorted({name for name in component_names if name})


def nearby_context(zone: dict[str, Any], primary_objects: list[dict[str, Any]], site: dict[str, Any]) -> dict[str, Any]:
    zone_position = vec3(zone.get("transform", {}).get("position"))
    zone_rotation = vec3(zone.get("transform", {}).get("rotation"))
    context: dict[str, Any] = {
        "nearest_by_type": {},
        "counts_within_30m": {},
        "counts_within_60m": {},
    }
    for facility_type in FACILITY_TYPES:
        nearest = None
        nearest_distance = None
        count_30 = 0
        count_60 = 0
        for other in primary_objects:
            if other["id"] == zone["id"] or other.get("source", {}).get("facility_type") != facility_type:
                continue
            other_position = vec3(other.get("transform", {}).get("position"))
            distance = distance_xz(zone_position, other_position)
            if distance <= 30.0:
                count_30 += 1
            if distance <= 60.0:
                count_60 += 1
            if nearest_distance is None or distance < nearest_distance:
                nearest_distance = distance
                nearest = other
        context["counts_within_30m"][facility_type] = count_30
        context["counts_within_60m"][facility_type] = count_60
        if nearest is None:
            context["nearest_by_type"][facility_type] = {
                "exists": False,
                "distance": None,
                "relative_x": None,
                "relative_z": None,
                "relative_yaw": None,
            }
        else:
            nearest_position = vec3(nearest.get("transform", {}).get("position"))
            nearest_rotation = vec3(nearest.get("transform", {}).get("rotation"))
            context["nearest_by_type"][facility_type] = {
                "exists": True,
                "distance": nearest_distance,
                "relative_x": nearest_position["x"] - zone_position["x"],
                "relative_z": nearest_position["z"] - zone_position["z"],
                "relative_yaw": (nearest_rotation["y"] - zone_rotation["y"] + 180.0) % 360.0 - 180.0,
            }
    context["normalized_position"] = normalized_position(zone_position, site)
    return context


def zone_record(scene: dict[str, Any], path: Path, zone: dict[str, Any], primary_objects: list[dict[str, Any]]) -> dict[str, Any]:
    source = zone.get("source", {})
    placement = zone.get("placement", {})
    transform = zone.get("transform", {})
    site = site_features(scene)
    asset_names, component_names = asset_names_for_zone(zone, scene.get("objects", []))

    return {
        "task": "zone_context_asset_set_prediction",
        "scene_id": scene.get("scene_id"),
        "scene_path": str(path),
        "zone_id": zone.get("id"),
        "source_layout_id": scene.get("source_layout", {}).get("id"),
        "input": {
            "zone": {
                "facility_index": source.get("facility_index"),
                "facility_type": source.get("facility_type"),
                "category": source.get("category"),
                "bbox_size": placement.get("bbox_size", {}),
                "clearance_radius_m": placement.get("clearance_radius_m"),
                "rotation_y": vec3(transform.get("rotation"))["y"],
                "position": vec3(transform.get("position")),
            },
            "site": site,
            "context": nearby_context(zone, primary_objects, site),
        },
        "target": {
            "primary_prefab": zone.get("prefab", {}).get("name"),
            "asset_names": asset_names,
            "component_prefab_names": component_names,
            "asset_count": len(asset_names),
            "component_count": len(component_names),
        },
    }


def export_scene(path: Path) -> list[dict[str, Any]]:
    scene = load_json(path)
    primary_objects = [
        obj for obj in scene.get("objects", [])
        if obj.get("source", {}).get("kind") == "primary"
    ]
    return [zone_record(scene, path, zone, primary_objects) for zone in primary_objects]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "scenes",
        nargs="*",
        type=Path,
        help="Compiled Unity scene JSON files. Defaults to filtered first-iteration scenes.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=ROOT / "output" / "first_ml_iteration_safe_filtered" / "zone_asset_dataset",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scene_paths = args.scenes or sorted((ROOT / "output" / "first_ml_iteration_safe_filtered" / "scenes").glob("*.json"))
    scene_paths = [path.resolve() for path in scene_paths if path.exists()]
    if not scene_paths:
        raise SystemExit("No scene JSON files found.")

    rows = []
    for path in scene_paths:
        rows.extend(export_scene(path))

    label_counts = Counter()
    for row in rows:
        label_counts.update(row["target"]["asset_names"])

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output_dir / "zone_asset_records.jsonl", rows)
    manifest = {
        "scene_count": len(scene_paths),
        "record_count": len(rows),
        "unique_asset_label_count": len(label_counts),
        "top_asset_labels": label_counts.most_common(30),
        "files": {
            "zone_asset_records": str(args.output_dir / "zone_asset_records.jsonl"),
        },
    }
    with (args.output_dir / "manifest.json").open("w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=2)

    print(f"Wrote zone asset dataset to {args.output_dir}")
    print(f"Scenes: {manifest['scene_count']}")
    print(f"Records: {manifest['record_count']}")
    print(f"Unique asset labels: {manifest['unique_asset_label_count']}")


if __name__ == "__main__":
    main()
