#!/usr/bin/env python3
"""Compile raw construction-site layout JSON into a 3D-ready scene graph."""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
        file.write("\n")


def as_world_point(point: dict[str, float], site_width: float, site_length: float) -> dict[str, float]:
    return {
        "x": point["x"] * site_width,
        "z": point["y"] * site_length,
    }


def distance_xz(a: dict[str, float], b: dict[str, float]) -> float:
    return math.hypot(a["x"] - b["x"], a["z"] - b["z"])


def nearest_anchor(
    position: dict[str, float],
    candidates: list[dict[str, Any]],
    fallback: str = "ground_00",
) -> str:
    if not candidates:
        return fallback
    return min(candidates, key=lambda item: distance_xz(position, item["world"]))["id"]


def normalized_polygon_to_world(
    polygon: list[list[float]],
    site_width: float,
    site_length: float,
) -> list[list[float]]:
    return [[x * site_width, y * site_length] for x, y in polygon]


def rectangle_corners_xz(
    center_x: float,
    center_z: float,
    width: float,
    length: float,
    rotation_deg: float,
) -> list[list[float]]:
    half_w = width / 2.0
    half_l = length / 2.0
    theta = math.radians(rotation_deg)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    local = [(-half_w, -half_l), (half_w, -half_l), (half_w, half_l), (-half_w, half_l)]
    corners = []
    for lx, lz in local:
        x = center_x + lx * cos_t - lz * sin_t
        z = center_z + lx * sin_t + lz * cos_t
        corners.append([x, z])
    return corners


