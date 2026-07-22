"""Export ML-ready records from compiled construction scene JSON files.

This script does not train a model. It creates compact supervised-learning
records from the scene JSONs produced by layout_to_scene.py so we can inspect
what the future model would learn before committing to a DL architecture.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


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


def bbox(data: dict[str, Any] | None) -> dict[str, float]:
    if not data:
        return {"x": 0.0, "y": 0.0, "z": 0.0}
    return vec3(data)


def distance_xz(a: dict[str, float], b: dict[str, float]) -> float:
    return math.hypot(a["x"] - b["x"], a["z"] - b["z"])


def point_in_polygon(point: list[float], polygon: list[list[float]]) -> bool:
    if len(polygon) < 3:
        return False

    x, z = point
    inside = False
    j = len(polygon) - 1
    for i, current in enumerate(polygon):
        xi, zi = current
        xj, zj = polygon[j]
        crosses = (zi > z) != (zj > z)
        if crosses:
            x_at_z = (xj - xi) * (z - zi) / (zj - zi) + xi
            if x < x_at_z:
                inside = not inside
        j = i
    return inside


def object_aabb(obj: dict[str, Any]) -> tuple[float, float, float, float]:
    corners = obj.get("footprint", [])
    if not corners:
        position = vec3(obj.get("transform", {}).get("position"))
        size = bbox(obj.get("placement", {}).get("bbox_size"))
        return (
            position["x"] - size["x"] * 0.5,
            position["z"] - size["z"] * 0.5,
            position["x"] + size["x"] * 0.5,
            position["z"] + size["z"] * 0.5,
        )
    xs = [corner[0] for corner in corners]
    zs = [corner[1] for corner in corners]
    return min(xs), min(zs), max(xs), max(zs)


def aabb_gap(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    dx = max(left[0] - right[2], right[0] - left[2], 0.0)
    dz = max(left[1] - right[3], right[1] - left[3], 0.0)
    if dx == 0.0 and dz == 0.0:
        overlap_x = min(left[2], right[2]) - max(left[0], right[0])
        overlap_z = min(left[3], right[3]) - max(left[1], right[1])
        return -min(overlap_x, overlap_z)
    return math.hypot(dx, dz)


def yaw_delta(dependent_yaw: float, anchor_yaw: float) -> float:
    delta = (dependent_yaw - anchor_yaw + 180.0) % 360.0 - 180.0
    return delta


def object_index(scene: dict[str, Any]) -> dict[str, dict[str, Any]]:
    objects = {obj["id"]: obj for obj in scene.get("objects", [])}
    for entrance in scene.get("site", {}).get("anchors", {}).get("entrances", []):
        world = entrance.get("world", {})
        objects[entrance["id"]] = {
            "id": entrance["id"],
            "source": {"kind": "site_anchor", "facility_type": "entrance", "category": "access"},
            "prefab": {"name": "SITE_ENTRANCE", "path": "", "assembly_type": "site_anchor"},
            "placement": {"bbox_size": {"x": 0.0, "y": 0.0, "z": 0.0}},
            "transform": {
                "position": {"x": world.get("x", 0.0), "y": 0.0, "z": world.get("z", 0.0)},
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
            },
            "anchors": {"support_id": "ground_00", "functional_id": None},
        }
    return objects


def site_features(scene: dict[str, Any]) -> dict[str, Any]:
    site = scene.get("site", {})
    source_layout = scene.get("source_layout", {})
    bounds = site.get("bounds", {})
    width = float(bounds.get("max_x", 0.0)) - float(bounds.get("min_x", 0.0))
    length = float(bounds.get("max_z", 0.0)) - float(bounds.get("min_z", 0.0))
    return {
        "site_width": width,
        "site_length": length,
        "site_area": max(0.0, width * length),
        "entrance_count": len(site.get("anchors", {}).get("entrances", [])),
        "road_zone_count": len(scene.get("site_visuals", {}).get("road_zones", [])),
        "source_layout_id": source_layout.get("id"),
        "source_objectives": source_layout.get("objectives", {}),
        "source_behaviors": source_layout.get("behaviors", {}),
        "source_feasibility": source_layout.get("feasibility", {}),
    }


def normalized_position(position: dict[str, float], site: dict[str, Any]) -> dict[str, float]:
    width = max(1e-6, float(site["site_width"]))
    length = max(1e-6, float(site["site_length"]))
    return {"x": position["x"] / width, "z": position["z"] / length}


def source_label(obj: dict[str, Any]) -> str:
    source = obj.get("source", {})
    kind = source.get("kind", "unknown")
    facility_type = source.get("facility_type", "unknown")
    return f"{kind}:{facility_type}"


def scene_geometry_features(scene: dict[str, Any]) -> dict[str, Any]:
    objects = scene.get("objects", [])
    primary_objects = [obj for obj in objects if obj.get("source", {}).get("kind") == "primary"]
    site = scene.get("site", {})
    bounds = site.get("bounds", {})
    boundary = site.get("boundary_polygon", [])
    exclusion_zones = site.get("exclusion_zones", [])

    overlap_pairs = 0
    min_primary_aabb_gap = None
    for index, left in enumerate(primary_objects):
        left_aabb = object_aabb(left)
        for right in primary_objects[index + 1 :]:
            gap = aabb_gap(left_aabb, object_aabb(right))
            if min_primary_aabb_gap is None or gap < min_primary_aabb_gap:
                min_primary_aabb_gap = gap
            if gap < 0.0:
                overlap_pairs += 1

    boundary_corner_violations = 0
    exclusion_center_hits = 0
    rectangular_margin_min = None
    for obj in primary_objects:
        min_x, min_z, max_x, max_z = object_aabb(obj)
        margins = [
            min_x - float(bounds.get("min_x", 0.0)),
            float(bounds.get("max_x", 0.0)) - max_x,
            min_z - float(bounds.get("min_z", 0.0)),
            float(bounds.get("max_z", 0.0)) - max_z,
        ]
        obj_margin = min(margins)
        rectangular_margin_min = obj_margin if rectangular_margin_min is None else min(rectangular_margin_min, obj_margin)
        if boundary:
            boundary_corner_violations += sum(1 for corner in obj.get("footprint", []) if not point_in_polygon(corner, boundary))
        center = [vec3(obj.get("transform", {}).get("position"))["x"], vec3(obj.get("transform", {}).get("position"))["z"]]
        for zone in exclusion_zones:
            if point_in_polygon(center, zone.get("polygon", [])):
                exclusion_center_hits += 1

    return {
        "primary_count": len(primary_objects),
        "primary_aabb_overlap_pairs": overlap_pairs,
        "primary_min_aabb_gap": min_primary_aabb_gap if min_primary_aabb_gap is not None else 999.0,
        "primary_boundary_corner_violations": boundary_corner_violations,
        "primary_exclusion_center_hits": exclusion_center_hits,
        "primary_min_rectangular_margin": rectangular_margin_min if rectangular_margin_min is not None else 999.0,
    }


def asset_selection_record(scene: dict[str, Any], obj: dict[str, Any], site: dict[str, Any]) -> dict[str, Any]:
    source = obj.get("source", {})
    prefab = obj.get("prefab", {})
    placement = obj.get("placement", {})
    transform = obj.get("transform", {})
    position = vec3(transform.get("position"))
    return {
        "task": "semantic_asset_selection",
        "scene_id": scene.get("scene_id"),
        "object_id": obj.get("id"),
        "input": {
            "source_kind": source.get("kind"),
            "facility_type": source.get("facility_type"),
            "category": source.get("category"),
            "facility_index": source.get("facility_index"),
            "bbox_size": bbox(placement.get("bbox_size")),
            "clearance_radius_m": placement.get("clearance_radius_m"),
            "normalized_position": normalized_position(position, site),
            "site": site,
        },
        "target": {
            "prefab_name": prefab.get("name"),
            "prefab_path": prefab.get("path"),
            "assembly_type": prefab.get("assembly_type"),
            "construction_class": prefab.get("construction_class"),
            "relation_role": prefab.get("relation_role"),
            "suggested_support_type": prefab.get("suggested_support_type"),
            "visual_variant": source.get("visual_variant"),
        },
    }


def relation_record(
    scene: dict[str, Any],
    dependent: dict[str, Any],
    anchor: dict[str, Any] | None,
    site: dict[str, Any],
    relation_source: str,
) -> dict[str, Any]:
    dep_transform = dependent.get("transform", {})
    dep_position = vec3(dep_transform.get("position"))
    dep_rotation = vec3(dep_transform.get("rotation"))
    anchor_position = vec3(anchor.get("transform", {}).get("position")) if anchor else {"x": 0.0, "y": 0.0, "z": 0.0}
    anchor_rotation = vec3(anchor.get("transform", {}).get("rotation")) if anchor else {"x": 0.0, "y": 0.0, "z": 0.0}

    return {
        "task": "relation_aware_placement",
        "scene_id": scene.get("scene_id"),
        "dependent_id": dependent.get("id"),
        "anchor_id": anchor.get("id") if anchor else None,
        "input": {
            "dependent_label": source_label(dependent),
            "dependent_bbox_size": bbox(dependent.get("placement", {}).get("bbox_size")),
            "dependent_prefab_name": dependent.get("prefab", {}).get("name"),
            "anchor_label": source_label(anchor) if anchor else "scene_root",
            "anchor_bbox_size": bbox(anchor.get("placement", {}).get("bbox_size")) if anchor else {"x": 0.0, "y": 0.0, "z": 0.0},
            "anchor_prefab_name": anchor.get("prefab", {}).get("name") if anchor else "scene_root",
            "relation_source": relation_source,
            "site": site,
        },
        "target": {
            "absolute_position": dep_position,
            "absolute_yaw": dep_rotation["y"],
            "relative_position": {
                "x": dep_position["x"] - anchor_position["x"],
                "y": dep_position["y"] - anchor_position["y"],
                "z": dep_position["z"] - anchor_position["z"],
            },
            "relative_yaw": yaw_delta(dep_rotation["y"], anchor_rotation["y"]),
            "distance_xz": distance_xz(dep_position, anchor_position),
        },
    }


def scene_record(scene: dict[str, Any], path: Path) -> dict[str, Any]:
    objects = scene.get("objects", [])
    validation = scene.get("validation_report", {})
    enrichment = scene.get("scene_enrichment", {})
    by_label: dict[str, int] = {}
    for obj in objects:
        label = source_label(obj)
        by_label[label] = by_label.get(label, 0) + 1
    return {
        "task": "scene_realism_summary",
        "scene_id": scene.get("scene_id"),
        "scene_path": str(path),
        "input": {
            "site": site_features(scene),
            "geometry": scene_geometry_features(scene),
            "object_count": len(objects),
            "object_count_by_label": by_label,
            "scatter_summary": enrichment.get("summary", {}),
            "generation_seed": enrichment.get("seed"),
        },
        "target": {
            "validation_status": validation.get("status"),
            "issue_count": validation.get("issue_count"),
            "issues": validation.get("issues", []),
            "is_training_clean": validation.get("status") == "pass",
            "optimizer_safe": scene.get("source_layout", {}).get("feasibility", {}).get("safe"),
            "optimizer_violations": scene.get("source_layout", {}).get("feasibility", {}).get("violations", []),
            "combined_score": scene.get("source_layout", {}).get("objectives", {}).get("combined_score"),
        },
    }


def export_scene(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    scene = load_json(path)
    objects_by_id = object_index(scene)
    objects = scene.get("objects", [])
    site = site_features(scene)

    asset_rows = [asset_selection_record(scene, obj, site) for obj in objects]

    relation_rows = []
    relation_tuples = scene.get("relations", {}).get("tuples", [])
    tuple_source_by_id = {
        item.get("dependent_id"): item.get("relation_source", "unknown")
        for item in relation_tuples
    }
    for obj in objects:
        anchor_id = obj.get("anchors", {}).get("functional_id") or obj.get("anchors", {}).get("support_id")
        anchor = objects_by_id.get(anchor_id)
        relation_rows.append(
            relation_record(
                scene=scene,
                dependent=obj,
                anchor=anchor,
                site=site,
                relation_source=tuple_source_by_id.get(obj.get("id"), "unknown"),
            )
        )

    return asset_rows, relation_rows, scene_record(scene, path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "scenes",
        nargs="*",
        type=Path,
        help="Compiled Unity scene JSON files. Defaults to output/*_unity_scene.json.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=ROOT / "output" / "ml_dataset",
        help="Directory for exported JSONL dataset files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scene_paths = args.scenes or sorted((ROOT / "output").glob("*_unity_scene.json"))
    scene_paths = [path.resolve() for path in scene_paths if path.exists()]
    if not scene_paths:
        raise SystemExit("No scene JSON files found.")

    asset_rows: list[dict[str, Any]] = []
    relation_rows: list[dict[str, Any]] = []
    scene_rows: list[dict[str, Any]] = []

    for path in scene_paths:
        scene_asset_rows, scene_relation_rows, summary_row = export_scene(path)
        asset_rows.extend(scene_asset_rows)
        relation_rows.extend(scene_relation_rows)
        scene_rows.append(summary_row)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.output_dir / "asset_selection.jsonl", asset_rows)
    write_jsonl(args.output_dir / "relation_placement.jsonl", relation_rows)
    write_jsonl(args.output_dir / "scene_realism.jsonl", scene_rows)

    manifest = {
        "scene_count": len(scene_paths),
        "asset_selection_records": len(asset_rows),
        "relation_placement_records": len(relation_rows),
        "scene_realism_records": len(scene_rows),
        "source_scenes": [str(path) for path in scene_paths],
        "files": {
            "asset_selection": str(args.output_dir / "asset_selection.jsonl"),
            "relation_placement": str(args.output_dir / "relation_placement.jsonl"),
            "scene_realism": str(args.output_dir / "scene_realism.jsonl"),
        },
    }
    with (args.output_dir / "manifest.json").open("w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=2)

    print(f"Wrote ML dataset to {args.output_dir}")
    print(f"Scenes: {manifest['scene_count']}")
    print(f"Asset-selection records: {manifest['asset_selection_records']}")
    print(f"Relation-placement records: {manifest['relation_placement_records']}")
    print(f"Scene-realism records: {manifest['scene_realism_records']}")


if __name__ == "__main__":
    main()
