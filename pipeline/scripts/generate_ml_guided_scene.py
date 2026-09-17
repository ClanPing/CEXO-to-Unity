#!/usr/bin/env python3
"""Generate a Unity scene JSON with hybrid ML-guided accessories.

This script keeps the raw optimized layout as the authority for primary
facilities, then lets the trained zone models make the scene dressing more
relation-aware:

- zone asset MLP proposes additional accessory prefab types per primary zone
- accessory placement MLP predicts relative x/z/yaw around each zone
- existing geometric validation decides whether a predicted placement is kept
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import random
from collections import Counter
from pathlib import Path
from typing import Any

import torch

import layout_to_scene
from export_zone_asset_dataset import export_scene as export_zone_asset_rows
from export_zone_asset_placement_dataset import placement_record
from train_zone_asset_mlp import ZoneAssetMLP, row_features as asset_row_features
from train_zone_asset_placement_mlp import ZoneAssetPlacementMLP, row_features as placement_row_features


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = (
    ROOT / "config" / "asset_catalog.generated.json"
    if (ROOT / "config" / "asset_catalog.generated.json").exists()
    else ROOT / "config" / "asset_catalog.json"
)

SEMANTIC_ACCESSORY_ALLOWLIST: dict[str, set[str]] = {
    "office": {
        "traffic_cone",
        "barrel",
        "floodlight_stand",
        "generator",
        "trash_decal",
    },
    "rest_area": {
        "traffic_cone",
        "barrel",
        "water_tank",
        "hose",
        "trash_decal",
        "paint_can",
    },
    "storage": {
        "pallet",
        "concrete_bag",
        "concrete_brick",
        "storage_pipe",
        "plywood_stack",
        "plank_stack",
        "log_tarp",
        "road_block",
        "traffic_cone",
        "barrel",
        "toolbox",
        "ladder",
        "trash_decal",
    },
    "core": {
        "scaffold_panel",
        "scaffold_corner",
        "generator",
        "hose",
        "floodlight_stand",
        "ladder",
        "toolbox",
        "paint_can",
        "dirt_decal",
        "concrete_mixer",
        "construction_lift",
        "traffic_cone",
        "barrel",
    },
    "crane": {
        "traffic_cone",
        "barrel",
        "road_block",
        "road_closure",
        "dirt_decal",
        "floodlight_stand",
    },
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
        file.write("\n")


def build_feature_vector(features: dict[str, float], feature_names: list[str]) -> torch.Tensor:
    return torch.tensor([[features.get(name, 0.0) for name in feature_names]], dtype=torch.float32)


def standardize_for_inference(x: torch.Tensor, mean: torch.Tensor, std: torch.Tensor, clamp: float = 6.0) -> torch.Tensor:
    """Standardize inference features while limiting out-of-domain spikes."""
    return torch.clamp((x - mean) / std, min=-clamp, max=clamp)


def load_asset_model(model_path: Path) -> tuple[ZoneAssetMLP, dict[str, Any]]:
    checkpoint = torch.load(model_path, map_location="cpu")
    model = ZoneAssetMLP(len(checkpoint["feature_names"]), len(checkpoint["label_names"]))
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    return model, checkpoint


def load_placement_model(model_path: Path) -> tuple[ZoneAssetPlacementMLP, dict[str, Any]]:
    checkpoint = torch.load(model_path, map_location="cpu")
    model = ZoneAssetPlacementMLP(len(checkpoint["feature_names"]))
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    return model, checkpoint


def yaw_from_sincos(sin_value: float, cos_value: float) -> float:
    return math.degrees(math.atan2(sin_value, cos_value))


def prefab_name_to_accessory_key() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for key, prefab in layout_to_scene.ACCESSORY_PREFABS.items():
        mapping[prefab["name"]] = key
    return mapping


def is_semantically_compatible(zone: dict[str, Any], accessory_key: str) -> bool:
    facility_type = zone.get("source", {}).get("facility_type", "unknown")
    allowed = SEMANTIC_ACCESSORY_ALLOWLIST.get(facility_type)
    if allowed is None:
        return True
    return accessory_key in allowed


def primary_objects(scene: dict[str, Any]) -> list[dict[str, Any]]:
    return [obj for obj in scene.get("objects", []) if obj.get("source", {}).get("kind") == "primary"]


def accessory_objects(scene: dict[str, Any]) -> list[dict[str, Any]]:
    return [obj for obj in scene.get("objects", []) if obj.get("source", {}).get("kind") == "accessory"]


def rule_scatter_objects(scene: dict[str, Any]) -> list[dict[str, Any]]:
    return [obj for obj in scene.get("objects", []) if obj.get("source", {}).get("kind") == "rule_scatter"]


def attached_to_zone(zone: dict[str, Any], objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    zone_id = zone["id"]
    attached = []
    for obj in objects:
        source = obj.get("source", {})
        anchors = obj.get("anchors", {})
        if source.get("parent_id") == zone_id or anchors.get("functional_id") == zone_id:
            attached.append(obj)
    return attached


def predict_zone_assets(
    scene_path: Path,
    asset_model: ZoneAssetMLP,
    checkpoint: dict[str, Any],
    top_k: int,
) -> dict[str, list[dict[str, Any]]]:
    feature_names = checkpoint["feature_names"]
    label_names = checkpoint["label_names"]
    mean = checkpoint["mean"]
    std = checkpoint["std"]
    predictions: dict[str, list[dict[str, Any]]] = {}

    for row in export_zone_asset_rows(scene_path.resolve()):
        features = asset_row_features(row)
        x = build_feature_vector(features, feature_names)
        x = standardize_for_inference(x, mean, std)
        with torch.no_grad():
            probs = torch.sigmoid(asset_model(x)).squeeze(0)
        top = probs.topk(min(top_k, len(label_names)))
        predictions[row["zone_id"]] = [
            {"prefab_name": label_names[index], "probability": float(prob)}
            for prob, index in zip(top.values, top.indices)
        ]
    return predictions


def make_ml_accessory(
    object_id: str,
    parent: dict[str, Any],
    accessory_key: str,
    defaults: dict[str, Any],
    probability: float,
) -> dict[str, Any]:
    obj = layout_to_scene.accessory_object(object_id, parent, accessory_key, 0.0, 0.0, 0.0, defaults)
    obj["source"]["kind"] = "accessory"
    obj["source"]["placement_source"] = "ml_zone_asset_model"
    obj["prefab"]["selection_score"] = probability
    obj["placement"]["placement_notes"] = "ML-selected accessory; relation placement predicted by zone asset placement MLP"
    return obj


def add_ml_selected_accessories(
    scene: dict[str, Any],
    scene_path: Path,
    defaults: dict[str, Any],
    predictions: dict[str, list[dict[str, Any]]],
    probability_threshold: float,
    extras_per_zone: int,
    seed: int,
    semantic_filter: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if extras_per_zone <= 0:
        return [], {
            "added_count": 0,
            "candidate_count": 0,
            "skipped_count": 0,
            "incompatible_count": 0,
            "semantic_filter_enabled": semantic_filter,
        }

    rng = random.Random(seed + 901)
    key_by_name = prefab_name_to_accessory_key()
    objects = scene["objects"]
    primaries = primary_objects(scene)
    next_index = len(objects) + 1
    added: list[dict[str, Any]] = []
    candidate_count = 0
    skipped_count = 0
    incompatible_count = 0
    accepted_by_facility: dict[str, Counter[str]] = {}

    for zone in primaries:
        facility_type = zone.get("source", {}).get("facility_type", "unknown")
        existing_names = {obj.get("prefab", {}).get("name") for obj in attached_to_zone(zone, objects + added)}
        zone_prefab_name = zone.get("prefab", {}).get("name")
        if zone_prefab_name:
            existing_names.add(zone_prefab_name)
        added_for_zone = 0
        for prediction in predictions.get(zone["id"], []):
            prefab_name = prediction["prefab_name"]
            probability = float(prediction["probability"])
            if probability < probability_threshold:
                continue
            if prefab_name in existing_names:
                continue
            accessory_key = key_by_name.get(prefab_name)
            if not accessory_key:
                continue
            if semantic_filter and not is_semantically_compatible(zone, accessory_key):
                incompatible_count += 1
                continue
            candidate_count += 1
            object_id = f"obj_{next_index:04d}"
            next_index += 1
            candidate = make_ml_accessory(object_id, zone, accessory_key, defaults, probability)
            # Tiny jitter before ML placement gives duplicate fallback positions stable but not identical.
            candidate["transform"]["rotation"]["y"] = zone["transform"]["rotation"]["y"] + rng.choice([0.0, 15.0, 30.0, 45.0])
            added.append(candidate)
            accepted_by_facility.setdefault(facility_type, Counter())[accessory_key] += 1
            existing_names.add(prefab_name)
            added_for_zone += 1
            if added_for_zone >= extras_per_zone:
                break
        skipped_count += max(0, len(predictions.get(zone["id"], [])) - added_for_zone)

    return added, {
        "added_count": len(added),
        "candidate_count": candidate_count,
        "skipped_count": skipped_count,
        "incompatible_count": incompatible_count,
        "semantic_filter_enabled": semantic_filter,
        "accepted_accessory_keys_by_facility": {
            facility_type: dict(counter)
            for facility_type, counter in sorted(accepted_by_facility.items())
        },
        "semantic_allowlist": {
            facility_type: sorted(keys)
            for facility_type, keys in sorted(SEMANTIC_ACCESSORY_ALLOWLIST.items())
        },
    }


def predict_relative_placement(
    row: dict[str, Any],
    placement_model: ZoneAssetPlacementMLP,
    checkpoint: dict[str, Any],
) -> tuple[float, float, float]:
    features = placement_row_features(row)
    x = build_feature_vector(features, checkpoint["feature_names"])
    x = standardize_for_inference(x, checkpoint["x_mean"], checkpoint["x_std"])
    with torch.no_grad():
        pred = placement_model(x).squeeze(0)
    pred = pred * checkpoint["y_std"] + checkpoint["y_mean"]
    return float(pred[0]), float(pred[1]), yaw_from_sincos(float(pred[2]), float(pred[3]))


def update_object_transform_from_prediction(obj: dict[str, Any], zone: dict[str, Any], rel_x: float, rel_z: float, rel_yaw: float) -> None:
    zone_position = zone["transform"]["position"]
    zone_yaw = float(zone["transform"]["rotation"]["y"])
    position = obj["transform"]["position"]
    position["x"] = zone_position["x"] + rel_x
    position["y"] = zone_position["y"]
    position["z"] = zone_position["z"] + rel_z
    obj["transform"]["rotation"]["y"] = zone_yaw + rel_yaw
    bbox = obj["placement"]["bbox_size"]
    obj["footprint"] = layout_to_scene.rectangle_corners_xz(
        position["x"],
        position["z"],
        float(bbox["x"]),
        float(bbox["z"]),
        float(obj["transform"]["rotation"]["y"]),
    )


def fallback_relative_placements(zone: dict[str, Any], obj: dict[str, Any], rel_yaw: float) -> list[tuple[float, float, float]]:
    zone_bbox = zone.get("placement", {}).get("bbox_size", {})
    obj_bbox = obj.get("placement", {}).get("bbox_size", {})
    half_x = float(zone_bbox.get("x", 1.0)) * 0.5
    half_z = float(zone_bbox.get("z", 1.0)) * 0.5
    obj_half_x = float(obj_bbox.get("x", 0.5)) * 0.5
    obj_half_z = float(obj_bbox.get("z", 0.5)) * 0.5
    base_radius = max(half_x + obj_half_x, half_z + obj_half_z) + 1.0
    candidates: list[tuple[float, float, float]] = []
    for radius in (base_radius, base_radius + 1.5, base_radius + 3.0):
        for angle in (0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0):
            theta = math.radians(angle)
            candidates.append((math.cos(theta) * radius, math.sin(theta) * radius, rel_yaw))
    return candidates


def try_fallback_placement(
    obj: dict[str, Any],
    zone: dict[str, Any],
    placed_without_candidate: list[dict[str, Any]],
    site: dict[str, Any],
    entrances: list[dict[str, Any]],
    min_spacing: float,
    rel_yaw: float,
) -> bool:
    for fallback_x, fallback_z, fallback_yaw in fallback_relative_placements(zone, obj, rel_yaw):
        candidate = copy.deepcopy(obj)
        update_object_transform_from_prediction(candidate, zone, fallback_x, fallback_z, fallback_yaw)
        if layout_to_scene.is_valid_scatter_position(
            candidate,
            placed_without_candidate,
            site,
            entrances,
            min_spacing=min_spacing,
            allowed_overlap_ids={zone["id"]},
        ):
            update_object_transform_from_prediction(obj, zone, fallback_x, fallback_z, fallback_yaw)
            obj["source"]["placement_source"] = "ml_zone_asset_model"
            obj["source"]["placement_strategy"] = "validated_fallback_ring"
            obj["placement"]["placement_notes"] = (
                "ML-selected accessory kept with validated local fallback placement "
                "after the placement MLP predicted an invalid position"
            )
            return True
    return False


def apply_ml_placements(
    scene: dict[str, Any],
    scene_path: Path,
    placement_model: ZoneAssetPlacementMLP,
    checkpoint: dict[str, Any],
    min_spacing: float,
) -> dict[str, Any]:
    site = scene["site"]
    entrances = scene["site"]["anchors"]["entrances"]
    primaries = primary_objects(scene)
    objects = scene["objects"]
    accepted = 0
    rejected = 0
    fallback_accepted = 0
    fallback_rejected = 0
    remove_ids: set[str] = set()
    predictions = []

    for zone in primaries:
        attached = [obj for obj in attached_to_zone(zone, objects) if obj.get("source", {}).get("kind") == "accessory"]
        totals: Counter[str] = Counter(obj.get("prefab", {}).get("name") for obj in attached)
        seen: Counter[str] = Counter()
        for obj in attached:
            prefab_name = obj.get("prefab", {}).get("name")
            occurrence_index = seen[prefab_name]
            seen[prefab_name] += 1
            row = placement_record(
                scene,
                scene_path,
                zone,
                obj,
                primaries,
                occurrence_index=occurrence_index,
                occurrence_count=totals[prefab_name],
            )
            rel_x, rel_z, rel_yaw = predict_relative_placement(row, placement_model, checkpoint)
            candidate = copy.deepcopy(obj)
            update_object_transform_from_prediction(candidate, zone, rel_x, rel_z, rel_yaw)
            placed_without_candidate = [other for other in objects if other["id"] != obj["id"]]
            if layout_to_scene.is_valid_scatter_position(
                candidate,
                placed_without_candidate,
                site,
                entrances,
                min_spacing=min_spacing,
                allowed_overlap_ids={zone["id"]},
            ):
                update_object_transform_from_prediction(obj, zone, rel_x, rel_z, rel_yaw)
                obj["source"]["placement_source"] = obj["source"].get("placement_source", "ml_zone_asset_placement_model")
                obj["placement"]["placement_notes"] = "accessory placement predicted by zone asset placement MLP"
                accepted += 1
                kept = True
            else:
                rejected += 1
                is_ml_added = obj.get("source", {}).get("placement_source") == "ml_zone_asset_model"
                if is_ml_added and try_fallback_placement(
                    obj,
                    zone,
                    placed_without_candidate,
                    site,
                    entrances,
                    min_spacing,
                    rel_yaw,
                ):
                    fallback_accepted += 1
                    kept = True
                else:
                    if is_ml_added:
                        remove_ids.add(obj["id"])
                        fallback_rejected += 1
                    kept = False
            predictions.append(
                {
                    "zone_id": zone["id"],
                    "object_id": obj["id"],
                    "prefab_name": prefab_name,
                    "relative_x": round(rel_x, 3),
                    "relative_z": round(rel_z, 3),
                    "relative_yaw": round(rel_yaw, 2),
                    "accepted": kept,
                    "fallback": obj.get("source", {}).get("placement_strategy") == "validated_fallback_ring",
                }
            )

    if remove_ids:
        scene["objects"] = [obj for obj in scene["objects"] if obj["id"] not in remove_ids]

    return {
        "attempted_count": accepted + rejected,
        "accepted_count": accepted,
        "rejected_count": rejected,
        "fallback_accepted_count": fallback_accepted,
        "fallback_rejected_count": fallback_rejected,
        "removed_ml_added_count": len(remove_ids),
        "min_spacing_m": min_spacing,
        "predictions": predictions[:80],
    }


def rebuild_scene_graph(scene: dict[str, Any]) -> None:
    objects = scene["objects"]
    entrances = scene["site"]["anchors"]["entrances"]
    relations = layout_to_scene.attach_relations(objects, entrances)
    scene["relations"] = relations
    scene["generation_order"] = layout_to_scene.generation_order(objects, relations)
    scene["validation_report"] = layout_to_scene.validate_scene(scene["site"], objects)
    scene["stats"].update(
        {
            "object_count": len(objects),
            "primary_count": len(primary_objects(scene)),
            "accessory_count": len(accessory_objects(scene)),
            "rule_scatter_count": len(rule_scatter_objects(scene)),
        }
    )


def generate_ml_guided_scene(args: argparse.Namespace) -> dict[str, Any]:
    input_path = args.input.resolve()
    defaults_path = args.defaults.resolve()
    catalog_path = args.catalog.resolve()
    defaults = load_json(defaults_path)

    scene = layout_to_scene.compile_layout(
        input_path,
        defaults_path,
        catalog_path,
        scatter_seed=args.scatter_seed,
        enable_scatter=not args.no_scatter,
    )
    seed = scene["scene_enrichment"]["seed"]
    temporary_scene_path = args.output.resolve() if args.output else ROOT / "output" / f"{input_path.stem}_ml_guided_unity_scene.json"
    write_json(temporary_scene_path, scene)

    asset_model, asset_checkpoint = load_asset_model(args.asset_model.resolve())
    placement_model, placement_checkpoint = load_placement_model(args.placement_model.resolve())
    zone_predictions = predict_zone_assets(temporary_scene_path, asset_model, asset_checkpoint, args.asset_top_k)
    ml_added, add_report = add_ml_selected_accessories(
        scene,
        temporary_scene_path,
        defaults,
        zone_predictions,
        args.asset_probability_threshold,
        args.ml_extras_per_zone,
        seed,
        semantic_filter=not args.disable_semantic_filter,
    )
    scene["objects"].extend(ml_added)
    placement_report = apply_ml_placements(scene, temporary_scene_path, placement_model, placement_checkpoint, args.min_spacing)
    scene["pipeline"]["name"] = "pair2scene-lite-construction-ml-guided"
    scene["pipeline"]["version"] = "0.2.0"
    scene["pipeline"]["description"] = "Raw layout JSON -> hybrid ML asset selection and relation-aware accessory placement -> validated Unity scene JSON"
    scene["ml_guidance"] = {
        "enabled": True,
        "asset_model": str(args.asset_model),
        "placement_model": str(args.placement_model),
        "asset_probability_threshold": args.asset_probability_threshold,
        "asset_top_k": args.asset_top_k,
        "ml_extras_per_zone": args.ml_extras_per_zone,
        "semantic_filter_enabled": not args.disable_semantic_filter,
        "asset_selection": {
            "zone_predictions": {
                zone_id: [
                    {"prefab_name": item["prefab_name"], "probability": round(float(item["probability"]), 4)}
                    for item in predictions
                ]
                for zone_id, predictions in zone_predictions.items()
            },
            **add_report,
        },
        "placement": placement_report,
        "notes": [
            "Primary optimized layout facilities are unchanged.",
            "ML-selected accessories are added only when their prefab name maps to the known accessory catalog.",
            "Semantic compatibility filters prevent storage-like clutter from being attached to admin/rest/crane zones.",
            "ML-predicted placements are kept only if they pass boundary, exclusion, entrance, and overlap checks.",
        ],
    }
    rebuild_scene_graph(scene)
    scene["ml_guidance"]["asset_selection"]["retained_ml_added_count"] = sum(
        1 for obj in scene["objects"] if obj.get("source", {}).get("placement_source") == "ml_zone_asset_model"
    )
    return scene


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Raw layout JSON path")
    parser.add_argument("-o", "--output", type=Path, help="Output Unity scene JSON path")
    parser.add_argument("--defaults", type=Path, default=ROOT / "config" / "facility_defaults.json")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--scatter-seed", type=int, default=None)
    parser.add_argument("--no-scatter", action="store_true")
    parser.add_argument(
        "--asset-model",
        type=Path,
        default=ROOT / "models" / "zone_asset_mlp" / "zone_asset_mlp.pt",
    )
    parser.add_argument(
        "--placement-model",
        type=Path,
        default=ROOT / "models" / "zone_asset_placement_mlp_accessory" / "zone_asset_placement_mlp.pt",
    )
    parser.add_argument("--asset-top-k", type=int, default=8)
    parser.add_argument("--asset-probability-threshold", type=float, default=0.35)
    parser.add_argument("--ml-extras-per-zone", type=int, default=1)
    parser.add_argument(
        "--disable-semantic-filter",
        action="store_true",
        help="Allow ML asset suggestions even when they do not match the facility-type compatibility rules.",
    )
    parser.add_argument("--min-spacing", type=float, default=0.15)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = args.output or ROOT / "output" / f"{args.input.stem}_ml_guided_unity_scene.json"
    scene = generate_ml_guided_scene(args)
    write_json(output_path.resolve(), scene)
    print(f"Wrote {output_path}")
    print(f"Objects: {scene['stats']['object_count']}")
    print(
        "ML added accessories: "
        f"{scene['ml_guidance']['asset_selection']['retained_ml_added_count']} retained "
        f"from {scene['ml_guidance']['asset_selection']['added_count']} proposed"
    )
    print(
        "ML placement: "
        f"{scene['ml_guidance']['placement']['accepted_count']} accepted, "
        f"{scene['ml_guidance']['placement']['rejected_count']} rejected"
    )
    print(f"Validation: {scene['validation_report']['status']} ({scene['validation_report']['issue_count']} issues)")


if __name__ == "__main__":
    main()