def infer_site(raw: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    site_defaults = defaults["site"]
    width = float(raw.get("site_width_m", site_defaults["default_width_m"]))
    length = float(raw.get("site_length_m", site_defaults["default_length_m"]))
    boundary = raw.get("boundary_polygon")
    exclusion_zones = raw.get("exclusion_zones", [])

    return {
        "coordinate_space": raw.get("coordinate_space", "normalized"),
        "bounds": {
            "min_x": 0.0,
            "max_x": width,
            "min_z": 0.0,
            "max_z": length,
        },
        "ground_y": float(site_defaults.get("ground_y", 0.0)),
        "boundary_polygon": normalized_polygon_to_world(boundary, width, length)
        if boundary
        else [[0.0, 0.0], [width, 0.0], [width, length], [0.0, length]],
        "exclusion_zones": [
            {
                "id": zone.get("name", f"exclusion_{index:03d}"),
                "polygon": normalized_polygon_to_world(zone.get("polygon", []), width, length),
            }
            for index, zone in enumerate(exclusion_zones)
        ],
    }


def build_entrances(raw: dict[str, Any], site: dict[str, Any]) -> list[dict[str, Any]]:
    width = site["bounds"]["max_x"]
    length = site["bounds"]["max_z"]
    entrances = []
    for index, entrance in enumerate(raw.get("entrances", [])):
        normalized = {"x": float(entrance["x"]), "y": float(entrance["y"])}
        entrances.append(
            {
                "id": f"entrance_{index:02d}",
                "index": index,
                "normalized": normalized,
                "world": as_world_point(normalized, width, length),
            }
        )
    return entrances


def point_xz_to_vector(point: list[float], y: float = 0.0) -> dict[str, float]:
    return {"x": point[0], "y": y, "z": point[1]}


def build_site_visuals(site: dict[str, Any], entrances: list[dict[str, Any]]) -> dict[str, Any]:
    ground_y = site["ground_y"]
    return {
        "boundary_points": [point_xz_to_vector(point, ground_y) for point in site.get("boundary_polygon", [])],
        "road_zones": [
            {
                "id": zone["id"],
                "polygon_points": [point_xz_to_vector(point, ground_y) for point in zone.get("polygon", [])],
            }
            for zone in site.get("exclusion_zones", [])
        ],
        "entrances": [
            {
                "id": entrance["id"],
                "position": {
                    "x": entrance["world"]["x"],
                    "y": ground_y,
                    "z": entrance["world"]["z"],
                },
            }
            for entrance in entrances
        ],
    }


def resolve_dimensions(
    facility: dict[str, Any],
    facility_type_defaults: dict[str, Any],
    site: dict[str, Any],
) -> dict[str, float]:
    site_width = site["bounds"]["max_x"]
    site_length = site["bounds"]["max_z"]
    width = float(facility.get("width", 0.0)) * site_width if "width" in facility else None
    length = float(facility.get("length", 0.0)) * site_length if "length" in facility else None
    return {
        "width_m": width if width and width > 0 else float(facility_type_defaults["width_m"]),
        "length_m": length if length and length > 0 else float(facility_type_defaults["length_m"]),
        "height_m": float(facility.get("height_m", facility_type_defaults["height_m"])),
    }


def select_prefab(
    facility_type: str,
    catalog: dict[str, list[dict[str, Any]]],
    variant_index: int = 0,
) -> dict[str, Any]:
    choices = catalog.get(facility_type) or catalog["unknown"]
    if facility_type in {"core", "crane"}:
        composite_choices = [choice for choice in choices if choice.get("assembly_type") == "compound_prefab"]
        if composite_choices:
            return composite_choices[variant_index % len(composite_choices)]
    viable_choices = [
        choice for choice in choices
        if choice.get("name") != "SM_Stock01_2"
        and not choice.get("name", "").endswith("_LOD0")
    ]
    if facility_type in {"office", "rest_area"}:
        viable_choices = [
            choice for choice in viable_choices
            if "Door" not in choice.get("name", "")
        ]
    if facility_type == "rest_area":
        rest_choices = [
            choice for choice in viable_choices
            if "Biotoilet" in choice.get("name", "") or "CargoContainer" in choice.get("name", "")
        ]
        viable_choices = rest_choices or viable_choices
    viable_choices = viable_choices or choices
    return viable_choices[variant_index % len(viable_choices)]


ACCESSORY_PREFABS: dict[str, dict[str, Any]] = {
    "traffic_cone": {
        "name": "SM_TrafficCone",
        "path": "Assets/ConstructionSite/Prefab/ConstructionSite/Props/SM_TrafficCone.prefab",
        "construction_class": "road_prop",
        "bbox_size": {"x": 0.2801, "y": 0.5015, "z": 0.2801},
    },
    "road_block": {
        "name": "SM_RoadBlock03",
        "path": "Assets/ConstructionSite/Prefab/Fence/SM_RoadBlock03.prefab",
        "construction_class": "fence",
        "bbox_size": {"x": 0.6255, "y": 0.7655, "z": 4.0040},
    },
    "fence": {
        "name": "SM_Fence05",
        "path": "Assets/ConstructionSite/Prefab/Fence/SM_Fence05.prefab",
        "construction_class": "fence",
        "bbox_size": {"x": 0.1354, "y": 2.8070, "z": 4.8223},
    },
    "pallet": {
        "name": "SM_Pallet01",
        "path": "Assets/ConstructionSite/Prefab/Storage/SM_Pallet01.prefab",
        "construction_class": "pallet",
        "bbox_size": {"x": 1.2574, "y": 0.1686, "z": 1.1430},
    },
    "concrete_bag": {
        "name": "SM_ConcreteBag02",
        "path": "Assets/ConstructionSite/Prefab/Storage/SM_ConcreteBag02.prefab",
        "construction_class": "material",
        "bbox_size": {"x": 1.3779, "y": 1.2380, "z": 1.1463},
    },
    "concrete_brick": {
        "name": "SM_ConcreteBrick04",
        "path": "Assets/ConstructionSite/Prefab/Storage/SM_ConcreteBrick04.prefab",
        "construction_class": "material",
        "bbox_size": {"x": 1.2885, "y": 1.3385, "z": 1.3181},
    },
    "barrel": {
        "name": "SM_TrafficBarrel01",
        "path": "Assets/ConstructionSite/Prefab/IndustryPropsPack6/SM_TrafficBarrel01.prefab",
        "construction_class": "small_prop",
        "bbox_size": {"x": 0.8107, "y": 0.9540, "z": 0.8107},
    },
    "floodlight": {
        "name": "SM_FloodlightTower03",
        "path": "Assets/ConstructionSite/Prefab/ConstructionSite/SM_FloodlightTower03.prefab",
        "construction_class": "light",
        "bbox_size": {"x": 2.1487, "y": 11.8591, "z": 2.8312},
    },
    "water_tank": {
        "name": "SM_WaterTank01",
        "path": "Assets/ConstructionSite/Prefab/IndustryPropsPack6/SM_WaterTank01.prefab",
        "construction_class": "small_prop",
        "bbox_size": {"x": 1.2862, "y": 1.4680, "z": 1.2519},
    },
    "wheelbarrow": {
        "name": "SM_WheelBarrow01",
        "path": "Assets/ConstructionSite/Prefab/ConstructionSite/SM_WheelBarrow01.prefab",
        "construction_class": "small_prop",
        "bbox_size": {"x": 0.5641, "y": 0.6210, "z": 1.4111},
    },
    "scaffold_panel": {
        "name": "SM_Scaffolding09",
        "path": "Assets/ConstructionSite/Prefab/Building/Scaffolding/SM_Scaffolding09.prefab",
        "construction_class": "scaffold",
        "bbox_size": {"x": 0.1960, "y": 4.1058, "z": 3.9655},
    },
    "scaffold_corner": {
        "name": "SM_Scaffolding12",
        "path": "Assets/ConstructionSite/Prefab/Building/Scaffolding/SM_Scaffolding12.prefab",
        "construction_class": "scaffold",
        "bbox_size": {"x": 0.9034, "y": 4.0396, "z": 1.5145},
    },
    "generator": {
        "name": "SM_MobileGenerator01",
        "path": "Assets/ConstructionSite/Prefab/ConstructionSite/SM_MobileGenerator01.prefab",
        "construction_class": "small_prop",
        "bbox_size": {"x": 1.2983, "y": 1.2378, "z": 3.0807},
    },
    "hose": {
        "name": "SM_Hose02",
        "path": "Assets/ConstructionSite/Prefab/ConstructionSite/SM_Hose02.prefab",
        "construction_class": "small_prop",
        "bbox_size": {"x": 0.9922, "y": 0.4178, "z": 0.8063},
    },
    "storage_pipe": {
        "name": "SM_StoragePipe03_2",
        "path": "Assets/ConstructionSite/Prefab/ConstructionSite/SM_StoragePipe03_2.prefab",
        "construction_class": "material",
        "bbox_size": {"x": 7.0296, "y": 2.0269, "z": 2.6638},
    },
    "plywood_stack": {
        "name": "SM_Plywood04Tarp",
        "path": "Assets/ConstructionSite/Prefab/ConstructionSite/SM_Plywood04Tarp.prefab",
        "construction_class": "material",
        "bbox_size": {"x": 1.5140, "y": 1.0282, "z": 4.7773},
    },
    "plank_stack": {
        "name": "SM_PlankWood08",
        "path": "Assets/ConstructionSite/Prefab/ConstructionSite/SM_PlankWood08.prefab",
        "construction_class": "material",
        "bbox_size": {"x": 0.6055, "y": 0.3402, "z": 5.9934},
    },
    "workbench": {
        "name": "SM_Worknench",
        "path": "Assets/ConstructionSite/Prefab/ConstructionSite/Props/SM_Worknench.prefab",
        "construction_class": "small_prop",
        "bbox_size": {"x": 1.7942, "y": 1.0164, "z": 0.9921},
    },
    "floodlight_stand": {
        "name": "SM_FloodlightStand",
        "path": "Assets/ConstructionSite/Prefab/ConstructionSite/Props/SM_FloodlightStand.prefab",
        "construction_class": "light",
        "bbox_size": {"x": 0.7064, "y": 1.4859, "z": 0.6150},
    },
    "dirt_decal": {
        "name": "Dirt",
        "path": "Assets/ConstructionSite/Prefab/Decal/Dirt.prefab",
        "construction_class": "ground_detail",
        "bbox_size": {"x": 5.0000, "y": 0.0000, "z": 2.5000},
    },
    "trash_decal": {
        "name": "TrashDecal02",
        "path": "Assets/ConstructionSite/Prefab/Decal/TrashDecal02.prefab",
        "construction_class": "ground_detail",
        "bbox_size": {"x": 2.0000, "y": 0.0000, "z": 2.0000},
    },
    "ladder": {
        "name": "SM_Ladder",
        "path": "Assets/ConstructionSite/Prefab/ConstructionSite/Props/SM_Ladder.prefab",
        "construction_class": "small_prop",
        "bbox_size": {"x": 0.6748, "y": 1.7229, "z": 1.2334},
    },
    "toolbox": {
        "name": "SM_ToolBox",
        "path": "Assets/ConstructionSite/Prefab/ConstructionSite/Props/SM_ToolBox.prefab",
        "construction_class": "small_prop",
        "bbox_size": {"x": 0.7284, "y": 0.3437, "z": 0.2590},
    },
    "paint_can": {
        "name": "SM_PaintCan01",
        "path": "Assets/ConstructionSite/Prefab/ConstructionSite/Props/SM_PaintCan01.prefab",
        "construction_class": "small_prop",
        "bbox_size": {"x": 0.2358, "y": 0.2855, "z": 0.2332},
    },
    "road_closure": {
        "name": "SM_RoadClosure02",
        "path": "Assets/ConstructionSite/Prefab/ConstructionSite/SM_RoadClosure02.prefab",
        "construction_class": "road_prop",
        "bbox_size": {"x": 0.8037, "y": 1.0540, "z": 0.9450},
    },
    "stock_stack": {
        "name": "SM_Stock01_2",
        "path": "Assets/ConstructionSite/Prefab/ConstructionSite/SM_Stock01_2.prefab",
        "construction_class": "material",
        "bbox_size": {"x": 3.8197, "y": 1.9483, "z": 1.9901},
    },
    "log_tarp": {
        "name": "SM_Log02Tarp",
        "path": "Assets/ConstructionSite/Prefab/ConstructionSite/SM_Log02Tarp.prefab",
        "construction_class": "material",
        "bbox_size": {"x": 1.5019, "y": 1.4678, "z": 6.5331},
    },
    "concrete_mixer": {
        "name": "SM_ConcreteMixer01",
        "path": "Assets/ConstructionSite/Prefab/ConstructionSite/SM_ConcreteMixer01.prefab",
        "construction_class": "small_equipment",
        "bbox_size": {"x": 0.6597, "y": 1.3343, "z": 1.9390},
    },
    "construction_lift": {
        "name": "SM_ConstructionLift05",
        "path": "Assets/ConstructionSite/Prefab/ConstructionSite/SM_ConstructionLift05.prefab",
        "construction_class": "site_equipment",
        "bbox_size": {"x": 2.9099, "y": 4.9108, "z": 2.7911},
    },
}


def rotate_offset(offset_x: float, offset_z: float, rotation_deg: float) -> tuple[float, float]:
    theta = math.radians(rotation_deg)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    return (
        offset_x * cos_t - offset_z * sin_t,
        offset_x * sin_t + offset_z * cos_t,
    )


def accessory_object(
    object_id: str,
    parent: dict[str, Any],
    accessory_key: str,
    local_x: float,
    local_z: float,
    local_rotation_y: float,
    defaults: dict[str, Any],
) -> dict[str, Any]:
    prefab = ACCESSORY_PREFABS[accessory_key]
    parent_position = parent["transform"]["position"]
    parent_rotation = parent["transform"]["rotation"]["y"]
    offset_x, offset_z = rotate_offset(local_x, local_z, parent_rotation)
    world_x = parent_position["x"] + offset_x
    world_z = parent_position["z"] + offset_z
    rotation_y = parent_rotation + local_rotation_y
    bbox = prefab["bbox_size"]

    return {
        "id": object_id,
        "source": {
            "facility_index": parent["source"]["facility_index"],
            "facility_type": parent["source"]["facility_type"],
            "category": parent["source"].get("category", "unknown"),
            "kind": "accessory",
            "parent_id": parent["id"],
            "accessory_type": accessory_key,
        },
        "prefab": {
            "name": prefab["name"],
            "path": prefab["path"],
            "construction_class": prefab["construction_class"],
            "relation_role": "dependent",
            "suggested_support_type": "grounded",
            "selection_score": 1.0,
            "assembly_type": "single_prefab",
            "children": [],
        },
        "placement": {
            "pivot_type": "bottom_centered",
            "snap_to_ground": True,
            "bbox_size": bbox,
            "prefab_bbox_size": bbox,
            "scale_policy": "native_prefab_size",
            "clearance_radius_m": 0.25,
            "placement_notes": "visual enrichment accessory",
        },
        "transform": {
            "position": {"x": world_x, "y": defaults["site"].get("ground_y", 0.0), "z": world_z},
            "rotation": {"x": 0.0, "y": rotation_y, "z": 0.0},
            "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
        },
        "footprint": rectangle_corners_xz(world_x, world_z, bbox["x"], bbox["z"], rotation_y),
        "anchors": {
            "support_id": "ground_00",
            "functional_id": parent["id"],
        },
    }


def create_visual_accessories(
    objects: list[dict[str, Any]],
    site: dict[str, Any],
    entrances: list[dict[str, Any]],
    defaults: dict[str, Any],
    rng: random.Random,
) -> list[dict[str, Any]]:
    accessories: list[dict[str, Any]] = []
    next_index = len(objects) + 1

    def add(parent: dict[str, Any], key: str, x: float, z: float, ry: float = 0.0) -> None:
        nonlocal next_index
        candidate = accessory_object(f"obj_{next_index:04d}", parent, key, x, z, ry, defaults)
        if not is_valid_scatter_position(
            candidate,
            objects + accessories,
            site,
            entrances,
            min_spacing=0.25,
            allowed_overlap_ids={parent["id"]},
        ):
            return
        accessories.append(candidate)
        next_index += 1

    for obj in objects:
        facility_type = obj["source"]["facility_type"]
        bbox = obj["placement"]["bbox_size"]
        half_x = max(float(bbox["x"]) / 2.0, 1.0)
        half_z = max(float(bbox["z"]) / 2.0, 1.0)

        if facility_type == "core":
            add(obj, "floodlight", half_x + 3.0, half_z + 3.0, 30.0)
            if rng.random() < 0.65:
                add(obj, rng.choice(["ladder", "toolbox", "paint_can"]), -half_x - 1.0, rng.uniform(-half_z, half_z), rng.choice([0.0, 45.0, 90.0]))
            if rng.random() < 0.45:
                add(obj, "dirt_decal", rng.uniform(-half_x, half_x), -half_z - 1.2, rng.uniform(0.0, 180.0))

        elif facility_type == "crane":
            radius = max(half_x, half_z, 6.0) + 2.0
            for x, z in ((-radius, -radius), (radius, -radius), (-radius, radius), (radius, radius)):
                add(obj, "traffic_cone", x, z, 0.0)
            add(obj, "road_block", 0.0, -radius, 90.0)
            add(obj, "road_block", 0.0, radius, 90.0)

        elif facility_type == "storage":
            variant_slot = int(obj["source"].get("visual_variant_index", 0)) % 3
            if variant_slot == 0:
                storage_slots = [
                    (-2.0, -1.5, "pallet"),
                    (0.0, -1.5, "concrete_bag"),
                    (2.0, -1.5, "concrete_brick"),
                    (-2.0, 1.5, "concrete_brick"),
                    (0.0, 1.5, "pallet"),
                    (2.0, 1.5, "concrete_bag"),
                ]
                selected_slots = rng.sample(storage_slots, k=rng.randint(2, min(4, len(storage_slots))))
                for x, z, key in selected_slots:
                    add(obj, key, x + rng.uniform(-0.35, 0.35), z + rng.uniform(-0.35, 0.35), rng.choice([0.0, 15.0, 45.0, 90.0]))
                add(obj, "road_block", -half_x - 1.0, rng.uniform(-0.7, 0.7), 0.0)
                if rng.random() < 0.75:
                    add(obj, "road_block", half_x + 1.0, rng.uniform(-0.7, 0.7), 0.0)
            elif variant_slot == 1:
                for x, z, key in [
                    (-2.4, 0.0, "storage_pipe"),
                    (2.3, 0.3, "plank_stack"),
                    (0.0, -1.9, "pallet"),
                ]:
                    add(obj, key, x + rng.uniform(-0.4, 0.4), z + rng.uniform(-0.4, 0.4), rng.choice([0.0, 20.0, 90.0]))
                if rng.random() < 0.55:
                    add(obj, "traffic_cone", -half_x - 0.8, -half_z - 0.8, 0.0)
            else:
                for x, z, key in [
                    (-1.8, -1.2, "concrete_bag"),
                    (-0.4, -1.0, "concrete_bag"),
                    (1.3, -1.1, "concrete_brick"),
                    (-1.5, 1.1, "pallet"),
                    (1.4, 1.2, "plywood_stack"),
                ]:
                    add(obj, key, x + rng.uniform(-0.25, 0.25), z + rng.uniform(-0.25, 0.25), rng.choice([0.0, 15.0, 45.0, 90.0]))
                if rng.random() < 0.65:
                    add(obj, "road_block", rng.choice([-half_x - 1.0, half_x + 1.0]), rng.uniform(-0.7, 0.7), 0.0)

        elif facility_type == "office":
            variant_slot = int(obj["source"].get("visual_variant_index", 0)) % 3
            add(obj, "traffic_cone", -half_x - 1.0, -half_z - 1.0, 0.0)
            add(obj, "traffic_cone", half_x + 1.0, -half_z - 1.0, 0.0)
            if variant_slot == 0:
                add(obj, "barrel", -half_x - 1.0, half_z + 1.0, 0.0)
                add(obj, "floodlight_stand", half_x + 1.2, half_z + 1.0, 35.0)
            elif variant_slot == 1:
                add(obj, "generator", half_x + 1.6, half_z + 1.0, 90.0)
            else:
                add(obj, "floodlight_stand", -half_x - 1.1, half_z + 1.0, -25.0)
                if rng.random() < 0.6:
                    add(obj, "barrel", half_x + 1.1, half_z + 1.0, 0.0)

        elif facility_type == "rest_area":
            variant_slot = int(obj["source"].get("visual_variant_index", 0)) % 3
            if variant_slot == 0:
                add(obj, "water_tank", half_x + 1.5, 0.0, 0.0)
                add(obj, "traffic_cone", -half_x - 0.8, -half_z - 0.8, 0.0)
                add(obj, "traffic_cone", half_x + 0.8, -half_z - 0.8, 0.0)
            elif variant_slot == 1:
                add(obj, "water_tank", -half_x - 1.5, 0.0, 0.0)
                add(obj, "barrel", half_x + 0.9, -half_z - 0.8, 0.0)
            else:
                add(obj, "traffic_cone", -half_x - 0.8, -half_z - 0.8, 0.0)
                add(obj, "barrel", half_x + 0.9, half_z + 0.8, 0.0)

    return accessories


SCATTER_RULES: dict[str, list[dict[str, Any]]] = {
    "core": [
        {"keys": ["generator"], "count_range": (0, 1), "radius_padding": (5.0, 10.0), "min_spacing": 3.0, "probability": 0.85},
        {"keys": ["hose"], "count_range": (1, 2), "radius_padding": (3.0, 7.0), "min_spacing": 2.0, "probability": 0.9},
        {"keys": ["floodlight_stand"], "count_range": (1, 2), "radius_padding": (6.0, 12.0), "min_spacing": 4.0, "probability": 0.9},
        {"keys": ["ladder", "toolbox", "paint_can", "concrete_mixer"], "count_range": (1, 3), "radius_padding": (2.5, 7.0), "min_spacing": 1.5, "probability": 0.9},
        {"keys": ["dirt_decal", "trash_decal"], "count_range": (0, 2), "radius_padding": (2.0, 8.0), "min_spacing": 1.0, "probability": 0.75},
    ],
    "crane": [
        {"keys": ["traffic_cone", "barrel"], "count_range": (3, 6), "radius_padding": (4.0, 8.0), "min_spacing": 1.2, "probability": 1.0},
        {"keys": ["barrel"], "count_range": (0, 2), "radius_padding": (5.0, 10.0), "min_spacing": 2.0, "probability": 0.7},
        {"keys": ["road_closure", "dirt_decal"], "count_range": (0, 2), "radius_padding": (5.0, 11.0), "min_spacing": 2.0, "probability": 0.65},
    ],
    "storage": [
        {"keys": ["storage_pipe", "plywood_stack", "plank_stack", "log_tarp", "pallet", "concrete_bag", "concrete_brick"], "count_range": (1, 4), "radius_padding": (3.0, 8.0), "min_spacing": 3.0, "probability": 1.0},
        {"keys": ["barrel", "traffic_cone"], "count_range": (0, 3), "radius_padding": (2.0, 6.0), "min_spacing": 2.0, "probability": 0.75},
        {"keys": ["toolbox", "ladder", "trash_decal"], "count_range": (0, 2), "radius_padding": (2.0, 5.0), "min_spacing": 1.2, "probability": 0.7},
    ],
    "office": [
        {"keys": ["traffic_cone", "barrel"], "count_range": (1, 3), "radius_padding": (2.0, 5.0), "min_spacing": 1.0, "probability": 0.9},
        {"keys": ["generator"], "count_range": (0, 1), "radius_padding": (3.0, 6.0), "min_spacing": 3.0, "probability": 0.5},
        {"keys": ["floodlight_stand"], "count_range": (0, 1), "radius_padding": (4.0, 8.0), "min_spacing": 4.0, "probability": 0.8},
        {"keys": ["trash_decal"], "count_range": (0, 1), "radius_padding": (2.0, 5.0), "min_spacing": 1.0, "probability": 0.45},
    ],
    "rest_area": [
        {"keys": ["barrel", "hose", "water_tank"], "count_range": (1, 2), "radius_padding": (2.0, 5.0), "min_spacing": 2.0, "probability": 0.9},
        {"keys": ["trash_decal", "paint_can"], "count_range": (0, 1), "radius_padding": (1.5, 4.0), "min_spacing": 1.0, "probability": 0.6},
    ],
}

MINI_CLUSTER_RULES: dict[str, dict[str, Any]] = {
    "traffic_cone": {"probability": 0.16, "count_range": (1, 2), "radius_range": (0.8, 2.2), "min_spacing": 0.45},
    "barrel": {"probability": 0.14, "count_range": (1, 1), "radius_range": (1.0, 2.6), "min_spacing": 0.8},
    "pallet": {"probability": 0.22, "count_range": (1, 1), "radius_range": (1.2, 3.0), "min_spacing": 0.8},
    "concrete_bag": {"probability": 0.22, "count_range": (1, 1), "radius_range": (1.1, 2.6), "min_spacing": 0.8},
    "concrete_brick": {"probability": 0.22, "count_range": (1, 1), "radius_range": (1.1, 2.6), "min_spacing": 0.8},
}


def scene_seed(raw: dict[str, Any], input_path: Path, requested_seed: int | None = None) -> int:
    if requested_seed is not None:
        return requested_seed
    seed_source = str(raw.get("id") or input_path.stem)
    return sum((index + 1) * ord(char) for index, char in enumerate(seed_source)) % (2**32)


def aabb_overlaps(left: tuple[float, float, float, float], right: tuple[float, float, float, float], padding: float = 0.0) -> bool:
    return not (
        left[2] + padding <= right[0]
        or right[2] + padding <= left[0]
        or left[3] + padding <= right[1]
        or right[3] + padding <= left[1]
    )


def object_center_dict(obj: dict[str, Any]) -> dict[str, float]:
    position = obj["transform"]["position"]
    return {"x": position["x"], "z": position["z"]}


def is_valid_scatter_position(
    candidate: dict[str, Any],
    placed_objects: list[dict[str, Any]],
    site: dict[str, Any],
    entrances: list[dict[str, Any]],
    min_spacing: float,
    allowed_overlap_ids: set[str] | None = None,
) -> bool:
    allowed_overlap_ids = allowed_overlap_ids or set()
    bounds = site["bounds"]
    min_x, min_z, max_x, max_z = object_aabb(candidate)
    if min_x < bounds["min_x"] or max_x > bounds["max_x"] or min_z < bounds["min_z"] or max_z > bounds["max_z"]:
        return False

    boundary = site.get("boundary_polygon", [])
    if boundary and not all(point_in_polygon(corner, boundary) for corner in candidate["footprint"]):
        return False

    center = footprint_center(candidate)
    for zone in site.get("exclusion_zones", []):
        polygon = zone.get("polygon", [])
        if point_in_polygon(center, polygon) or any(point_in_polygon(corner, polygon) for corner in candidate["footprint"]):
            return False

    for entrance in entrances:
        if distance_xz({"x": center[0], "z": center[1]}, entrance["world"]) < 7.0:
            return False

    candidate_aabb = object_aabb(candidate)
    for obj in placed_objects:
        if obj["id"] in allowed_overlap_ids:
            continue
        if aabb_overlaps(candidate_aabb, object_aabb(obj), padding=min_spacing):
            return False

    return True


def create_scatter_object(
    object_id: str,
    parent: dict[str, Any],
    accessory_key: str,
    world_x: float,
    world_z: float,
    rotation_y: float,
    defaults: dict[str, Any],
    rule_notes: str,
) -> dict[str, Any]:
    prefab = ACCESSORY_PREFABS[accessory_key]
    bbox = prefab["bbox_size"]
    ground_y = defaults["site"].get("ground_y", 0.0)
    return {
        "id": object_id,
        "source": {
            "facility_index": parent["source"]["facility_index"],
            "facility_type": parent["source"]["facility_type"],
            "category": parent["source"].get("category", "unknown"),
            "kind": "rule_scatter",
            "parent_id": parent["id"],
            "accessory_type": accessory_key,
        },
        "prefab": {
            "name": prefab["name"],
            "path": prefab["path"],
            "construction_class": prefab["construction_class"],
            "relation_role": "dependent",
            "suggested_support_type": "grounded",
            "selection_score": 1.0,
            "assembly_type": "single_prefab",
            "children": [],
        },
        "placement": {
            "pivot_type": "bottom_centered",
            "snap_to_ground": True,
            "bbox_size": bbox,
            "prefab_bbox_size": bbox,
            "scale_policy": "native_prefab_size",
            "clearance_radius_m": 0.35,
            "placement_notes": rule_notes,
        },
        "transform": {
            "position": {"x": world_x, "y": ground_y, "z": world_z},
            "rotation": {"x": 0.0, "y": rotation_y, "z": 0.0},
            "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
        },
        "footprint": rectangle_corners_xz(world_x, world_z, bbox["x"], bbox["z"], rotation_y),
        "anchors": {
            "support_id": "ground_00",
            "functional_id": parent["id"],
        },
    }


def create_rule_based_scatter(
    primary_objects: list[dict[str, Any]],
    placed_objects: list[dict[str, Any]],
    site: dict[str, Any],
    entrances: list[dict[str, Any]],
    defaults: dict[str, Any],
    seed: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rng = random.Random(seed)
    scatter: list[dict[str, Any]] = []
    next_index = len(placed_objects) + 1
    attempts = 0
    rejected = 0
    cluster_attempts = 0
    cluster_accepted = 0

    for parent in primary_objects:
        facility_type = parent["source"]["facility_type"]
        rules = SCATTER_RULES.get(facility_type, [])
        parent_position = parent["transform"]["position"]
        bbox = parent["placement"]["bbox_size"]
        base_radius = max(float(bbox["x"]), float(bbox["z"])) * 0.5

        for rule in rules:
            if rng.random() > float(rule.get("probability", 1.0)):
                continue
            accepted_for_rule = 0
            min_count, max_count = rule.get("count_range", (rule.get("count", 0), rule.get("count", 0)))
            target_count = rng.randint(int(min_count), int(max_count))
            if target_count <= 0:
                continue
            max_attempts = target_count * 22
            for _ in range(max_attempts):
                if accepted_for_rule >= target_count:
                    break

                attempts += 1
                min_pad, max_pad = rule["radius_padding"]
                radius = base_radius + rng.uniform(float(min_pad), float(max_pad))
                angle = rng.uniform(0.0, math.tau)
                world_x = parent_position["x"] + math.cos(angle) * radius
                world_z = parent_position["z"] + math.sin(angle) * radius
                rotation_y = rng.choice([0.0, 30.0, 45.0, 60.0, 90.0, 120.0, 180.0, 240.0, 270.0])
                accessory_key = rng.choice(rule["keys"])
                candidate = create_scatter_object(
                    f"obj_{next_index:04d}",
                    parent,
                    accessory_key,
                    world_x,
                    world_z,
                    rotation_y,
                    defaults,
                    "rule-based scene enrichment: near parent, avoid roads/entrances/boundary/objects",
                )

                if not is_valid_scatter_position(candidate, placed_objects + scatter, site, entrances, float(rule["min_spacing"])):
                    rejected += 1
                    continue

                scatter.append(candidate)
                next_index += 1
                accepted_for_rule += 1

                cluster_rule = MINI_CLUSTER_RULES.get(accessory_key)
                if cluster_rule and rng.random() <= float(cluster_rule["probability"]):
                    min_count, max_count = cluster_rule["count_range"]
                    target_cluster_count = rng.randint(int(min_count), int(max_count))
                    accepted_in_cluster = 0
                    for _ in range(target_cluster_count * 6):
                        if accepted_in_cluster >= target_cluster_count:
                            break
                        cluster_attempts += 1
                        min_radius, max_radius = cluster_rule["radius_range"]
                        cluster_radius = rng.uniform(float(min_radius), float(max_radius))
                        cluster_angle = rng.uniform(0.0, math.tau)
                        cluster_x = world_x + math.cos(cluster_angle) * cluster_radius
                        cluster_z = world_z + math.sin(cluster_angle) * cluster_radius
                        cluster_rotation_y = rotation_y + rng.choice([-20.0, 0.0, 15.0, 30.0, 90.0])
                        cluster_candidate = create_scatter_object(
                            f"obj_{next_index:04d}",
                            parent,
                            accessory_key,
                            cluster_x,
                            cluster_z,
                            cluster_rotation_y,
                            defaults,
                            "rule-based mini cluster: nearby repeated small prop, avoid roads/entrances/boundary/objects",
                        )
                        if not is_valid_scatter_position(
                            cluster_candidate,
                            placed_objects + scatter,
                            site,
                            entrances,
                            float(cluster_rule["min_spacing"]),
                        ):
                            rejected += 1
                            continue
                        scatter.append(cluster_candidate)
                        next_index += 1
                        accepted_in_cluster += 1
                        cluster_accepted += 1

    report = {
        "enabled": True,
        "seed": seed,
        "accepted_count": len(scatter),
        "attempt_count": attempts,
        "mini_cluster_attempt_count": cluster_attempts,
        "mini_cluster_accepted_count": cluster_accepted,
        "rejected_count": rejected,
        "rules": {
            facility_type: [
                {
                    "accessory_choices": rule["keys"],
                    "target_count_range_per_parent": list(rule.get("count_range", (rule.get("count", 0), rule.get("count", 0)))),
                    "probability": rule.get("probability", 1.0),
                    "radius_padding_m": list(rule["radius_padding"]),
                    "min_spacing_m": rule["min_spacing"],
                }
                for rule in rules
            ]
            for facility_type, rules in SCATTER_RULES.items()
        },
        "constraints": [
            "inside site boundary",
            "outside road/exclusion polygons",
            "minimum distance from entrances",
            "no padded AABB overlap with existing objects",
        ],
    }
    return scatter, report


def create_primary_objects(
    raw: dict[str, Any],
    site: dict[str, Any],
    entrances: list[dict[str, Any]],
    defaults: dict[str, Any],
    catalog: dict[str, list[dict[str, Any]]],
    rng: random.Random | None = None,
) -> list[dict[str, Any]]:
    width = site["bounds"]["max_x"]
    length = site["bounds"]["max_z"]
    ground_y = site["ground_y"]
    type_defaults = defaults["facility_types"]
    objects = []
    variant_starts: dict[str, int] = {}
    variant_counts: dict[str, int] = {}

    for index, facility in enumerate(raw.get("facilities", []), start=1):
        facility_type = facility.get("type", "unknown")
        facility_default = type_defaults.get(facility_type, type_defaults["storage"])
        dimensions = resolve_dimensions(facility, facility_default, site)
        if facility_type not in variant_starts:
            variant_starts[facility_type] = rng.randrange(1000) if rng is not None and facility_type == "core" else 0
            variant_counts[facility_type] = 0
        variant_index = variant_starts[facility_type] + variant_counts[facility_type]
        variant_counts[facility_type] += 1
        prefab = select_prefab(facility_type, catalog, variant_index)
        position_xz = as_world_point({"x": float(facility["x"]), "y": float(facility["y"])}, width, length)
        rotation_y = float(facility.get("rotation", facility_default["default_rotation_deg"]))
        object_id = f"obj_{index:04d}"

        objects.append(
            {
                "id": object_id,
                "source": {
                    "facility_index": index - 1,
                    "facility_type": facility_type,
                    "category": facility.get("category", "unknown"),
                    "kind": "primary",
                    "visual_variant": prefab["name"],
                    "visual_variant_index": variant_index,
                },
                "prefab": {
                    "name": prefab["name"],
                    "path": prefab["path"],
                    "construction_class": prefab["construction_class"],
                    "relation_role": facility_default["relation_role"],
                    "suggested_support_type": facility_default["support_type"],
                    "selection_score": prefab.get("selection_score", 0.0),
                    "assembly_type": prefab.get("assembly_type", "single_prefab"),
                    "children": prefab.get("children", []),
                },
                "placement": {
                    "pivot_type": prefab.get("pivot_type", "bottom_centered"),
                    "snap_to_ground": bool(prefab.get("snap_to_ground", True)),
                    "bbox_size": {
                        "x": dimensions["width_m"],
                        "y": dimensions["height_m"],
                        "z": dimensions["length_m"],
                    },
                    "prefab_bbox_size": prefab.get("bbox_size"),
                    "scale_policy": "fit_facility_footprint",
                    "clearance_radius_m": float(facility_default["clearance_radius_m"]),
                    "placement_notes": "compiled from raw optimized layout",
                },
                "transform": {
                    "position": {
                        "x": position_xz["x"],
                        "y": ground_y,
                        "z": position_xz["z"],
                    },
                    "rotation": {"x": 0.0, "y": rotation_y, "z": 0.0},
                    "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
                },
                "footprint": rectangle_corners_xz(
                    position_xz["x"],
                    position_xz["z"],
                    dimensions["width_m"],
                    dimensions["length_m"],
                    rotation_y,
                ),
                "anchors": {
                    "support_id": "ground_00",
                    "functional_id": None,
                },
            }
        )
    return objects


def infer_functional_anchor(
    obj: dict[str, Any],
    objects: list[dict[str, Any]],
    entrances: list[dict[str, Any]],
) -> str:
    facility_type = obj["source"]["facility_type"]
    position = obj["transform"]["position"]

    by_type: dict[str, list[dict[str, Any]]] = {}
    for other in objects:
        if other["id"] == obj["id"]:
            continue
        by_type.setdefault(other["source"]["facility_type"], []).append(
            {"id": other["id"], "world": other["transform"]["position"]}
        )

    entrance_candidates = [{"id": item["id"], "world": item["world"]} for item in entrances]

    if facility_type == "crane":
        return nearest_anchor(position, by_type.get("core", []), nearest_anchor(position, entrance_candidates))
    if facility_type == "storage":
        return nearest_anchor(position, by_type.get("crane", []) + by_type.get("core", []), nearest_anchor(position, entrance_candidates))
    if facility_type == "core":
        return nearest_anchor(position, by_type.get("crane", []), nearest_anchor(position, entrance_candidates))
    if facility_type == "office":
        return nearest_anchor(position, entrance_candidates)
    if facility_type == "rest_area":
        return nearest_anchor(position, by_type.get("office", []), nearest_anchor(position, entrance_candidates))
    return nearest_anchor(position, entrance_candidates)


def attach_relations(
    objects: list[dict[str, Any]],
    entrances: list[dict[str, Any]],
) -> dict[str, list[dict[str, str]]]:
    support = [{"support_id": "scene_root", "dependent_id": "ground_00", "relation": "support"}]
    functional = []
    tuples = []

    for obj in objects:
        if obj["source"].get("kind") == "accessory" and obj["anchors"].get("functional_id"):
            functional_id = obj["anchors"]["functional_id"]
        else:
            functional_id = infer_functional_anchor(obj, objects, entrances)
        obj["anchors"]["functional_id"] = functional_id
        support.append({"support_id": "ground_00", "dependent_id": obj["id"], "relation": "support"})
        functional.append({"anchor_id": functional_id, "dependent_id": obj["id"], "relation": "functional"})
        tuples.append(
            {
                "dependent_id": obj["id"],
                "support_id": "ground_00",
                "functional_id": functional_id,
                "relation_source": f"{obj['source'].get('kind', 'primary')}:{obj['source']['facility_type']}",
            }
        )

    return {"support": support, "functional": functional, "tuples": tuples}


def generation_order(objects: list[dict[str, Any]], relations: dict[str, list[dict[str, str]]]) -> dict[str, list[str]]:
    support_bfs = ["ground_00"] + [obj["id"] for obj in objects]

    adjacency: dict[str, list[str]] = {}
    for relation in relations["functional"]:
        adjacency.setdefault(relation["anchor_id"], []).append(relation["dependent_id"])

    ordered = []
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        for child_id in adjacency.get(node_id, []):
            if child_id in visited:
                continue
            visited.add(child_id)
            ordered.append(child_id)
            visit(child_id)

    for obj in objects:
        if obj["id"] not in visited:
            visited.add(obj["id"])
            ordered.append(obj["id"])
            visit(obj["id"])

    return {
        "support_bfs": support_bfs,
        "functional_dfs": ordered,
        "serialized": ordered,
    }


def object_aabb(obj: dict[str, Any]) -> tuple[float, float, float, float]:
    corners = obj["footprint"]
    xs = [corner[0] for corner in corners]
    zs = [corner[1] for corner in corners]
    return min(xs), min(zs), max(xs), max(zs)


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


def footprint_center(obj: dict[str, Any]) -> list[float]:
    position = obj["transform"]["position"]
    return [position["x"], position["z"]]


def validate_scene(site: dict[str, Any], objects: list[dict[str, Any]]) -> dict[str, Any]:
    issues = []
    bounds = site["bounds"]
    boundary = site.get("boundary_polygon", [])
    exclusion_zones = site.get("exclusion_zones", [])

    for obj in objects:
        min_x, min_z, max_x, max_z = object_aabb(obj)
        if min_x < bounds["min_x"] or max_x > bounds["max_x"] or min_z < bounds["min_z"] or max_z > bounds["max_z"]:
            issues.append(
                {
                    "severity": "warning",
                    "type": "object_outside_rectangular_bounds",
                    "object_id": obj["id"],
                }
            )
        if boundary and not all(point_in_polygon(corner, boundary) for corner in obj["footprint"]):
            issues.append(
                {
                    "severity": "warning",
                    "type": "footprint_not_fully_inside_boundary_polygon",
                    "object_id": obj["id"],
                }
            )
        center = footprint_center(obj)
        for zone in exclusion_zones:
            if point_in_polygon(center, zone.get("polygon", [])):
                issues.append(
                    {
                        "severity": "warning",
                        "type": "object_center_inside_exclusion_zone",
                        "object_id": obj["id"],
                        "zone_id": zone["id"],
                    }
                )

    for index, left in enumerate(objects):
        if left["source"].get("kind") != "primary":
            continue
        left_aabb = object_aabb(left)
        for right in objects[index + 1 :]:
            if right["source"].get("kind") != "primary":
                continue
            right_aabb = object_aabb(right)
            overlap = not (
                left_aabb[2] <= right_aabb[0]
                or right_aabb[2] <= left_aabb[0]
                or left_aabb[3] <= right_aabb[1]
                or right_aabb[3] <= left_aabb[1]
            )
            if overlap:
                issues.append(
                    {
                        "severity": "warning",
                        "type": "aabb_overlap",
                        "object_ids": [left["id"], right["id"]],
                    }
                )

    return {
        "status": "needs_review" if issues else "pass",
        "issue_count": len(issues),
        "issues": issues,
        "notes": [
            "Boundary-polygon checks require every footprint corner to be inside the site polygon.",
            "Exclusion-zone checks currently flag objects whose footprint center falls inside a zone.",
            "Collision checks currently use conservative axis-aligned bounding boxes.",
        ],
    }


def compile_layout(
    input_path: Path,
    defaults_path: Path,
    catalog_path: Path,
    scatter_seed: int | None = None,
    enable_scatter: bool = True,
) -> dict[str, Any]:
    raw = load_json(input_path)
    defaults = load_json(defaults_path)
    catalog = load_json(catalog_path)

    site = infer_site(raw, defaults)
    entrances = build_entrances(raw, site)
    seed = scene_seed(raw, input_path, scatter_seed)
    primary_rng = random.Random(seed + 17)
    primary_objects = create_primary_objects(raw, site, entrances, defaults, catalog, primary_rng)
    accessory_rng = random.Random(seed + 101)
    accessory_objects = create_visual_accessories(primary_objects, site, entrances, defaults, accessory_rng)
    if enable_scatter:
        rule_scatter_objects, enrichment_report = create_rule_based_scatter(
            primary_objects,
            primary_objects + accessory_objects,
            site,
            entrances,
            defaults,
            seed,
        )
    else:
        rule_scatter_objects = []
        enrichment_report = {
            "enabled": False,
            "seed": seed,
            "accepted_count": 0,
            "attempt_count": 0,
            "rejected_count": 0,
            "rules": {},
            "constraints": [],
        }
    objects = primary_objects + accessory_objects + rule_scatter_objects
    relations = attach_relations(objects, entrances)
    order = generation_order(objects, relations)
    validation = validate_scene(site, objects)

    return {
        "scene_id": f"{raw.get('id', input_path.stem)}_scene",
        "pipeline": {
            "name": "pair2scene-lite-construction",
            "version": "0.1.0",
            "description": "Raw construction layout JSON -> semantic prefab selection -> relation-ordered 3D scene JSON",
        },
        "source_layout": {
            "path": str(input_path.as_posix()),
            "id": raw.get("id"),
            "objectives": raw.get("objectives", {}),
            "behaviors": raw.get("behaviors", {}),
            "feasibility": raw.get("feasibility", {}),
        },
        "site": {
            **site,
            "anchors": {
                "scene_root": "scene_root",
                "ground": "ground_00",
                "entrances": entrances,
            },
        },
        "site_visuals": build_site_visuals(site, entrances),
        "objects": objects,
        "relations": relations,
        "generation_order": order,
        "scene_enrichment": enrichment_report,
        "validation_report": validation,
        "stats": {
            "facility_count": len(raw.get("facilities", [])),
            "object_count": len(objects),
            "primary_count": len(primary_objects),
            "accessory_count": len(accessory_objects),
            "rule_scatter_count": len(rule_scatter_objects),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Raw layout JSON path")
    parser.add_argument("-o", "--output", type=Path, help="Output scene JSON path")
    parser.add_argument(
        "--defaults",
        type=Path,
        default=ROOT / "config" / "facility_defaults.json",
        help="Facility defaults config",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=ROOT / "config" / "asset_catalog.json",
        help="Asset catalog config",
    )
    parser.add_argument(
        "--scatter-seed",
        type=int,
        default=None,
        help="Seed for deterministic visual variation. Same seed gives same scatter, different seed gives a different valid scene dressing.",
    )
    parser.add_argument(
        "--no-scatter",
        action="store_true",
        help="Disable rule-based scatter enrichment while keeping primary facilities and fixed site context.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = args.input.resolve()
    output_path = args.output or ROOT / "output" / f"{input_path.stem}_scene.json"
    scene = compile_layout(
        input_path,
        args.defaults.resolve(),
        args.catalog.resolve(),
        scatter_seed=args.scatter_seed,
        enable_scatter=not args.no_scatter,
    )
    write_json(output_path.resolve(), scene)
    print(f"Wrote {output_path}")
    print(f"Objects: {scene['stats']['object_count']}")
    print(f"Scatter seed: {scene['scene_enrichment']['seed']}")
    print(f"Scatter objects: {scene['stats']['rule_scatter_count']}")
    print(f"Validation: {scene['validation_report']['status']} ({scene['validation_report']['issue_count']} issues)")


if __name__ == "__main__":
    main()
