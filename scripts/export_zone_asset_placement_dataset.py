"""Export zone+asset -> relative-placement training records.

Each record corresponds to a non-primary object attached to a primary layout
zone. The model input is the zone context plus the selected asset identity.
The target is the object's relative x/z/yaw placement around the zone.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from export_zone_asset_dataset import (
    load_json,
    nearby_context,
    site_features,
    vec3,
    write_jsonl,
)


ROOT = Path(__file__).resolve().parents[1]


def yaw_delta(dependent_yaw: float, anchor_yaw: float) -> float:
    return (dependent_yaw - anchor_yaw + 180.0) % 360.0 - 180.0


def attached_non_primary_objects(zone: dict[str, Any], objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    zone_id = zone["id"]
    attached = []
    for obj in objects:
        if obj["id"] == zone_id or obj.get("source", {}).get("kind") == "primary":
            continue
        source = obj.get("source", {})
        anchors = obj.get("anchors", {})
        if source.get("parent_id") == zone_id or anchors.get("functional_id") == zone_id:
            attached.append(obj)
    return attached


def placement_record(
    scene: dict[str, Any],
    path: Path,
    zone: dict[str, Any],
    dependent: dict[str, Any],
    primary_objects: list[dict[str, Any]],
    occurrence_index: int,
    occurrence_count: int,
) -> dict[str, Any]:
    site = site_features(scene)
    zone_source = zone.get("source", {})
    dep_source = dependent.get("source", {})
    zone_position = vec3(zone.get("transform", {}).get("position"))
    dep_position = vec3(dependent.get("transform", {}).get("position"))
    zone_rotation = vec3(zone.get("transform", {}).get("rotation"))
    dep_rotation = vec3(dependent.get("transform", {}).get("rotation"))
    relative_yaw = yaw_delta(dep_rotation["y"], zone_rotation["y"])
    placement = dependent.get("placement", {})
    prefab = dependent.get("prefab", {})

    return {
        "task": "zone_asset_relation_placement",
        "scene_id": scene.get("scene_id"),
        "scene_path": str(path),
        "source_layout_id": scene.get("source_layout", {}).get("id"),
        "zone_id": zone.get("id"),
        "dependent_id": dependent.get("id"),
        "input": {
            "zone": {
                "facility_index": zone_source.get("facility_index"),
                "facility_type": zone_source.get("facility_type"),
                "category": zone_source.get("category"),
                "bbox_size": zone.get("placement", {}).get("bbox_size", {}),
                "clearance_radius_m": zone.get("placement", {}).get("clearance_radius_m"),
                "rotation_y": zone_rotation["y"],
                "position": zone_position,
            },
            "asset": {
                "prefab_name": prefab.get("name"),
                "construction_class": prefab.get("construction_class"),
                "relation_role": prefab.get("relation_role"),
                "suggested_support_type": prefab.get("suggested_support_type"),
                "source_kind": dep_source.get("kind"),
                "accessory_type": dep_source.get("accessory_type"),
                "occurrence_index": occurrence_index,
                "occurrence_count": occurrence_count,
                "occurrence_fraction": occurrence_index / max(1, occurrence_count - 1),
                "bbox_size": placement.get("bbox_size", {}),
                "clearance_radius_m": placement.get("clearance_radius_m"),
            },
            "site": site,
            "context": nearby_context(zone, primary_objects, site),
        },
        "target": {
            "relative_position": {
                "x": dep_position["x"] - zone_position["x"],
                "y": dep_position["y"] - zone_position["y"],
                "z": dep_position["z"] - zone_position["z"],
            },
            "relative_yaw": relative_yaw,
            "relative_yaw_sin": math.sin(math.radians(relative_yaw)),
            "relative_yaw_cos": math.cos(math.radians(relative_yaw)),
            "absolute_position": dep_position,
            "absolute_yaw": dep_rotation["y"],
        },
    }


def export_scene(path: Path) -> list[dict[str, Any]]:
    scene = load_json(path)
    objects = scene.get("objects", [])
    primary_objects = [obj for obj in objects if obj.get("source", {}).get("kind") == "primary"]
    rows = []
    for zone in primary_objects:
        attached = attached_non_primary_objects(zone, objects)
        totals: Counter[str] = Counter(obj.get("prefab", {}).get("name") for obj in attached)
        seen: Counter[str] = Counter()
        for dependent in attached:
            prefab_name = dependent.get("prefab", {}).get("name")
            occurrence_index = seen[prefab_name]
            seen[prefab_name] += 1
            rows.append(
                placement_record(
                    scene,
                    path,
                    zone,
                    dependent,
                    primary_objects,
                    occurrence_index=occurrence_index,
                    occurrence_count=totals[prefab_name],
                )
            )
    return rows


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
        default=ROOT / "output" / "first_ml_iteration_safe_filtered" / "zone_asset_placement_dataset",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scene_paths = args.scenes or sorted((ROOT / "output" / "first_ml_iteration_safe_filtered" / "scenes").glob("*.json"))
    scene_paths = [path.resolve() for path in scene_paths if path.exists()]
    if not scene_paths:
        raise SystemExit("No scene JSON files found.")

    rows = []
    labels = Counter()
    kinds = Counter()
    for path in scene_paths:
        scene_rows = export_scene(path)
        rows.extend(scene_rows)
        for row in scene_rows:
            labels[row["input"]["asset"].get("prefab_name")] += 1
            kinds[row["input"]["asset"].get("source_kind")] += 1

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output_dir / "zone_asset_placement_records.jsonl", rows)
    manifest = {
        "scene_count": len(scene_paths),
        "record_count": len(rows),
        "unique_asset_label_count": len(labels),
        "top_asset_labels": labels.most_common(30),
        "source_kind_counts": dict(kinds),
        "files": {
            "zone_asset_placement_records": str(args.output_dir / "zone_asset_placement_records.jsonl"),
        },
    }
    with (args.output_dir / "manifest.json").open("w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=2)

    print(f"Wrote zone asset placement dataset to {args.output_dir}")
    print(f"Scenes: {manifest['scene_count']}")
    print(f"Records: {manifest['record_count']}")
    print(f"Unique asset labels: {manifest['unique_asset_label_count']}")


if __name__ == "__main__":
    main()
